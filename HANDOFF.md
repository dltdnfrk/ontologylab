# ontologylab — 개발 핸드오프

> 이 문서는 새 세션에서 개발을 이어가기 위한 요약이다. 용어는 전부 중립(지식그래프 파이프라인 / 최적화 프레임워크)으로 유지한다.

## 한 줄 정의

**로컬 우선 지식그래프 파이프라인**: 문서 수집(공개 논문 API + 웹/URL) → LLM 자동 추출(엔티티·관계 = 온톨로지) → **휴먼인더루프 검증** → 지식그래프(sqlite) → 하나의 배포 단위 **지식 팩** → **로컬 MCP 서버**로 노출(Claude 등 MCP 클라이언트가 붙어서 쿼리).

레퍼런스: `opencrab.sh/mcp`(Ontology Graph RAG 플랫폼)의 **로컬-우선·단일 사용자** 버전.

## 확정된 결정

| 항목 | 결정 |
|---|---|
| 온톨로지 구축 | LLM 자동추출 **기본** + **휴먼인더루프 검증**(하이브리드). 추출 항목은 `proposed → verified → rejected` 상태 lifecycle, verified만 정답으로 승격 |
| 지식 팩 | **하나의 배포 단위** (검증된 KG + 온톨로지 스키마 + provenance 번들) |
| MCP 도구 | 일단 **전부** 노출: 그래프 쿼리 · 시맨틱 검색 · 엔티티 조회 · 관계/경로 탐색 · 팩 관리 (나중에 추림) |
| KG 저장 | **sqlite 재사용** (nodes/edges 테이블 + 임베딩 컬럼). 외부 그래프 DB 없음 |
| 배포 | **로컬 우선** (로컬 MCP 서버 + 로컬 KG, 단일 사용자). 나중 호스팅 여지 남김 |
| 데이터 소스 | **공개 논문 API + 웹/URL 수집** |
| 추론 엔진 | **구독 CLI 무키 스위칭** (기본 `claude` / `claude-fable-5`, + codex/gemini/mock) |
| 프로젝트명 | **ontologylab** (기존 코드베이스 `drylab`에서 진화/개명) |
| 비목표 | 멀티유저/클라우드 배포, 물리 하드웨어, 규제/이중용도 도메인(커넥터 allowlist 차단) |
| 도메인 예시 | 소프트웨어·기술·일반 지식만. (특정 규제 도메인 예시 금지) |

## 재사용할 기반 코드

`~/Documents/MUNI/drylab/` — **로컬 반복 최적화 프레임워크**. 동작 검증 완료. 재사용 인프라:

| 모듈 | 재사용 용도 |
|---|---|
| `drylab/engines.py` | 구독 CLI 서브프로세스 어댑터(claude/codex/gemini/mock), `async generate(prompt, model)`. **추출에 그대로 사용** |
| `drylab/sandbox.py` | 격리 실행 |
| `drylab/provenance.py` | provenance + 비용 추적 |
| `drylab/safety.py` | caps + kill-switch |
| `drylab/memory.py` | sqlite 영속 계층 (nodes/edges로 확장) |
| `drylab/server/` + `web/` | FastAPI + 바닐라 로컬 SaaS 셸 + SSE |
| `drylab/config.py`, `models.py` | 설정·데이터클래스 패턴 |

> 최적화 루프 `coordinator` + 빈패킹 도메인(`domain/heuristic_evolution.py`)은 이 프로젝트의 핵심이 아님 — 참고/드롭. 재사용은 **엔진 어댑터 + 지원 계층 + SaaS 셸** 중심.

## 설계 문서 (완료 · ready-to-build)

설계 → 적대적 비평 → 개정 → 재검증까지 마쳐서 **ready-to-build** 상태다. 프레이밍/bio 토큰 0건 확인됨.
- `~/Documents/MUNI/ontologylab/docs/ARCHITECTURE.md` (60k) — 아키텍처 + KG 데이터모델(sqlite DDL, 엔티티 해소·추출 계약·팩 저장 물리 포함) + MCP 도구 8종 스펙 + drylab 재사용 표 + 승인 CLI + allowlist(deny-by-default)
- `~/Documents/MUNI/ontologylab/docs/ROADMAP.md` (29k) — M0~M8 단계별 계획 + **MVP 컷라인** + 마일스톤별 수용 기준

