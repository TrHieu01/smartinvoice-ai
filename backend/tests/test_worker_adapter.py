"""The SDK invokes the worker from an already running asyncio loop."""

import asyncio
from importlib import import_module
from uuid import uuid4


def test_runpod_handler_inside_existing_loop(monkeypatch):
    adapter = import_module("worker.handler")
    payload = {"job_id": str(uuid4())}

    async def process(value):
        assert value == payload
        await asyncio.sleep(0)
        return {"decision": "saved"}

    monkeypatch.setattr(adapter, "process", process)

    async def invoke_like_sdk():
        assert await adapter.handler({"id": "provider-job", "input": payload}) == {
            "decision": "saved"
        }

    asyncio.run(invoke_like_sdk())
