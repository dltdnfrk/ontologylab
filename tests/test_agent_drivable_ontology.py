"""The ontology screen has two users, and only one of them has eyes.

Same contract as `test_agent_drivable_ui.py`: a control an agent must find
states its own name, and every server-derived string reaches the DOM through
`escapeHtml` or `textContent`. Term definitions, aliases and xref labels are
reviewed prose from external authorities — untrusted by construction.

The byte scan is here rather than in a linter because the defect it catches
is invisible in an editor: a literal NUL inside a JS string literal, used as
a map-key separator.
"""

from __future__ import annotations

import re

import pytest

from ontologylab import web_assets

MARKUP = web_assets.read_asset_text("index.html")
SCRIPT = web_assets.read_asset_text("app.js")
STYLE = web_assets.read_asset_text("style.css")

# Every value the ontology panel renders that an authority or a reviewer
# typed. If one of these is interpolated raw, the panel executes it.
UNTRUSTED = (
    "preferred_label",
    "definition",
    "change_reason",
    "reviewer",
    "provenance",
    "authority",
    "external_id",
    "source_uri",
)


def _js_files() -> list[str]:
    return sorted(
        path for path in web_assets.asset_paths() if path.endswith(".js")
    )


# --------------------------------------------------------------------------
# The NUL byte
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", _js_files())
def test_no_shipped_script_carries_a_control_byte_separator(name: str) -> None:
    """Given the shipped scripts, When scanned, Then no NUL byte is present.

    `s.tool + "\\0" + s.action` embedded a raw 0x00 in the source. It keys a
    map, so it never renders — but it makes the file binary to git, grep and
    every editor that reads it, and a copy through any text pipeline silently
    changes the key. An escaped textual separator does the same job.
    """
    data = web_assets.read_asset_bytes(name)

    assert b"\x00" not in data, f"{name} carries a literal NUL byte"


def test_the_step_key_separator_is_an_escaped_textual_one() -> None:
    """Given the step de-duplication key, Then it uses a visible separator."""
    match = re.search(r'var key = s\.action === "phase"\s*\n?\s*\? "phase:" \+ '
                      r's\.detail : s\.tool \+ (.+?) \+ s\.action;', SCRIPT)

    assert match, "the step key must stay one readable expression"
    assert match.group(1) == '"\\u0000"', "separator must be escaped, not literal"


# --------------------------------------------------------------------------
# What the agent can reach
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("element_id", "name"),
    [
        ("term-select", "온톨로지 용어"),
        ("term-rename-label", "새 대표 이름"),
        ("term-rename-language", "언어 태그"),
        ("term-reviewer", "검토자"),
        ("term-provenance", "출처 기록"),
        ("term-lifecycle-state", "수명주기 상태"),
        ("term-lifecycle-replacement", "대체 용어"),
        ("term-lifecycle-reason", "변경 사유"),
        ("term-alias-label", "추가할 별칭"),
        ("term-alias-language", "별칭 언어 태그"),
        ("term-alias-kind", "별칭 종류"),
    ],
)
def test_an_ontology_control_states_its_own_name(
    element_id: str, name: str
) -> None:
    """Given a lifecycle control, Then its name is stated, not inferred."""
    tag = re.search(
        rf'<(?:input|select|textarea)[^>]*id="{element_id}"[^>]*>', MARKUP, re.S
    )

    assert tag, f"{element_id} not found in the ontology panel"
    assert f'aria-label="{name}"' in tag.group(0)


@pytest.mark.parametrize(
    "action_id",
    ["term-rename-btn", "term-lifecycle-btn", "term-alias-btn"],
)
def test_every_mutation_is_a_button_a_person_presses(action_id: str) -> None:
    """Given a state change, Then it is behind an explicit named control."""
    tag = re.search(rf'<button[^>]*id="{action_id}"[^>]*>', MARKUP)

    assert tag, f"{action_id} must exist as a button"
    assert "aria-label=" in tag.group(0)


