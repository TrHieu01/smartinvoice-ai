"""RunPod entry point. Database leases fence duplicate and late invocations."""

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import sys

import httpx

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError
from backend.app.core.supabase import SupabaseGateway
from backend.app.schemas.contracts import ExtractionResult, ProcessTask


def log_diagnostics(stderr):
    for category, kind in re.findall(
        r"^VLM_SCHEMA (money|quantity|date|evidence|data|other) "
        r"(string_type|string_pattern_mismatch|missing|list_type|too_short|too_long|"
        r"extra_forbidden|literal_error|value_error|json_invalid|int_parsing|other)$",
        stderr,
        re.MULTILINE,
    )[:10]:
        logging.getLogger(__name__).warning("VLM schema category=%s type=%s", category, kind)
    for stage, reason in re.findall(
        r"^VLM_DIAG (prepare|generate|decode|evidence|validate) "
        r"(runtime|schema|missing_data|missing_evidence|invalid)$",
        stderr,
        re.MULTILINE,
    )[:5]:
        logging.getLogger(__name__).warning("VLM fallback stage=%s reason=%s", stage, reason)


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
            if os.getenv("EXTRACTION_BACKEND") == "qwen_vl":
                from worker.resident import pipeline

                response = await asyncio.to_thread(
                    pipeline.run,
                    dict(
                        content=content,
                        mime=row["content_type"],
                        receipt_id=row["id"],
                        job_id=str(task.job_id),
                    ),
                )
                log_diagnostics("\n".join(response["diagnostics"]))
                result = ExtractionResult.model_validate_json(response["result"])
            else:
                run = await asyncio.to_thread(
                    subprocess.run,
                    [sys.executable, "-m", "worker.process"],
                    input=json.dumps(message),
                    text=True,
                    capture_output=True,
                    timeout=240,
                    check=True,
                )
                log_diagnostics(run.stderr)
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
                if isinstance(error, (subprocess.TimeoutExpired, TimeoutError))
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
