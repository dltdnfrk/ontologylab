from pathlib import Path


def test_provider_form_has_no_user_editable_env_field() -> None:
    root = Path(__file__).resolve().parents[1]
    index = (root / "web" / "index.html").read_text(encoding="utf-8")
    app = (root / "web" / "app.js").read_text(encoding="utf-8")

    assert 'id="provider-api-key-env"' not in index
    assert "provider-api-key-env" not in app
