"""Exercise actual process reuse, crash recovery and hard timeout without a GPU."""

import json
import os
import time
from uuid import uuid4

import pymupdf
import pytest

from worker.resident import ResidentPipeline


def fake_pipeline(connection):
    count = 0
    while True:
        try:
            message = connection.recv()
        except EOFError:
            return
        if message == "crash":
            os._exit(1)
        if message == "hang":
            time.sleep(20)
        count += 1
        connection.send({"result": {"pid": os.getpid(), "count": count}, "diagnostics": []})


def test_reuses_same_child_and_process_local_cache_between_jobs():
    runner = ResidentPipeline(target=fake_pipeline)
    try:
        first = runner.run({}, timeout=10)["result"]
        second = runner.run({}, timeout=10)["result"]
        assert first["pid"] == second["pid"]
        assert [first["count"], second["count"]] == [1, 2]
    finally:
        runner.close()


@pytest.mark.parametrize("failure", ["hang", "crash"])
def test_timeout_or_crash_kills_child_and_next_job_restarts(failure):
    runner = ResidentPipeline(target=fake_pipeline)
    try:
        old = runner.run({}, timeout=10)["result"]["pid"]
        with pytest.raises((TimeoutError, EOFError, ConnectionError)):
            runner.run(failure, timeout=0.1)
        assert runner.child is None
        restarted = runner.run({}, timeout=10)["result"]
        assert restarted["pid"] != old and restarted["count"] == 1
    finally:
        runner.close()


def test_real_pdf_pipeline_round_trips_twice_in_resident_process(monkeypatch):
    monkeypatch.setenv("EXTRACTION_BACKEND", "rules")
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((40, 40), "SYNTHETIC SHOP\nTotal: 100,000 VND")
        content = document.tobytes()
    runner = ResidentPipeline()
    try:
        for _ in range(2):
            job = str(uuid4())
            response = runner.run(
                dict(content=content, mime="application/pdf", receipt_id=str(uuid4()), job_id=job),
                timeout=20,
            )
            result = json.loads(response["result"])
            assert result["job_id"] == job
            assert result["data"]["total_amount"] == "100000.00"
    finally:
        runner.close()
