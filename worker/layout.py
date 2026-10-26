"""Column-aware fallback for fragmented retail and restaurant OCR."""

import re
from decimal import Decimal


def geometry_items(ocr):
    from worker.pipeline import NUMBER, QUANTITY, UNITS, fold, money, product_name

    result = []
    for page in ocr.pages:
        lines = sorted(page.lines, key=lambda line: (line.bbox.y0 + line.bbox.y1) / 2)

        def center(line):
            return (line.bbox.y0 + line.bbox.y1) / 2

        patterns = {
            "quantity": r"(?:sl|s1|so luong|so hung|quantity|qty)",
            "unit_price": r"(?:dgia|d gia|don gia|gia ban|gle ban|unit price)",
            "line_total": r"(?:so tien|t\.?\s*ti[e6]n|thanh ti[e]?n(?: ch(?:ua|ura) co)?|amount)",
            "unit": r"(?:don\s*vi tinh|unit)",
        }
        headers = []
        for price in lines:
            if not re.fullmatch(patterns["unit_price"], fold(price.text).strip()):
                continue
            columns = {"unit_price": price}
            for key, pattern in patterns.items():
                matches = [
                    line
                    for line in lines
                    if abs(center(line) - center(price)) < 0.035
                    and re.fullmatch(pattern, fold(line.text).strip())
                ]
                if len(matches) == 1:
                    columns[key] = matches[0]
            if "quantity" in columns and "line_total" in columns:
                headers.append((price, columns))
        if headers:
            header, columns = headers[0]
            top = max(line.bbox.y1 for line in columns.values())
            footer = [
                line.bbox.y0
                for line in lines
                if line.bbox.y0 > top
                and re.match(
                    r"^(?:tong|tng|cong tien|cng tien|subtotal|total|tien mat|cash|theo phieu|cam on|thank)\b",
                    fold(line.text),
                )
            ]
            bottom = min(footer, default=1.0)
            edge = columns.get("unit", columns["unit_price"]).bbox.x0 - 0.01
            names = [
                line
                for line in lines
                if top <= center(line) < bottom
                and line.bbox.x0 < edge
                and line.bbox.y1 - line.bbox.y0 < 0.07
                and product_name(line.text)
            ]
            for index, name in enumerate(names):
                end = center(names[index + 1]) if index + 1 < len(names) else bottom
                band = [
                    line
                    for line in lines
                    if line.id != name.id
                    and center(name) - 0.004 <= center(line) < end
                    and center(line) - center(name) < 0.065
                ]
                values = dict(
                    name=re.sub(r"^\d{1,3}\s+", "", name.text).strip(),
                    quantity=None,
                    unit_price=None,
                    line_total=None,
                )
                sources = {"name": [name]}
                if "unit" in columns:
                    column = columns["unit"]
                    candidates = [
                        line
                        for line in band
                        if abs((line.bbox.x0 + line.bbox.x1 - column.bbox.x0 - column.bbox.x1) / 2)
                        < 0.06
                        and re.fullmatch(r"[A-Za-zÀ-ỹ.]{1,20}", line.text.strip())
                    ]
                    if len(candidates) == 1:
                        unit = candidates[0]
                        values["unit"] = UNITS.get(
                            fold(unit.text).replace(".", ""), unit.text.strip()
                        )
                        sources["unit"] = [unit]
                for key in ("quantity", "unit_price", "line_total"):
                    column = columns[key]
                    target = (column.bbox.x0 + column.bbox.x1) / 2
                    candidates = []
                    for line in band:
                        text = line.text.strip()
                        x = (line.bbox.x0 + line.bbox.x1) / 2
                        barcode_price = re.fullmatch(rf"\d{{12,14}}\s+({NUMBER})", text)
                        if barcode_price:
                            if key != "unit_price":
                                continue
                            text, x = barcode_price[1], target
                        if abs(x - target) > 0.14:
                            continue
                        if key == "quantity":
                            value = text.replace(",", ".") if re.fullmatch(QUANTITY, text) else None
                            if value is not None and Decimal(value) <= 0:
                                value = None
                        else:
                            value = money(text) if re.fullmatch(NUMBER, text) else None
                        if value is not None:
                            # A token belongs to its nearest numeric column.
                            nearest = min(
                                ("quantity", "unit_price", "line_total"),
                                key=lambda k: abs(
                                    x - (columns[k].bbox.x0 + columns[k].bbox.x1) / 2
                                ),
                            )
                            if nearest == key:
                                candidates.append((value, line))
                    if len(candidates) == 1:
                        values[key], source = candidates[0]
                        sources[key] = [source]
                if values["line_total"] is not None:
                    result.append((values, sources))
        else:
            # Three-column restaurant tickets may omit the unit price/header.
            for index, line in enumerate(lines):
                match = re.fullmatch(rf"({QUANTITY})\s+(.+)", line.text.strip())
                name = match[2] if match else line.text.strip()
                if (
                    not product_name(name)
                    or line.bbox.x0 > 0.5
                    or re.match(r"^(?:reg|cashier|manager|pos|ban\s*so|mc)\b", fold(name))
                ):
                    continue
                candidates = [
                    other
                    for other in lines
                    if other.bbox.x0 > line.bbox.x1 - 0.02
                    and other.bbox.x0 > 0.6
                    and abs(center(other) - center(line)) < 0.014
                    and re.fullmatch(NUMBER, other.text.strip())
                    and not re.match(r"^0\d", other.text.strip())
                ]
                if len(candidates) != 1 or (match and Decimal(match[1].replace(",", ".")) <= 0):
                    continue
                price = candidates[0]
                result.append(
                    (
                        dict(
                            name=name,
                            quantity=match[1].replace(",", ".") if match else None,
                            unit_price=None,
                            line_total=money(price.text),
                        ),
                        dict(name=[line], quantity=[line], line_total=[price]),
                    )
                )
    return result[:500]
