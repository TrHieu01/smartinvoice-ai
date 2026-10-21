import hashlib
import json
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from time import perf_counter
from typing import Annotated, Literal
from uuid import UUID, uuid4

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import AppError
from backend.app.core.supabase import SupabaseGateway
from backend.app.schemas.contracts import (
    AcceptedJob,
    AnalyticsSummary,
    CreateReceiptRequest,
    CreateReceiptResponse,
    DeleteAccepted,
    FileTicket,
    HealthResponse,
    ReceiptDetail,
    ReceiptList,
    ReceiptStatus,
    ReceiptStatusResponse,
    ReviewRequest,
)
from backend.app.services.files import inspect_file
from backend.app.services.validation import validate_receipt

logger = logging.getLogger("smartinvoice")
bearer = HTTPBearer(auto_error=False)


def create_app(settings: Settings | None = None, transport=None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=30, transport=transport) as client:
            app.state.gateway = SupabaseGateway(settings, client)
            yield

    app = FastAPI(title="SmartInvoice AI API", version="1.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
        ],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def trace(request: Request, call_next):
        request.state.request_id = str(uuid4())
        start = perf_counter()
        result = await call_next(request)
        result.headers["X-Request-ID"] = request.state.request_id
        result.headers["Cache-Control"] = "no-store"
        logger.info(
            json.dumps(
                {
                    "event": "request",
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "status": result.status_code,
                    "latency_ms": round((perf_counter() - start) * 1000),
                }
            )
        )
        return result

    def error_body(request, code, details=None):
        return {
            "error": {
                "code": code,
                "message": code.replace("_", " "),
                "request_id": getattr(request.state, "request_id", str(uuid4())),
                "details": details or [],
            }
        }

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        headers = {"Retry-After": "60"} if exc.status == 429 else None
        return JSONResponse(error_body(request, exc.code), status_code=exc.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(map(str, err["loc"])), "code": err["type"]} for err in exc.errors()
        ]
        return JSONResponse(error_body(request, "invalid_request", details), status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        logger.error(
            json.dumps(
                {
                    "event": "unexpected_error",
                    "request_id": getattr(request.state, "request_id", ""),
                    "exception_type": type(exc).__name__,
                }
            )
        )
        return JSONResponse(error_body(request, "internal_error"), status_code=500)

    def gateway(request: Request) -> SupabaseGateway:
        return request.app.state.gateway

    async def actor(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
        service: Annotated[SupabaseGateway, Depends(gateway)],
    ) -> str:
        if credentials is None:
            raise AppError("authentication_required", 401)
        return await service.user(credentials.credentials)

    Service = Annotated[SupabaseGateway, Depends(gateway)]
    Actor = Annotated[str, Depends(actor)]

    async def nudge(service: SupabaseGateway):
        if settings.dispatcher_url and settings.dispatcher_secret.get_secret_value():
            try:
                await service.client.post(
                    settings.dispatcher_url,
                    headers={"x-dispatch-secret": settings.dispatcher_secret.get_secret_value()},
                    json={},
                    timeout=10,
                )
            except httpx.HTTPError:
                logger.warning('{"event":"dispatch_deferred"}')

    @app.get("/health", response_model=HealthResponse, operation_id="health")
    def health():
        return {"status": "ok", "version": "0.2.0"}

    @app.get("/ready")
    def ready():
        if not settings.configured:
            raise AppError("service_not_configured", 503)
        return {"status": "configured"}

    @app.post(
        "/api/v1/receipts",
        response_model=CreateReceiptResponse,
        status_code=201,
        operation_id="createReceipt",
    )
    async def create_receipt(
        body: CreateReceiptRequest,
        response: Response,
        user: Actor,
        service: Service,
        idempotency_key: Annotated[UUID, Header()],
    ):
        if body.size_bytes > settings.max_upload_bytes:
            raise AppError("file_too_large", 413)
        payload = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        row = await service.rpc(
            "si_create",
            {
                "p_actor": user,
                "p_key": str(idempotency_key),
                "p_filename": body.filename,
                "p_mime": body.content_type,
                "p_size": body.size_bytes,
                "p_hash": hashlib.sha256(payload.encode()).hexdigest(),
            },
        )
        response.status_code = 200 if row["replayed"] else 201
        upload = None
        if row["status"] == "awaiting_upload":
            token = await service.signed_upload(row["storage_path"])
            expires = datetime.now(timezone.utc) + timedelta(hours=2)
            row = await service.rpc(
                "si_ticket",
                {
                    "p_actor": user,
                    "p_id": row["id"],
                    "p_expires": (expires + timedelta(minutes=1)).isoformat(),
                },
            )
            if row["status"] == "awaiting_upload":
                upload = {
                    "bucket": "receipts",
                    "path": row["storage_path"],
                    "token": token,
                    "expires_at": expires,
                    "upsert": False,
                    "max_bytes": 5_000_000,
                }
        return {
            "id": row["id"],
            "status": row["status"],
            "version": row["version"],
            "upload": upload,
        }

    @app.get("/api/v1/receipts", response_model=ReceiptList, operation_id="listReceipts")
    async def list_receipts(
        user: Actor,
        service: Service,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        merchant: str | None = Query(None, max_length=300),
        status: ReceiptStatus | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        min_amount: str | None = Query(None, pattern=r"^(0|[1-9][0-9]{0,13})(\.[0-9]{1,2})?$"),
        max_amount: str | None = Query(None, pattern=r"^(0|[1-9][0-9]{0,13})(\.[0-9]{1,2})?$"),
        sort: Literal[
            "created_at_desc", "purchase_date_desc", "total_amount_desc"
        ] = "created_at_desc",
    ):
        if (date_from and date_to and date_to < date_from) or (
            min_amount is not None
            and max_amount is not None
            and Decimal(max_amount) < Decimal(min_amount)
        ):
            raise AppError("invalid_request")
        return await service.rpc(
            "si_list",
            {
                "p_actor": user,
                "p_page": page,
                "p_size": page_size,
                "p_merchant": merchant,
                "p_status": status,
                "p_from": str(date_from) if date_from else None,
                "p_to": str(date_to) if date_to else None,
                "p_min": min_amount,
                "p_max": max_amount,
                "p_sort": sort,
            },
        )

    @app.get("/api/v1/receipts/{id}", response_model=ReceiptDetail, operation_id="getReceipt")
    async def receipt(id: UUID, user: Actor, service: Service):
        return await service.rpc("si_detail", {"p_actor": user, "p_id": str(id)})

    @app.get(
        "/api/v1/receipts/{id}/status",
        response_model=ReceiptStatusResponse,
        operation_id="getReceiptStatus",
    )
    async def receipt_status(id: UUID, user: Actor, service: Service):
        detail = await service.rpc("si_detail", {"p_actor": user, "p_id": str(id)})
        return {key: detail[key] for key in ("id", "status", "version", "job", "updated_at")} | {
            "poll_after_ms": 2000 if detail["status"] in ("queued", "processing") else None
        }

    @app.post(
        "/api/v1/receipts/{id}/submit",
        response_model=AcceptedJob,
        status_code=202,
        operation_id="submitReceipt",
    )
    async def submit(
        id: UUID,
        user: Actor,
        service: Service,
        background: BackgroundTasks,
        idempotency_key: Annotated[UUID, Header()],
    ):
        metadata = await service.file_metadata(user, str(id))
        sha, pages = None, None
        if metadata["status"] == "awaiting_upload":
            content = await service.download(metadata["storage_path"], settings.max_upload_bytes)
            if len(content) != metadata["size_bytes"]:
                raise AppError("size_mismatch")
            pages = await run_in_threadpool(
                inspect_file,
                content,
                metadata["content_type"],
                settings.max_pdf_pages,
                settings.max_image_pixels,
            )
            sha = hashlib.sha256(content).hexdigest()
        result = await service.rpc(
            "si_enqueue",
            {
                "p_actor": user,
                "p_id": str(id),
                "p_key": str(idempotency_key),
                "p_sha": sha,
                "p_pages": pages,
                "p_retry": False,
            },
        )
        background.add_task(nudge, service)
        return result

    @app.post(
        "/api/v1/receipts/{id}/retry",
        response_model=AcceptedJob,
        status_code=202,
        operation_id="retryReceipt",
    )
    async def retry(
        id: UUID,
        user: Actor,
        service: Service,
        background: BackgroundTasks,
        idempotency_key: Annotated[UUID, Header()],
    ):
        result = await service.rpc(
            "si_enqueue",
            {"p_actor": user, "p_id": str(id), "p_key": str(idempotency_key), "p_retry": True},
        )
        background.add_task(nudge, service)
        return result

    @app.get("/api/v1/receipts/{id}/file", response_model=FileTicket, operation_id="getReceiptFile")
    async def file_ticket(id: UUID, user: Actor, service: Service):
        metadata = await service.file_metadata(user, str(id))
        if metadata["status"] == "awaiting_upload":
            raise AppError("upload_missing", 409)
        return {
            "url": await service.signed_download(metadata["storage_path"]),
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=300),
        }

    @app.patch("/api/v1/receipts/{id}", response_model=ReceiptDetail, operation_id="reviewReceipt")
    async def review(id: UUID, body: ReviewRequest, user: Actor, service: Service):
        data = body.data.model_dump(mode="json")
        for key in ("subtotal", "tax_amount", "discount_amount", "total_amount"):
            if data[key] is not None:
                data[key] = f"{Decimal(data[key]):.2f}"
        for item in data["items"]:
            for key in ("quantity", "unit_price", "line_total"):
                if item[key] is not None:
                    places = 3 if key == "quantity" else 2
                    item[key] = f"{Decimal(item[key]):.{places}f}"
        return await service.rpc(
            "si_review",
            {
                "p_actor": user,
                "p_id": str(id),
                "p_expected": body.expected_version,
                "p_action": body.action,
                "p_data": data,
                "p_category": body.category,
                "p_warnings": [
                    item.model_dump(mode="json") for item in validate_receipt(body.data)
                ],
            },
        )

    @app.delete(
        "/api/v1/receipts/{id}",
        response_model=DeleteAccepted,
        status_code=202,
        operation_id="deleteReceipt",
    )
    async def delete(id: UUID, user: Actor, service: Service, background: BackgroundTasks):
        result = await service.rpc("si_delete", {"p_actor": user, "p_id": str(id)})
        background.add_task(nudge, service)
        return result

    @app.get(
        "/api/v1/analytics/summary",
        response_model=AnalyticsSummary,
        operation_id="getAnalyticsSummary",
    )
    async def analytics(user: Actor, service: Service, date_from: date, date_to: date):
        if not 0 <= (date_to - date_from).days <= 365:
            raise AppError("invalid_request")
        return await service.rpc(
            "si_analytics", {"p_actor": user, "p_from": str(date_from), "p_to": str(date_to)}
        )

    return app


app = create_app()
