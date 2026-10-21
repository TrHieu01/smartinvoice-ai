"""Bounded OCR with a PDF text fast path and evidence-preserving rules."""

import io
import os
import re
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from functools import lru_cache
from time import perf_counter

import pymupdf
from PIL import Image, ImageOps

from backend.app.schemas.contracts import DocumentOCR, ExtractionResult, ReceiptData
from backend.app.services.files import inspect_file
from backend.app.services.validation import validate_receipt

VERSION = "rules-0.2.0"


def fold(text):
    return "".join(
        c
        for c in unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
        if unicodedata.category(c) != "Mn"
    )


def money(text):
    """Parse an unsigned printed amount; a 3-digit suffix is a grouping separator."""
    text = re.sub(r"[^\d.,]", "", text)
    if not text:
        return None
    last = max(text.rfind(","), text.rfind("."))
    if last >= 0 and len(text) - last - 1 in (1, 2):
        text = re.sub(r"[.,]", "", text[:last]) + "." + text[last + 1 :]
    else:
        text = re.sub(r"[.,]", "", text)
    try:
        value = Decimal(text)
        return f"{value:.2f}" if 0 <= value <= Decimal("99999999999999.99") else None
    except InvalidOperation:
        return None


def rows(ocr):
    """Join OCR fragments sharing a baseline, retaining their original line IDs."""
    result = []
    for page in ocr.pages:
        groups = []
        for line in sorted(
            page.lines, key=lambda line: ((line.bbox.y0 + line.bbox.y1) / 2, line.bbox.x0)
        ):
            center = (line.bbox.y0 + line.bbox.y1) / 2
            height = line.bbox.y1 - line.bbox.y0
            if groups and abs(groups[-1][0] - center) < min(height * 0.45, 0.012):
                groups[-1][1].append(line)
            else:
                groups.append((center, [line]))
        for _, group in groups:
            group.sort(key=lambda line: line.bbox.x0)
            result.append(("  ".join(line.text for line in group), group))
    return result


