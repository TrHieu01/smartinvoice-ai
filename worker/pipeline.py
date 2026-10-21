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

VERSION = "rules-0.4.0"


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


NUMBER = r"\d{1,14}(?:[.,]\d+)*"
QUANTITY = r"\d{1,8}(?:[.,]\d{1,3})?"
PRINTED_AMOUNT = rf"({NUMBER})\s*(?:vnd|₫|đ|d)?"
UNITS = {
    "kg": "kg",
    "g": "g",
    "l": "l",
    "ml": "ml",
    "chai": "chai",
    "hop": "hộp",
    "goi": "gói",
    "tui": "túi",
    "cai": "cái",
    "bo": "bộ",
    "pcs": "pcs",
    "piece": "piece",
}
NON_PRODUCT = (
    r"^(?:tong|tng|tam tinh|thanh toan|tien|tin |thue|vat|giam|subtotal|total|"
    r"discount|date|ngay|so ct|s ct|so hoa don|don hang|invoice|receipt|"
    r"nhan vien|dia chi|address|hotline|tel|phone|mst|ma so thue|"
    r"phieu|phiu|cam on|thank|gia ban|don gia|sl\b|qty\b)"
)


def product_name(text):
    return (
        sum(c.isalpha() for c in text) >= 3
        and not re.search(NON_PRODUCT, fold(text))
        and not re.search(r"https?://|www\.", text.lower())
    )


def nearby(first, second, max_gap=0.06):
    """Never join separate pages or widely separated receipt sections."""
    return (
        first[0].id.split("-")[0] == second[0].id.split("-")[0]
        and -0.01
        <= min(line.bbox.y0 for line in second) - max(line.bbox.y1 for line in first)
        <= max_gap
    )


