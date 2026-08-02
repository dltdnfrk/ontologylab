"""Engine adapters for ontologylab.

Engines turn an extraction prompt into raw model text. The downstream
extraction pipeline (``extractor.parse_and_validate_extraction``) is
responsible for pulling the fenced ```json block out of that text and
validating it — engines never parse or execute anything themselves.

Provided engines (ported from drylab, adapters unchanged at the subprocess
boundary):
  - MockEngine: fully offline and deterministic. Scans the prompt's
    ``<document-chunk>`` section for CamelCase tokens and emits a valid
    extraction JSON block with real chunk-local character offsets, so the
    whole pipeline (parsing, span rebasing, entity resolution, citation
    integrity) is exercisable in tests and CI with zero network/CLI use.
  - ClaudeEngine: shells out to `claude -p <prompt> --model <model>`
    (default model: paths.DEFAULT_MODEL).
  - CodexEngine: shells out to `codex exec <prompt>` (best-effort).
  - GeminiEngine: shells out to `gemini -p <prompt>` (best-effort).

All real (non-mock) engines return raw stdout text, enforce a timeout, and
raise EngineError on failure (missing binary, timeout, non-zero exit).
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import pathlib
import re
import shutil
import subprocess
import time
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ontologylab.paths import DEFAULT_MODEL, assert_network_allowed, default_data_dir


def _url_is_loopback(url: str) -> bool:
    """True iff ``url``'s host is localhost / a loopback IP (stays on-machine)."""
    host = urlparse(url).hostname
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
from ontologylab.providers import (
    PROVIDER_ID_RE,
    Provider,
    get_provider,
    resolve_api_key,
)


