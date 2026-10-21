import copy

import pytest
from pydantic import ValidationError

from backend.app.schemas.contracts import ReceiptData
from backend.tests.test_receipt_layout import checked_extract, document, row


@pytest.mark.parametrize(
    "printed,unit", [("RAU (KG)", "kg"), ("TRỨNG (HỘP)", "hộp"), ("Lốc 4 hộp sữa", None)]
)
def test_explicit_unit_has_evidence_and_pack_text_does_not_imply_sale_unit(printed, unit):
    data, evidence, _ = checked_extract(
        document(row(0.2, (f"{printed} | 2 | 10.000 | 20.000", 0.1, 0.95)))
    )
    assert data.items[0].unit == unit
    assert any(e["field"] == "/items/0/unit" for e in evidence) == (unit is not None)


@pytest.mark.parametrize(
    "line", ["Rau | kg | 0.5 | 20.000 | 10.000", "Rau | 0.5 | kg | 20.000 | 10.000"]
)
def test_explicit_unit_column_both_orders(line):
    data, _, _ = checked_extract(document(row(0.2, (line, 0.1, 0.95))))
    assert data.items[0].unit == "kg"
    assert data.items[0].quantity == "0.5"


def test_address_continuation_and_payment_have_original_sources():
    data, evidence, _ = checked_extract(
        document(
            row(0.02, ("SHOP MẪU", 0.1, 0.8))
            + row(0.1, ("Địa chỉ: 12 Đường Mẫu", 0.1, 0.8))
            + row(0.125, ("Quận 1, TP. Hồ Chí Minh", 0.1, 0.8))
            + row(0.3, ("Thanh toán (Chuyển khoản): 20.000đ", 0.1, 0.95))
        )
    )
    assert data.merchant_address == "12 Đường Mẫu Quận 1, TP. Hồ Chí Minh"
    assert data.payment_method == "Chuyển khoản"
    assert {e["field"] for e in evidence} >= {"/merchant_address", "/payment_method"}


def test_customer_delivery_address_and_mixed_payments_are_not_guessed():
    data, _, warnings = checked_extract(
        document(
            row(0.1, ("Địa chỉ giao hàng: 99 Đường Khác", 0.1, 0.9))
            + row(0.2, ("Thanh toán tiền mặt: 10.000", 0.1, 0.9))
            + row(0.25, ("Thanh toán thẻ: 20.000", 0.1, 0.9))
        )
    )
    assert data.merchant_address is None
    assert data.payment_method is None
    assert any(w["field"] == "/payment_method" for w in warnings)


def test_legacy_data_remains_readable_and_manual_field_limits_are_enforced():
    legacy = dict(
        merchant=None,
        merchant_tax_id=None,
        invoice_number=None,
        purchase_date=None,
        subtotal=None,
        tax_amount=None,
        discount_amount=None,
        total_amount=None,
        currency=None,
        items=[dict(line_number=1, name="Rau", quantity="1", unit_price=None, line_total=None)],
    )
    data = ReceiptData.model_validate(legacy)
    assert (
        data.merchant_address is None and data.payment_method is None and data.items[0].unit is None
    )
    for field, value in [("merchant_address", "x" * 501), ("payment_method", "x" * 51)]:
        with pytest.raises(ValidationError):
            ReceiptData.model_validate({**legacy, field: value})
    invalid = copy.deepcopy(legacy)
    invalid["items"][0]["unit"] = "x" * 51
    with pytest.raises(ValidationError):
        ReceiptData.model_validate(invalid)
