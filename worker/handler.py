"""RunPod entry point. Database leases fence duplicate and late invocations."""

import asyncio
import hashlib
import json
import subprocess
import sys

import httpx

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError
from backend.app.core.supabase import SupabaseGateway
from backend.app.schemas.contracts import ExtractionResult, ProcessTask


async def process(payload):
    task = ProcessTask.model_validate(payload)
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        gateway = SupabaseGateway(settings, client)
        claim = await gateway.rpc("si_claim", {"p_job": str(task.job_id)})
        if claim["decision"] != "claimed":
            return {"decision": claim["decision"]}
        row, token = claim["receipt"], claim["lease_token"]
        try:
            content = await gateway.download(row["storage_path"], settings.max_upload_bytes)
            if hashlib.sha256(content).hexdigest() != row["file_sha256"]:
                raise AppError("file_integrity_failed")
            # The child can be killed even when a native OCR library hangs.
            import base64

            message = dict(
                content=base64.b64encode(content).decode(),
                mime=row["content_type"],
                receipt_id=row["id"],
                job_id=str(task.job_id),
            )
            run = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "worker.process"],
                input=json.dumps(message),
                text=True,
                capture_output=True,
                timeout=240,
                check=True,
            )
            result = ExtractionResult.model_validate_json(run.stdout)
            saved = await gateway.rpc(
                "si_complete",
                {
                    "p_job": str(task.job_id),
                    "p_token": token,
                    "p_result": result.model_dump(mode="json"),
                },
            )
            return {"decision": "saved" if saved else "stale"}
        except Exception as error:
            code = (
                error.code
                if isinstance(error, AppError)
                else "processing_timeout"
                if isinstance(error, subprocess.TimeoutExpired)
                else "processing_failed"
            )
            # Store only a stable code; subprocess output can contain receipt text.
            await gateway.rpc(
                "si_fail", {"p_job": str(task.job_id), "p_token": token, "p_code": code}
            )
            return {"decision": "failed", "error_code": code}


async def handler(job):
    # RunPod 1.10 invokes handlers inside its existing event loop.
    return await process(job["input"])


if __name__ == "__main__":
    import runpod

    runpod.serverless.start({"handler": handler})
