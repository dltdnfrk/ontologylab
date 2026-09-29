"""Bounded trial harness; no replacement extraction attempts."""
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import time
from typing import Any

import httpx

ROOT = Path.cwd()
PYTHON = str(ROOT / ".venv/bin/python")
PREFIX = "/private/tmp/ol-polarity4-20260927T064204Z"
KEY = os.environ.get("GOOGLE_API_KEY", "")


def safe(text):
    return text.replace(KEY, "[REDACTED]") if KEY else text


def emit(payload):
    print(safe(json.dumps(payload, sort_keys=True)), flush=True)


def save(path, payload):
    path.write_text(safe(json.dumps(payload, indent=2, sort_keys=True)) + "\n")


async def cli(*args, timeout=30):
    proc = await asyncio.create_subprocess_exec(
        PYTHON, "-m", "ontologylab.main", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.terminate()
        output, _ = await asyncio.wait_for(proc.communicate(), 15)
        return {"exit": proc.returncode, "timeout": True,
                "output": safe(output.decode())}
    return {"exit": proc.returncode, "output": safe(output.decode())}


async def register(directory):
    from ontologylab.providers import dedicated_api_key_env
    base = "https://generativelanguage.googleapis.com/v1beta/openai"
    name = dedicated_api_key_env("gemini", base)
    assert KEY and os.environ.get(name) == KEY
    result = await cli(
        "provider", "add", "--id", "gemini", "--kind", "openai",
        "--base-url", base, "--api-key-env", name,
        "--models", "gemini-3.6-flash", "--data-dir", str(directory),
    )
    assert result["exit"] == 0, result
    return result


async def preflight():
    directory = Path(PREFIX + "-r1")
    directory.mkdir(exist_ok=False)
    report: dict[str, Any] = {"registration": await register(directory)}
    start = time.monotonic()
    report["provider_test"] = await cli(
        "provider", "test", "--id", "gemini", "--model", "gemini-3.6-flash",
        "--data-dir", str(directory), timeout=320,
    )
    report["elapsed_s"] = time.monotonic() - start
    save(directory / "preflight.json", report)
    emit(report)
    return 0 if report["provider_test"]["exit"] == 0 else 2


async def trial(number):
    directory = Path(PREFIX + f"-r{number}")
    if number == 1:
        assert json.loads((directory / "preflight.json").read_text())[
            "provider_test"]["exit"] == 0
        assert not (directory / "kg.sqlite").exists()
    else:
        directory.mkdir(exist_ok=False)
        await register(directory)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    assert port != 8799
    proc = await asyncio.create_subprocess_exec(
        PYTHON, "-m", "ontologylab.serve", "--port", str(port),
        "--data-dir", str(directory), "--packs-dir", str(directory / "packs"),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.pid not in (87584, 3284)
    ready = asyncio.Event()
    report: dict[str, Any] = {"run": number, "data_dir": str(directory), "port": port,
              "server_pid": proc.pid, "server_argv": "ontologylab.serve",
              "started_at": time.time()}
    job_id = None

    async def drain():
        assert proc.stdout is not None
        with (directory / "server.log").open("w") as log:
            async for line in proc.stdout:
                text = safe(line.decode(errors="replace"))
                log.write(text)
                log.flush()
                if "Uvicorn running on" in text:
                    ready.set()

    drainer = asyncio.create_task(drain())
    try:
        await asyncio.wait_for(ready.wait(), 45)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False,
        ) as client:
            (await client.get("/")).raise_for_status()
            response = await client.post("/api/schema", json={"preset": "agrochem-v2"})
            response.raise_for_status()
            report["schema"] = response.json()
            files = sorted((ROOT / "tests/gold/agrochem-polarity/sources/full").glob("*.txt"))
            assert len(files) == 5
            response = await client.post("/api/collect", json={"files": list(map(str, files))})
            response.raise_for_status()
            report["collect"] = response.json()
            assert report["collect"]["ok"] and report["collect"]["created"] == 5
            response = await client.get("/api/documents")
            response.raise_for_status()
            documents = response.json()["documents"]
            report["documents"] = documents
            assert len(documents) == 5
            assert all(d["content_kind"] == "fulltext" and d["extractable"] for d in documents)
            body = {
                "engine": "api:gemini", "model": "gemini-3.6-flash",
                "doc_ids": [d["id"] for d in documents],
                "max_engine_calls": 60, "seed": 7,
            }
            report["request"] = body
            try:
                async with asyncio.timeout(14220):
                    async with client.stream("GET", "/api/jobs/stream", timeout=None) as stream:
                        stream.raise_for_status()
                        async for line in stream.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            snapshot = json.loads(line[6:])
                            if job_id is None:
                                assert snapshot["jobs"] == []
                                response = await client.post("/api/extract", json=body)
                                response.raise_for_status()
                                job_id = response.json()["job_id"]
                                report["job_id"] = job_id
                                emit({"event": "started", "run": number, "job_id": job_id,
                                      "port": port, "pid": proc.pid})
                                continue
                            job = next((j for j in snapshot["jobs"]
                                        if j["job_id"] == job_id), None)
                            if job:
                                response = await client.get(f"/api/jobs/{job_id}")
                                response.raise_for_status()
                                job = response.json()
                            if job and job["status"] != "running":
                                report["terminal"] = job
                                break
                        else:
                            raise RuntimeError("SSE ended without terminal state")
            except (TimeoutError, httpx.HTTPError, RuntimeError) as exc:
                report["interrupted"] = type(exc).__name__
                if job_id:
                    response = await client.post(f"/api/jobs/{job_id}/cancel")
                    report["cancel"] = {"http_status": response.status_code,
                                        "response": response.json()}
                raise
            response = await client.get("/api/claims/stages?include_proposed=true")
            response.raise_for_status()
            report["stages"] = response.json()
    except Exception as exc:
        report["driver_error"] = safe(f"{type(exc).__name__}: {exc}")
    finally:
        if proc.returncode is None:
            proc.terminate()
        report["server_exit"] = await asyncio.wait_for(proc.wait(), 30)
        await drainer
        with socket.socket() as check:
            check.settimeout(3)
            report["port_connect_ex"] = check.connect_ex(("127.0.0.1", port))
        assert report["port_connect_ex"] != 0
        report["finished_at"] = time.time()
        save(directory / "http-receipt.json", report)
        emit({"event": "finished", "run": number, "port": port,
              "port_connect_ex": report["port_connect_ex"],
              "terminal": report.get("terminal"),
              "driver_error": report.get("driver_error")})
    return int("driver_error" in report)


async def main():
    if sys.argv[1] == "all":
        if await preflight():
            return 2
        results = await asyncio.gather(*(trial(number) for number in (1, 2, 3)))
        return max(results)
    return await preflight() if sys.argv[1] == "preflight" else await trial(int(sys.argv[1]))


raise SystemExit(asyncio.run(main()))
