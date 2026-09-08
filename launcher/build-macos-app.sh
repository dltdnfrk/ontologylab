#!/bin/bash
# Assemble the Task-3 macOS bundle around the bundle-relative Swift supervisor.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT="$HOME/Applications"
BACKEND="${ONTOLOGYLAB_DESKTOP_BACKEND-}"
APP_NAME="ontologylab"

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2;;
    --backend) BACKEND="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

if [ -z "$BACKEND" ] || [ ! -x "$BACKEND" ]; then
  echo "error: provide an executable desktop backend with --backend or ONTOLOGYLAB_DESKTOP_BACKEND" >&2
  exit 1
fi
if ! command -v swiftc >/dev/null 2>&1; then
  echo "error: swiftc not found; install Xcode Command Line Tools" >&2
  exit 1
fi
if ! command -v codesign >/dev/null 2>&1; then
  echo "error: codesign not found; cannot sign the Keychain helper" >&2
  exit 1
fi

VERSION="$(/usr/bin/awk -F'"' '/^version = "/ { print $2; exit }' "$REPO/pyproject.toml")"
if [ -z "$VERSION" ]; then
  echo "error: application version is unavailable from pyproject.toml" >&2
  exit 1
fi

APP="$OUT/$APP_NAME.app"
CONTENTS="$APP/Contents"
rm -rf "$APP"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"
SDK="$(/usr/bin/xcrun --show-sdk-path)"

SUPERVISOR="$CONTENTS/MacOS/ontologylab-supervisor"
if ! swiftc -O \
  -sdk "$SDK" \
  -framework Foundation \
  -framework Security \
  -o "$SUPERVISOR" \
  "$SCRIPT_DIR/supervisor/main.swift" \
  "$SCRIPT_DIR/supervisor/Supervisor.swift" \
  "$SCRIPT_DIR/supervisor/Protocol.swift" \
  "$SCRIPT_DIR/supervisor/ProcessSupport.swift" \
  "$SCRIPT_DIR/supervisor/StateSupport.swift" \
  "$SCRIPT_DIR/supervisor/StorageHolders.swift" \
  "$SCRIPT_DIR/supervisor/StorageQuiescence.swift"
then
  echo "error: failed to compile ontologylab supervisor" >&2
  exit 1
fi
chmod 0755 "$SUPERVISOR"
install -m 0755 "$BACKEND" "$CONTENTS/Resources/ontologylab-serve-desktop"
install -m 0644 "$REPO/ontologylab/storage-compatibility.json" \
  "$CONTENTS/Resources/storage-compatibility.json"

# The signed helper contract remains unchanged: the backend receives both the
# bundle-relative helper path and its designated requirement from the parent.
HELPER_SRC="$SCRIPT_DIR/keychain-helper.swift"
HELPER_BIN="$CONTENTS/Resources/keychain-helper"
if [ ! -f "$HELPER_SRC" ]; then
  echo "error: missing Keychain helper source: $HELPER_SRC" >&2
  exit 1
fi
if ! swiftc -O \
  -sdk "$SDK" \
  -framework Security \
  -framework Foundation \
  -o "$HELPER_BIN" \
  "$HELPER_SRC"
then
  echo "error: failed to compile Keychain helper" >&2
  exit 1
fi
chmod 0755 "$HELPER_BIN"
IDENTITY="${CODESIGN_IDENTITY-}"
if [ -z "$IDENTITY" ]; then
  IDENTITY="$(/usr/bin/security find-identity -v -p codesigning 2>/dev/null \
    | /usr/bin/sed -n 's/^[[:space:]]*[0-9][0-9]*)[[:space:]]\{1,\}[A-F0-9]\{40,\}[[:space:]]\{1,\}"\(.*\)"$/\1/p' \
    | /usr/bin/head -n 1)"
fi
if [ -z "$IDENTITY" ]; then
  IDENTITY="-"
fi
if ! /usr/bin/codesign --force --sign "$IDENTITY" \
  --identifier "town.neobio.ontologylab.keychain-helper" \
  "$HELPER_BIN"
then
  echo "error: Keychain helper signing is unavailable or refused" >&2
  exit 1
fi
if ! /usr/bin/codesign --verify "$HELPER_BIN"; then
  echo "error: Keychain helper signature could not be verified" >&2
  exit 1
fi
if ! HELPER_REQUIREMENT_OUTPUT="$(
  /usr/bin/codesign -d -r- "$HELPER_BIN" 2>&1
)"; then
  echo "error: Keychain helper designated requirement is unavailable" >&2
  exit 1
fi
if ! HELPER_REQUIREMENT="$(
  printf '%s\n' "$HELPER_REQUIREMENT_OUTPUT" \
    | /bin/bash "$SCRIPT_DIR/normalize-designated-requirement.sh"
)"; then
  echo "error: Keychain helper designated requirement is unavailable" >&2
  exit 1
fi
printf '%s\n' "$HELPER_REQUIREMENT" \
  > "$CONTENTS/Resources/keychain-helper.requirement"
chmod 0644 "$CONTENTS/Resources/keychain-helper.requirement"

cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>ontologylab</string>
  <key>CFBundleIdentifier</key><string>town.neobio.ontologylab.launcher</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>ontologylab-supervisor</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST
chmod 0644 "$CONTENTS/Info.plist"
touch "$APP"

echo "Built: $APP"
echo "Version: $VERSION"
