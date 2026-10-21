from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from backend.app.schemas.contracts import (
    CreateReceiptRequest,
    ExtractionResult,
    ReviewRequest,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def example():
    return json.loads((ROOT / "contracts/examples/extraction.vi.json").read_text(encoding="utf-8"))


def test_example_is_valid_in_python_and_portable_json_schema(example):
    ExtractionResult.model_validate(example)
    schema = json.loads((ROOT / "contracts/extraction.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)


@pytest.mark.parametrize(
    "value", ["1,000", "1.000.000", "-1", "NaN", "Infinity", "01", "1.234", 100, True]
)
def test_money_is_canonical_nonnegative_decimal_text(example, value):
    example["data"]["total_amount"] = value
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(example)


def test_unknown_fields_stay_null_instead_of_becoming_zero(example):
    parsed = ExtractionResult.model_validate(example)
    assert parsed.data.discount_amount is None
    assert parsed.data.merchant_tax_id is None
    assert parsed.model_dump(mode="json")["data"]["discount_amount"] is None


def test_nonexistent_evidence_and_bounding_boxes_are_rejected(example):
    example["evidence"][0]["line_ids"] = ["p1-l999"]
    with pytest.raises(ValidationError, match="existing OCR lines"):
        ExtractionResult.model_validate(example)
    example["evidence"][0]["line_ids"] = ["p1-l1"]
    example["ocr"]["pages"][0]["lines"][0]["bbox"]["x1"] = 0.05
    with pytest.raises(ValidationError, match="positive area"):
        ExtractionResult.model_validate(example)


def test_evidence_cannot_be_removed_or_attached_to_null_fields(example):
    example["evidence"].pop()
    with pytest.raises(ValidationError, match="requires source evidence"):
        ExtractionResult.model_validate(example)
    example["evidence"].append(
        {
            "field": "/discount_amount",
            "line_ids": ["p1-l1"],
            "method": "rule",
            "ocr_confidence": None,
        }
    )
    with pytest.raises(ValidationError, match="null fields"):
        ExtractionResult.model_validate(example)


@pytest.mark.parametrize("value", ["21/10/2026", "2026-02-30", "20261021", 0])
def test_date_must_be_real_iso_calendar_date(example, value):
    example["data"]["purchase_date"] = value
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(example)


def test_duplicate_item_positions_and_zero_quantity_are_rejected(example):
    item = {
        "line_number": 1,
        "name": "Sample",
        "quantity": "0",
        "unit_price": None,
        "line_total": None,
    }
    example["data"]["items"] = [item]
    with pytest.raises(ValidationError, match="greater than zero"):
        ExtractionResult.model_validate(example)
    item["quantity"] = "1"
    example["data"]["items"].append(copy.deepcopy(item))
    with pytest.raises(ValidationError, match="unique"):
        ExtractionResult.model_validate(example)


@pytest.mark.parametrize("size", [0, 5_000_001, True, "100"])
def test_upload_rejects_bad_declared_sizes(size):
    with pytest.raises(ValidationError):
        CreateReceiptRequest(filename="sample.png", content_type="image/png", size_bytes=size)


def test_upload_has_exact_5mb_limit_and_no_client_owned_user_id():
    CreateReceiptRequest(
        filename="sample.pdf", content_type="application/pdf", size_bytes=5_000_000
    )
    with pytest.raises(ValidationError):
        CreateReceiptRequest(
            filename="sample.pdf", content_type="application/pdf", size_bytes=100, user_id="forged"
        )


def test_confirm_requires_required_fields_but_draft_allows_missing_data(example):
    data = example["data"]
    data["total_amount"] = None
    with pytest.raises(ValidationError, match="confirmation requires"):
        ReviewRequest(expected_version=4, action="confirm", data=data, category="uncategorized")
    ReviewRequest(expected_version=4, action="save", data=data, category="uncategorized")


def test_review_fixture_uses_full_replace_and_no_readonly_fields():
    payload = json.loads((ROOT / "contracts/examples/review.json").read_text(encoding="utf-8"))
    ReviewRequest.model_validate(payload)
    payload["status"] = "confirmed"
    with pytest.raises(ValidationError):
        ReviewRequest.model_validate(payload)


def test_openapi_references_resolve_without_exposing_a_worker_endpoint():
    public = json.loads((ROOT / "contracts/openapi.json").read_text(encoding="utf-8"))
    assert all(not path.startswith("/internal") for path in public["paths"])
    for document in [public]:
        ids = [op["operationId"] for path in document["paths"].values() for op in path.values()]
        assert len(ids) == len(set(ids))

        def check_refs(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    target = document
                    for key in value["$ref"].removeprefix("#/").split("/"):
                        target = target[key]
                for nested in value.values():
                    check_refs(nested)
            elif isinstance(value, list):
                for nested in value:
                    check_refs(nested)

        check_refs(document)


def test_generated_files_are_current():
    from scripts.export_contracts import documents

    for path, expected in documents().items():
        assert json.loads(path.read_text(encoding="utf-8")) == expected


def test_openapi_documents_validate_against_specification():
    from openapi_spec_validator import validate

    for name in ("openapi.json",):
        validate(json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8")))