**새 세션에서 이 두 파일을 먼저 읽고 ROADMAP의 MVP부터 시작할 것.**

핵심 설계 확정사항(비평 반영):
- **엔티티 해소**를 MVP 경로에 포함 — `insert_proposed` 안에서 `(schema_version, entity_type, normalized_name)`로 dedup, relation 엔드포인트를 해소된 node id에 바인딩 (없으면 KG가 문서별로 단절됨)
- 추출 계약: LLM은 `{entities, relations}` JSON, relation은 엔드포인트를 `{name, entity_type}`로 참조(인덱스/모델 id 금지), 청킹 ~1500토큰/150오버랩, `source_span` char offset 재기준
- 팩 저장: build 시 WAL off + checkpoint + VACUUM, FTS5는 팩 안으로 재구축, MCP는 `file:...?mode=ro&immutable=1`로 읽기전용
- HITL: 행은 `proposed`로 태어나고 `approve`만 `verified`로. 팩은 verified-only 쿼리로 빌드 → 미검증 데이터는 MCP에서 구조적으로 도달 불가
- 승인은 `ontologylab.main approve|reject|review` CLI (headless)

## 실행 환경 노트

- **Python 3.11+ 필수** (`python3.13` / `python3.11`). 시스템 `python`/`python3`는 3.8이라 안 돌아감.
- SaaS 레이어 구동: `python3.13 -m venv .venv && .venv/bin/pip install -e ".[server]"` → `.venv/bin/python -m ...serve` (pip은 샌드박스 밖에서 직접).
- **모든 온디스크 아티팩트는 이미 중립 용어로 정리됨** — 새 세션은 다시 스크럽할 필요 없이 중립 용어만 유지하면 됨.

## 구현 상태 (2026-07-14)

MVP 컷라인 + post-MVP Wave 1 + Wave 2 핵심 **코드 + 테스트 완료**.

| 영역 | 상태 |
|---|---|
| M0–M6 코어 (kgstore, connectors incl. paper_api, extractor, CLI, packbuilder) | ✅ |
| M7 MCP (`mcp_server.py` PackSession + 8 tools) | ✅ |
| M8 대시보드 (Review + Merge / Sources / Jobs / Packs / MCP 화면) | ✅ |
| Wave 1 (W1 outputSchema · W2 provenance 필드 · W3 confidence 트리아지 · W4 키보드 리뷰 · W5 골드셋 P/R/F1) | ✅ (`6207b70`) |
| W6 하이브리드 검색 (Embedder 프로토콜, embed 백필, BM25+cosine RRF, 정직한 tier 라벨) | ✅ + **실모델 검증 완료** (all-MiniLM-L6-v2 다운로드·백필·시맨틱 쿼리 확인, 2026-07-14) |
| W7 엔티티 병합 리뷰 (merge_candidates + merge_nodes + Merge 탭/CLI, 사람만 병합) | ✅ (`1acfdaf`) |
| W8 크리틱 트리아지 (critic_reviews, order=critic, 불일치 플래그 — 순수 자문, 자동승인 없음) | ✅ (`c304a20`) |
| W10 .mcpb 팩 번들 (단일파일 배포, Claude Desktop 드래그앤드롭) | ✅ (`f56a68f`) |
| W9 MCP 2단 응답 (컴팩트 기본 + `get_entity` 상세 + `detail=` 옵트인) + `pack://` resources 3종 — 구버전 팩 하위호환 가드 포함, 실 stdio 왕복 검증 | ✅ (`6c8bb64`) |
| pytest (203) | ✅ green |
| E2E: collect → extract → approve → pack → MCP query (CLI + API 양쪽) | ✅ |

