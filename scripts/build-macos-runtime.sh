#!/bin/bash
# Build the deterministic Apple-Silicon PyInstaller onedir application payload.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="$ROOT/release/runtime-build.json"
SPEC="$ROOT/release/pyinstaller/ontologylab-runtime.spec"
OUT="${TMPDIR:-/tmp}/ontologylab-runtime-output"
KEEP_WORK=0

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --keep-work) KEEP_WORK=1; shift ;;
    *) echo "runtime_build_refused member=argument detail=$1" >&2; exit 2 ;;
  esac
done

[ "$(/usr/bin/uname -m)" = "arm64" ] || {
  echo "runtime_build_refused member=architecture detail=$(uname -m)" >&2
  exit 1
}
for command in uv swiftc clang codesign lipo otool node; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "runtime_build_refused member=tool detail=$command" >&2
    exit 1
  }
done

VERSION="$(ROOT="$ROOT" uv run python - <<'PY'
import os
import tomllib
from pathlib import Path
root = Path(os.environ["ROOT"])
print(tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"])
PY
)"
PYINSTALLER_VERSION="$(ROOT="$ROOT" uv run python - <<'PY'
import json
import os
from pathlib import Path
root = Path(os.environ["ROOT"])
print(json.loads((root / "release/runtime-build.json").read_text())["pyinstaller"])
PY
)"
WORK="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/ontologylab-task4-build.XXXXXX")"
cleanup() {
  if [ "$KEEP_WORK" -eq 0 ]; then rm -rf "$WORK"; fi
}
trap cleanup EXIT INT TERM

export PYTHONHASHSEED=0
export SOURCE_DATE_EPOCH=0
export PYINSTALLER_CONFIG_DIR="$WORK/pyinstaller-config"
uv run \
  --extra server --extra mcp --extra graph --extra vec --extra test \
  --with "pyinstaller==$PYINSTALLER_VERSION" \
  pyinstaller --noconfirm --clean \
  --distpath "$WORK/dist" --workpath "$WORK/work" \
  "$SPEC"

APP="$OUT/OntologyLab.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/config"
mv "$WORK/dist/ontologylab-runtime" "$APP/Contents/Resources/runtime"

SDK="$(xcrun --show-sdk-path)"
swiftc -O -target arm64-apple-macos15.0 -sdk "$SDK" \
  -framework Foundation -framework Security \
  -o "$APP/Contents/MacOS/ontologylab-supervisor" \
  "$ROOT/launcher/supervisor/main.swift" \
  "$ROOT/launcher/supervisor/Supervisor.swift" \
  "$ROOT/launcher/supervisor/Protocol.swift" \
  "$ROOT/launcher/supervisor/ProcessSupport.swift" \
  "$ROOT/launcher/supervisor/StateSupport.swift"
clang -O2 -arch arm64 -mmacosx-version-min=15.0 \
  -o "$APP/Contents/Resources/ontologylab-serve-desktop" \
  "$ROOT/release/pyinstaller/backend-shim.c"
swiftc -O -target arm64-apple-macos15.0 -sdk "$SDK" \
  -framework Foundation -framework Security \
  -o "$APP/Contents/Resources/keychain-helper" \
  "$ROOT/launcher/keychain-helper.swift"
codesign --force --sign - \
  --identifier town.neobio.ontologylab.keychain-helper \
  "$APP/Contents/Resources/keychain-helper"
codesign --verify "$APP/Contents/Resources/keychain-helper"
codesign -d -r- "$APP/Contents/Resources/keychain-helper" 2>&1 \
  | sed -n 's/^# designated => //p' \
  > "$APP/Contents/Resources/keychain-helper.requirement"
test -s "$APP/Contents/Resources/keychain-helper.requirement"

install -m 0644 "$ROOT/release/mcp-config.json" "$APP/Contents/Resources/config/mcp.json"
install -m 0644 "$ROOT/ontologylab/storage-compatibility.json" \
  "$APP/Contents/Resources/storage-compatibility.json"
install -m 0644 "$CONTRACT" "$APP/Contents/Resources/runtime/runtime-build.json"
install -m 0644 "$ROOT/release/release-policy.json" "$APP/Contents/Resources/runtime/release-policy.json"
# Editable-install provenance is a build-host detail and an illegal runtime fallback.
find "$APP/Contents/Resources/runtime" -type f -name direct_url.json -delete
printf '{"schema":"ontologylab.runtime-version.v1","version":"%s"}\n' "$VERSION" \
  > "$APP/Contents/Resources/runtime/version-receipt.json"

uv run python "$ROOT/release/pyinstaller/rewrite_zip.py" \
  "$APP/Contents/Resources/runtime"
uv run python "$ROOT/release/pyinstaller/write_sbom.py" \
  "$APP/Contents/Resources/runtime" "$ROOT/LICENSE" "$VERSION"
uv run python "$ROOT/release/pyinstaller/inspect_macho.py" \
  "$APP/Contents/Resources/runtime" \
  "$APP/Contents/Resources/runtime/native-inventory.json"
uv run python "$ROOT/release/pyinstaller/write_manifest.py" \
  "$APP/Contents/Resources/runtime" "$VERSION" "$CONTRACT"
uv run python "$ROOT/release/pyinstaller/normalize_manifest.py" \
  "$APP/Contents/Resources/runtime/runtime-manifest.json" \
  "$APP/Contents/Resources/normalized-unsigned-manifest.json"
uv run python "$ROOT/release/pyinstaller/inspect_macho.py" \
  "$APP" "$APP/Contents/Resources/native-inventory.json"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>OntologyLab</string>
<key>CFBundleDisplayName</key><string>OntologyLab</string>
<key>CFBundleIdentifier</key><string>town.neobio.ontologylab.launcher</string>
<key>CFBundleVersion</key><string>$VERSION</string>
<key>CFBundleShortVersionString</key><string>$VERSION</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleExecutable</key><string>ontologylab-supervisor</string>
<key>LSMinimumSystemVersion</key><string>15.0</string>
<key>LSArchitecturePriority</key><array><string>arm64</string></array>
<key>LSUIElement</key><true/>
</dict></plist>
PLIST

while IFS= read -r -d '' javascript; do node --check "$javascript" >/dev/null; done \
  < <(find "$APP/Contents/Resources/runtime" -type f -name '*.js' -print0)
if grep -R -a -l -F "$ROOT" "$APP" | grep -q .; then
  echo "runtime_build_refused member=checkout_path detail=$ROOT" >&2
  exit 1
fi
if grep -R -a -l -F '/.venv/' "$APP" | grep -q .; then
  echo "runtime_build_refused member=venv_path detail=payload" >&2
  exit 1
fi

touch -t 198001010000 "$APP"
printf 'runtime_build_complete app=%s version=%s format=onedir architecture=arm64\n' "$APP" "$VERSION"