def test_the_ontology_panel_reports_outcomes_to_a_reader() -> None:
    """Given a result region, Then a screen reader is told it changed."""
    tag = re.search(r'<div[^>]*id="term-result"[^>]*>', MARKUP)

    assert tag, "the ontology panel needs a result region"
    assert 'aria-live="polite"' in tag.group(0)


# --------------------------------------------------------------------------
# Untrusted text
# --------------------------------------------------------------------------


def _ontology_source() -> str:
    """The whole lifecycle block, inner comments and all.

    Sliced to the next top-level section banner rather than to the next
    comment: stopping at the first `/*` inside the block would leave most of
    the rendering code unexamined, and an unescaped value there would pass.
    """
    start = SCRIPT.index("/* -- 온톨로지 용어 수명주기")
    end = SCRIPT.index("/* ---- M8 dashboard", start)
    block = SCRIPT[start:end]
    assert block.count("function ") >= 8, "the slice must cover the renderers"
    return block


@pytest.mark.parametrize("field", UNTRUSTED)
def test_a_server_value_is_never_concatenated_straight_into_markup(
    field: str,
) -> None:
    """Given a reviewed field, When rendered, Then it is not glued to a tag.

    A cheap shape check, deliberately: it catches the careless
    `"<p>" + term.definition` and nothing subtler. Proving this text is
    actually inert is the browser evidence's job — see
    `.omo/evidence/ontology-platform-roadmap/task-6-xss-*`, where the real
    panel renders a hostile definition, alias and xref and the resulting DOM
    is inspected for injected elements and fired handlers.
    """
    source = _ontology_source()
    glued = re.compile(rf'["\']\s*\+\s*[\w.]*\.{field}\b')

    assert f".{field}" in source, f"{field} is never read — probe watches nothing"
    assert not glued.search(source), (
        f"{field} is concatenated into markup without escapeHtml"
    )


def test_the_panel_renders_terms_without_document_write_or_eval() -> None:
    """Given untrusted prose, Then no execution sink is anywhere near it."""
    source = _ontology_source()

    for sink in ("eval(", "document.write(", "new Function(", "outerHTML"):
        assert sink not in source


def test_the_term_option_list_is_built_as_text_not_markup() -> None:
    """Given a malicious preferred label, Then the picker cannot execute it.

    An `<option>` built by string concatenation is the easiest place to lose
    escaping, because the value looks inert.
    """
    source = _ontology_source()

    assert "createElement(\"option\")" in source
    assert re.search(r'option\.textContent = ', source), (
        "option labels must be assigned as text"
    )


# --------------------------------------------------------------------------
# The screen it lives on
# --------------------------------------------------------------------------


def test_the_lifecycle_panel_sits_in_the_settings_ontology_area() -> None:
    """Given the existing schema panel, Then the new one is beside it."""
    schema_at = MARKUP.index('id="schema-installed"')
    panel_at = MARKUP.index('id="term-panel"')
    settings_end = MARKUP.index('</section>', schema_at)

    assert schema_at < panel_at < settings_end


def test_the_panel_uses_the_design_system_rather_than_new_magic_numbers() -> None:
    """Given the term styles, Then spacing and colour come from tokens.

    A one-off hex or a hand-picked pixel gap is how a design system stops
    being one, and this panel is the newest surface in the app.
    """
    marker = "/* ---------- ontology term lifecycle ---------- */"
    block = STYLE[STYLE.index(marker) + len(marker):]
    end = block.find("\n/* ----------")
    block = block if end < 0 else block[:end]
    # An at-rule prelude is not a declaration: the 860px breakpoint is the
    # one this stylesheet already narrows at, and repeating it is what keeps
    # the panel collapsing with everything else rather than on its own.
    declarations = re.sub(r"@media[^{]*\{", "", block)

    for value in re.findall(r"[\w-]+:\s*([^;]+);", declarations):
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", value), value
        assert "var(--" in value or not re.search(r"\b\d+px\b", value), value
    assert "@media (max-width: 860px)" in block, "reuse the shared breakpoint"
