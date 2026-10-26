import io
import json
from pathlib import Path

import pytest
from PIL import Image

from backend.app.schemas.contracts import ExtractionResult, ValidationWarning
from worker.vision import VisionPayload, enhance, normalize_payload
from worker.handler import log_diagnostics


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


def test_generation_failure_does_not_expose_provider_output(baseline, capsys, caplog):
    def fail(*_):
        raise RuntimeError("PRIVATE CREDENTIAL OR RECEIPT CONTENT")

    result = enhance(baseline, image(), "image/png", fail)
    assert result.pipeline_version.endswith("+vlm-fallback")
    assert "PRIVATE" not in result.model_dump_json()
    stderr = capsys.readouterr().err
    assert stderr == "VLM_DIAG generate runtime\n"
    log_diagnostics(stderr + "PRIVATE CREDENTIAL OR RECEIPT CONTENT\n")
    assert "stage=generate reason=runtime" in caplog.text
    assert "PRIVATE" not in caplog.text


def test_empty_scalar_citation_can_reuse_identical_verified_baseline(baseline):
    response = payload(baseline)
    for source in response["evidence"]:
        if source["field"] == "/total_amount":
            source["line_ids"] = []
    result = enhance(baseline, image(), "image/png", lambda *_: json.dumps(response))
    assert result.pipeline_version.endswith("+qwen3vl4b")
    total = next(e for e in result.evidence if e.field == "/total_amount")
    original = next(e for e in baseline.evidence if e.field == "/total_amount")
    assert total.method == "rule" and total.line_ids == original.line_ids


def test_empty_citation_cannot_borrow_sources_for_changed_value(baseline):
    response = payload(baseline)
    response["data"]["total_amount"] = "1.00"
    for source in response["evidence"]:
        if source["field"] == "/total_amount":
            source["line_ids"] = []
    result = enhance(baseline, image(), "image/png", lambda *_: json.dumps(response))
    assert result.pipeline_version.endswith("+vlm-fallback")


def test_missing_wrapper_has_safe_diagnostics(baseline, capsys):
    result = enhance(baseline, image(), "image/png", lambda *_: json.dumps({"PRIVATE": 1}))
    assert result.pipeline_version.endswith("+vlm-fallback")
    stderr = capsys.readouterr().err
    assert stderr.endswith("VLM_DIAG decode missing_data\n")
    assert "PRIVATE" not in stderr


def test_child_log_forwarding_rejects_arbitrary_details(caplog):
    log_diagnostics(
        "VLM_DIAG generate runtime PRIVATE\nVLM_DIAG PRIVATE schema\n"
        "VLM_SCHEMA money string_type PRIVATE\nVLM_SCHEMA PRIVATE missing\n"
    )
    assert not caplog.records


@pytest.mark.parametrize("value,expected", [(0, "0"), (110000, "110000"), (1234.25, "1234.25")])
def test_json_numeric_amounts_and_quantities_are_converted_exactly(baseline, value, expected):
    response = payload(baseline)
    response["data"]["total_amount"] = value
    response["data"]["items"] = [
        {
            "line_number": 1,
            "name": "Synthetic",
            "quantity": 0.508,
            "unit_price": 25000,
            "line_total": None,
        }
    ]
    result = VisionPayload.model_validate(normalize_payload(json.dumps(response), "VND"))
    assert result.data.total_amount == expected
    assert result.data.items[0].quantity == "0.508"
    assert result.data.items[0].unit_price == "25000"


@pytest.mark.parametrize("value", [True, -1, 0.001, 0.30000000000000004])
def test_numeric_wire_values_are_not_rounded_or_treated_as_booleans(baseline, value):
    response = payload(baseline)
    response["data"]["total_amount"] = value
    result = enhance(baseline, image(), "image/png", lambda *_: json.dumps(response))
    assert result.pipeline_version.endswith("+vlm-fallback")


def test_numeric_exponents_are_bounded_before_formatting(baseline):
    response = payload(baseline)
    response["data"]["total_amount"] = "EXPONENT"
    text = json.dumps(response).replace('"EXPONENT"', "1e99999999")
    with pytest.raises(ValueError):
        VisionPayload.model_validate(normalize_payload(text, "VND"))


