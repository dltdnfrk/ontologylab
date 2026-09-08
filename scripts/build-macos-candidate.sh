#!/bin/bash
# Build one receipt-bound Task 11 candidate without credentials or network resolution.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_OFFLINE=1
export UV_FROZEN=1
export PYTHONHASHSEED=0
export SOURCE_DATE_EPOCH=0

# candidate_cli enforces subprocess timeout, interruption cleanup, source revalidation,
# atomic receipt, and the final read-only byte freeze.
exec uv run --frozen --offline python -m release.candidate_cli \
  --root "$ROOT" \
  --timeout-seconds "${ONTOLOGYLAB_CANDIDATE_TIMEOUT_SECONDS:-1800}" \
  "$@"
