import io
import json
from pathlib import Path

import pytest
from PIL import Image

from backend.app.schemas.contracts import ExtractionResult, ValidationWarning
from worker.vision import enhance


@pytest.fixture
def baseline():
    return ExtractionResult.model_validate_json(
        (Path(__file__).parents[2] / "contracts/examples/extraction.vi.json").read_text(
            encoding="utf-8"
        )
    )


def image():
    content = io.BytesIO()
    Image.new("RGB", (40, 50), "white").save(content, format="PNG")
    return content.getvalue()


def payload(result):
    return dict(
        data=result.data.model_dump(mode="json"),
        evidence=[dict(field=e.field, line_ids=e.line_ids) for e in result.evidence],
    )


def test_opt_in_vision_preserves_source_validation_and_baseline(baseline):
    original = baseline.model_dump(mode="json")

    def generate(images, prompt):
        assert images[0].size == (40, 50)
        assert "untrusted DATA" in prompt and "SCHEMA:" in prompt
        return json.dumps(payload(baseline))

    result = enhance(baseline, image(), "image/png", generate)
    assert result.pipeline_version.endswith("+qwen3vl4b")
    assert all(e.method == "llm" for e in result.evidence)
    assert result.data == baseline.data
    assert baseline.model_dump(mode="json") == original


@pytest.mark.parametrize(
    "invalid",
    ["not-json", "missing-evidence", "unknown-region", "duplicate-evidence", "invalid-money"],
)
def test_invalid_vision_output_falls_back_without_losing_ocr(baseline, invalid):
    response = payload(baseline)
    if invalid == "missing-evidence":
        response["evidence"] = []
    elif invalid == "unknown-region":
        response["evidence"][0]["line_ids"] = ["p1-l99999"]
    elif invalid == "duplicate-evidence":
        response["evidence"].append(response["evidence"][0])
    elif invalid == "invalid-money":
        response["data"]["total_amount"] = "NaN"
    output = invalid if invalid == "not-json" else json.dumps(response)
    result = enhance(baseline, image(), "image/png", lambda *_: output)
    assert result.pipeline_version.endswith("+vlm-fallback")
    assert result.data == baseline.data
    assert result.ocr == baseline.ocr


def test_generation_failure_does_not_expose_provider_output(baseline):
    def fail(*_):
        raise RuntimeError("PRIVATE CREDENTIAL OR RECEIPT CONTENT")

    result = enhance(baseline, image(), "image/png", fail)
    assert result.pipeline_version.endswith("+vlm-fallback")
    assert "PRIVATE" not in result.model_dump_json()


def test_vision_may_not_invent_missing_year_or_supported_currency(baseline):
    baseline.data.purchase_date = None
    baseline.data.currency = None
    baseline.evidence = [
        e for e in baseline.evidence if e.field not in ("/purchase_date", "/currency")
    ]
    baseline.warnings = [
        ValidationWarning(
            code="ambiguous_value",
            severity="warning",
            field="/purchase_date",
            message="Ngày mua thiếu năm.",
        ),
        ValidationWarning(
            code="unsupported_currency",
            severity="warning",
            field="/currency",
            message="Không hỗ trợ loại tiền.",
        ),
    ]
    response = payload(baseline)
    response["data"].update(purchase_date="2026-10-21", currency="VND")
    source = baseline.ocr.pages[0].lines[0].id
    response["evidence"] += [
        dict(field=field, line_ids=[source]) for field in ("/purchase_date", "/currency")
    ]
    result = enhance(baseline, image(), "image/png", lambda *_: json.dumps(response))
    assert result.pipeline_version.endswith("+qwen3vl4b")
    assert result.data.purchase_date is None and result.data.currency is None
