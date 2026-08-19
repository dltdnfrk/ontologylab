"""Review-queue auto-activation: conformal/calibration badges switch on with data.

The queue must not hard-wire the statistical triage: it renders the
conformal "safe to review last" badge and the calibrated confidence only
when /api/review/triage and /api/review/calibration report `available`
(19+ rejected / 20+ reviewed). These tests pin the two pure helpers the
switch is built from, executed under node against the real app.js code.
"""

from __future__ import annotations

from tests.test_ui_failure_honesty import _extract, _run_js


def test_calibrated_confidence_step_function() -> None:
    script = (
        _extract("calibratedConfidence")
        + "\nvar curve = {boundaries: [0.5, 0.8], values: [0.6, 0.95]};\n"
        + "console.log(JSON.stringify({"
        + "hi: calibratedConfidence(curve, 0.9),"
        + "mid: calibratedConfidence(curve, 0.7),"
        + "lo: calibratedConfidence(curve, 0.1),"
        + "edge: calibratedConfidence(curve, 0.8),"
        + "none: calibratedConfidence(curve, null),"
        + "off: calibratedConfidence(null, 0.9)"
        + "}));"
    )
    out = _run_js(script)
    assert out == {
        "hi": 0.95,
        "mid": 0.6,
        "lo": 0.6,
        "edge": 0.95,
        "none": None,
        "off": None,
    }


def test_safe_to_review_last_gate() -> None:
    script = (
        _extract("safeToReviewLast")
        + "\nvar tri = {available: true, threshold: 0.3};\n"
        + "console.log(JSON.stringify({"
        + "above: safeToReviewLast(tri, 0.5),"
        + "below: safeToReviewLast(tri, 0.2),"
        + "missing_score: safeToReviewLast(tri, null),"
        + "unavailable: safeToReviewLast(null, 0.9),"
        + "not_available: safeToReviewLast({available: false, threshold: 0.3}, 0.9)"
        + "}));"
    )
    out = _run_js(script)
    assert out == {
        "above": True,
        "below": False,
        "missing_score": False,
        "unavailable": False,
        "not_available": False,
    }
