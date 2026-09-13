import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from ontologylab.web_assets import asset_paths


def test_fresh_wheel_contains_and_verifies_every_dashboard_asset(tmp_path: Path) -> None:
    """A checkout must not conceal missing package-data globs or stale build files."""
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copyfile(root / name, source / name)
    shutil.copytree(
        root / "ontologylab", source / "ontologylab",
        ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
    )

    build = subprocess.run(
        ["uv", "build", "--offline", "--wheel", "--out-dir", str(tmp_path / "dist"), str(source)],
        cwd=root, capture_output=True, text=True, timeout=120, check=False,
    )

    assert build.returncode == 0, build.stderr
    wheel, = (tmp_path / "dist").glob("*.whl")
    expected = {"ontologylab/web/" + path for path in asset_paths()}
    with zipfile.ZipFile(wheel) as archive:
        assert expected <= set(archive.namelist())
    probe = subprocess.run(
        [sys.executable, "-I", "-c",
         "import json,sys; sys.path.insert(0,sys.argv[1]); "
         "from ontologylab.web_assets import verify_assets; "
         "print(json.dumps(sorted(verify_assets().content)))", str(wheel)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert json.loads(probe.stdout) == sorted(asset_paths())
