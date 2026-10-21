"""Opt-in benchmark entry point, restricted to a bundled synthetic receipt.

Never accepts user files, URLs, receipt IDs, or database tasks. Raw model output
can be inspected privately in the RunPod job response for this synthetic fixture.
Production continues to use worker.handler, which never returns raw output.
"""

import contextlib
import hashlib
import os
import sys
from pathlib import Path
from uuid import uuid4

from worker import vision
from worker.pipeline import run_pipeline

FIXTURE_HASH = "377b50859b18b2c0e5c67bdf445fe13c66995059b97e111efad8a684406a2c8d"


def benchmark(payload):
    if payload != {"fixture": "synthetic-receipt-v1"}:
        raise ValueError("Only the bundled synthetic fixture is supported")
    content = (Path(__file__).parent / "fixtures/synthetic-receipt.png").read_bytes()
    if hashlib.sha256(content).hexdigest() != FIXTURE_HASH:
        raise ValueError("Synthetic fixture integrity check failed")
    raw = []

    def capture(images, prompt):
        text = vision.generate(images, prompt)
        raw.append(text[:250_000])
        return text

    # Set rules only while obtaining a baseline, then invoke VLM exactly once.
    previous = os.environ.get("EXTRACTION_BACKEND")
    try:
        os.environ["EXTRACTION_BACKEND"] = "rules"
        with contextlib.redirect_stdout(sys.stderr):
            baseline = run_pipeline(content, "image/png", uuid4(), uuid4())
            candidate = vision.enhance(baseline, content, "image/png", capture)
    finally:
        if previous is None:
            os.environ.pop("EXTRACTION_BACKEND", None)
        else:
            os.environ["EXTRACTION_BACKEND"] = previous
    return {
        "fixture": "synthetic-receipt-v1",
        "fixture_sha256": FIXTURE_HASH,
        "baseline": baseline.model_dump(mode="json"),
        "candidate": candidate.model_dump(mode="json"),
        "synthetic_model_output": raw[0] if raw else None,
    }


def handler(job):
    return benchmark(job["input"])


if __name__ == "__main__":
    import runpod

    runpod.serverless.start({"handler": handler})
