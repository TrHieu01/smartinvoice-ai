"""Generate OpenAPI/JSON Schema without starting placeholder application endpoints."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.schemas import contracts as c  # noqa: E402

MODELS = [
    c.CreateReceiptRequest,
    c.CreateReceiptResponse,
    c.AcceptedJob,
    c.ReceiptStatusResponse,
    c.ReceiptDetail,
    c.ReceiptList,
    c.ReviewRequest,
    c.FileTicket,
    c.DeleteAccepted,
    c.AnalyticsSummary,
    c.ErrorResponse,
    c.ProcessTask,
    c.CleanupTask,
    c.HealthResponse,
    c.ExtractionResult,
]


def ref(model: type[c.Contract]) -> dict:
    return {"$ref": f"#/components/schemas/{model.__name__}"}


def response(description: str, model: type[c.Contract]) -> dict:
    return {"description": description, "content": {"application/json": {"schema": ref(model)}}}


def parameter(name: str, location: str, schema: dict, required: bool = False, **kw) -> dict:
    return {"name": name, "in": location, "required": required, "schema": schema, **kw}


def operation(
    operation_id: str,
    summary: str,
    result: type[c.Contract],
    *,
    code: int = 200,
    body: type[c.Contract] | None = None,
    params: list | None = None,
    errors: tuple[int, ...] = (),
    description: str = "",
    auth: str = "SupabaseBearer",
) -> dict:
    responses = {str(code): response("Success", result)}
    for status in set(errors) | {401, 429, 503}:
        responses[str(status)] = response(
            "See stable error codes in docs/api-contract.md", c.ErrorResponse
        )
    result_dict = {
        "operationId": operation_id,
        "summary": summary,
        "description": description,
        "security": [{auth: []}],
        "responses": responses,
    }
    if params:
        result_dict["parameters"] = params
    if body:
        result_dict["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": ref(body)}},
        }
    return result_dict


def documents() -> dict[Path, dict]:
    schemas = {}
    for model in MODELS:
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(schema.pop("$defs", {}))
        schemas[model.__name__] = schema

    rid = parameter("id", "path", {"type": "string", "format": "uuid"}, True)
    idem = parameter("Idempotency-Key", "header", {"type": "string", "format": "uuid"}, True)
    date_schema = {"type": "string", "format": "date"}
    money_schema = {"type": "string", "pattern": r"^(0|[1-9][0-9]{0,13})(\.[0-9]{1,2})?$"}
    paths = {
        "/api/v1/receipts": {
            "post": operation(
                "createReceipt",
                "Create receipt and signed upload ticket",
                c.CreateReceiptResponse,
                code=201,
                body=c.CreateReceiptRequest,
                params=[idem],
                errors=(409, 413, 415, 422),
                description="Same user/key and payload returns the same receipt. A replay may mint a fresh ticket only while awaiting_upload; record maximum ticket expiry before responding. After submit upload=null. 5 MB = 5,000,000 bytes. Use Supabase uploadToSignedUrl(path, token, file), upsert=false.",
            ),
            "get": operation(
                "listReceipts",
                "Search own receipts",
                c.ReceiptList,
                errors=(422,),
                params=[
                    parameter("page", "query", {"type": "integer", "minimum": 1, "default": 1}),
                    parameter(
                        "page_size",
                        "query",
                        {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    ),
                    parameter("merchant", "query", {"type": "string", "maxLength": 300}),
                    parameter(
                        "status",
                        "query",
                        {
                            "type": "string",
                            "enum": [
                                s.value for s in c.ReceiptStatus if s != c.ReceiptStatus.DELETING
                            ],
                        },
                    ),
                    parameter("date_from", "query", date_schema),
                    parameter("date_to", "query", date_schema),
                    parameter("min_amount", "query", money_schema),
                    parameter("max_amount", "query", money_schema),
                    parameter(
                        "sort",
                        "query",
                        {
                            "type": "string",
                            "enum": ["created_at_desc", "purchase_date_desc", "total_amount_desc"],
                            "default": "created_at_desc",
                        },
                    ),
                ],
            ),
        },
        "/api/v1/receipts/{id}": {
            "get": operation(
                "getReceipt",
                "Get own receipt and latest AI result",
                c.ReceiptDetail,
                params=[rid],
                errors=(404, 422),
            ),
            "patch": operation(
                "reviewReceipt",
                "Save corrections or confirm reviewed receipt",
                c.ReceiptDetail,
                body=c.ReviewRequest,
                params=[rid],
                errors=(404, 409, 422),
                description="Full replacement of editable data, not JSON Merge Patch. expected_version is mandatory. Revalidate; preserve original AI output and append correction event atomically.",
            ),
            "delete": operation(
                "deleteReceipt",
                "Hide receipt and schedule durable cleanup",
                c.DeleteAccepted,
                code=202,
                params=[rid],
                errors=(404, 422),
                description="Repeat while tombstone exists returns 202; after hard deletion returns 404. Workers must not resurrect deleted receipts.",
            ),
        },
        "/api/v1/receipts/{id}/submit": {
            "post": operation(
                "submitReceipt",
                "Verify uploaded file and enqueue OCR",
                c.AcceptedJob,
                code=202,
                params=[rid, idem],
                errors=(404, 409, 413, 415, 422),
                description="Locks receipt, validates actual bytes and file signature, stores SHA-256, inserts one durable database job and outbox event. Repeated submit returns existing job. A server-side dispatcher invokes the configured RunPod worker.",
            )
        },
        "/api/v1/receipts/{id}/retry": {
            "post": operation(
                "retryReceipt",
                "Create next processing run after terminal failure",
                c.AcceptedJob,
                code=202,
                params=[rid, idem],
                errors=(404, 409, 422),
                description="Only failed receipts. Same key replays the same job; different keys cannot create concurrent active jobs. Reviewed/confirmed receipts cannot be reprocessed in v1.",
            )
        },
        "/api/v1/receipts/{id}/status": {
            "get": operation(
                "getReceiptStatus",
                "Poll processing state",
                c.ReceiptStatusResponse,
                params=[rid],
                errors=(404, 422),
            )
        },
        "/api/v1/receipts/{id}/file": {
            "get": operation(
                "getReceiptFile",
                "Create a 300-second private preview URL",
                c.FileTicket,
                params=[rid],
                errors=(404, 409, 422),
                description="Ownership checked before signing. Cache-Control: no-store. URL may remain valid until expiry after deletion.",
            )
        },
        "/api/v1/analytics/summary": {
            "get": operation(
                "getAnalyticsSummary",
                "Aggregate confirmed VND receipts",
                c.AnalyticsSummary,
                params=[
                    parameter("date_from", "query", date_schema, True),
                    parameter("date_to", "query", date_schema, True),
                ],
                errors=(422,),
                description="Inclusive purchase_date range, <=366 days; zero-fill monthly buckets. Excludes all unconfirmed/deleting receipts and missing totals.",
            )
        },
        "/health": {
            "get": {
                "operationId": "health",
                "summary": "Liveness only; no secrets or dependency details",
                "security": [],
                "responses": {"200": response("Alive", c.HealthResponse)},
            }
        },
    }
    paths["/api/v1/receipts"]["post"]["responses"]["200"] = response(
        "Idempotent replay; current receipt and fresh ticket when still awaiting upload",
        c.CreateReceiptResponse,
    )
    security_schemes = {
        "SupabaseBearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Validated Supabase access token. Verify signature, issuer, audience and expiry. Subject determines ownership; never trust a client user_id.",
        },
    }
    public = {
        "openapi": "3.1.0",
        "info": {
            "title": "SmartInvoice AI API",
            "version": "1.0.0",
            "description": "Contract milestone; runtime not yet implemented. Auth sign-up/sign-in uses Supabase Auth directly.",
        },
        "servers": [{"url": "http://localhost:8000", "description": "Planned local API"}],
        "security": [{"SupabaseBearer": []}],
        "paths": paths,
        "components": {"securitySchemes": security_schemes, "schemas": schemas},
    }
    ai_schema = c.ExtractionResult.model_json_schema()
    ai_schema.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smartinvoice:extraction:1.0.0",
        }
    )
    process_schema = c.ProcessTask.model_json_schema()
    process_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    cleanup_schema = c.CleanupTask.model_json_schema()
    cleanup_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return {
        ROOT / "contracts/openapi.json": public,
        ROOT / "contracts/extraction.schema.json": ai_schema,
        ROOT / "contracts/process-job.schema.json": process_schema,
        ROOT / "contracts/cleanup-receipt.schema.json": cleanup_schema,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail when generated files drift")
    args = parser.parse_args()
    for path, document in documents().items():
        encoded = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != encoded:
                raise SystemExit(f"Stale contract: {path.relative_to(ROOT)}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(encoded, encoding="utf-8")
        print(f"{'Checked' if args.check else 'Generated'} {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
