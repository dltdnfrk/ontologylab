# ontologylab

Local-first, single-user **knowledge-graph pipeline**:

```
collect → extract (LLM) → verify (human) → knowledge pack → local MCP server
```

Neutral domain only (software / technical docs / general knowledge). No cloud, no multi-user.

## Requirements

- Python **3.11+** (system `python3` 3.8 is not enough)
- Optional: `claude` / `codex` / `gemini` CLI for live extraction; `mock` for offline

## Install

```bash
cd ontologylab
python3.13 -m venv .venv
.venv/bin/pip install -e ".[server,mcp,test]"
# if extras fail on an older setuptools:
.venv/bin/pip install -e . pytest httpx fastapi 'uvicorn[standard]' 'mcp>=1.2'
```

## CLI

```bash
# ingest a local file (or --url against allowlisted hosts)
python -m ontologylab.main collect --file ./docs/note.md

# extract with mock (CI) or claude (live)
python -m ontologylab.main extract --engine mock

# human verification gate
python -m ontologylab.main review
python -m ontologylab.main approve --id <node_or_edge_id>
python -m ontologylab.main reject --id <id>

# build immutable verified-only pack
python -m ontologylab.main build-pack --name my-pack
```

## Local dashboard

```bash
python -m ontologylab.serve --host 127.0.0.1 --port 8765
# open http://127.0.0.1:8765  → Review queue (approve/reject)
```

**One-click launch (macOS):** build a double-clickable app that starts the
dashboard and opens the browser for you — `bash launcher/build-macos-app.sh`
puts `ontologylab.app` in `~/Applications`. 한글 실행 가이드: [`launcher/README.md`](launcher/README.md).

## MCP server

```bash
python -m ontologylab.mcp_server --packs-dir ./packs
# optional pin: --pack <pack_id>
```

Claude Desktop / Claude Code snippet:

```json
{
  "mcpServers": {
    "ontologylab": {
      "command": "/path/to/ontologylab/.venv/bin/python",
      "args": ["-m", "ontologylab.mcp_server", "--packs-dir", "/path/to/ontologylab/packs"]
    }
  }
}
```

Tools (all read-only against the pack): `list_packs`, `load_pack`, `get_schema`,
`entity_lookup`, `semantic_search` (FTS5 lexical; optional fail-open LLM query
expansion via `expand=True` + `--expansion-engine` — still not vector search),
`graph_query`, `traverse_relations`, `find_path`.

## Tests

```bash
.venv/bin/pytest -q
```

## Docs

- `HANDOFF.md` — session handoff
- `docs/ARCHITECTURE.md` — data model + MCP contracts
- `docs/ROADMAP.md` — M0–M8 + MVP cut line
