"""Opt-in live Auth/Storage/API/worker test using disposable synthetic data.

Only run against the explicitly named project, with disposable synthetic data.
RunPod requests require the explicit --remote-worker flag and a configured dispatcher.
Test-only cleanup removes exactly the UUIDs created by this invocation.
"""

import argparse
import asyncio
import io
import json
import secrets
import time
from datetime import date
from uuid import uuid4

import httpx
import pymupdf
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from backend.app.core.config import get_settings
from backend.app.main import create_app
from worker.handler import process
from worker.pipeline import run_pipeline


def fixture_pdf():
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text(
            (40, 40),
            "SYNTHETIC TEST CAFE\nInvoice No: TEST-001\nDate: "
            + date.today().strftime("%d/%m/%Y")
            + "\nSubtotal: 100,000\nVAT 10%: 10,000\nDiscount: 0\nGrand total: 110,000 VND",
            fontsize=14,
        )
        return document.tobytes()


def fixture_image():
    image = Image.new("RGB", (900, 1100), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 34)
    except OSError:
        font = ImageFont.load_default(size=32)
    lines = [
        "CỬA HÀNG MINH HỌA",
        "HÓA ĐƠN BÁN HÀNG",
        "Ngày: " + date.today().strftime("%d/%m/%Y"),
        "MST: 0123456789",
        "Tiền hàng: 100.000",
        "Tiền thuế: 10.000",
        "Giảm giá: 0",
        "Tổng thanh toán: 110.000 VND",
    ]
    for i, line in enumerate(lines):
        draw.text((60, 70 + i * 105), line, fill="black", font=font)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def cloud(project, api_origin=None, remote_worker=False, image=False, expect_pipeline=None):
    settings = get_settings()
    assert settings.supabase_url == f"https://{project}.supabase.co", "Project mismatch"
    if api_origin:
        assert api_origin.startswith("https://"), "Cloud API must use HTTPS"
    if remote_worker:
        assert api_origin, "Remote worker smoke requires the deployed API"
    key = settings.supabase_secret_key.get_secret_value()
    headers = {"apikey": key, "Authorization": "Bearer " + key}
    users, receipts, paths = [], [], []
    with httpx.Client(base_url=settings.supabase_url, headers=headers, timeout=60) as remote:
        try:
            tokens = []
            for _ in range(2):
                email, password = f"smoke-{uuid4()}@example.com", secrets.token_urlsafe(32)
                result = remote.post(
                    "/auth/v1/admin/users",
                    json={
                        "email": email,
                        "password": password,
                        "email_confirm": True,
                        "app_metadata": {"purpose": "smartinvoice-disposable-smoke"},
                    },
                )
                result.raise_for_status()
                users.append(result.json()["id"])
                login = remote.post(
                    "/auth/v1/token?grant_type=password",
                    json={"email": email, "password": password},
                )
                login.raise_for_status()
                tokens.append(login.json()["access_token"])
            api = (
                httpx.Client(base_url=api_origin, timeout=120)
                if api_origin
                else TestClient(create_app(settings), raise_server_exceptions=False)
            )
            with api as client:
                assert client.get("/health").status_code == 200
                assert client.get("/api/v1/receipts").status_code == 401
                if api_origin:
                    origin = "https://smartinvoice-ai-coral.vercel.app"
                    preflight = client.options(
                        "/api/v1/receipts",
                        headers={
                            "Origin": origin,
                            "Access-Control-Request-Method": "POST",
                            "Access-Control-Request-Headers": "authorization,content-type",
                        },
                    )
                    assert preflight.headers.get("access-control-allow-origin") == origin
                    denied = client.options(
                        "/api/v1/receipts",
                        headers={
                            "Origin": "https://untrusted.example",
                            "Access-Control-Request-Method": "POST",
                        },
                    )
                    assert "access-control-allow-origin" not in denied.headers
                client.headers["Authorization"] = "Bearer " + tokens[0]
                payload = fixture_image() if image else fixture_pdf()
                content_type = "image/png" if image else "application/pdf"
                create = client.post(
                    "/api/v1/receipts",
                    headers={"Idempotency-Key": str(uuid4())},
                    json={
                        "filename": "synthetic-smoke.png" if image else "synthetic-smoke.pdf",
                        "content_type": content_type,
                        "size_bytes": len(payload),
                    },
                )
                assert create.status_code == 201, create.text
                record = create.json()
                rid = record["id"]
                receipts.append(rid)
                upload = record["upload"]
                paths.append(upload["path"])
                signed = remote.put(
                    "/storage/v1/object/upload/sign/receipts/" + upload["path"],
                    params={"token": upload["token"]},
                    content=payload,
                    headers={
                        "Content-Type": content_type,
                        "x-upsert": "false",
                        "Authorization": "Bearer " + tokens[0],
                    },
                )
                assert signed.is_success, signed.status_code
                submitted = client.post(
                    f"/api/v1/receipts/{rid}/submit", headers={"Idempotency-Key": str(uuid4())}
                )
                assert submitted.status_code == 202, submitted.text
                if remote_worker:
                    deadline = time.monotonic() + 600
                    while time.monotonic() < deadline:
                        state = client.get(f"/api/v1/receipts/{rid}/status")
                        assert state.status_code == 200, state.status_code
                        status = state.json()["status"]
                        if status == "needs_review":
                            break
                        assert status in {"queued", "processing"}, status
                        time.sleep(5)
                    else:
                        raise AssertionError("Remote worker did not finish in 600 seconds")
                else:
                    worker = asyncio.run(process({"job_id": submitted.json()["job"]["id"]}))
                    assert worker["decision"] == "saved", worker
                detail = client.get(f"/api/v1/receipts/{rid}")
                assert detail.status_code == 200, detail.text
                detail = detail.json()
                pipeline = detail["latest_extraction"]["pipeline_version"]
                if expect_pipeline:
                    assert pipeline.endswith(expect_pipeline), f"Unexpected pipeline: {pipeline}"
                assert detail["data"]["total_amount"] == "110000.00"
                other = {"Authorization": "Bearer " + tokens[1]}
                assert client.get(f"/api/v1/receipts/{rid}", headers=other).status_code == 404
                assert client.get("/api/v1/receipts", headers=other).json()["total_count"] == 0
                ticket = client.get(f"/api/v1/receipts/{rid}/file").json()
                assert httpx.get(ticket["url"]).content == payload
                reviewed = client.patch(
                    f"/api/v1/receipts/{rid}",
                    json={
                        "expected_version": detail["version"],
                        "action": "confirm",
                        "data": detail["data"],
                        "category": "food",
                    },
                )
                assert reviewed.status_code == 200, reviewed.text
                today = date.today().isoformat()
                stats = client.get(f"/api/v1/analytics/summary?date_from={today}&date_to={today}")
                assert stats.status_code == 200, stats.text
                assert stats.json()["total_amount"] == "110000.00"
                assert client.delete(f"/api/v1/receipts/{rid}").status_code == 202
                assert client.get(f"/api/v1/receipts/{rid}").status_code == 404
                print(
                    json.dumps(
                        {
                            "live_smoke": "passed",
                            "pipeline_version": pipeline,
                            "auth_users": 2,
                            "file": "synthetic Vietnamese PNG" if image else "synthetic PDF",
                            "api": api_origin or "local TestClient",
                            "steps": [
                                "Auth",
                                "signed upload",
                                "file validation",
                                "RunPod via Edge dispatcher"
                                if remote_worker
                                else "local worker subprocess",
                                "evidence",
                                "tenant isolation",
                                "signed download",
                                "human review",
                                "analytics",
                                "delete",
                            ],
                            "runpod_credit_used": remote_worker,
                        }
                    )
                )
        finally:
            if paths:
                remote.request(
                    "DELETE", "/storage/v1/object/receipts", json={"prefixes": paths}
                ).raise_for_status()
            for rid in receipts:
                remote.delete("/rest/v1/receipts", params={"id": "eq." + rid}).raise_for_status()
            for user in users:
                remote.delete("/auth/v1/admin/users/" + user).raise_for_status()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", help="Explicit development project ref for live test")
    parser.add_argument("--api-origin", help="Explicit HTTPS origin of the deployed API")
    parser.add_argument(
        "--remote-worker", action="store_true", help="Spend RunPod credit via dispatcher"
    )
    parser.add_argument(
        "--image", action="store_true", help="Use a synthetic Vietnamese image instead of PDF"
    )
    parser.add_argument(
        "--expect-pipeline", help="Require a pipeline suffix, e.g. +qwen3vl4b (reject rules fallback)"
    )
    parser.add_argument(
        "--ocr", action="store_true", help="Download models and test a synthetic Vietnamese image"
    )
    args = parser.parse_args()
    if args.ocr:
        result = run_pipeline(fixture_image(), "image/png", uuid4(), uuid4())
        print(
            json.dumps(
                {
                    "synthetic_image": "completed",
                    "data": result.data.model_dump(mode="json"),
                    "synthetic_ocr": [
                        line.text for page in result.ocr.pages for line in page.lines
                    ],
                    "timings": result.timings.model_dump(),
                },
                ensure_ascii=True,
            )
        )
    elif args.project:
        cloud(args.project, args.api_origin, args.remote_worker, args.image, args.expect_pipeline)
    else:
        parser.error("Specify --project or --ocr")
