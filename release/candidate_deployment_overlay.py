"""Derived builder overlay for the standalone internal deployment executable."""

from __future__ import annotations

from typing import Final

from .candidate_types import CandidateRefused

_RUNTIME_BUILD_ANCHOR: Final = '  "$SPEC"\n'
_APP_ASSEMBLY_ANCHOR: Final = (
    'mv "$WORK/dist/ontologylab-runtime" "$APP/Contents/Resources/runtime"\n'
)
_FINALIZE_ANCHOR: Final = 'touch -t 198001010000 "$APP"\n'
_DEPLOYMENT_BUILD: Final = """DEPLOYMENT_SPEC="$ROOT/release/pyinstaller/ontologylab-internal-deployment.spec"
uv run --extra server --with "pyinstaller==$PYINSTALLER_VERSION" \\
  pyinstaller --noconfirm --clean --distpath "$WORK/deployment-dist" \\
  --workpath "$WORK/deployment-work" "$DEPLOYMENT_SPEC"
"""
_DEPLOYMENT_ASSEMBLY: Final = """mv "$WORK/deployment-dist/ontologylab-internal-deploy" \\
  "$APP/Contents/MacOS/ontologylab-internal-deploy"
DEPLOYMENT_SHA256="$(/usr/bin/shasum -a 256 \\
  "$APP/Contents/MacOS/ontologylab-internal-deploy" | /usr/bin/awk '{print $1}')"
printf '{"architecture":"arm64","executable_path":"Contents/MacOS/ontologylab-internal-deploy","executable_sha256":"%s","schema":"ontologylab.internal-deployment-build.v1","version":"%s"}\\n' \\
  "$DEPLOYMENT_SHA256" "$VERSION" > "$APP/Contents/Resources/internal-deployment.json"
"""
_APP_SIGNING: Final = """codesign --force --sign - --timestamp=none "$APP"
codesign --verify --deep --strict "$APP"
"""


def patch_deployment_builder(text: str) -> str:
    """Add the independently specified executable build and app assembly steps."""
    if text.count(_RUNTIME_BUILD_ANCHOR) != 1:
        raise CandidateRefused("builder_overlay_anchor", "runtime-build")
    if text.count(_APP_ASSEMBLY_ANCHOR) != 1:
        raise CandidateRefused("builder_overlay_anchor", "app-assembly")
    if text.count(_FINALIZE_ANCHOR) != 1:
        raise CandidateRefused("builder_overlay_anchor", "app-finalize")
    return (
        text.replace(
            _RUNTIME_BUILD_ANCHOR,
            _RUNTIME_BUILD_ANCHOR + _DEPLOYMENT_BUILD,
        )
        .replace(
            _APP_ASSEMBLY_ANCHOR,
            _APP_ASSEMBLY_ANCHOR + _DEPLOYMENT_ASSEMBLY,
        )
        .replace(
            _FINALIZE_ANCHOR,
            _APP_SIGNING + _FINALIZE_ANCHOR,
        )
    )