def layout_items(ocr, document_rows):
    """Extract table rows and order cards with field-specific OCR evidence."""
    items = []
    table_page = None
    for index, (text, lines) in enumerate(document_rows):
        normalized = fold(text)
        page = lines[0].id.split("-")[0]
        if re.match(r"^(?:sl|so luong|qty|quantity)\s{2,}", normalized):
            table_page = page
            continue
        if re.match(r"^(?:tong|tng|subtotal|total|thanh toan)\b", normalized):
            table_page = None
        parts = [p.strip() for p in re.split(r"\s*\|\s*|\t+|\s{2,}", text) if p.strip()]
        explicit_unit = None
        if len(parts) == 5 and product_name(parts[0]):
            unit_index, qty_index = (1, 2) if re.fullmatch(QUANTITY, parts[2]) else (2, 1)
            if (
                re.fullmatch(QUANTITY, parts[qty_index])
                and re.fullmatch(r"[a-zA-ZÀ-ỹ][a-zA-ZÀ-ỹ .-]{0,49}", parts[unit_index])
                and all(re.fullmatch(PRINTED_AMOUNT, fold(part)) for part in parts[3:])
            ):
                explicit_unit = UNITS.get(fold(parts[unit_index]), parts[unit_index])
                name, qty, unit, total = parts[0], parts[qty_index], parts[3], parts[4]
                sources = dict.fromkeys(
                    ("name", "unit", "quantity", "unit_price", "line_total"), lines
                )
            else:
                continue
        elif (
            len(parts) == 4
            and product_name(parts[0])
            and re.fullmatch(QUANTITY, parts[1])
            and all(re.fullmatch(PRINTED_AMOUNT, fold(part)) for part in parts[2:])
        ):
            name, qty, unit, total = parts
            sources = dict.fromkeys(("name", "quantity", "unit_price", "line_total"), lines)
        elif (
            table_page == page
            and index
            and re.fullmatch(rf"\s*{QUANTITY}\s+{NUMBER}\s+{PRINTED_AMOUNT}\s*", normalized)
        ):
            numbers = re.findall(NUMBER, normalized)
            name, name_lines = document_rows[index - 1]
            if not product_name(name) or not nearby(name_lines, lines):
                continue
            qty, unit, total = numbers
            sources = dict(name=name_lines, quantity=lines, unit_price=lines, line_total=lines)
        else:
            continue
        unit, total = money(unit), money(total)
        qty = qty.replace(",", ".")
        if unit is not None and total is not None and Decimal(qty) > 0:
            items.append(
                (
                    dict(
                        name=name[:300],
                        unit=explicit_unit,
                        quantity=qty,
                        unit_price=unit,
                        line_total=total,
                    ),
                    sources,
                )
            )

    # Explicit quantity labels anchor cards. Individual boxes exclude package
    # thumbnail text and keep a former price below the primary price separate.
    for page in ocr.pages:
        quantities = [
            line
            for line in page.lines
            if re.match(r"(?:sl|so luong|qty|quantity)\b", fold(line.text))
        ]
        for quantity in quantities[:500]:
            qty = re.fullmatch(
                rf"(?:sl|so luong|qty|quantity)\s*[:x]?\s*({QUANTITY})", fold(quantity.text)
            )
            if not qty or quantity.bbox.x0 < 0.5 or Decimal(qty[1].replace(",", ".")) <= 0:
                continue
            band = [
                line
                for line in page.lines
                if quantity.bbox.y0 - 0.09 <= line.bbox.y0 <= quantity.bbox.y1 + 0.035
            ]
            if len(band) > 150:
                continue
            choices = []
            for price in band:
                amount = re.fullmatch(PRINTED_AMOUNT, fold(price.text))
                if not amount or price.bbox.x0 < 0.65:
                    continue
                if not -0.01 <= quantity.bbox.y0 - price.bbox.y0 <= 0.09:
                    continue
                names = [
                    line
                    for line in band
                    if line.bbox.x1 < price.bbox.x0
                    and abs((line.bbox.y0 + line.bbox.y1 - price.bbox.y0 - price.bbox.y1) / 2)
                    <= max(0.012, (price.bbox.y1 - price.bbox.y0) * 0.6)
                    and product_name(line.text)
                ]
                if names:
                    name = max(names, key=lambda line: line.bbox.x1 - line.bbox.x0)
                    choices.append((price, name, amount[1]))
            if not choices:
                continue
            price, name, amount = min(choices, key=lambda value: value[0].bbox.y0)
            if any(
                other_name.id == name.id
                and abs(other_price.bbox.y0 - price.bbox.y0) < 0.006
                and money(other_amount) != money(amount)
                for other_price, other_name, other_amount in choices
            ):
                continue
            name_lines = [name]
            for line in band:
                if (
                    name.bbox.y1 - 0.005 <= line.bbox.y0 <= quantity.bbox.y1
                    and abs(line.bbox.x0 - name.bbox.x0) < 0.035
                    and line.bbox.x1 < price.bbox.x0
                    and line.id != name.id
                    and re.search(r"[a-zA-ZÀ-ỹ]", line.text)
                    and not re.search(NON_PRODUCT, fold(line.text))
                ):
                    name_lines.append(line)
            name_lines.sort(key=lambda line: line.bbox.y0)
            unit_lines = [
                line
                for line in band
                if name.bbox.y0 <= line.bbox.y0 <= quantity.bbox.y1 + 0.035
                and abs(line.bbox.x0 - name.bbox.x0) < 0.05
                and re.match(r"gia ban\s*:", fold(line.text))
            ]
            unit_match = (
                re.search(rf"gia ban\s*:\s*({NUMBER})", fold(unit_lines[0].text))
                if len(unit_lines) == 1
                else None
            )
            values = dict(
                name=" ".join(line.text for line in name_lines)[:300],
                quantity=qty[1].replace(",", "."),
                unit_price=money(unit_match[1]) if unit_match else None,
                line_total=money(amount),
            )
            sources = dict(name=name_lines, quantity=[quantity], line_total=[price])
            if values["unit_price"] is not None:
                sources["unit_price"] = unit_lines
            used = {line.id for _, source in items for line in source["line_total"]}
            if price.id not in used:
                items.append((values, sources))
    return items[:500]


def merchant_header(document_rows):
    for text, lines in document_rows[:12]:
        normalized = fold(text).strip()
        if re.fullmatch(r"(?:tax\s+)?(?:invoice|receipt)", normalized):
            continue
        if re.search(
            r"^(?:<?\s*)?(?:don hang|so ct|s ct|invoice|receipt|ngay|date|dia chi|da chi)\b",
            normalized,
        ):
            break
        if (
            not product_name(text)
            or re.search(
                r"\d{1,2}:\d{2}|www\.|https?://|@|\?|\bmenu\b|tim gi|tim kiem|search", normalized
            )
            or re.match(r"[\d\W]", normalized)
            or re.search(
                r"hoa don|phieu|phiu|thanh toan|quan |qun |phuong|phung|thanh pho|thanh ph",
                normalized,
            )
        ):
            continue
        if sum(c.isalpha() for c in text) >= 4:
            return text[:300], lines
    return None


