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
    (default model "claude-fable-5").
  - CodexEngine: shells out to `codex exec <prompt>` (best-effort).
  - GeminiEngine: shells out to `gemini -p <prompt>` (best-effort).

All real (non-mock) engines return raw stdout text, enforce a timeout, and
raise EngineError on failure (missing binary, timeout, non-zero exit).
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from typing import Optional


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

# CamelCase tokens ("RateLimiter", "TokenBucketAlgorithm") stand in for
# extractable entities in the neutral software-docs example domain.
_CAMELCASE_RE = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")

# Matches the "- name: ... (source type: X, target type: Y ...)" lines the
# extraction prompt renders for each relation type (extractor._schema_block).
_RELATION_LINE_RE = re.compile(
    r"^- (\w+): .*\(source type: (\S+), target type: (\S+)[;)]", re.MULTILINE
)

# Splits one CamelCase token into its words ("RateLimiter" -> Rate, Limiter).
_CAMEL_WORD_RE = re.compile(r"[A-Z][a-z0-9]+")


def _mock_relation_type(prompt: str) -> str:
    """Pick a relation type from the prompt's schema that accepts Component
    endpoints ('*' or Component on both sides), so mock relations always
    validate against whatever ontology the prompt embeds."""
    for name, domain, range_ in _RELATION_LINE_RE.findall(prompt):
        if domain in ("*", "Component") and range_ in ("*", "Component"):
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
    relation_type = _mock_relation_type(prompt)

    entities: list[dict] = []
    seen: dict[str, dict] = {}
    order: list[str] = []
    for match in _CAMELCASE_RE.finditer(chunk):
        token = match.group(0)
        if token not in seen:
            entity = {
                "name": token,
                "entity_type": "Component",
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
                "source": {"name": left, "entity_type": "Component"},
                "target": {"name": right, "entity_type": "Component"},
                "confidence": 0.8,
                "source_span": {
                    "start": left_span["start"],
                    "end": right_span["end"],
                },
            }
        )

    payload = {"entities": entities, "relations": relations}
    return "```json\n" + json.dumps(payload, indent=2) + "\n```"


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
    function of the prompt text: prompts containing a <query-expansion>
    section get a deterministic expansion array; anything else gets the
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
        if QUERY_MARKER_OPEN in prompt:
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


class ClaudeEngine:
    """Engine backed by the `claude` CLI.

    Invokes: claude -p <prompt> --model <model>
    Default model is "claude-fable-5" per project configuration.
    """

    def __init__(
        self,
        model: Optional[str] = "claude-fable-5",
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._model = model or "claude-fable-5"
        self._timeout_s = timeout_s

    def name(self) -> str:
        return "claude"

    async def generate(
        self, prompt: str, *, model: Optional[str] = None
    ) -> tuple[str, dict]:
        use_model = model or self._model
        cmd = ["claude", "-p", prompt, "--model", use_model]
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
        use_model = model or self._model
        cmd = ["codex", "exec", prompt]
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
        use_model = model or self._model
        cmd = ["gemini", "-p", prompt]
        if use_model:
            cmd += ["--model", use_model]
        stdout, elapsed = _run_subprocess(cmd, self._timeout_s)
        usage = {"calls": 1, "elapsed": elapsed, "engine": "gemini", "model": use_model}
        return stdout, usage


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_ENGINE_NAMES = ("mock", "claude", "codex", "gemini")


def get_engine(name: str, model: Optional[str] = None, seed: int = 7):
    """Return an Engine instance for ``name`` in {mock, claude, codex, gemini}.

    ``seed`` only affects MockEngine; the CLI-backed engines ignore it.
    """
    if name == "mock":
        return MockEngine(seed=seed)
    if name == "claude":
        return ClaudeEngine(model=model or "claude-fable-5")
    if name == "codex":
        return CodexEngine(model=model)
    if name == "gemini":
        return GeminiEngine(model=model)
    raise EngineError(f"unknown engine {name!r}; expected one of {_ENGINE_NAMES}")
