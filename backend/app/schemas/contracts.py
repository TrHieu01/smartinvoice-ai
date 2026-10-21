"""Source of truth for API and worker JSON contracts.

Money deliberately uses decimal strings at the JSON boundary. Unknown information
is null, not a guessed zero; warnings preserve arithmetic mismatches for review.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Money = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,13})(\.[0-9]{1,2})?$")]
Quantity = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,8})(\.[0-9]{1,3})?$")]
ShortText = Annotated[str, Field(min_length=1, max_length=300)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReceiptStatus(StrEnum):
    AWAITING_UPLOAD = "awaiting_upload"
    QUEUED = "queued"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    DELETING = "deleting"


class Category(StrEnum):
    UNCATEGORIZED = "uncategorized"
    FOOD = "food"
    SHOPPING = "shopping"
    TRANSPORT = "transport"
    UTILITIES = "utilities"
    HEALTH = "health"
    EDUCATION = "education"
    OTHER = "other"


class ExtractedItem(Contract):
    line_number: int = Field(ge=1, le=500)
    name: ShortText
    quantity: Quantity | None
    unit_price: Money | None
    line_total: Money | None

    @model_validator(mode="after")
    def positive_quantity(self) -> ExtractedItem:
        if self.quantity is not None and Decimal(self.quantity) <= 0:
            raise ValueError("quantity must be greater than zero")
        return self


class ReceiptData(Contract):
    merchant: ShortText | None
    merchant_tax_id: Annotated[str, Field(pattern=r"^[0-9]{10}(-[0-9]{3})?$")] | None
    invoice_number: Annotated[str, Field(min_length=1, max_length=100)] | None
    purchase_date: date | None
    subtotal: Money | None
    tax_amount: Money | None
    discount_amount: Money | None
    total_amount: Money | None
    currency: Literal["VND"] | None
    items: list[ExtractedItem] = Field(max_length=500)

    @field_validator("purchase_date", mode="before")
    @classmethod
    def iso_calendar_date(cls, value):
        if value is None or type(value) is date:
            return value
        if not isinstance(value, str):
            raise ValueError("purchase_date must be an ISO calendar date")
        parsed = date.fromisoformat(value)
        if value != parsed.isoformat():
            raise ValueError("purchase_date must use YYYY-MM-DD")
        return parsed

    @model_validator(mode="after")
    def unique_line_numbers(self) -> ReceiptData:
        numbers = [item.line_number for item in self.items]
        if len(numbers) != len(set(numbers)):
            raise ValueError("item line_number must be unique")
        return self


class BoundingBox(Contract):
    """Normalized coordinates in the displayed, orientation-corrected page."""

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered_coordinates(self) -> BoundingBox:
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("bounding box must have positive area")
        return self


class OCRLine(Contract):
    id: Annotated[str, Field(pattern=r"^p[1-5]-l[1-9][0-9]*$")]
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    bbox: BoundingBox
    confidence: float | None = Field(ge=0, le=1)
    source: Literal["paddleocr", "pdf_text"]


class OCRPage(Contract):
    page_number: int = Field(ge=1, le=5)
    width: int = Field(gt=0, le=20000)
    height: int = Field(gt=0, le=20000)
    lines: list[OCRLine] = Field(max_length=5000)


class DocumentOCR(Contract):
    engine: ShortText
    engine_version: ShortText
    languages: list[Literal["vi", "en"]] = Field(min_length=1, max_length=2)
    pages: list[OCRPage] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def line_identifiers(self) -> DocumentOCR:
        if len(self.languages) != len(set(self.languages)):
            raise ValueError("languages must be unique")
        page_numbers = [page.page_number for page in self.pages]
        if page_numbers != list(range(1, len(self.pages) + 1)):
            raise ValueError("pages must be contiguous and ordered from 1")
        ids = []
        for page in self.pages:
            for line in page.lines:
                if not line.id.startswith(f"p{page.page_number}-"):
                    raise ValueError("line identifier must refer to its page")
                ids.append(line.id)
        if len(ids) != len(set(ids)):
            raise ValueError("OCR line identifiers must be unique")
        if sum(len(line.text) for page in self.pages for line in page.lines) > 100_000:
            raise ValueError("OCR text exceeds document limit of 100,000 characters")
        return self


FieldPath = Annotated[
    str,
    Field(
        pattern=(
            r"^/(merchant|merchant_tax_id|invoice_number|purchase_date|subtotal|tax_amount|"
            r"discount_amount|total_amount|currency|items/[0-9]+/(name|quantity|unit_price|line_total))$"
        )
    ),
]


class FieldEvidence(Contract):
    field: FieldPath
    line_ids: list[str] = Field(min_length=1, max_length=20)
    method: Literal["rule", "llm"]
    # This is OCR recognition confidence, NOT an extraction correctness probability.
    ocr_confidence: float | None = Field(ge=0, le=1)


class WarningCode(StrEnum):
    MISSING_FIELD = "missing_field"
    TOTAL_MISMATCH = "total_mismatch"
    ITEM_TOTAL_MISMATCH = "item_total_mismatch"
    LOW_OCR_CONFIDENCE = "low_ocr_confidence"
    UNSUPPORTED_CURRENCY = "unsupported_currency"
    AMBIGUOUS_VALUE = "ambiguous_value"
    EMPTY_DOCUMENT = "empty_document"


class ValidationWarning(Contract):
    code: WarningCode
    severity: Literal["info", "warning", "error"]
    field: FieldPath | None
    message: Annotated[str, Field(min_length=1, max_length=500)]


class Timings(Contract):
    preprocess_ms: int = Field(ge=0)
    ocr_ms: int = Field(ge=0)
    extraction_ms: int = Field(ge=0)
    validation_ms: int = Field(ge=0)
    total_ms: int = Field(ge=0)


class ExtractionResult(Contract):
    schema_version: Literal["1.0.0"]
    receipt_id: UUID
    job_id: UUID
    pipeline_version: ShortText
    processed_at: AwareDatetime
    data: ReceiptData
    ocr: DocumentOCR
    evidence: list[FieldEvidence] = Field(max_length=2500)
    warnings: list[ValidationWarning] = Field(max_length=100)
    timings: Timings

    @model_validator(mode="after")
    def valid_evidence(self) -> ExtractionResult:
        line_ids = {line.id for page in self.ocr.pages for line in page.lines}
        seen = set()
        for evidence in self.evidence:
            if evidence.field in seen:
                raise ValueError("evidence field paths must be unique")
            seen.add(evidence.field)
            if not set(evidence.line_ids) <= line_ids:
                raise ValueError("evidence must reference existing OCR lines")
            value = self.data.model_dump(mode="json")
            for segment in evidence.field.strip("/").split("/"):
                try:
                    value = value[int(segment)] if isinstance(value, list) else value[segment]
                except (IndexError, KeyError, ValueError, TypeError) as error:
                    raise ValueError("evidence path does not exist") from error
            if value is None:
                raise ValueError("null fields cannot have extraction evidence")
        data = self.data.model_dump(mode="json")
        populated = {
            f"/{key}" for key, value in data.items() if key != "items" and value is not None
        }
        for index, item in enumerate(data["items"]):
            populated.update(
                f"/items/{index}/{key}"
                for key, value in item.items()
                if key != "line_number" and value is not None
            )
        if not populated <= seen:
            raise ValueError("every extracted value requires source evidence")
        return self


MimeType = Literal["image/jpeg", "image/png", "image/webp", "application/pdf"]


class CreateReceiptRequest(Contract):
    filename: Annotated[str, Field(min_length=1, max_length=255)]
    content_type: MimeType
    size_bytes: int = Field(strict=True, gt=0, le=5_000_000)


class UploadTicket(Contract):
    bucket: Literal["receipts"]
    path: str
    token: str
    expires_at: AwareDatetime
    upsert: Literal[False]
    max_bytes: Literal[5_000_000]


class CreateReceiptResponse(Contract):
    id: UUID
    status: ReceiptStatus
    version: int = Field(ge=1)
    upload: UploadTicket | None


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobSummary(Contract):
    id: UUID
    run_number: int = Field(ge=1)
    status: JobStatus
    attempts: int = Field(ge=0, le=3)
    error_code: str | None
    latency_ms: int | None = Field(ge=0)


class AcceptedJob(Contract):
    receipt_id: UUID
    status: ReceiptStatus
    job: JobSummary
    poll_after_ms: int | None = Field(ge=1000, le=30000)


class ReceiptStatusResponse(Contract):
    id: UUID
    status: ReceiptStatus
    version: int = Field(ge=1)
    job: JobSummary | None
    updated_at: AwareDatetime
    poll_after_ms: int | None = Field(ge=1000, le=30000)


class ReceiptSummary(Contract):
    id: UUID
    filename: str
    status: ReceiptStatus
    merchant: ShortText | None
    purchase_date: date | None
    total_amount: Money | None
    currency: Literal["VND"] | None
    category: Category
    version: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ReceiptDetail(ReceiptSummary):
    data: ReceiptData
    job: JobSummary | None
    latest_extraction: ExtractionResult | None
    warnings: list[ValidationWarning]
    confirmed_at: AwareDatetime | None


class ReceiptList(Contract):
    items: list[ReceiptSummary]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total_count: int = Field(ge=0)


class ReviewRequest(Contract):
    expected_version: int = Field(ge=1)
    action: Literal["save", "confirm"]
    data: ReceiptData
    category: Category

    @model_validator(mode="after")
    def confirm_requires_reviewable_fields(self) -> ReviewRequest:
        if self.action == "confirm":
            required = ("merchant", "purchase_date", "total_amount", "currency")
            if any(getattr(self.data, field) is None for field in required):
                raise ValueError("confirmation requires merchant, date, total and currency")
        return self


class FileTicket(Contract):
    url: str
    expires_at: AwareDatetime


class DeleteAccepted(Contract):
    id: UUID
    status: Literal["deleting"]


class MonthlySpend(Contract):
    month: Annotated[str, Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")]
    total_amount: Money
    receipt_count: int = Field(ge=0)


class CategorySpend(Contract):
    category: Category
    total_amount: Money
    receipt_count: int = Field(ge=0)


class AnalyticsSummary(Contract):
    date_from: date
    date_to: date
    currency: Literal["VND"]
    included_status: Literal["confirmed"]
    total_amount: Money
    receipt_count: int = Field(ge=0)
    monthly: list[MonthlySpend]
    categories: list[CategorySpend]


class ErrorDetail(Contract):
    code: str
    message: str
    request_id: UUID
    details: list[dict[str, str]] = Field(default_factory=list)


class ErrorResponse(Contract):
    error: ErrorDetail


class ProcessTask(Contract):
    job_id: UUID
    # File paths and user identities are loaded from the database, never from a task payload.


class CleanupTask(Contract):
    receipt_id: UUID


class HealthResponse(Contract):
    status: Literal["ok"]
    version: str
