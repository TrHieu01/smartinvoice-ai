"""Accept independently validated model fields only when OCR supports them."""

import re
from decimal import Decimal
from difflib import SequenceMatcher

from backend.app.schemas.contracts import ExtractedItem, ReceiptData


def align_data(raw, baseline):
    from worker.pipeline import fold, money

    original = baseline.data.model_dump(mode="json")
    data = dict(original)
    evidence = {e.field: e.model_dump(mode="json") for e in baseline.evidence}
    lines = [line for page in baseline.ocr.pages for line in page.lines]
    partial = any(
        field.is_required() and key not in raw for key, field in ReceiptData.model_fields.items()
    )
    accepted = 0
    empty = dict.fromkeys(ReceiptData.model_fields)
    empty["items"] = []

    def normalized(text):
        return re.sub(r"[^a-z0-9]", "", fold(str(text)))

    def supported(value, key, candidates):
        if value is None:
            return []
        if key in {
            "subtotal",
            "tax_amount",
            "discount_amount",
            "total_amount",
            "quantity",
            "unit_price",
            "line_total",
        }:
            choices = []
            for line in candidates:
                for token in re.findall(r"(?<![\w/.-])\d+(?:[.,]\d+)*(?![\w/.-])", line.text):
                    number = token.replace(",", ".") if key == "quantity" else money(token)
                    try:
                        if number is not None and Decimal(number) == Decimal(value):
                            choices.append(line)
                            break
                    except Exception:
                        continue
            return choices if len(choices) == 1 else []
        if key == "purchase_date":
            choices = []
            for line in candidates:
                text = re.sub(r"\s*([/.-])\s*", r"\1", line.text)
                date = str(value)
                year, month, day = date.split("-")
                if date in text or re.search(
                    rf"\b0?{int(day)}[/.-]0?{int(month)}[/.-]{year}\b", text
                ):
                    choices.append(line)
            return choices[:1]
        target = normalized(value)
        choices = []
        for line in candidates:
            text = normalized(line.text)
            if target and (target == text or (len(target) >= 5 and target in text)):
                score = 1.0
            else:
                score = SequenceMatcher(None, target, text).ratio()
            if score >= 0.84:
                choices.append((score, line))
        choices.sort(key=lambda pair: pair[0], reverse=True)
        if choices and (len(choices) == 1 or choices[0][0] - choices[1][0] > 0.08):
            return [choices[0][1]]
        return []

    def source(path, found):
        scores = [line.confidence for line in found if line.confidence is not None]
        return dict(
            field=path,
            line_ids=[line.id for line in found],
            method="llm",
            ocr_confidence=min(scores) if scores else None,
        )

    for key, value in raw.items():
        if key == "items":
            continue
        if key not in ReceiptData.model_fields:
            partial = True
            continue
        if value is None:
            continue  # An absent model value must not erase a valid baseline.
        try:
            checked = ReceiptData.model_validate({**empty, key: value}).model_dump(mode="json")[key]
        except ValueError:
            partial = True
            continue
        path = "/" + key
        if checked == original.get(key) and path in evidence:
            data[key] = checked
            accepted += 1
            continue
        candidates = lines
        if key == "merchant":
            candidates = [line for line in lines if line.bbox.y0 < 0.3]
        elif key == "merchant_address":
            candidates = [line for line in lines if line.bbox.y0 < 0.25]
        elif key in {"subtotal", "tax_amount", "discount_amount", "total_amount"}:
            labels = {
                "subtotal": r"tien hang|subtotal|tam tinh|excluding vat",
                "tax_amount": r"thue|vat|tax",
                "discount_amount": r"giam|discount|chiet khau",
                "total_amount": r"tong|tng|total|thanh toan|tien mat|cash",
            }
            anchors = [line for line in lines if re.search(labels[key], fold(line.text))]
            candidates = [
                line
                for line in lines
                if any(
                    line.id.split("-")[0] == a.id.split("-")[0]
                    and -0.01 <= line.bbox.y0 - a.bbox.y0 < 0.045
                    for a in anchors
                )
            ]
        found = supported(checked, key, candidates)
        if found:
            data[key], evidence[path] = checked, source(path, found)
            accepted += 1
        else:
            partial = True
    model_items = raw.get("items", [])
    if not isinstance(model_items, list) or len(model_items) > 500:
        model_items = []
        partial = True
    items, item_evidence, used_names = [], [], set()
    for raw_item in model_items:
        if not isinstance(raw_item, dict):
            partial = True
            continue
        try:
            item = ExtractedItem.model_validate(
                dict(
                    line_number=1,
                    name=raw_item.get("name"),
                    quantity=None,
                    unit_price=None,
                    line_total=None,
                )
            )
        except ValueError:
            partial = True
            continue
        found = supported(item.name, "name", lines)
        if not found or found[0].id in used_names:
            partial = True
            continue
        name = found[0]
        used_names.add(name.id)
        known_names = {
            line_id
            for path, entry in evidence.items()
            if re.fullmatch(r"/items/\d+/name", path)
            for line_id in entry["line_ids"]
        }
        next_names = [
            (line.bbox.y0 + line.bbox.y1) / 2
            for line in lines
            if line.id in known_names
            and line.id.split("-")[0] == name.id.split("-")[0]
            and (line.bbox.y0 + line.bbox.y1) / 2 > (name.bbox.y0 + name.bbox.y1) / 2 + 0.005
        ]
        end = min(next_names, default=1.0)
        band = [
            line
            for line in lines
            if line.id.split("-")[0] == name.id.split("-")[0]
            and -0.008 <= line.bbox.y0 - name.bbox.y0 < 0.06
            and (line.bbox.y0 + line.bbox.y1) / 2 < end
        ]
        index = len(items)
        sources = [source(f"/items/{index}/name", found)]
        for old_index, old_item in enumerate(original["items"]):
            old_source = evidence.get(f"/items/{old_index}/name")
            if old_source and name.id in old_source["line_ids"]:
                item = ExtractedItem.model_validate({**old_item, "name": item.name})
                for key in ("unit", "quantity", "unit_price", "line_total"):
                    path = f"/items/{old_index}/{key}"
                    if path in evidence:
                        sources.append({**evidence[path], "field": f"/items/{index}/{key}"})
                break
        for key in ("unit", "quantity", "unit_price", "line_total"):
            value = raw_item.get(key)
            if value is None:
                continue
            try:
                candidate = ExtractedItem.model_validate({**item.model_dump(), key: value})
            except ValueError:
                partial = True
                continue
            matches = supported(value, key, band)
            if matches:
                item = candidate
                sources = [entry for entry in sources if entry["field"] != f"/items/{index}/{key}"]
                sources.append(source(f"/items/{index}/{key}", matches))
            else:
                partial = True
        item.line_number = index + 1
        items.append(item.model_dump(mode="json"))
        item_evidence.extend(sources)
    # Keep every baseline product if the model provides only a subset. Matching
    # by an OCR name ID avoids joining unrelated products by ordinal position.
    for index, item in enumerate(original["items"]):
        if len(items) >= 500:
            partial = True
            break
        name_source = evidence.get(f"/items/{index}/name")
        if name_source and not (set(name_source["line_ids"]) & used_names):
            new_index = len(items)
            items.append({**item, "line_number": new_index + 1})
            for path, entry in evidence.items():
                if path.startswith(f"/items/{index}/"):
                    item_evidence.append(
                        {
                            **entry,
                            "field": path.replace(f"/items/{index}/", f"/items/{new_index}/", 1),
                        }
                    )
    if model_items or items:
        if len(used_names) < len(original["items"]):
            partial = True
        data["items"] = items
        evidence = {
            path: entry for path, entry in evidence.items() if not path.startswith("/items/")
        }
        evidence.update({entry["field"]: entry for entry in item_evidence})
        accepted += len(used_names)
    return ReceiptData.model_validate(data), list(evidence.values()), partial, accepted
