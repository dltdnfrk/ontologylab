#!/bin/bash
set -euo pipefail

/usr/bin/awk '
  /^(# )?designated => / {
    count += 1
    requirement = $0
    sub(/^# designated => /, "", requirement)
    sub(/^designated => /, "", requirement)
  }
  END {
    if (count != 1 || requirement == "") exit 1
    print requirement
  }
'