def extract(ocr):
    data = dict.fromkeys(
        (
            "merchant",
            "merchant_address",
            "payment_method",
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
    for row_index, (text, lines) in enumerate(document_rows):
        normalized = fold(text)
        address = re.match(r"^(?:dia chi(?: cua hang)?|address|dc)\s*:\s*(.+)", normalized)
        street = re.match(r"^\d+[\w/-]*\s+(?:duong|dung|street|road)\b", normalized)
        if address or (street and row_index < 10):
            value = text.split(":", 1)[1].strip() if address else text.strip()
            address_lines = list(lines)
            if row_index + 1 < len(document_rows):
                following, following_lines = document_rows[row_index + 1]
                if nearby(lines, following_lines, max_gap=0.025) and re.match(
                    r"^(?:quan|qun|phuong|phung|thanh pho|thanh ph|tp\b|district|ward)",
                    fold(following),
                ):
                    value += " " + following
                    address_lines += following_lines
            candidates.setdefault("merchant_address", []).append((value[:500], address_lines))
        if re.search(r"thanh toan|hinh thuc|phuong thuc|payment|paid", normalized):
            for pattern, method in (
                (r"chuyen khoan|bank transfer", "Chuyển khoản"),
                (r"tien mat|\bcash\b", "Tiền mặt"),
                (r"\bthe\b|\bcard\b", "Thẻ"),
                (r"vi dien tu|e-wallet", "Ví điện tử"),
            ):
                if re.search(pattern, normalized):
                    candidates.setdefault("payment_method", []).append((method, lines))
        # Tolerate a small edit in an explicit amount label, including OCR boxes
        # joined without a colon. Always flag this inference for human review.
        if ":" in normalized or re.search(r"\s\d", normalized):
            if ":" in normalized:
                prefix, tail = normalized.split(":", 1)
            else:
                prefix, tail = re.split(r"\s+(?=\d)", normalized, maxsplit=1)
            aliases = (
                "tong thanh toan",
                "tong cong",
                "tong tien",
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
        if re.search(
            r"\bvnd\b|\bvnđ\b|\bdong\b|₫|\d[\d.,]*\s*[đd]\b", text.lower() + " " + normalized
        ):
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
        if (
            not found_date
            and not vn_date
            and re.search(r"mua luc|ngay|date", normalized)
            and re.search(r"\b\d{1,2}/\d{1,2}\b", normalized)
        ):
            warnings.append(
                dict(
                    code="ambiguous_value",
                    severity="warning",
                    field="/purchase_date",
                    message="Ngày mua thiếu năm; cần bổ sung theo hóa đơn gốc.",
                )
            )
        tax = re.search(r"(?:mst|ma so thue|tax id)\s*[:#]?\s*(\d{10}(?:-\d{3})?)\b", normalized)
        if tax:
            put("merchant_tax_id", tax[1], lines)
        invoice = re.search(
            r"(?:so hoa don|so chung tu|s[o]? ct|don hang|invoice\s*(?:no\.?|number|#)|receipt\s*(?:no\.?|#))\s*[:#]{0,2}\s*([A-Za-z0-9/-]+)",
            normalized,
        )
        if invoice:
            put("invoice_number", invoice[1].upper()[:100], lines)
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
                elif not tail.strip(" :=") and row_index + 1 < len(document_rows):
                    next_text, next_lines = document_rows[row_index + 1]
                    amount = re.fullmatch(PRINTED_AMOUNT, fold(next_text).strip())
                    if amount and nearby(lines, next_lines, max_gap=0.04):
                        value = money(amount[1])
                        if value is not None:
                            candidates.setdefault(field, []).append((value, lines + next_lines))
                break
    for values, sources in layout_items(ocr, document_rows):
        # Only an explicit unit next to a name or in a five-column row is used;
        # a pack description such as '4 hộp' is not proof of the sale unit.
        name_text = values["name"]
        unit = re.search(r"\((kg|g|l|ml|chai|hop|goi|tui|cai|bo|pcs|piece)\)\s*$", fold(name_text))
        if not values.get("unit"):
            values["unit"] = UNITS[unit[1]] if unit else None
        if unit and "unit" not in sources:
            sources["unit"] = sources["name"]
        index = len(data["items"])
        data["items"].append(dict(line_number=index + 1, **dict.fromkeys(values)))
        for key, value in values.items():
            if value is not None:
                put(f"items/{index}/{key}", value, sources[key])
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
    merchant = merchant_header(document_rows)
    if merchant:
        put("merchant", *merchant)
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
        schema_version="1.1.0",
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
