"""Read-only closure and exact-value secret checks for the three trial roots."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

prefix = Path(sys.argv[1])
roots = [Path(f"{prefix}-r{number}") for number in (1, 2, 3)]
roots.append(Path(f"{prefix}-tests"))
paths = {path for root in roots for path in root.rglob("*") if path.is_file()}
paths.update(Path("evidence").glob("polarity-trial-3-2026-09-27*"))
paths.update(Path("evidence").glob("polarity3_*.py"))
receipt = Path(
    "/Users/hyunjun/Documents/MUNI/ontologylab/.omo/evidence/"
    "task-26-ontologylab-completion.md"
)
if receipt.exists():
    paths.add(receipt)
key = os.environ["GOOGLE_API_KEY"]
assert key
matches = 0
for path in sorted(paths):
    result = subprocess.run(
        ["grep", "-a", "-F", "-c", "-f", "/dev/stdin", "--", str(path)],
        input=key + "\n", capture_output=True, text=True, timeout=30,
    )
    assert result.returncode in (0, 1), f"grep failed on {path}"
    matches += int(result.stdout.strip())
ports = []
hashes = {}
for root in roots[:3]:
    http = json.loads((root / "http-receipt.json").read_text())
    port = http["port"]
    assert port != 8799 and http["server_pid"] not in (87584, 3284)
    with socket.socket() as sock:
        sock.settimeout(3)
        code = sock.connect_ex(("127.0.0.1", port))
    result = subprocess.run(
        ["ps", "-p", str(http["server_pid"]), "-o", "pid=,command="],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 1 and not result.stdout.strip()
    assert code == 61, (port, code)
    ports.append({"port": port, "connect_ex": code, "pid_absent": True})
    for name in ("kg.sqlite", "kg.sqlite-wal", "kg.sqlite-shm"):
        path = root / name
        if path.exists():
            hashes[str(path)] = {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
print(json.dumps({
    "secret_scan": {"files": len(paths), "matches": matches,
                    "method": "grep -a -F -c -f /dev/stdin -- FILE",
                    "all_exit_codes_checked": True},
    "ports_closed": ports,
    "closed_store_hashes": hashes,
}, sort_keys=True))
raise SystemExit(0 if matches == 0 else 1)
