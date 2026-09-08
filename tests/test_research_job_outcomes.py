"""Execute shipped job listeners/renderers with controlled UI wire fixtures.

These are not observations of a real HTTP server or a naturally locked DB.
The real apiSend, showResult, error surface and bound-chat update run here;
the browser and resource-independent sibling panels are the test doubles.
"""

from __future__ import annotations

import pytest

from tests.research_job_outcome_support import _cancel_response, _run, _terminal


@pytest.mark.parametrize(
    ("status", "body", "retry_after", "variant"),
    [
        (503, {"ok": False, "error_kind": "busy", "detail": "다른 실행이 저장소를 사용하고 있습니다."}, "5", "busy"),
        (200, {"ok": False, "error_kind": "busy", "detail": "busy", "retry_after": 5}, None, "busy"),
        (401, {"ok": False, "error_kind": "unauthenticated", "detail": "session required"}, None, "auth"),
        (403, {"detail": {"field": "job_id", "detail": "request refused"}}, None, "forbidden"),
    ],
)
def test_cancel_refusal_preserves_active_job(status, body, retry_after, variant) -> None:
    out = _run(_cancel_response(body, status, retry_after) + """
console.log(JSON.stringify({during: during, after: snapshot(), requests: requests}));
""")
    assert out["during"]["cancelDisabled"] is True
    after = out["after"]
    assert after["jobId"] == "g003-job", "refusal is not an ended job"
    assert after["submitDisabled"] is True
    assert after["cancelDisabled"] is False
    assert after["cancelHidden"] is False
    assert after["bound"] == ["g003-job"]
    assert after["errorVariant"] == variant
    assert "이미 종료된" not in after["form"]
    assert "[object Object]" not in after["form"]
    if variant == "busy":
        assert "5" in after["errorHelp"], "the server's non-default delay must be visible"
        assert after["errorHelpHidden"] is False, "retry text in a hidden element is not visible guidance"
        assert after["errorHelpExpanded"] == "true"
    else:
        assert after["errorHelpHidden"] is True
        assert after["errorHelpExpanded"] == "false"
    assert out["requests"] == [{"path": "/api/jobs/g003-job/cancel", "method": "POST", "body": {}}]


@pytest.mark.parametrize("wait", [None, "0", "5"])
def test_cancel_retry_help_keeps_manual_toggle_in_sync(wait: str | None) -> None:
    out = _run(_cancel_response(
        {"ok": False, "error_kind": "busy", "detail": "QA busy refusal"}, 503, wait
    ) + """
var initial = snapshot();
var toggle = $("#research-result").children[0].querySelector(".error-help-toggle");
await errorClick({target: toggle});
var toggled = snapshot();
await errorClick({target: toggle});
console.log(JSON.stringify({initial: initial, toggled: toggled, restored: snapshot()}));
""")
    for stage in ("initial", "restored"):
        assert out[stage]["errorHelpHidden"] is (wait is None)
        assert out[stage]["errorHelpExpanded"] == ("false" if wait is None else "true")
        if wait is not None:
            assert wait in out[stage]["errorHelp"]
    assert out["toggled"]["errorHelpHidden"] is (wait is not None)
    assert out["toggled"]["errorHelpExpanded"] == ("true" if wait is None else "false")
    assert out["restored"]["jobId"] == "g003-job"
    assert out["restored"]["errorVariant"] == "busy"


def test_accepted_cancel_waits_for_the_terminal_job_event() -> None:
    out = _run(_cancel_response({"ok": True, "cancelled": True}) + """
var accepted = snapshot();
applyJobs([{job_id: "g003-job", kind: "research", status: "cancelled", steps: [], totals: {}}]);
console.log(JSON.stringify({during: during, accepted: accepted, ended: snapshot()}));
""")
    accepted = out["accepted"]
    assert accepted["jobId"] == "g003-job"
    assert accepted["submitDisabled"] is True
    assert accepted["cancelHidden"] is False
    assert accepted["cancelDisabled"] is False
    assert accepted["bound"] == ["g003-job"]
    assert accepted["clearedTimers"] == []
    assert accepted["announcements"] == ""
    assert "중단을 요청" in accepted["form"]
    assert out["ended"]["jobId"] is None
    assert out["ended"]["submitDisabled"] is False
    assert out["ended"]["cancelHidden"] is True
    assert out["ended"]["bound"] == []
    assert out["ended"]["clearedTimers"] == [17]


