#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import signal
import socket
import sqlite3
import sys
from pathlib import Path

mode = os.environ.get("FAKE_BACKEND_MODE", "valid")
if mode == "decoy":
    print(f"DECOY_PID:{os.getpid()}", flush=True)
    signal.pause()
    raise SystemExit(0)

print(f"BACKEND_PID:{os.getpid()}", file=sys.stderr, flush=True)
if mode == "immediate_exit":
    raise SystemExit(23)

listener_fd = int(os.environ["ONTOLOGYLAB_LISTENER_FD"])
ready_fd = int(os.environ["ONTOLOGYLAB_READY_FD"])
listener = socket.socket(fileno=listener_fd)
port = listener.getsockname()[1]
databases: list[sqlite3.Connection] = []
if mode == "hold_sqlite":
    data_dir = Path(os.environ["ONTOLOGYLAB_APP_SUPPORT_ROOT"]) / "data"
    for name in ("kg.sqlite", "chat.sqlite"):
        connection = sqlite3.connect(data_dir / name)
        connection.execute("SELECT name FROM sqlite_schema LIMIT 1").fetchone()
        databases.append(connection)
payload: dict[str, str | int] = {
    "schema": "ontologylab-ready-v1",
    "version": os.environ["ONTOLOGYLAB_APP_VERSION"],
    "port": port,
    "nonce": os.environ["ONTOLOGYLAB_NONCE"],
    "storage_version": os.environ["ONTOLOGYLAB_STORAGE_VERSION"],
}

if mode == "eof":
    os.close(ready_fd)
    raise SystemExit(24)
if mode == "timeout":
    signal.pause()
    raise SystemExit(0)
if mode == "malformed":
    line = b"{not-json}\n"
elif mode == "duplicate":
    line = (
        json.dumps(payload, separators=(",", ":"))
        .replace(
            '"schema":"ontologylab-ready-v1"',
            '"schema":"ontologylab-ready-v1","schema":"ontologylab-ready-v1"',
        )
        .encode()
        + b"\n"
    )
elif mode == "trailing":
    line = json.dumps(payload, separators=(",", ":")).encode() + b" true\n"
elif mode == "extra_line":
    line = json.dumps(payload, separators=(",", ":")).encode() + b"\n{}\n"
else:
    mismatch = {
        "version_mismatch": ("version", "9.9.9"),
        "storage_mismatch": ("storage_version", "999"),
        "nonce_mismatch": ("nonce", "0" * 32),
        "port_mismatch": ("port", 1 if port != 1 else 2),
        "type_mismatch": ("port", str(port)),
    }.get(mode)
    if mismatch is not None:
        payload[mismatch[0]] = mismatch[1]
    line = json.dumps(payload, separators=(",", ":")).encode() + b"\n"

os.write(ready_fd, line)
os.close(ready_fd)
if mode in {"hold", "hold_sqlite", "ignore_term"}:
    if mode == "ignore_term":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print("BACKEND_IGNORING_TERM", file=sys.stderr, flush=True)
    signal.pause()
for database in databases:
    database.close()
listener.close()
