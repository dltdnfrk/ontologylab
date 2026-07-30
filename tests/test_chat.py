"""A chat answer is a claim until it says what produced it.

Moving the primary surface into a conversation moved work behind a
sentence: the person types a topic and a paragraph comes back, with the
engine call, six network requests and a store read all invisible. That is
the arrangement in which a tool quietly answers from the wrong source and
nobody can tell. So every reply carries `steps`, and every reply is
written down.

Three properties are load-bearing here:

* The model picks a name out of a fixed table. It never returns code, a
  URL, or a query to run, so what a sentence can reach is an edit to
  `intent.ACTIONS` rather than an emergent property of a prompt.
* Research from chat goes through `start_research`, inheriting every gate
  instead of becoming a second, laxer entrance to the same fan-out.
* A mutating action is never run by classification alone.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from ontologylab import paths
from ontologylab.chatstore import MAX_TURNS, ChatStore
from ontologylab.intent import ACTIONS, Intent, requires_confirmation
from ontologylab.server import routes
from ontologylab.server.app import create_app


@pytest.fixture()
def client(tmp_path):
    os.environ.setdefault("ONTOLOGYLAB_ALLOWED_HOSTS", "testserver")
    data_dir = tmp_path / "data"
    routes.attach_data_dir(data_dir)
    return TestClient(create_app(data_dir=data_dir, packs_dir=tmp_path / "packs"))


def _classify_as(monkeypatch, intent: Intent) -> None:
    async def fake(message, engine, model=None):
        return intent

    monkeypatch.setattr("ontologylab.intent.classify", fake, raising=True)


# --------------------------------------------------------------------------
# What a sentence is allowed to reach
# --------------------------------------------------------------------------


def test_the_confirmation_gate_reads_the_table_at_call_time() -> None:
    """The first shape of this was a frozen snapshot and it tested green
    against a hand-typed set.

    With exactly one mutating action, "the set of confirming actions" and
    "a set containing build_pack" are the same value, so a test comparing
    them could not tell a re-derivation from a copy — and a newly added
    mutating action would quietly not be gated. Adding one here proves the
    gate is reading the table rather than a copy of it.
    """
    from ontologylab.intent import Action

    ACTIONS["wipe_graph"] = Action("Delete everything", confirm=True)
    try:
        assert requires_confirmation("wipe_graph") is True
    finally:
        del ACTIONS["wipe_graph"]

    assert requires_confirmation("status") is False
    assert requires_confirmation("nonexistent") is False


def test_an_invented_parameter_never_reaches_a_handler() -> None:
    """The table decides what chat can reach, not the prompt.

    A stray key surviving here is the difference between a fixed surface
    and one the model can widen by writing a different JSON object.
    """
    from ontologylab.intent import _clean_params

    cleaned = _clean_params(
        "research", {"topic": "TP53", "sources": ["evil"], "limit": 9999}
    )

    assert cleaned == {"topic": "TP53"}


def test_a_reply_that_is_not_an_object_is_an_answer_not_a_crash() -> None:
    """Engines here are CLI-backed and sometimes fence or preface output.

    A classification failure has to come back as `unknown` carrying the
    reason, because a 500 gives the person nothing to act on.
    """
    import asyncio

    class Rambling:
        async def generate(self, prompt, *, model=None):
            return "I think you want to search for papers!", {}

    intent = asyncio.run(
        __import__("ontologylab.intent", fromlist=["classify"]).classify(
            "찾아줘", Rambling()
        )
    )

    assert intent.action == "unknown"
    assert intent.error


def test_a_fenced_object_is_still_read() -> None:
    """Refusing a code fence would turn a cosmetic difference into
    "I didn't understand you"."""
    import asyncio

    class Fencing:
        async def generate(self, prompt, *, model=None):
            return '```json\n{"action": "status", "reading": "상태"}\n```', {}

    intent = asyncio.run(
        __import__("ontologylab.intent", fromlist=["classify"]).classify(
            "상태", Fencing()
        )
    )

    assert intent.action == "status"
    assert intent.error is None


# --------------------------------------------------------------------------
# Every reply says what it used
# --------------------------------------------------------------------------


def test_a_read_only_answer_reports_the_engine_and_the_store(client) -> None:
    body = client.post(
        "/api/chat", json={"message": "지금 상태 알려줘", "engine": "mock"}
    ).json()

    assert [(s["tool"], s["action"]) for s in body["steps"]] == [
        ("mock", "classify"),
        ("store", "read"),
    ]


def test_the_engine_that_read_the_message_is_named(client) -> None:
    """Which model read the sentence is the first thing to check when a
    request was misread, and it is not recoverable afterwards."""
    body = client.post(
        "/api/chat", json={"message": "지금 상태 알려줘", "engine": "mock"}
    ).json()

    assert body["steps"][0]["tool"] == "mock"
    assert body["steps"][0]["detail"] == "status"


def test_a_failed_classification_does_not_quote_the_reason(
    client, monkeypatch
) -> None:
    """The step says it failed; it does not repeat the exception.

    Exception text in this codebase can carry a request URL, and a request
    URL can carry an API key — the same reason `fetch_sources` reports a
    failure *kind* to the log and sends the exception to provenance.
    """
    _classify_as(
        monkeypatch,
        Intent("unknown", error="401 from https://api.example/v1?key=sk-secret"),
    )

    body = client.post(
        "/api/chat", json={"message": "뭐든", "engine": "mock"}
    ).json()

    step = body["steps"][0]
    assert step["status"] == "failed"
    assert "sk-secret" not in step["detail"]


def test_an_engine_that_will_not_load_still_answers_with_a_step(
    client,
) -> None:
    body = client.post(
        "/api/chat", json={"message": "상태", "engine": "nope"}
    ).json()

    assert body["ok"] is False
    assert body["steps"] == [
        {"tool": "nope", "action": "classify", "status": "failed",
         "detail": "unavailable"}
    ]


# --------------------------------------------------------------------------
# Nothing mutates on a classification alone
# --------------------------------------------------------------------------


def test_a_mutating_action_is_not_run_by_classification(client) -> None:
    body = client.post(
        "/api/chat", json={"message": "팩 만들어줘", "engine": "mock"}
    ).json()

    assert body["result"] == {"kind": "confirm", "action": "build_pack"}
    assert body["needs_confirmation"] is True
    # Nothing was built: no pack id came back to point at.
    assert "pack_id" not in body["result"]


def test_an_unanswered_confirmation_is_not_a_turn(client) -> None:
    """A stored `confirm` turn would come back on every reload showing its
    button — a second, stale way to authorise the same change, sitting
    above the place where it was already decided."""
    body = client.post(
        "/api/chat", json={"message": "팩 만들어줘", "engine": "mock"}
    ).json()

    assert body["result"]["kind"] == "confirm"
    assert body.get("turn_id") is None
    assert client.get("/api/chat/history").json()["turns"] == []


# --------------------------------------------------------------------------
# Research from chat is the same research
# --------------------------------------------------------------------------


def test_research_from_chat_actually_starts_a_run(client, monkeypatch) -> None:
    _classify_as(
        monkeypatch, Intent("research", params={"topic": "TP53"}, reading="…")
    )
    started = {}

    def fake_start(body):
        started["topic"] = body.topic
        started["engine"] = body.engine
        return {"ok": True, "job_id": "research-1", "status": "running"}

    monkeypatch.setattr(routes, "start_research", fake_start, raising=True)

    body = client.post(
        "/api/chat", json={"message": "TP53 찾아줘", "engine": "mock"}
    ).json()

    assert body["result"] == {
        "kind": "job", "job_id": "research-1", "topic": "TP53"
    }
    # The topic reaches the runner intact, and the run uses the engine the
    # conversation is using rather than the request schema's default.
    assert started == {"topic": "TP53", "engine": "mock"}


def test_research_from_chat_is_refused_by_the_same_gates(
    client, monkeypatch
) -> None:
    """The gates are `start_research`'s, not re-implemented here.

    Asserted through the offline kill switch because it is the cheapest
    real gate to trip: if chat had grown its own path to `fetch_sources`,
    this request would have gone out.
    """
    _classify_as(
        monkeypatch, Intent("research", params={"topic": "TP53"}, reading="…")
    )
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")

    body = client.post(
        "/api/chat", json={"message": "TP53 찾아줘", "engine": "mock"}
    ).json()

    assert body["result"]["kind"] == "blocked"
    assert body["result"]["error_kind"] == "offline"
    assert body["steps"][-1] == {
        "tool": "ontologylab", "action": "research", "status": "failed",
        "detail": "offline",
    }


def test_a_refusal_is_not_reported_as_a_started_run(
    client, monkeypatch
) -> None:
    """The failure mode worth naming: a chat bubble that says "asking…" and
    binds to a job id that does not exist."""
    _classify_as(
        monkeypatch, Intent("research", params={"topic": "TP53"}, reading="…")
    )
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")

    body = client.post(
        "/api/chat", json={"message": "TP53 찾아줘", "engine": "mock"}
    ).json()

    assert "job_id" not in body["result"]


def test_research_without_a_topic_asks_rather_than_searching(
    client, monkeypatch
) -> None:
    _classify_as(monkeypatch, Intent("research", params={}, reading="…"))

    body = client.post(
        "/api/chat", json={"message": "찾아줘", "engine": "mock"}
    ).json()

    assert body["result"]["error_kind"] == "shape"
    assert body["steps"][-1]["detail"] == "no_topic"


# --------------------------------------------------------------------------
# The transcript
# --------------------------------------------------------------------------


def test_a_turn_is_stored_as_answered_not_as_a_recipe(client) -> None:
    """Recomputing on read is the tempting shortcut and the wrong one: a
    `status` turn re-run tomorrow answers about tomorrow's store, so the
    transcript would quietly rewrite its own history every time it loaded.
    """
    client.post("/api/chat", json={"message": "지금 상태 알려줘", "engine": "mock"})
    first = client.get("/api/chat/history").json()["turns"][0]["result"]

    client.post("/api/chat", json={"message": "지금 상태 알려줘", "engine": "mock"})
    turns = client.get("/api/chat/history").json()["turns"]

    assert turns[0]["result"] == first, "the first answer was rewritten"
    assert turns[0]["steps"], "the trace has to survive the reload too"


def test_turns_come_back_oldest_first(client, monkeypatch) -> None:
    _classify_as(monkeypatch, Intent("status"))
    for n in range(3):
        client.post("/api/chat", json={"message": f"질문 {n}", "engine": "mock"})

    turns = client.get("/api/chat/history").json()["turns"]

    assert [t["message"] for t in turns] == ["질문 0", "질문 1", "질문 2"]


def test_a_turn_that_started_a_run_carries_its_job(client, monkeypatch) -> None:
    _classify_as(
        monkeypatch, Intent("research", params={"topic": "TP53"}, reading="…")
    )
    monkeypatch.setattr(
        routes, "start_research",
        lambda body: {"ok": True, "job_id": "research-1"}, raising=True,
    )

    client.post("/api/chat", json={"message": "TP53 찾아줘", "engine": "mock"})

    assert client.get("/api/chat/history").json()["turns"][0]["job_id"] == (
        "research-1"
    )
    # And the run can name the question, which is the direction people ask
    # in: they find a document, not a job id.
    asked = client.get("/api/jobs/research-1/asked").json()
    assert asked["turn"]["message"] == "TP53 찾아줘"


def test_a_run_started_from_the_form_reports_an_absence_not_an_error(
    client,
) -> None:
    response = client.get("/api/jobs/research-from-the-form/asked")

    assert response.status_code == 200
    assert response.json() == {"turn": None}


def test_a_failed_turn_is_stored_too(client, monkeypatch) -> None:
    """A transcript that silently drops its failures reads as though
    nothing was ever tried."""
    _classify_as(
        monkeypatch, Intent("research", params={"topic": "TP53"}, reading="…")
    )
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")

    client.post("/api/chat", json={"message": "TP53 찾아줘", "engine": "mock"})
    turns = client.get("/api/chat/history").json()["turns"]

    assert len(turns) == 1
    assert turns[0]["result"]["kind"] == "blocked"


def test_a_transcript_that_cannot_be_written_does_not_break_the_answer(
    client, monkeypatch
) -> None:
    """The record of the feature is worth less than the feature.

    A chat that 500s because its own history file is locked has traded the
    thing the person asked for against the note that they asked for it.
    """
    def boom(*a, **k):
        raise OSError("database is locked")

    monkeypatch.setattr(routes, "_open_chat_store", boom, raising=True)

    body = client.post(
        "/api/chat", json={"message": "지금 상태 알려줘", "engine": "mock"}
    ).json()

    assert body["ok"] is True
    assert body["result"]["kind"] == "status"
    assert body["turn_id"] is None


def test_the_conversation_can_be_forgotten(client) -> None:
    """A local-first tool that keeps a transcript owes the person a way to
    end it — and must not take the knowledge with it."""
    client.post("/api/chat", json={"message": "지금 상태 알려줘", "engine": "mock"})

    cleared = client.request("DELETE", "/api/chat/history").json()

    assert cleared == {"ok": True, "cleared": 1}
    assert client.get("/api/chat/history").json()["turns"] == []
    assert client.get("/api/proposals").status_code == 200


# --------------------------------------------------------------------------
# Containment
# --------------------------------------------------------------------------


def test_the_transcript_is_not_in_the_knowledge_graph(tmp_path) -> None:
    """A different file, not a table someone remembered not to copy.

    `build_pack` assembles a pack from an explicit list of tables. A chat
    table living in `kg.sqlite` would be one line away from shipping in
    something the person hands to a colleague, and the line that adds it
    looks exactly like the lines that belong.
    """
    assert paths.chat_db_path(tmp_path) != paths.kg_db_path(tmp_path)

    store = ChatStore.open(paths.chat_db_path(tmp_path))
    store.record(message="비밀", action="status", reading="", result={},
                 steps=[])
    store.close()

    kg = paths.kg_db_path(tmp_path)
    assert "비밀".encode() not in (kg.read_bytes() if kg.exists() else b"")


def test_the_log_is_capped(tmp_path) -> None:
    store = ChatStore.open(tmp_path / "chat.sqlite")
    for n in range(MAX_TURNS + 10):
        store.record(message=f"질문 {n}", action="status", reading="",
                     result={}, steps=[], created_ts=float(n))

    turns = store.history(limit=MAX_TURNS + 50)

    assert len(turns) == MAX_TURNS
    # The oldest went, not the newest: the cap follows the visible order.
    assert turns[0]["message"] == "질문 10"
    store.close()


def test_a_corrupted_row_does_not_end_the_conversation(tmp_path) -> None:
    """The turn still happened. Showing the message without its answer
    beats dropping the transcript at the damaged row."""
    store = ChatStore.open(tmp_path / "chat.sqlite")
    store.record(message="첫 질문", action="status", reading="", result={},
                 steps=[])
    store.conn.execute("UPDATE turns SET result_json = '{oops'")
    store.conn.commit()

    turns = store.history()

    assert len(turns) == 1
    assert turns[0]["message"] == "첫 질문"
    assert turns[0]["result"] == {}
    store.close()


# --------------------------------------------------------------------------
# Calling a route as a function
# --------------------------------------------------------------------------


def test_every_action_actually_runs(client, monkeypatch) -> None:
    """Each dispatch branch, exercised once.

    `search_entities` and `enrich` shipped broken because no test ever took
    those branches: the first returned a 500 and the second a permanent
    "enrichment failed", and the suite was green the whole time. Coverage of
    the classifier is not coverage of what it dispatches to.
    """
    outcomes = {}
    for action, params in [
        ("status", {}), ("help", {}), ("show_review", {}),
        ("show_graph", {}), ("show_packs", {}), ("show_sources", {}),
        ("search_entities", {"query": "TP53"}), ("enrich", {}),
    ]:
        _classify_as(monkeypatch, Intent(action, params=params, reading="…"))
        response = client.post(
            "/api/chat", json={"message": "x", "engine": "mock"}
        )
        assert response.status_code == 200, f"{action} raised"
        outcomes[action] = response.json()["result"]

    assert outcomes["search_entities"]["kind"] == "search"
    assert "results" in outcomes["search_entities"]
    # `enrich` may legitimately find nothing, but it must not fail.
    assert outcomes["enrich"].get("error_kind") is None, outcomes["enrich"]


def test_chat_supplies_every_query_parameter() -> None:
    """A route's defaults are `Query(...)` objects, not values.

    Calling one as a plain function and omitting a parameter binds the
    marker object itself — which reached sqlite as "type 'Query' is not
    supported". Nothing about the call site looks wrong, so the rule is
    checked rather than remembered.
    """
    import ast
    import inspect
    from pathlib import Path

    from fastapi import params as fastapi_params

    source = Path("ontologylab/server/routes.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    run_intent = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_run_intent"
    )

    for call in ast.walk(run_intent):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        target = getattr(routes, call.func.id, None)
        if target is None or not callable(target):
            continue
        try:
            signature = inspect.signature(target)
        except (TypeError, ValueError):
            continue
        supplied = {kw.arg for kw in call.keywords}
        supplied.update(
            list(signature.parameters)[: len(call.args)]
        )
        for name, parameter in signature.parameters.items():
            if not isinstance(parameter.default, fastapi_params.Param):
                continue
            assert name in supplied, (
                f"_run_intent calls {call.func.id}() without `{name}`, "
                f"so a {type(parameter.default).__name__} object is bound "
                f"instead of a value"
            )


def test_the_originating_question_reaches_a_screen() -> None:
    """An endpoint nothing calls is a claim nobody can check.

    `/api/jobs/{id}/asked` justifies itself by what the Jobs screen needed,
    and shipped with tests, a docstring and no caller — so the run detail
    still showed only `research-20260728-071805`.
    """
    from pathlib import Path

    script = Path("web/app.js").read_text(encoding="utf-8")
    markup = Path("web/index.html").read_text(encoding="utf-8")

    assert "/asked" in script, "no caller for the endpoint"
    assert 'id="job-asked"' in markup, "nowhere to render it"
    # And it is drawn where the run is described, not somewhere unrelated.
    detail = script.split("function renderJobDetail", 1)[1][:400]
    assert "renderJobAsked" in detail
