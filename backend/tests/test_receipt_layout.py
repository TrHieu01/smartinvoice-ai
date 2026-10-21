"""Receipt layout regressions; synthetic OCR boxes contain no user documents."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.app.schemas.contracts import DocumentOCR, ExtractionResult
from backend.app.services.validation import validate_receipt
from worker.pipeline import VERSION, extract


def row(y, *cells):
    return [(text, x0, y, x1, y + 0.02) for text, x0, x1 in cells]


def document(*pages):
    return DocumentOCR(
        engine="test",
        engine_version="1",
        languages=["vi", "en"],
        pages=[
            dict(
                page_number=number,
                width=1000,
                height=1500,
                lines=[
                    dict(
                        id=f"p{number}-l{index}",
                        text=text,
                        bbox=dict(x0=x0, y0=y0, x1=x1, y1=y1),
                        confidence=0.92,
                        source="paddleocr",
                    )
                    for index, (text, x0, y0, x1, y1) in enumerate(lines, 1)
                ],
            )
            for number, lines in enumerate(pages, 1)
        ],
    )


def checked_extract(ocr):
    data, evidence, warnings = extract(ocr)
    # Validate every returned field's source path, original line ID and bounds.
    ExtractionResult(
        schema_version="1.0.0",
        receipt_id=uuid4(),
        job_id=uuid4(),
        pipeline_version=VERSION,
        processed_at=datetime.now(timezone.utc),
        data=data,
        ocr=ocr,
        evidence=evidence,
        warnings=warnings,
        timings=dict.fromkeys(
            ("preprocess_ms", "ocr_ms", "extraction_ms", "validation_ms", "total_ms"), 0
        ),
    )
    return data, evidence, warnings


def test_weighted_items_below_name_and_ocr_total_label():
    ocr = document(
        row(0.02, ("CỬA HÀNG MẪU", 0.15, 0.8))
        + row(0.08, ("S CT:", 0.1, 0.25), ("TEST-2026-001", 0.35, 0.8))
        + row(0.12, ("Ngày CT: 16/07/2021", 0.1, 0.8))
        + row(0.18, ("SL", 0.15, 0.22), ("Giá bán", 0.5, 0.65), ("T.Tiền", 0.8, 0.95))
        + row(0.22, ("XÀ LÁCH (KG)", 0.1, 0.6))
        + row(0.245, ("0.16", 0.15, 0.25), ("35,000", 0.5, 0.65), ("5,600", 0.8, 0.95))
        + row(0.29, ("NGÒ RI (KG)", 0.1, 0.6))
        + row(0.315, ("0.116", 0.15, 0.25), ("52,000", 0.5, 0.65), ("6,032", 0.8, 0.95))
        + row(0.37, ("Tng tien:", 0.15, 0.4), ("11,632", 0.8, 0.95))
        + row(0.42, ("Thanh toán:", 0.15, 0.4), ("0", 0.8, 0.95))
    )
    data, evidence, warnings = checked_extract(ocr)
    assert data.invoice_number == "TEST-2026-001"
    assert str(data.purchase_date) == "2021-07-16"
    assert data.total_amount == "11632.00"
    assert len(data.items) == 2
    assert data.items[0].quantity == "0.16"
    assert data.items[1].line_total == "6032.00"
    assert data.currency is None  # Locale and store names do not prove currency.
    assert any(w["code"] == "ambiguous_value" for w in warnings)
    name = next(e for e in evidence if e["field"] == "/items/0/name")
    amount = next(e for e in evidence if e["field"] == "/items/0/line_total")
    assert set(name["line_ids"]).isdisjoint(amount["line_ids"])


def test_order_cards_ignore_status_bar_and_keep_free_item():
    ocr = document(
        row(0.02, ("16:15", 0.1, 0.25), (".Il", 0.7, 0.76), ("68", 0.85, 0.94))
        + row(0.08, ("MENU", 0.05, 0.15), ("Bn tìm gì?", 0.2, 0.5))
        + row(0.14, ("Đơn hàng #DEMO-123", 0.2, 0.85))
        + row(0.2, ("Mua lúc: 15:04, 21/10", 0.5, 0.95))
        + row(0.3, ("Lốc 4 hộp sữa chua", 0.22, 0.7), ("55.000đ", 0.82, 0.97))
        + row(0.325, ("Nhãn mẫu 100g", 0.22, 0.6), ("SL:2", 0.89, 0.97))
        + row(0.35, ("Giá bán: 27.500đ/sản phẩm", 0.22, 0.7))
        + row(0.45, ("Lốc 4 hộp sữa chua", 0.22, 0.7), ("0", 0.9, 0.97))
        + row(0.475, ("100g", 0.22, 0.4), ("27.500đ", 0.82, 0.97))
        + row(0.5, ("SL:1", 0.89, 0.97))
        + row(0.6, ("Tng tin", 0.05, 0.3), ("55.000d", 0.8, 0.97))
    )
    data, _, warnings = checked_extract(ocr)
    assert data.merchant is None
    assert data.invoice_number == "DEMO-123"
    assert data.purchase_date is None
    assert data.currency == "VND"
    assert data.total_amount == "55000.00"
    assert len(data.items) == 2
    assert data.items[0].name == "Lốc 4 hộp sữa chua Nhãn mẫu 100g"
    assert data.items[0].unit_price == "27500.00"
    assert data.items[1].line_total == "0.00"
    assert data.items[1].unit_price is None  # Former price is not a paid unit price.
    assert any(w["field"] == "/purchase_date" for w in warnings)


@pytest.mark.parametrize("label", ["Số CT", "S CT", "Số chứng từ", "Đơn hàng #"])
def test_document_number_aliases(label):
    data, _, _ = checked_extract(document(row(0.1, (label + ": DEMO-123", 0.1, 0.9))))
    assert data.invoice_number == "DEMO-123"


@pytest.mark.parametrize(
    "gap,second_page,expected", [(0.03, False, "123000.00"), (0.2, False, None), (0.03, True, None)]
)
def test_total_on_next_line_is_bounded_by_distance_and_page(gap, second_page, expected):
    label = row(0.1, ("Tổng thanh toán:", 0.1, 0.6))
    value = row(0.1 + gap, ("123.000 VND", 0.65, 0.95))
    ocr = document(label, value) if second_page else document(label + value)
    assert checked_extract(ocr)[0].total_amount == expected


def test_table_does_not_join_across_pages_or_without_header():
    title = row(0.1, ("SL  Giá bán  Thành tiền", 0.1, 0.95))
    name = row(0.2, ("SẢN PHẨM MẪU", 0.1, 0.6))
    numbers = row(0.23, ("2  10.000  20.000", 0.1, 0.95))
    assert not checked_extract(document(title + name, numbers))[0].items
    assert not checked_extract(document(name + numbers))[0].items


def test_ambiguous_card_price_is_not_guessed():
    ocr = document(
        row(0.3, ("SẢN PHẨM MẪU", 0.2, 0.6), ("20.000đ", 0.7, 0.8), ("30.000đ", 0.85, 0.98))
        + row(0.33, ("SL:2", 0.85, 0.98))
    )
    assert not checked_extract(ocr)[0].items


def test_conflicting_totals_and_item_arithmetic_remain_visible():
    data, _, warnings = checked_extract(
        document(
            row(0.02, ("SHOP MẪU", 0.1, 0.8))
            + row(0.1, ("Coffee | 2 | 10.000 | 30.000", 0.1, 0.95))
            + row(0.2, ("Tổng tiền: 30.000 VND", 0.1, 0.95))
            + row(0.25, ("Tổng cộng: 40.000 VND", 0.1, 0.95))
        )
    )
    assert data.total_amount is None
    assert data.items[0].line_total == "30000.00"
    assert any(w["code"] == "ambiguous_value" for w in warnings)
    assert any(w.code == "item_total_mismatch" for w in validate_receipt(data))


@pytest.mark.parametrize("heading", ["HÓA ĐƠN BÁN LẺ", "Invoice", "Receipt", "Tax invoice"])
def test_receipt_title_and_partial_ocr_rounding_note_are_not_merchant_or_currency(heading):
    data, _, _ = checked_extract(
        document(
        row(0.02, (heading, 0.1, 0.9))
            + row(0.06, ("SHOP MẪU", 0.1, 0.9))
            + row(0.5, ("(Đ làm tròn)", 0.1, 0.9))
        )
    )
    assert data.merchant == "SHOP MẪU"
    assert data.currency is None
