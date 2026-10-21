import io
import json
from uuid import uuid4

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.main import create_app
from backend.app.services.files import inspect_file
from worker.pipeline import extract, money, run_pipeline
from backend.app.schemas.contracts import DocumentOCR


def test_api_authentication_and_error_redaction():
    requests = []

    def provider(request):
        requests.append(request)
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": str(uuid4()), "email": "test@example.com"})
        return httpx.Response(400, json={"message": "private SQL details and receipt content"})

    app = create_app(
        Settings(supabase_url="https://example.supabase.co", supabase_secret_key="server-secret"),
        httpx.MockTransport(provider),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/api/v1/receipts").status_code == 401
        assert not requests
        result = client.get("/api/v1/receipts", headers={"Authorization": "Bearer test-token"})
        assert result.status_code == 503
        assert "private" not in result.text
        assert result.headers["cache-control"] == "no-store"
        assert result.headers["x-request-id"]
        assert requests[0].headers["authorization"] == "Bearer test-token"
        assert requests[1].headers["apikey"] == "server-secret"
        body = json.loads(requests[1].content)
        assert body["p_actor"]
        assert client.get("/openapi.json").status_code == 200


def test_upload_file_validation():
    image = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(image, format="PNG")
    assert inspect_file(image.getvalue(), "image/png") == 1
    with pytest.raises(AppError):
        inspect_file(image.getvalue(), "image/jpeg")
    with pytest.raises(AppError):
        inspect_file(b"pretend PDF", "application/pdf")
    with pytest.raises(AppError):
        inspect_file(image.getvalue(), "image/png", max_pixels=100)
    with pymupdf.open() as document:
        for _ in range(6):
            document.new_page()
        with pytest.raises(AppError):
            inspect_file(document.tobytes(), "application/pdf")


@pytest.mark.parametrize(
    "printed,expected",
    [
        ("123.456", "123456.00"),
        ("123,456", "123456.00"),
        ("1.234,50", "1234.50"),
        ("1,234.50", "1234.50"),
        ("0", "0.00"),
        ("abc", None),
    ],
)
def test_printed_money(printed, expected):
    assert money(printed) == expected


def test_real_pdf_text_pipeline_has_evidence_and_does_not_require_ocr_models():
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text(
            (40, 40),
            "SAMPLE COFFEE\nInvoice No: INV-123\nDate: 21/10/2026\nSubtotal: 100,000\nVAT 10%: 10,000\nDiscount: 0\nGrand total: 110,000 VND",
            fontsize=12,
        )
        content = document.tobytes()
    result = run_pipeline(content, "application/pdf", uuid4(), uuid4())
    assert result.data.merchant == "SAMPLE COFFEE"
    assert str(result.data.purchase_date) == "2026-10-21"
    assert result.data.total_amount == "110000.00"
    assert result.data.tax_amount == "10000.00"
    assert result.data.currency == "VND"
    assert result.evidence
    assert all(line.source == "pdf_text" for page in result.ocr.pages for line in page.lines)
    assert not result.warnings


def test_extraction_ambiguity_items_and_currency_are_not_silently_guessed():
    def document(texts):
        return DocumentOCR(
            engine="test",
            engine_version="1",
            languages=["vi", "en"],
            pages=[
                dict(
                    page_number=1,
                    width=900,
                    height=1100,
                    lines=[
                        dict(
                            id=f"p1-l{i + 1}",
                            text=text,
                            bbox=dict(x0=0.1, y0=0.02 + i * 0.05, x1=0.9, y1=0.05 + i * 0.05),
                            confidence=0.9,
                            source="paddleocr",
                        )
                        for i, text in enumerate(texts)
                    ],
                )
            ],
        )

    data, evidence, warnings = extract(
        document(["TEST SHOP", "Tng thanh toán: 110.000 VND", "Coffee | 2 | 50.000 | 100.000"])
    )
    assert data.total_amount == "110000.00"
    assert data.items[0].quantity == "2"
    assert any(w["code"] == "ambiguous_value" for w in warnings)
    assert any(e["field"] == "/items/0/name" for e in evidence)
    data, _, warnings = extract(document(["TEST SHOP", "Total: 100 USD", "Total: 200 USD"]))
    assert data.total_amount is None
    assert data.currency is None
    assert {"unsupported_currency", "ambiguous_value"} <= {w["code"] for w in warnings}
