"""The browser UI has two users, and only one of them has eyes.

This app is loaded as a web app inside the Aside browser so that Aside's
built-in AI can drive it, while a human watches the dashboard. That makes
the accessibility tree a load-bearing interface, not a courtesy: an agent
picks controls by name, so a control with no name is a control that does
not exist for it.

It was already broken, and invisibly. All ten navigation tabs — the only
way to reach nine of the ten screens — read as bare `tab [ref_3] …
tab [ref_12]` with no names, at every viewport width. The markup looked
fine and the screen looked fine; the names simply were not being computed
from the child `<span>`, so nothing on screen betrayed it.

Hence the rule these tests hold: for controls an agent must find, the name
is stated with `aria-label`, never inferred from contents.
"""

from __future__ import annotations

import re

import pytest

from ontologylab.server.app import WEB_DIR

MARKUP = (WEB_DIR / "index.html").read_text(encoding="utf-8")
SCRIPT = (WEB_DIR / "app.js").read_text(encoding="utf-8")

TAB_BUTTON_RE = re.compile(r'<button[^>]*\bclass="tab-btn[^"]*"[^>]*>')

# The ten screens, and what each is called. One name per screen, used by
# both the label an agent reads and the status bar a human reads — two
# names for one place is how an agent and its user stop understanding
# each other mid-conversation.
SCREENS = {
    "home": "홈",
    "sources": "리서치",
    "review": "검토",
    "packs": "팩",
    "mcp": "연결",
    "merge": "병합",
    "communities": "커뮤니티",
    "graph": "그래프",
    "engines": "엔진",
    "settings": "설정",
}


def _tab_buttons() -> dict[str, str]:
    found = {}
    for tag in TAB_BUTTON_RE.findall(MARKUP):
        tab = re.search(r'data-tab="(\w+)"', tag)
        if tab:
            found[tab.group(1)] = tag
    return found


# --------------------------------------------------------------------------
# What the agent can reach
# --------------------------------------------------------------------------


def test_every_screen_has_a_navigation_tab() -> None:
    assert set(_tab_buttons()) == set(SCREENS)


@pytest.mark.parametrize(("tab", "name"), sorted(SCREENS.items()))
def test_a_navigation_tab_states_its_name_rather_than_implying_it(
    tab: str, name: str
) -> None:
    """The regression that motivated this file.

    A `<span>` inside the button is not a name an agent is guaranteed to
    see — the reader used here did not derive one, and the app was
    unnavigable as a result. `aria-label` is not a fallback for the visible
    text; it is the interface.
    """
    tag = _tab_buttons()[tab]

    assert f'aria-label="{name}"' in tag


@pytest.mark.parametrize(("tab", "name"), sorted(SCREENS.items()))
def test_a_navigation_tab_names_itself_for_a_human_too(
    tab: str, name: str
) -> None:
    """The rail collapses to icons in a narrow pane, which is the pane this
    app actually runs in. Ten unlabelled glyphs is a memory test."""
    tag = _tab_buttons()[tab]

    assert f'title="{name} —' in tag, "hovering an icon must name the screen"


def test_the_icons_are_hidden_from_the_tree_they_decorate() -> None:
    """An icon that reaches the accessibility tree adds noise to the name."""
    for tag in TAB_BUTTON_RE.findall(MARKUP):
        start = MARKUP.index(tag)
        button = MARKUP[start : MARKUP.index("</button>", start)]
        assert 'aria-hidden="true"' in button


# --------------------------------------------------------------------------
# What the human can see while the agent works
# --------------------------------------------------------------------------


def test_the_status_bar_reports_location_and_activity() -> None:
    """The human is a spectator here, not the driver.

    The agent changes screens on its own, so "where am I" and "is anything
    running" cannot live inside whichever screen happens to be open — a
    research run used to be observable only from the research screen, so
    navigating away made a live job indistinguishable from no job.
    """
    assert 'id="statusbar-where"' in MARKUP
    assert 'id="statusbar-run"' in MARKUP

    # Scoped to the status bar's own element on purpose. Asserting that
    # `aria-live="polite"` appears *somewhere* in the file passes on the
    # fan-out's copy of it, so the status bar could be muted with the test
    # still green — which is what mutation testing caught it doing.
    tag = re.search(r'<div class="statusbar-activity"[^>]*>', MARKUP)
    assert tag, "the activity region must be a findable element"
    assert 'aria-live="polite"' in tag.group(0), "changes must reach a reader"


def test_the_fan_out_announces_its_own_changes() -> None:
    """The second live region, and the one that changes during a run.

    The status bar says *that* research is running; the fan-out says which
    sources answered. Muting it leaves a watcher — human or agent — polling
    the DOM to notice a source dropped out.
    """
    tag = re.search(r'<div id="research-fanout"[^>]*>', MARKUP)
    assert tag, "the fan-out must be a findable element"
    assert 'aria-live="polite"' in tag.group(0)