@pytest.mark.parametrize("reason", ["unknown job", "already complete", "already cancelled"])
def test_ended_or_unknown_cancel_is_a_legitimate_success_response(reason: str) -> None:
    out = _run(_cancel_response({"ok": True, "cancelled": False, "reason": reason}) + """
console.log(JSON.stringify(snapshot()));
""")
    assert out["jobId"] is None
    assert out["submitDisabled"] is False
    assert out["cancelHidden"] is True
    assert out["cancelDisabled"] is False
    assert out["errorVariant"] is None
    assert "이미 종료된" in out["form"]


@pytest.mark.parametrize("status", ["failed", "cancelled"])
@pytest.mark.parametrize("totals", [
    {"nodes_new": 7, "edges_new": 3},
    {"nodes_merged": 5, "edges_merged": 2},
    {"nodes_new": 1, "nodes_merged": 4, "edges_new": 2, "edges_merged": 6},
])
def test_bound_chat_preserves_retained_results(status: str, totals: dict) -> None:
    out = _terminal(status, totals)
    assert out["totals"] in out["ended"]["chat"], "chat must not discard retained counts"
    assert out["totals"] in out["ended"]["form"]
    assert out["label"] in out["ended"]["chat"]
    assert out["label"] in out["ended"]["form"]
    assert "[object Object]" not in out["ended"]["chat"] + out["ended"]["form"]
    assert out["formReview"] is out["chatReview"] is True
    assert out["navigations"] == ["review", "review"]
    assert "proposals" in out["ended"]["reloads"]
    assert out["retry"] is True
    assert out["retries"] == ['RateLimiter <again> & "retry"']
    assert out["ended"]["bound"] == []
    assert out["ended"]["clearedTimers"] == [17]


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_zero_result_terminal_job_does_not_invent_review_work(status: str) -> None:
    out = _terminal(status, {})
    assert out["label"] in out["ended"]["chat"]
    assert out["label"] in out["ended"]["form"]
    assert out["formReview"] is out["chatReview"] is False
    assert out["navigations"] == []
    assert out["retry"] is True
    assert out["retries"] == ['RateLimiter <again> & "retry"']


@pytest.mark.parametrize("totals", [{}, {"nodes_new": 7, "edges_new": 3}])
def test_complete_job_preserves_existing_review_and_count_behavior(totals: dict) -> None:
    out = _terminal("complete", totals)
    added = totals.get("nodes_new", 0) + totals.get("edges_new", 0)
    assert f"<strong>{added}건</strong>" in out["ended"]["chat"]
    assert out["totals"] in out["ended"]["form"]
    assert out["formReview"] is out["chatReview"] is True
    assert out["navigations"] == ["review", "review"]
    assert out["retry"] is False
    assert out["running"]["bound"] == ["g003-job"]
    assert out["running"]["clearedTimers"] == []
    assert out["running"]["announcements"] == ""
    assert out["ended"]["bound"] == []
    assert out["ended"]["clearedTimers"] == [17]
    assert str(added) in out["ended"]["announcements"]


def test_known_service_failure_uses_the_existing_localized_label() -> None:
    out = _run("""
var detail = "enrichment failed: ResourceError <private>";
var answer = chatAnswer({result: {kind: "blocked", error_kind: "failed", detail: detail}});
console.log(JSON.stringify({answer: answer, label: statusKo("failed"), detail: escapeHtml(detail)}));
""")
    assert "<strong>" + out["label"] + "</strong>" in out["answer"]
    assert out["detail"] in out["answer"], "the technical refusal detail must remain available"
