"""One reusable, killable pipeline process per worker; model caches survive jobs."""

import atexit
import contextlib
import io
import multiprocessing
import os
import re
import threading

DIAGNOSTIC = re.compile(r"^VLM_(?:DIAG|SCHEMA) [a-z_]+ [a-z_]+$")


class Diagnostics(io.TextIOBase):
    def __init__(self):
        self.pending = ""
        self.lines = []

    def write(self, text):
        # Native logs and receipt contents are never returned to the parent.
        self.pending += text[:4096]
        parts = self.pending.split("\n")
        self.pending = parts.pop()[-4096:]
        for line in parts:
            if len(self.lines) < 30 and DIAGNOSTIC.fullmatch(line):
                self.lines.append(line)
        return len(text)


def serve(connection):
    with open(os.devnull, "w") as null:
        os.dup2(null.fileno(), 1)
        os.dup2(null.fileno(), 2)
    while True:
        try:
            message = connection.recv()
        except EOFError:
            return
        diagnostics = Diagnostics()
        try:
            with contextlib.redirect_stdout(diagnostics), contextlib.redirect_stderr(diagnostics):
                from worker.pipeline import run_pipeline

                result = run_pipeline(**message)
            connection.send({"result": result.model_dump_json(), "diagnostics": diagnostics.lines})
        except Exception:
            connection.send({"error": "processing_failed"})


class ResidentPipeline:
    def __init__(self, target=serve):
        self.target = target
        self.lock = threading.Lock()
        self.child = None
        self.connection = None

    def close(self):
        if self.child is not None:
            if self.child.is_alive():
                self.child.kill()
            self.child.join(timeout=5)
            self.child.close()
            self.child = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def run(self, message, timeout=240):
        # RunPod concurrency remains one; this also protects against accidental
        # concurrent callers consuming another job's response.
        with self.lock:
            try:
                if self.child is None or not self.child.is_alive():
                    self.close()
                    context = multiprocessing.get_context("spawn")
                    self.connection, remote = context.Pipe()
                    self.child = context.Process(target=self.target, args=(remote,), daemon=True)
                    self.child.start()
                    remote.close()
                self.connection.send(message)
                if not self.connection.poll(timeout):
                    raise TimeoutError("pipeline deadline")
                response = self.connection.recv()
                if "error" in response:
                    raise RuntimeError("pipeline failed")
                return response
            except BaseException:
                self.close()
                raise


pipeline = ResidentPipeline()
atexit.register(pipeline.close)
