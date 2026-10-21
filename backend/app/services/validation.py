from decimal import Decimal

from backend.app.schemas.contracts import ReceiptData, ValidationWarning


def validate_receipt(data: ReceiptData) -> list[ValidationWarning]:
    warnings = []
    for field in ("merchant", "purchase_date", "total_amount", "currency"):
        if getattr(data, field) is None:
            warnings.append(
                ValidationWarning(
                    code="missing_field",
                    severity="warning",
                    field="/" + field,
                    message="Cần kiểm tra và bổ sung trường này.",
                )
            )
    amounts = [data.subtotal, data.tax_amount, data.discount_amount, data.total_amount]
    if all(value is not None for value in amounts):
        subtotal, tax, discount, total = map(Decimal, amounts)
        if abs(subtotal + tax - discount - total) > 1:
            warnings.append(
                ValidationWarning(
                    code="total_mismatch",
                    severity="warning",
                    field="/total_amount",
                    message="Tổng thanh toán không khớp tiền hàng + thuế - giảm giá.",
                )
            )
    for index, item in enumerate(data.items):
        if all(value is not None for value in (item.quantity, item.unit_price, item.line_total)):
            if (
                abs(Decimal(item.quantity) * Decimal(item.unit_price) - Decimal(item.line_total))
                > 1
            ):
                warnings.append(
                    ValidationWarning(
                        code="item_total_mismatch",
                        severity="warning",
                        field=f"/items/{index}/line_total",
                        message="Thành tiền không khớp số lượng × đơn giá.",
                    )
                )
    return warnings[:100]
