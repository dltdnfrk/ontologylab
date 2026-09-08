from ontologylab import web_assets


def test_provider_form_has_no_user_editable_env_field() -> None:
    index = web_assets.read_asset_text("index.html")
    app = web_assets.read_asset_text("app.js")

    assert 'id="provider-api-key-env"' not in index
    assert "provider-api-key-env" not in app
