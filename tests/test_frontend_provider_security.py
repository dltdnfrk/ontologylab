"""Frontend secret posture for the provider form (React source).

The retired vanilla ``web/app.js`` this used to read is gone; the contract it
guarded is not. What matters now: a pasted key leaves the browser exactly
once (the POST body), is never rendered back, and the input is password-type
so it is not echoed on screen.
"""

from pathlib import Path

_ENGINES = (
    Path(__file__).resolve().parents[1]
    / "frontend"
    / "src"
    / "pages"
    / "Engines.tsx"
)


def _source() -> str:
    return _ENGINES.read_text(encoding="utf-8")


def test_key_field_is_password_type_and_never_rendered() -> None:
    src = _source()
    assert 'id="provider-api-key"' in src
    assert 'type="password"' in src
    # The value must only flow into the POST body — never into rendered
    # output. `value={apiKey}` is the controlled-input binding, which is
    # fine; what must not exist is the key interpolated into visible JSX
    # (a badge, a table cell, a detail line).
    assert "{apiKey}" not in src.replace("value={apiKey}", "")
    # No key field is ever rendered — key_present/key_location are the only
    # provider.key* members the UI may read.
    import re

    assert not re.search(r"\{provider\.key(?!_present|_location)", src)


def test_key_is_sent_once_and_cleared() -> None:
    src = _source()
    # Exactly one outbound use: the create-provider POST body.
    assert src.count("key: apiKey") == 1
    # And the form clears it on reset so it does not linger in state.
    assert 'setApiKey("")' in src


def test_oauth_connect_uses_redirect_not_key_entry() -> None:
    src = _source()
    # The OpenRouter connect button navigates to the server-issued auth URL;
    # it never collects or posts a key itself.
    assert "window.location.assign(result.auth_url)" in src
    assert "/providers/openrouter/connect" in src
