"""Child-process JSON boundary. Reserve stdout for the validated result."""

import base64
import contextlib
import json
import sys


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        from worker.pipeline import run_pipeline

        result = run_pipeline(
            base64.b64decode(payload["content"], validate=True),
            payload["mime"],
            payload["receipt_id"],
            payload["job_id"],
        )
    sys.stdout.write(result.model_dump_json())