@pytest.mark.parametrize("items", [None, []])
def test_no_products_and_redundant_array_evidence_are_supported(baseline, items):
    response = payload(baseline)
    response["data"]["items"] = items
    response["evidence"].append({"field": "/data/items", "line_ids": []})
    result = enhance(baseline, image(), "image/png", lambda *_: json.dumps(response))
    assert result.pipeline_version.endswith("+qwen3vl4b")
    assert result.data.items == []


def test_array_citation_cannot_replace_leaf_evidence(baseline):
    response = payload(baseline)
    response["data"]["items"] = [
        {
            "line_number": 1,
            "name": "Synthetic",
            "quantity": "1",
            "unit_price": None,
            "line_total": None,
        }
    ]
    response["evidence"].append({"field": "/data/items/0", "line_ids": ["p1-l1"]})
    result = enhance(baseline, image(), "image/png", lambda *_: json.dumps(response))
    assert result.pipeline_version.endswith("+vlm-fallback")


def test_empty_optional_scalars_are_unknown_not_invented_zero(baseline):
    response = payload(baseline)
    response["data"].update(
        merchant_tax_id="", merchant_address="  ", payment_method="", tax_amount=""
    )
    parsed = VisionPayload.model_validate(normalize_payload(json.dumps(response), "VND"))
    assert parsed.data.merchant_tax_id is None
    assert parsed.data.merchant_address is None
    assert parsed.data.payment_method is None
    assert parsed.data.tax_amount is None


def test_empty_product_name_is_still_invalid(baseline):
    response = payload(baseline)
    response["data"]["items"] = [
        {"line_number": 1, "name": "", "quantity": "1", "unit_price": None, "line_total": None}
    ]
    with pytest.raises(ValueError):
        VisionPayload.model_validate(normalize_payload(json.dumps(response), "VND"))


def test_schema_diagnostics_never_include_property_names_or_values(baseline, capsys, caplog):
    response = payload(baseline)
    response["data"]["PRIVATE_PROPERTY"] = "PRIVATE_VALUE"
    enhance(baseline, image(), "image/png", lambda *_: json.dumps(response))
    stderr = capsys.readouterr().err
    log_diagnostics(stderr)
    assert "VLM_SCHEMA data extra_forbidden" in stderr
    assert "category=data type=extra_forbidden" in caplog.text
    assert "PRIVATE" not in stderr + caplog.text


def test_benchmark_rejects_user_documents():
    from worker.benchmark import benchmark

    for request in (
        {"content": "PRIVATE"},
        {"job_id": "PRIVATE"},
        {"fixture": "synthetic-receipt-v1", "url": "PRIVATE"},
    ):
        with pytest.raises(ValueError, match="Only the bundled synthetic fixture"):
            benchmark(request)


def test_benchmark_returns_only_fixed_synthetic_model_output(baseline, monkeypatch):
    from worker import benchmark as module

    original = json.dumps(payload(baseline))
    monkeypatch.setattr(module, "run_pipeline", lambda *_: baseline)
    monkeypatch.setattr(module.vision, "generate", lambda *_: original)
    monkeypatch.setenv("EXTRACTION_BACKEND", "qwen_vl")
    result = module.benchmark({"fixture": "synthetic-receipt-v1"})
    assert result["synthetic_model_output"] == original
    assert result["candidate"]["pipeline_version"].endswith("+qwen3vl4b")
    assert result["fixture_sha256"] == module.FIXTURE_HASH
    import os

    assert os.environ["EXTRACTION_BACKEND"] == "qwen_vl"


