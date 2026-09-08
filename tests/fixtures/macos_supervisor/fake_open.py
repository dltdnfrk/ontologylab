#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys

print("OPEN:" + json.dumps(sys.argv[1:], separators=(",", ":")), flush=True)
if os.environ.get("FAKE_OPEN_ASIDE", "success") == "fail" and "-b" in sys.argv:
    raise SystemExit(1)
raise SystemExit(0)