def test_the_location_label_uses_the_same_names_as_the_tabs() -> None:
    match = re.search(r"var SCREEN_KO = \{(.*?)\};", SCRIPT, re.S)
    assert match, "SCREEN_KO drives the status bar's location label"

    mapping = dict(re.findall(r"(\w+): \"([^\"]+)\"", match.group(1)))

    assert mapping == SCREENS


def test_the_status_bar_survives_the_narrow_pane_it_runs_in() -> None:
    """Something has to give at ~500px, and it must not be the activity.

    Shortcut hints belong to a human with a keyboard; when an agent is
    driving, what matters is that the run is still going. The counts are on
    the home board either way.
    """
    css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    narrow = css[css.index("@media (max-width: 860px)") :]
    narrow = narrow[: narrow.index("\n}\n", narrow.index(".statusbar"))]

    assert ".statusbar-keys { display: none; }" in narrow
    assert ".statusbar-activity" in narrow
    assert ".sb-run { display: none" not in narrow


# --------------------------------------------------------------------------
# State that colour alone would hide
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Row actions must name what they act on
# --------------------------------------------------------------------------


def test_a_row_action_names_the_proposal_it_would_act_on() -> None:
    """The sharpest edge in the app, given who is clicking.

    Thirteen buttons all named "승인" leave a driver nothing to choose by
    except position — and this list is sorted by confidence and re-fetched
    after every decision, so position is not stable between reading the
    page and clicking it. The product's one promise is that only what a
    person approved becomes knowledge; an approval whose target is
    ambiguous breaks that promise without any error.
    """
    for action in ("승인", "거부", "자세히", "선택"):
        assert f'"{action}: " + what' in SCRIPT or \
               f'"{action}: " + what' in SCRIPT.replace("'", '"'), \
               f"the {action} control must name its target"


def test_the_target_name_carries_both_kind_and_label() -> None:
    """`관계 A → B` and `개념 A` are different things that can share a name."""
    assert 'var what = kindKo(item.kind) + " " + label;' in SCRIPT


def test_a_control_is_not_named_by_its_own_help_text() -> None:
    """`title` is a description; readers hand it out as the name when no
    name exists, which turned the critic button into a sentence and every
    "자세히" into the same sentence."""
    assert 'aria-label="크리틱 실행"' in MARKUP
    assert 'aria-describedby="critic-run-help"' in MARKUP
    assert 'id="critic-run-help"' in MARKUP


def test_a_control_is_not_named_by_its_current_value() -> None:
    """A select named "확신도 낮은 순" tells a driver what is chosen, never
    what the control is for."""
    assert 'id="review-order" aria-label="검토 목록 정렬"' in MARKUP
    assert 'id="critic-engine" aria-label="크리틱 채점에 쓸 엔진"' in MARKUP


@pytest.mark.parametrize(
    ("element_id", "name"),
    [
        ("research-topic", "리서치 주제"),
        ("palette-input", "화면 이동 또는 개체 검색"),
        ("source-id", "키를 연결할 논문 소스"),
        ("source-key", "API 키"),
    ],
)
def test_an_input_has_a_name_and_not_merely_a_placeholder(
    element_id: str, name: str
) -> None:
    """Placeholders vanish on the first keystroke and are not names.

    These four were unnamed, and two of them are the app's main verbs: the
    research topic and the command palette.
    """
    tag = re.search(rf'<(?:input|select)[^>]*id="{element_id}"[^>]*>', MARKUP, re.S)
    if tag is None:
        tag = re.search(rf'<(?:input|select)[^>]*id="{element_id}"[^>]*?>', MARKUP)
    assert tag, f"{element_id} not found"
    assert f'aria-label="{name}"' in tag.group(0)


# --------------------------------------------------------------------------
# State that colour alone would hide
# --------------------------------------------------------------------------


def test_a_failed_source_says_so_in_text_not_only_in_colour() -> None:
    """Amber is invisible to a DOM reader and to a colour-blind user alike.

    The fan-out's whole job is to answer "why did only some sources
    answer", so the answer cannot be carried by a hue.
    """
    assert "': 답하지 않음'" in SCRIPT or '": 답하지 않음"' in SCRIPT
    assert "chip-mark" in SCRIPT, "a glyph carries it for sighted users"
    assert "aria-label='" in SCRIPT, "and the label carries it for readers"


def test_a_running_source_says_so_in_text_too() -> None:
    assert "': 질의 중'" in SCRIPT or '": 질의 중"' in SCRIPT