def extract(ocr):
    data = dict.fromkeys(
        (
            "merchant",
            "merchant_tax_id",
            "invoice_number",
            "purchase_date",
            "subtotal",
            "tax_amount",
            "discount_amount",
            "total_amount",
            "currency",
        )
    )
    data["items"] = []
    evidence, warnings = {}, []

    def put(field, value, lines):
        if value is None:
            return
        if field.startswith("items/"):
            _, index, key = field.split("/")
            data["items"][int(index)][key] = value
        else:
            data[field] = value
        scores = [line.confidence for line in lines if line.confidence is not None]
        evidence[field] = {
            "field": "/" + field,
            "line_ids": [line.id for line in lines][:20],
            "method": "rule",
            "ocr_confidence": min(scores) if scores else None,
        }

    candidates = {}
    document_rows = rows(ocr)
    labels = [
        ("discount_amount", r"giam gia|chiet khau|discount"),
        ("subtotal", r"tam tinh|tien hang|subtotal|sub total|cong tien hang"),
        ("tax_amount", r"tien thue|thue gtgt|vat|\btax\b"),
        (
            "total_amount",
            r"tong thanh toan|tong cong|thanh tien|grand total|amount due|^total\b|tong tien",
        ),
    ]
    for text, lines in document_rows:
        normalized = fold(text)
        # OCR sometimes drops accented characters. Only tolerate a small edit in
        # an explicit label before ':', and flag that inference for human review.
        if ":" in normalized:
            prefix, tail = normalized.split(":", 1)
            aliases = (
                "tong thanh toan",
                "tong cong",
                "tien hang",
                "tien thue",
                "giam gia",
                "subtotal",
                "grand total",
                "discount",
                "amount due",
            )
            closest = max(
                aliases, key=lambda label: SequenceMatcher(None, prefix.strip(), label).ratio()
            )
            ratio = SequenceMatcher(None, prefix.strip(), closest).ratio()
            if closest != prefix.strip() and 0.87 <= ratio < 1:
                normalized = closest + ":" + tail
                warnings.append(
                    dict(
                        code="ambiguous_value",
                        severity="warning",
                        field=None,
                        message="Có nhãn bị OCR đọc thiếu ký tự; cần đối chiếu số tiền với bản gốc.",
                    )
                )
        if re.search(r"\b(usd|eur|gbp)\b|[$€£]", normalized):
            warnings.append(
                dict(
                    code="unsupported_currency",
                    severity="warning",
                    field="/currency",
                    message="MVP chỉ hỗ trợ VND; cần kiểm tra loại tiền.",
                )
            )
        if re.search(r"\bvnd\b|\bvnđ\b|dong\b|₫|đ(?:\s|$)", text.lower() + " " + normalized):
            put("currency", "VND", lines)
        found_date = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", text)
        vn_date = re.search(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b", text)
        try:
            if found_date:
                put("purchase_date", date(*map(int, found_date.groups())).isoformat(), lines)
            elif vn_date:
                day, month, year = map(int, vn_date.groups())
                put("purchase_date", date(year, month, day).isoformat(), lines)
        except ValueError:
            pass
        tax = re.search(r"(?:mst|ma so thue|tax id)\s*[:#]?\s*(\d{10}(?:-\d{3})?)\b", normalized)
        if tax:
            put("merchant_tax_id", tax[1], lines)
        invoice = re.search(
            r"(?:so hoa don|invoice\s*(?:no\.?|number|#)|receipt\s*(?:no\.?|#))\s*[:#]?\s*([A-Za-z0-9/-]+)",
            normalized,
        )
        if invoice:
            put("invoice_number", invoice[1].upper()[:100], lines)
        matched = False
        for field, pattern in labels:
            label = re.search(pattern, normalized)
            if label:
                tail = normalized[label.end() :]
                amounts = re.findall(r"(?<![\d-])\d[\d.,]*(?:[ \u00a0]\d{3})*(?!\d)", tail)
                # A percentage by itself is not a tax amount.
                if amounts and not re.fullmatch(r"\s*[:=]?\s*\d+(?:[.,]\d+)?\s*%\s*", tail):
                    value = money(amounts[-1])
                    if value is not None:
                        candidates.setdefault(field, []).append((value, lines))
                matched = True
                break
        # Conservative item baseline: explicitly separated name, quantity, price, total.
        parts = [p.strip() for p in re.split(r"\s*\|\s*|\t+|\s{2,}", text) if p.strip()]
        if not matched and len(parts) == 4 and re.fullmatch(r"\d{1,8}(?:[.,]\d{1,3})?", parts[1]):
            qty = parts[1].replace(",", ".")
            unit, total = money(parts[2]), money(parts[3])
            if unit and total and Decimal(qty) > 0 and len(data["items"]) < 500:
                idx = len(data["items"])
                data["items"].append(
                    dict(
                        line_number=idx + 1,
                        name=parts[0][:300],
                        quantity=None,
                        unit_price=None,
                        line_total=None,
                    )
                )
                for key, value in (
                    ("name", parts[0][:300]),
                    ("quantity", qty),
                    ("unit_price", unit),
                    ("line_total", total),
                ):
                    put(f"items/{idx}/{key}", value, lines)
    for field, options in candidates.items():
        if len(set(value for value, _ in options)) == 1:
            put(field, options[0][0], options[0][1])
        else:
            warnings.append(
                dict(
                    code="ambiguous_value",
                    severity="warning",
                    field="/" + field,
                    message="Có nhiều giá trị khác nhau; cần xác nhận thủ công.",
                )
            )
    for text, lines in document_rows[:6]:
        if re.search(r"[a-zA-ZÀ-ỹ]", text) and not re.search(
            r"hoa don|invoice|receipt|dia chi|address|mst|tax|ngay|date|tel|phone|hotline",
            fold(text),
        ):
            put("merchant", text[:300], lines)
            break
    if any(w["code"] == "unsupported_currency" for w in warnings):
        data["currency"] = None
        evidence.pop("currency", None)
    if not document_rows:
        warnings.append(
            dict(
                code="empty_document",
                severity="error",
                field=None,
                message="Không tìm thấy văn bản.",
            )
        )
    if any(
        line.confidence is not None and line.confidence < 0.7
        for page in ocr.pages
        for line in page.lines
    ):
        warnings.append(
            dict(
                code="low_ocr_confidence",
                severity="warning",
                field=None,
                message="Có dòng OCR độ tin cậy thấp; hãy đối chiếu ảnh gốc.",
            )
        )
    return ReceiptData.model_validate(data), list(evidence.values()), warnings


@lru_cache(maxsize=1)
def paddle_engine():
    from paddleocr import PaddleOCR

    return PaddleOCR(
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="latin_PP-OCRv5_mobile_rec",
        device=os.getenv("OCR_DEVICE", "cpu"),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
    )


def ocr_image(image):
    import cv2
    import numpy as np

    # EXIF orientation is corrected before coordinates are generated.
    rgb = np.asarray(image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    output = []
    for prediction in paddle_engine().predict(bgr):
        result = prediction.json
        if callable(result):
            result = result()
        if isinstance(result, str):
            import json

            result = json.loads(result)
        result = result.get("res", result)
        for text, score, poly in zip(
            result["rec_texts"], result["rec_scores"], result["rec_polys"]
        ):
            xs, ys = zip(*poly)
            output.append((text, (min(xs), min(ys), max(xs), max(ys)), float(score), "paddleocr"))
    return output


def run_pipeline(content, mime, receipt_id, job_id):
    start = perf_counter()
    inspect_file(content, mime)
    preprocessed = perf_counter()
    pages = []

    def append_page(number, width, height, raw_lines):
        lines = []
        for text, box, score, source in raw_lines:
            text = text.strip()
            x0, y0, x1, y1 = box
            coords = dict(
                x0=max(0, x0 / width),
                y0=max(0, y0 / height),
                x1=min(1, x1 / width),
                y1=min(1, y1 / height),
            )
            if text and coords["x0"] < coords["x1"] and coords["y0"] < coords["y1"]:
                lines.append(
                    dict(
                        id=f"p{number}-l{len(lines) + 1}",
                        text=text[:2000],
                        bbox=coords,
                        confidence=score,
                        source=source,
                    )
                )
        pages.append(
            dict(page_number=number, width=round(width), height=round(height), lines=lines[:5000])
        )

    if mime == "application/pdf":
        with pymupdf.open(stream=content, filetype="pdf") as document:
            for number, page in enumerate(document, 1):
                raw = []
                for block in page.get_text("dict")["blocks"]:
                    for line in block.get("lines", []):
                        raw.append(
                            (
                                " ".join(s["text"] for s in line["spans"]),
                                line["bbox"],
                                None,
                                "pdf_text",
                            )
                        )
                if sum(len(r[0].strip()) for r in raw) >= 20:
                    append_page(number, page.rect.width, page.rect.height, raw)
                else:
                    pix = page.get_pixmap(dpi=200, alpha=False)
                    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    append_page(number, pix.width, pix.height, ocr_image(image))
    else:
        with Image.open(io.BytesIO(content)) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            append_page(1, image.width, image.height, ocr_image(image))
    ocr = DocumentOCR(
        engine="PyMuPDF+PaddleOCR", engine_version="1.26.7/3", languages=["vi", "en"], pages=pages
    )
    recognized = perf_counter()
    data, evidence, warnings = extract(ocr)
    extracted = perf_counter()
    warnings.extend(w.model_dump(mode="json") for w in validate_receipt(data))
    finished = perf_counter()

    def ms(a, b):
        return round((b - a) * 1000)

    return ExtractionResult(
        schema_version="1.0.0",
        receipt_id=receipt_id,
        job_id=job_id,
        pipeline_version=VERSION,
        processed_at=datetime.now(timezone.utc),
        data=data,
        ocr=ocr,
        evidence=evidence,
        warnings=warnings[:100],
        timings=dict(
            preprocess_ms=ms(start, preprocessed),
            ocr_ms=ms(preprocessed, recognized),
            extraction_ms=ms(recognized, extracted),
            validation_ms=ms(extracted, finished),
            total_ms=ms(start, finished),
        ),
    )