### 환경 트랩 (재부팅 후 재발 가능)

- macOS가 venv `site-packages`의 editable `.pth` 파일에 UF_HIDDEN 플래그를
  붙여 Python 3.11.14+가 이를 무시함 (`Skipping hidden .pth file`) →
  `ModuleNotFoundError: ontologylab`. `chflags nohidden`은 다시 hidden으로
  되돌아가므로, `site-packages/sitecustomize.py`가 repo 경로를 sys.path에
  주입하는 영구 우회를 적용해둠 (2026-07-14). 재발 시 그 파일 존재만 확인.

```bash
cd ~/Documents/MUNI/ontologylab
python3.13 -m venv .venv && .venv/bin/pip install -e . pytest httpx fastapi 'uvicorn[standard]' 'mcp>=1.2'
.venv/bin/pytest -q
.venv/bin/python -m ontologylab.serve --port 8765
.venv/bin/python -m ontologylab.mcp_server --packs-dir ./packs
```

## 남은 선택 작업 (post-MVP / M8 polish)

- ~~paper_api connector~~ ✅ 완료 (arXiv Atom, deny-by-default allowlist, 아키텍트+레드팀 게이트 통과)
- ~~대시보드 Sources / Extraction Jobs / Packs / MCP Status 화면 (M8)~~ ✅ 완료 (polling 기반 잡 상태 — SSE는 ROADMAP에 선택 업그레이드로 명시)
- ~~live `claude` 엔진 실문서 추출 데모~~ ✅ 완료 (2026-07-13): README.md 1건 → `claude-fable-5` 실추출 29노드/29엣지 proposed → 검증기가 환각 표면형 5건 거부(synthesized로만 편입) → conf≥0.65 벌크 승인 24/24 (미검증 엔드포인트 엣지 5건 자동 skip) → verified-only 팩 빌드 → PackSession으로 entity_lookup/FTS5/find_path(2-hop) 응답. 주의: 이 샌드박스는 python 자식 프로세스의 네트워크를 차단하므로 엔진 호출만 셸에서 실행 후 파이프라인에 주입함 — 일반 환경에선 `extract --engine claude` 한 방으로 동일.
- ~~엔티티 tier-2 search~~ ✅ 완료 (2026-07-13): 임베딩 대신 **fail-open LLM 쿼리 확장** (gajae-code와 동일 노선 — BM25 lexical 유지 + LLM이 동의어/분절 변형 생성, 실패 시 plain lexical로 무해하게 폴백). `ontologylab search "<q>" --expand --engine <e>`, MCP `semantic_search(expand=true)` + `--expansion-engine`. 티어 라벨 정직: 변형이 실제 사용될 때만 `fts5+llm-expansion`. 라이브 검증: claude 확장으로 plain 0건이던 'rate limiter' → RateLimiter 검색 성공. 임베딩은 명시적 유보(opt-in 외부 백엔드, sqlite-vec이 최종 스케일 단계).

## 남은 선택 작업 (Wave 2 잔여 + Wave 3)

- **W11** 엔티티 중심 리뷰 모드 (한 엔티티의 모든 멘션·관계 한 화면)
- Wave 3 (W12 커뮤니티 요약 / W13 bitemporal / W14 팩 diff) — `docs/RESEARCH-post-mvp.md` 참조

## 새 세션 시작 프롬프트 (붙여넣기용)

```
~/Documents/MUNI/ontologylab/HANDOFF.md 를 읽고 이어서 작업해줘.
MVP(M0–M8) + Wave 1 + W6 실모델 + W7/W8/W9/W10까지 완료 (pytest 203 green).
남은 선택 작업: W11 (엔티티 중심 리뷰), Wave 3 (W12/W13/W14).
용어는 계속 중립(지식그래프/최적화 프레임워크)으로 유지.
```

## MVP 목표 (엔드투엔드 최소) — 달성

파일 인제스트 1건 → 추출 → 사람 승인 → 지식 팩 빌드 → 로컬 MCP로 entity_lookup / find_path 응답.