class EngineError(Exception):
    """Raised when an engine fails to produce usable output."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _fence_re(lang: str) -> re.Pattern[str]:
    return re.compile(
        r"```(?:%s)?\s*\n(.*?)```" % re.escape(lang), re.DOTALL | re.IGNORECASE
    )


def extract_fenced_block(text: str, lang: str = "json") -> str:
    """Extract the first fenced ``lang`` code block from ``text``.

    Falls back to a bare ``` fence if no language-tagged fence is present.
    Raises EngineError if no non-empty fenced block can be found.
    """
    match = _fence_re(lang).search(text)
    if match is None:
        match = re.compile(r"```\s*\n(.*?)```", re.DOTALL).search(text)
    if match is None:
        raise EngineError(f"no fenced {lang} block found in engine output")
    block = match.group(1).strip("\n")
    if not block.strip():
        raise EngineError(f"fenced {lang} block was empty")
    return block


def resolve_cli(name: str) -> str:
    """Find a CLI engine's executable, or return the bare name.

    `PATH` is not the same everywhere this runs. Under launchd — which is
    how the launcher starts the server — it is the minimal
    `/usr/bin:/bin:/usr/sbin:/sbin`, so a `claude` installed by npm into
    `~/.npm-global/bin` is invisible and every extraction fails with
    "engine executable not found". From an interactive shell the same call
    works, which makes it look like an intermittent fault rather than a
    missing directory.

    Falls back to the bare name so the error message stays the familiar
    one when the binary genuinely is not installed.
    """
    found = shutil.which(name)
    if found:
        return found
    home = pathlib.Path.home()
    for base in (home/".npm-global/bin", home/".local/bin",
                 pathlib.Path("/opt/homebrew/bin"), pathlib.Path("/usr/local/bin"),
                 home/".bun/bin", home/".volta/bin"):
        candidate = base/name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return name


def resolve_available(name: str) -> bool:
    """Whether this process could actually run ``name``.

    Availability has to be decided by the lookup that will do the running,
    or the answer describes a different process than the one asking. It was
    `shutil.which` alone while invocation had already moved on to
    `resolve_cli`, and the two disagreed under exactly the PATH the launcher
    provides — so the API advertised no CLI engines while the CLI engines
    worked.
    """
    return resolve_cli(name) != name


def _run_subprocess(cmd: list[str], timeout_s: float) -> tuple[str, float]:
    """Run ``cmd``, returning (stdout, elapsed_seconds).

    Raises EngineError on non-zero exit, timeout, or missing executable.
    """
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        raise EngineError(f"engine executable not found: {cmd[0]!r}") from exc
    except subprocess.TimeoutExpired as exc:
        raise EngineError(f"engine call timed out after {timeout_s}s") from exc
    elapsed = time.monotonic() - start
    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "").strip()[-500:]
        raise EngineError(
            f"engine command {cmd!r} exited with code {proc.returncode}: {stderr_tail}"
        )
    return proc.stdout, elapsed


# ---------------------------------------------------------------------------
# Mock engine (offline, deterministic)
# ---------------------------------------------------------------------------

# Shared prompt-format contract: extractor.build_extraction_prompt wraps the
# chunk in these markers and MockEngine parses them back out. Both sides use
# these constants so the coupling is by symbol, not by duplicated strings.
CHUNK_MARKER_OPEN = "<document-chunk>"
CHUNK_MARKER_CLOSE = "</document-chunk>"

_CHUNK_SECTION_RE = re.compile(
    re.escape(CHUNK_MARKER_OPEN) + r"\n(.*?)\n" + re.escape(CHUNK_MARKER_CLOSE),
    re.DOTALL,
)

# Shared prompt-format contract with expansion.build_expansion_prompt: the
# query to expand is wrapped in these markers and MockEngine parses it back
# out. Marker precedence in MockEngine.generate: query-expansion first,
# document-chunk (extraction) otherwise.
QUERY_MARKER_OPEN = "<query-expansion>"
QUERY_MARKER_CLOSE = "</query-expansion>"

_QUERY_SECTION_RE = re.compile(
    re.escape(QUERY_MARKER_OPEN) + r"\n(.*?)\n" + re.escape(QUERY_MARKER_CLOSE),
    re.DOTALL,
)

# Shared prompt-format contract with communities.build_summary_prompt: the
# community context to summarize is wrapped in these markers as JSON.
COMMUNITY_MARKER_OPEN = "<community-summary>"
COMMUNITY_MARKER_CLOSE = "</community-summary>"

_COMMUNITY_SECTION_RE = re.compile(
    re.escape(COMMUNITY_MARKER_OPEN) + r"\n(.*?)\n"
    + re.escape(COMMUNITY_MARKER_CLOSE),
    re.DOTALL,
)

# Shared prompt-format contract with intent.classify: the sentence to route
# is wrapped in these markers. Without this MockEngine falls through to the
# extraction branch and every chat message classifies as "unknown", so the
# offline engine — the default, and the one the tests use — would make the
# whole chat surface look broken rather than merely unconfigured.
INTENT_MARKER_OPEN = "<intent-message>"
INTENT_MARKER_CLOSE = "</intent-message>"

_INTENT_SECTION_RE = re.compile(
    re.escape(INTENT_MARKER_OPEN) + r"\n(.*?)\n" + re.escape(INTENT_MARKER_CLOSE),
    re.DOTALL,
)

# Shared prompt-format contract with critic.build_critic_prompt: the items
# to score are wrapped in these markers as a JSON array.
CRITIC_MARKER_OPEN = "<critic-items>"
CRITIC_MARKER_CLOSE = "</critic-items>"

_CRITIC_SECTION_RE = re.compile(
    re.escape(CRITIC_MARKER_OPEN) + r"\n(.*?)\n" + re.escape(CRITIC_MARKER_CLOSE),
    re.DOTALL,
)

# CamelCase tokens ("RateLimiter", "TokenBucketAlgorithm") stand in for
# extractable entities in the neutral software-docs example domain.
_CAMELCASE_RE = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")

# Matches the "- name: ... (source type: X, target type: Y ...)" lines the
# extraction prompt renders for each relation type (extractor._schema_block).
# The first entity type in the prompt's own schema block. `Entity types:`
# and `Relation types:` are both `- name: description` lists, so the split
# on the relation header is what keeps this from matching a relation.
_ENTITY_LINE_RE = re.compile(r"^- (\w+):", re.MULTILINE)


def _first_entity_type(prompt: str) -> str:
    """An entity type from the prompt's own schema block.

    `Component` when the schema defines it, because that is what the tokens
    this engine emits actually are — CamelCase identifiers — and the gold
    set in `test_extraction_quality` measures against that reading. Any
    other ontology gets its first declared type, which is arbitrary but
    valid; the point is only that the offline engine produces something the
    active schema accepts rather than silently nothing.
    """
    block = prompt.split("Relation types:", 1)[0].split("Entity types:", 1)[-1]
    names = _ENTITY_LINE_RE.findall(block)
    if "Component" in names:
        return "Component"
    return names[0] if names else "Component"


_RELATION_LINE_RE = re.compile(
    r"^- (\w+): .*\(source type: (\S+), target type: (\S+)[;)]", re.MULTILINE
)

# Splits one CamelCase token into its words ("RateLimiter" -> Rate, Limiter).
_CAMEL_WORD_RE = re.compile(r"[A-Z][a-z0-9]+")


def _mock_entity_type(prompt: str) -> str:
    """Pick an entity type from the prompt's own schema block.

    This used to be the literal `"Component"`, which is a type only the
    software-docs ontology defines. Once a schema could be installed, the
    offline engine silently produced nothing on every other one: each
    entity was rejected as off-schema, so a 23-document research run
    finished `complete` with zero proposals and no error anywhere — the
    worst shape a failure can take.

    Relations already read the schema (`_mock_relation_type`); entities
    being hardcoded next to them was an asymmetry waiting to be found.
    """
    return _first_entity_type(prompt)


def _mock_relation_type(prompt: str, entity_type: str = "Component") -> str:
    """Pick a relation type from the prompt's schema whose endpoints accept
    the entity type mock is emitting, so mock relations always validate
    against whatever ontology the prompt embeds."""
    for name, domain, range_ in _RELATION_LINE_RE.findall(prompt):
        if domain in ("*", entity_type) and range_ in ("*", entity_type):
            return name
    return "related_to"


def _mock_extraction(prompt: str) -> str:
    """Deterministically derive an extraction JSON block from the prompt.

    Finds CamelCase tokens inside the prompt's <document-chunk> section,
    emits each unique token as a Component entity with its first-occurrence
    chunk-local span, and relates consecutive distinct entities with a
    relation type read from the prompt's own schema block. Output is purely
    a function of the prompt text.
    """
    section = _CHUNK_SECTION_RE.search(prompt)
    chunk = section.group(1) if section else prompt
    # Both read from the prompt's own schema block. Hardcoding either one
    # makes this engine silently produce nothing under any ontology that
    # does not define that exact name.
    entity_type = _mock_entity_type(prompt)
    relation_type = _mock_relation_type(prompt, entity_type)

    entities: list[dict] = []
    seen: dict[str, dict] = {}
    order: list[str] = []
    for match in _CAMELCASE_RE.finditer(chunk):
        token = match.group(0)
        if token not in seen:
            entity = {
                "name": token,
                "entity_type": entity_type,
                "aliases": [],
                "properties": {},
                "confidence": 0.9,
                "source_span": {"start": match.start(), "end": match.end()},
            }
            seen[token] = entity
            entities.append(entity)
            order.append(token)

    relations: list[dict] = []
    for left, right in zip(order, order[1:]):
        left_span = seen[left]["source_span"]
        right_span = seen[right]["source_span"]
        relations.append(
            {
                "relation_type": relation_type,
                "source": {"name": left, "entity_type": entity_type},
                "target": {"name": right, "entity_type": entity_type},
                "confidence": 0.8,
                "source_span": {
                    "start": left_span["start"],
                    "end": right_span["end"],
                },
            }
        )

    payload = {"entities": entities, "relations": relations}
    return "```json\n" + json.dumps(payload, indent=2) + "\n```"


def _mock_intent(prompt: str) -> str:
    """Route the prompt's <intent-message> by keyword, deterministically.

    Keyword matching, not understanding — which is the honest thing for an
    offline engine to do. The point is that the dispatch table, the
    confirmation gate and the trace can all be exercised without a network
    call; a message this cannot place returns "unknown", which is a real
    answer the UI has to render anyway.
    """
    section = _INTENT_SECTION_RE.search(prompt)
    message = section.group(1).strip() if section else ""
    low = message.lower()

    def _has(*words: str) -> bool:
        return any(w in low for w in words)

    if _has("검토", "review", "승인", "대기"):
        action, params = "show_review", {}
    elif _has("그래프", "graph"):
        action, params = "show_graph", {}
    elif _has("팩 만들", "build pack", "팩 빌드"):
        action, params = "build_pack", {}
    elif _has("팩", "pack"):
        action, params = "show_packs", {}
    elif _has("문서", "document", "소스", "source"):
        action, params = "show_sources", {}
    elif _has("상태", "status", "얼마나"):
        action, params = "status", {}
    elif _has("보강", "enrich"):
        action, params = "enrich", {}
    elif _has("뭘 할", "무엇을 할", "help", "도움"):
        action, params = "help", {}
    elif _has("찾아", "research", "논문", "연구", "search"):
        # The topic is the message with the request verb stripped: enough
        # to prove the parameter reaches the runner intact.
        topic = re.sub(
            r"(찾아\s*줘|찾아|관련\s*논문|최신\s*연구|에\s*대해|research|about)",
            " ", message, flags=re.I,
        )
        action = "research"
        params = {"topic": " ".join(topic.split()) or message}
    else:
        action, params = "unknown", {}

    return json.dumps(
        {
            "action": action,
            "params": params,
            "reading": f"'{message}' 요청으로 읽었어요." if message else "",
        },
        ensure_ascii=False,
    )


def _mock_critic(prompt: str) -> str:
    """Deterministically score the items in the prompt's <critic-items> JSON.

    Purely a function of each item's label text: labels containing
    "suspicious" (case-insensitive) score 0.15, everything else 0.9 — so
    tests can stage low-scoring items on purpose. Unknown/invalid payloads
    yield an empty array (the critic layer treats that as "no scores").
    """
    section = _CRITIC_SECTION_RE.search(prompt)
    reviews: list[dict] = []
    if section is not None:
        try:
            items = json.loads(section.group(1))
        except json.JSONDecodeError:
            items = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict) or "id" not in item:
                    continue
                label = str(item.get("label", ""))
                low = "suspicious" in label.lower()
                reviews.append(
                    {
                        "id": item["id"],
                        "score": 0.15 if low else 0.9,
                        "rationale": (
                            "label reads as an extraction artifact"
                            if low
                            else "label consistent with the cited evidence"
                        ),
                    }
                )
    return "```json\n" + json.dumps(reviews, indent=2) + "\n```"


def _mock_community_summary(prompt: str) -> str:
    """Deterministic one-line summary of a <community-summary> payload."""
    section = _COMMUNITY_SECTION_RE.search(prompt)
    anchor = "this community"
    if section is not None:
        try:
            payload = json.loads(section.group(1))
            members = payload.get("members") or []
            if members:
                anchor = str(members[0])
        except json.JSONDecodeError:
            pass
    return f"Mock summary: a cluster anchored by {anchor}."


def _mock_expansion(prompt: str) -> str:
    """Deterministically derive an expansion JSON array from the prompt.

    Output is purely a function of the query text between the
    <query-expansion> markers: ordered unique casefolded variants are
    [lowercased query (when it differs), concatenation of all word tokens
    lowercased ("rate limiter" -> "ratelimiter"), space-joined split of
    each CamelCase token lowercased ("RateLimiter" -> "rate limiter")],
    minus anything equal to the casefolded original, capped at 8.
    """
    section = _QUERY_SECTION_RE.search(prompt)
    query = section.group(1).strip() if section else prompt.strip()

    candidates: list[str] = []
    lowered = query.lower()
    if lowered != query:
        candidates.append(lowered)
    tokens = re.findall(r"\w+", query)
    if tokens:
        candidates.append("".join(tokens).lower())
    for token in tokens:
        if _CAMELCASE_RE.fullmatch(token):
            words = _CAMEL_WORD_RE.findall(token)
            candidates.append(" ".join(w.lower() for w in words))

    seen = {query.casefold()}
    variants: list[str] = []
    for cand in candidates:
        key = cand.casefold()
        if key in seen:
            continue
        seen.add(key)
        variants.append(cand)
        if len(variants) >= 8:
            break
    return "```json\n" + json.dumps(variants, indent=2) + "\n```"


class MockEngine:
    """Offline, deterministic engine used by default in tests and CI.

    Never shells out and never touches the network. Output is purely a
    function of the prompt text: prompts containing a <critic-items>
    section get a deterministic critic scoring array, <query-expansion>
    gets a deterministic expansion array; anything else gets the
    <document-chunk> extraction payload (the seed is kept for interface
    compatibility; it does not affect output).
    """

    def __init__(self, seed: int = 7) -> None:
        self._seed = seed
        self._calls = 0

    def name(self) -> str:
        return "mock"

    async def generate(
        self, prompt: str, *, model: Optional[str] = None
    ) -> tuple[str, dict]:
        start = time.monotonic()
        if INTENT_MARKER_OPEN in prompt:
            text = _mock_intent(prompt)
        elif CRITIC_MARKER_OPEN in prompt:
            text = _mock_critic(prompt)
        elif COMMUNITY_MARKER_OPEN in prompt:
            text = _mock_community_summary(prompt)
        elif QUERY_MARKER_OPEN in prompt:
            text = _mock_expansion(prompt)
        else:
            text = _mock_extraction(prompt)
        self._calls += 1
        elapsed = time.monotonic() - start
        usage = {"calls": 1, "elapsed": elapsed, "engine": "mock"}
        return text, usage


# ---------------------------------------------------------------------------
# CLI-backed engines
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_S = 300.0

# Extraction needs only the model's text; these tools would let injected
# document content act on the local machine.
_CLAUDE_DISALLOWED_TOOLS = (
    "Bash,Edit,Write,NotebookEdit,Read,Glob,Grep,WebFetch,WebSearch,Agent,mcp"
)


class ClaudeEngine:
    """Engine backed by the `claude` CLI.

    Invokes: claude -p <prompt> --model <model>
    Default model comes from paths.DEFAULT_MODEL.
    """

    def __init__(
        self,
        model: Optional[str] = DEFAULT_MODEL,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._model = model or DEFAULT_MODEL
        self._timeout_s = timeout_s

    def name(self) -> str:
        return "claude"

    async def generate(
        self, prompt: str, *, model: Optional[str] = None
    ) -> tuple[str, dict]:
        assert_network_allowed("claude CLI engine")
        use_model = model or self._model
        # The prompt carries collected documents; tool access would let
        # injected text act locally. Extraction needs only the text.
        cmd = [resolve_cli("claude"), "-p", prompt, "--model", use_model,
               "--disallowedTools", _CLAUDE_DISALLOWED_TOOLS]
        stdout, elapsed = _run_subprocess(cmd, self._timeout_s)
        usage = {"calls": 1, "elapsed": elapsed, "engine": "claude", "model": use_model}
        return stdout, usage


class CodexEngine:
    """Best-effort engine backed by the `codex` CLI.

    Invokes: codex exec <prompt>
    """

    def __init__(
        self, model: Optional[str] = None, timeout_s: float = _DEFAULT_TIMEOUT_S
    ) -> None:
        self._model = model
        self._timeout_s = timeout_s

    def name(self) -> str:
        return "codex"

    async def generate(
        self, prompt: str, *, model: Optional[str] = None
    ) -> tuple[str, dict]:
        assert_network_allowed("codex CLI engine")
        use_model = model or self._model
        cmd = [resolve_cli("codex"), "exec", "--sandbox", "read-only", prompt]
        if use_model:
            cmd += ["--model", use_model]
        stdout, elapsed = _run_subprocess(cmd, self._timeout_s)
        usage = {"calls": 1, "elapsed": elapsed, "engine": "codex", "model": use_model}
        return stdout, usage


class GeminiEngine:
    """Best-effort engine backed by the `gemini` CLI.

    Invokes: gemini -p <prompt>
    """

    def __init__(
        self, model: Optional[str] = None, timeout_s: float = _DEFAULT_TIMEOUT_S
    ) -> None:
        self._model = model
        self._timeout_s = timeout_s

    def name(self) -> str:
        return "gemini"

    async def generate(
        self, prompt: str, *, model: Optional[str] = None
    ) -> tuple[str, dict]:
        assert_network_allowed("gemini CLI engine")
        use_model = model or self._model
        cmd = [resolve_cli("gemini"), "--approval-mode", "plan", "-p", prompt]
        if use_model:
            cmd += ["--model", use_model]
        stdout, elapsed = _run_subprocess(cmd, self._timeout_s)
        usage = {"calls": 1, "elapsed": elapsed, "engine": "gemini", "model": use_model}
        return stdout, usage


# ---------------------------------------------------------------------------
# API-backed engine (configurable providers)
# ---------------------------------------------------------------------------

# Anthropic Messages API requires an output-token cap on every request.
_API_MAX_TOKENS = 4096

# Extraction is a parsing task, not a creative one, so the default sampler
# is deterministic-ish. Which keys are legal at all is a property of the
# provider's API, not of this codebase: the Anthropic Messages API takes
# top_k and refuses seed; every OpenAI-compatible /chat/completions endpoint
# (OpenAI, xAI, OpenRouter, a local Ollama/LM Studio) takes seed and refuses
# top_k. Sending an unsupported key is a 400 from the provider, so it is
# refused here first.
DECODE_PARAM_SUPPORT: dict[str, frozenset[str]] = {
    "anthropic": frozenset({"temperature", "top_p", "top_k"}),
    "openai": frozenset({"temperature", "top_p", "seed"}),
}

DEFAULT_DECODE_PARAMS: dict[str, float] = {"temperature": 0.0}

# T=0 is a request, not bit-determinism: batch composition, MoE routing, and
# float reduction order still move the logits. The name says "requested" so
# no reader upgrades it into a reproducibility guarantee.
DECODE_PARAMS_NOTE = (
    "decode_params are the sampling parameters REQUESTED of the provider; "
    "identical parameters do not guarantee identical output."
)


def validate_decode_params(
    kind: str, params: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """Return the parameters to send for ``kind``; raise on anything unsendable.

    None means the caller made no choice and gets the pinned default. An
    unknown key is almost always a typo, and an unsupported key is a 400
    from the provider — both fail here, loudly, instead of at the wire.
    """
    if params is None:
        return dict(DEFAULT_DECODE_PARAMS)
    supported = DECODE_PARAM_SUPPORT.get(kind, frozenset())
    for key, value in params.items():
        if key not in supported:
            raise EngineError(
                f"decode parameter {key!r} is not supported by provider kind "
                f"{kind!r} (supported: {sorted(supported)})"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EngineError(
                f"decode parameter {key!r} must be a number, got {value!r}"
            )
        if key == "temperature" and not 0.0 <= value <= 2.0:
            raise EngineError(
                f"temperature must be within [0.0, 2.0], got {value}"
            )
        if key == "top_p" and not 0.0 < value <= 1.0:
            raise EngineError(
                f"top_p must be within (0.0, 1.0], got {value}"
            )
        if key == "top_k" and (not isinstance(value, int) or value < 1):
            raise EngineError(f"top_k must be an integer >= 1, got {value!r}")
        if key == "seed" and not isinstance(value, int):
            raise EngineError(f"seed must be an integer, got {value!r}")
    return dict(params)


def _http_post_json(
    url: str, headers: dict[str, str], payload: dict, timeout_s: float
) -> dict:
    """POST ``payload`` as JSON to ``url`` and return the decoded JSON body.

    The single network boundary for ApiEngine (separated for test
    monkeypatching, exactly like paper_api._http_get_text). ``urlopen``
    raises HTTPError on a non-2xx status, so callers wrap it into a redacted
    EngineError; this helper never logs headers (which carry the API key).
    """
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=headers, method="POST")
    with urlopen(request, timeout=timeout_s) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        raw = response.read().decode(charset, errors="replace")
    return json.loads(raw)


class ApiEngine:
    """Engine backed by a configured API provider (Anthropic or OpenAI-compatible).

    Selected as ``api:<provider.id>``. The API key is resolved from the
    provider's ``api_key_env`` environment variable at call time and is never
    stored, logged, or echoed in an error. The blocking urllib call runs in a
    worker thread so the event loop is never blocked.
    """

    def __init__(
        self,
        provider: Provider,
        model: Optional[str] = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        decode_params: Optional[dict[str, Any]] = None,
    ) -> None:
        self._provider = provider
        self._model = model or (provider.models[0] if provider.models else None)
        self._timeout_s = timeout_s
        self._decode_params = validate_decode_params(provider.kind, decode_params)

    def name(self) -> str:
        return f"api:{self._provider.id}"

    def _build_request(
        self, prompt: str, key: str, model: str
    ) -> tuple[str, dict[str, str], dict]:
        """Return (url, headers, body) for the provider's kind."""
        base = self._provider.base_url.rstrip("/")
        if self._provider.kind == "anthropic":
            headers = {
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            body = {
                "model": model,
                "max_tokens": _API_MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
                **self._decode_params,
            }
            return f"{base}/messages", headers, body
        # kind == "openai" (validated at registration time)
        headers = {
            "Authorization": f"Bearer {key}",
            "content-type": "application/json",
        }
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            **self._decode_params,
        }
        return f"{base}/chat/completions", headers, body

    def _parse_response(self, response: dict) -> tuple[str, dict]:
        """Extract (text, token-usage) from a provider response by kind.

        Indexes the required container directly, so a missing/empty response
        shape raises (KeyError/IndexError/TypeError) and generate() turns it
        into an EngineError — rather than silently returning empty text.
        """
        usage_meta = response.get("usage") or {}
        if self._provider.kind == "anthropic":
            blocks = response["content"]
            text = "".join(
                block.get("text", "")
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
            tokens = {
                "prompt_tokens": usage_meta.get("input_tokens"),
                "completion_tokens": usage_meta.get("output_tokens"),
            }
        else:  # openai
            text = response["choices"][0]["message"]["content"] or ""
            tokens = {
                "prompt_tokens": usage_meta.get("prompt_tokens"),
                "completion_tokens": usage_meta.get("completion_tokens"),
            }
        return text, {k: v for k, v in tokens.items() if v is not None}

    async def generate(
        self, prompt: str, *, model: Optional[str] = None
    ) -> tuple[str, dict]:
        provider_id = self._provider.id
        key = resolve_api_key(self._provider)
        if not key:
            raise EngineError(
                f"provider {provider_id!r}: env var "
                f"{self._provider.api_key_env} is not set"
            )
        effective_model = model or self._model
        if not effective_model:
            raise EngineError(
                f"provider {provider_id!r}: no model given and the provider "
                "has no default model — pass --model or add one"
            )
        url, headers, body = self._build_request(prompt, key, effective_model)

        # Offline mode blocks egress that leaves the machine. A provider that
        # points at loopback (local Ollama / LM Studio) keeps data on-device,
        # so it stays allowed; only remote endpoints are refused.
        if not _url_is_loopback(url):
            assert_network_allowed(f"api provider {provider_id!r} ({url})")

        start = time.monotonic()
        try:
            response = await asyncio.to_thread(
                _http_post_json, url, headers, body, self._timeout_s
            )
        except HTTPError as exc:
            # Redacted: status only, never the request headers (which hold the key).
            raise EngineError(
                f"provider {provider_id!r}: HTTP {exc.code} from the "
                f"{self._provider.kind} endpoint"
            ) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise EngineError(
                f"provider {provider_id!r}: request failed "
                f"({type(exc).__name__})"
            ) from None
        except (json.JSONDecodeError, ValueError):
            raise EngineError(
                f"provider {provider_id!r}: response was not valid JSON"
            ) from None
        elapsed = time.monotonic() - start

        try:
            text, tokens = self._parse_response(response)
        except (KeyError, IndexError, TypeError):
            raise EngineError(
                f"provider {provider_id!r}: unexpected response shape"
            ) from None
        usage = {
            "calls": 1,
            "elapsed": elapsed,
            "engine": self.name(),
            "model": effective_model,
            "decode_params": dict(self._decode_params),
            **tokens,
        }
        return text, usage


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

# Single source of truth for "which engines exist" — argparse choices
# in main.py / mcp_server.py consume this instead of re-typing the list.
ENGINE_NAMES = ("mock", "claude", "codex", "gemini")
_ENGINE_NAMES = ENGINE_NAMES  # back-compat alias

# ``api:`` engine names select a configured provider instead of a built-in.
_API_ENGINE_PREFIX = "api:"


def is_valid_engine_name(name: str) -> bool:
    """Whether ``name`` is a built-in engine or a well-formed ``api:<slug>``.

    Does NOT check that the provider exists (that needs a data_dir) — only
    the *shape*. ``get_engine`` resolves an unknown provider to EngineError.
    """
    if name in ENGINE_NAMES:
        return True
    if name.startswith(_API_ENGINE_PREFIX):
        return bool(PROVIDER_ID_RE.fullmatch(name[len(_API_ENGINE_PREFIX):]))
    return False


def engine_name_arg(value: str) -> str:
    """argparse ``type=`` validator: accept a built-in or ``api:<slug>``.

    Replaces the rigid ``choices=list(ENGINE_NAMES)`` so ``api:<id>`` engines
    are selectable on the CLI, while junk still errors at parse time.
    """
    if is_valid_engine_name(value):
        return value
    raise argparse.ArgumentTypeError(
        f"invalid engine {value!r}: expected one of {ENGINE_NAMES} "
        "or 'api:<provider-id>'"
    )


def get_engine(
    name: str,
    model: Optional[str] = None,
    seed: int = 7,
    data_dir=None,
    decode_params: Optional[dict[str, Any]] = None,
):
    """Return an Engine instance for ``name``.

    ``name`` is one of {mock, claude, codex, gemini}, or ``api:<provider-id>``
    to use a configured provider (loaded from ``data_dir`` or the default data
    dir). ``seed`` only affects MockEngine; the CLI-backed engines ignore it.

    ``decode_params`` selects sampling parameters, and only an API provider
    can honour them — the CLI adapters have no sampling flag, so passing a
    selection to one raises instead of silently recording a parameter the
    run never used.
    """
    if decode_params is not None and not name.startswith(_API_ENGINE_PREFIX):
        raise EngineError(
            f"engine {name!r} cannot apply sampling parameters (no CLI flag "
            f"exists); use an api:<provider-id> engine"
        )
    if name == "mock":
        return MockEngine(seed=seed)
    if name == "claude":
        return ClaudeEngine(model=model or DEFAULT_MODEL)
    if name == "codex":
        return CodexEngine(model=model)
    if name == "gemini":
        return GeminiEngine(model=model)
    if name.startswith(_API_ENGINE_PREFIX):
        provider_id = name[len(_API_ENGINE_PREFIX):]
        provider = get_provider(data_dir or default_data_dir(), provider_id)
        if provider is None:
            raise EngineError(
                f"unknown provider {provider_id!r}; register it with "
                "`ontologylab provider add`"
            )
        return ApiEngine(provider, model=model, decode_params=decode_params)
    raise EngineError(f"unknown engine {name!r}; expected one of {_ENGINE_NAMES}")