def test_recorded_gpu_output_replays_against_same_fixture_local_ocr():
    examples = Path(__file__).parents[2] / "contracts/examples"
    # Real recorded GPU text; OCR is a local replay of the identical bundled PNG
    # and the same Paddle models, not a new GPU run or an accuracy benchmark.
    baseline = ExtractionResult.model_validate_json(
        (examples / "vlm.synthetic.baseline.json").read_text(encoding="utf-8")
    )
    raw = (examples / "vlm.synthetic.raw.json").read_text(encoding="utf-8")
    content = (Path(__file__).parents[2] / "worker/fixtures/synthetic-receipt.png").read_bytes()
    result = enhance(baseline, content, "image/png", lambda *_: raw)
    assert result.pipeline_version.endswith("+qwen3vl4b")
    assert [i.name for i in result.data.items] == ["Sữa tươi", "Táo đỏ"]
    assert [i.unit for i in result.data.items] == ["hộp", "kg"]
    assert result.data.total_amount == "99000"
    assert result.data.tax_amount == "9000"
    assert result.data.payment_method == "Tiền mặt"
    assert result.data.merchant_address == "123 đường Minh Hoa, Quận 1"
    assert not any(w.code in {"total_mismatch", "item_total_mismatch"} for w in result.warnings)


def test_normalization_preserves_arithmetic_disagreement():
    examples = Path(__file__).parents[2] / "contracts/examples"
    baseline = ExtractionResult.model_validate_json(
        (examples / "vlm.synthetic.baseline.json").read_text(encoding="utf-8")
    )
    response = json.loads((examples / "vlm.synthetic.raw.json").read_text(encoding="utf-8"))
    response["data"]["total_amount"] = "98.000"
    result = enhance(baseline, image(), "image/png", lambda *_: json.dumps(response))
    assert result.pipeline_version.endswith("+qwen3vl4b")
    assert result.data.total_amount == "98000"
    assert any(w.code == "total_mismatch" for w in result.warnings)


@pytest.mark.parametrize(
    "printed,expected",
    [
        ("99.000", "99000"),
        ("99,000", "99000"),
        ("1.234,50", "1234.50"),
        ("1,234.50", "1234.50"),
        ("1234.50", "1234.50"),
        ("0.50", "0.50"),
    ],
)
def test_vnd_grouping_normalization_never_changes_canonical_decimals(baseline, printed, expected):
    response = payload(baseline)
    response["data"]["total_amount"] = printed
    response["data"]["items"] = [
        {
            "line_number": 1,
            "name": "Synthetic",
            "quantity": "0.508",
            "unit_price": None,
            "line_total": None,
        }
    ]
    parsed = VisionPayload.model_validate(normalize_payload(json.dumps(response), "VND"))
    assert parsed.data.total_amount == expected
    assert parsed.data.items[0].quantity == "0.508"


def test_currency_grouping_requires_independent_baseline_context(baseline):
    response = payload(baseline)
    response["data"]["total_amount"] = "99.000"
    # A model claim alone must not turn an ambiguous amount into VND thousands.
    assert normalize_payload(json.dumps(response), None)["data"]["total_amount"] == "99.000"
    baseline.data.currency = None
    result = enhance(baseline, image(), "image/png", lambda *_: json.dumps(response))
    assert result.pipeline_version.endswith("+vlm-fallback")


@pytest.mark.parametrize("invalid", ["0.123", "1.23.456", "-99.000", "NaN"])
def test_normalization_does_not_guess_invalid_money(baseline, invalid):
    response = payload(baseline)
    response["data"]["total_amount"] = invalid
    result = enhance(baseline, image(), "image/png", lambda *_: json.dumps(response))
    assert result.pipeline_version.endswith("+vlm-fallback")


@pytest.mark.parametrize("invalid", ["duplicate", "unknown-null", "empty-nonnull"])
def test_normalized_paths_still_require_valid_unique_sources(baseline, invalid):
    response = payload(baseline)
    first = response["evidence"][0]
    if invalid == "duplicate":
        response["evidence"].append(
            {"field": "/data" + first["field"], "line_ids": first["line_ids"]}
        )
    elif invalid == "unknown-null":
        response["evidence"].append({"field": "/data/not_a_field", "line_ids": []})
    else:
        first["line_ids"] = []
        response["data"][first["field"].removeprefix("/")] = "UNSUPPORTED VALUE"
    result = enhance(baseline, image(), "image/png", lambda *_: json.dumps(response))
    assert result.pipeline_version.endswith("+vlm-fallback")


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
