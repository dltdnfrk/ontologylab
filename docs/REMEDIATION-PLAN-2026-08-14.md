# 적대적 재검수 + 코드 보수 고도화 계획 (2026-08-14)

공동 시운전 보고서(`evidence/aside-cli-adversarial-trial-2026-08-14.md`)의
7개 P1/P2를 **코드 원문 대조로 적대적 재검수**한 결과와, 통과한 항목에 대한
수정 계획. 검수 기준: 리뷰가 지목한 라인을 직접 읽고, 반대 측(=버그가 아니다)
논거를 먼저 세운 뒤, 그 논거가 무너질 때만 confirmed로 판정한다.

## 판정 요약

| # | 항목 | 판정 | 심각도 조정 |
|---|---|---|---|
| F1 | chunk 실패해도 job은 `complete` | **confirmed** | P1 → **P1 (범위 축소)** |
| F2 | EngineError 원문이 progress로 유출 | **confirmed** | P1 → **P2** |
| F3 | MCP가 광고한 schema를 강제 안 함 | **confirmed** | P1 유지 |
| F4 | 비활성 pack read가 integrity gate 우회 | **confirmed (최우선)** | P1 유지 |
| F5 | UI가 구조화 오류를 `[object Object]`로 표시 | **confirmed** | P1 → **P2** |
| F6 | busy 503을 UI가 성공처럼 처리 | **confirmed** | P1 유지 |
| F7 | malformed manifest가 화면 간 모순 유발 | **confirmed** | P1 유지 |

7개 모두 실재. 다만 **심각도는 그대로 받아들이지 않았다** — F1/F2/F5는
아래 반론이 성립해 한 단계 낮췄다.

## 항목별 근거와 반론

### F4 — 비활성 pack read가 integrity gate 우회 (최우선)

- 우회: `mcp_server.py:631-638`. `pack_id != self.pack_id`면
  `pack_sqlite_path()` → `KGStore.open()`으로 **바로 연다**.
  `pack_sqlite_path()`는 traversal만 막고 **해시는 검증하지 않는다**
  (`packbuilder.py:820-827`).
- 정상 경로: `load_pack()`은 `_verified_pack()`으로 현재 바이트에서 SHA-256을
  재계산한다(`mcp_server.py:580`).
- **반론 시도**: "traversal은 막히니 임의 파일은 못 읽는다" → 맞다. 그러나
  packs_dir 안의 **변조된** pack은 그대로 읽힌다. 시운전에서 동일 길이 변조
  후 `load_pack`은 `PackIntegrityError`, `get_schema`는 변조값 정상 반환으로
  실측됐다. 반론 붕괴.
- **왜 테스트가 못 잡았나 (핵심)**: `tests/test_mcp_pack_integrity.py`의
  8개 테스트가 **전부 `load_pack`만** 호출한다. 문서 문자열도 불변식을
  "`PackSession.load_pack()`이 재계산해야 한다"로 **메서드 단위**로 적어
  놓았다. 불변식이 *read 표면* 단위가 아니라 *메서드* 단위로 기술된 탓에,
  나중에 생긴 두 번째 read 문(`get_schema`)이 게이트 밖에 남았다.
  이 저장소가 경계하는 "고의로 깨뜨려도 통과하는 테스트" 그 자체.
- 범위: 우회는 **1곳뿐**. `_verified_pack`은 501/580에서 정상 사용 중.

### F1 — chunk 실패해도 job은 `complete`

- 근거: `extractor.py:760-774`가 `EngineError`를 `continue`로 흡수 →
  worker가 정상 반환 → `jobs.py:637-645`가 `status = "complete"`.
  동시에 `extraction_state.py:354`는 **run status를 `failed`로 기록**한다.
- **반론 시도**: "pack build 게이트가 막으니 데이터는 안 썩는다" →
  **성립한다**. `IncompleteExtractionError`와
  `allow_incomplete_extraction` + `override_intent` 강제
  (`packbuilder.py:55, 327-332`)로 불완전 추출은 pack에 조용히 못 들어간다.
- 그래서 **데이터 무결성 문제는 아니다 → 범위 축소**. 그러나 durable store는
  `failed`, job API/UI는 `complete`로 **두 저장소가 서로 모순**된다.
  운영자가 "추출 완료!"를 보고 재시도하지 않는 것이 실제 피해.
  제품 정직성 결함으로 confirmed 유지.

### F3 — MCP가 광고한 input schema를 강제하지 않음

- 근거: `mcp_runtime.py:146`이 `function(**arguments)`로 **그대로 splat**.
  `_input_schema`(51-65)는 schema를 *생성만* 하고 호출 시 대조하지 않는다.
  타입 강제·범위 검사·미지 인자 거부가 전부 없다.
- **반론 시도**: "MCP는 읽기 전용이라 위험이 낮다" → 부분적으로만 맞다.
  `graph_query(limit=-1)`이 SQLite unlimited가 되어 bounded-response 약속을
  깬다(실측: 전체 graph 반환). 읽기 전용이어도 DoS/과다응답은 남는다.
  또 미지 인자가 **Python 함수 시그니처 오류 원문**을 노출한다.

### F6 — busy 503을 UI가 성공처럼 처리

- 근거: backend는 정상이다 — `app.py:96-120`이 busy를 503 +
  `Retry-After` + `{ok:false, error_kind:"busy"}`로 올바르게 응답.
- UI가 문제: `apiSend()`(`app.js:1682-1701`)는 non-2xx여도 JSON body를
  **먼저 반환**한다. `invalidateEdge`(`app.js:3213-3221`)의 가드는
  `res.ok === undefined && res.detail`이라, `ok:false`인 busy 봉투는
  **가드를 통과**해 `loadEntityPanel()`로 진행한다. 조작자는 실패를 못 본다.
- `Retry-After` 헤더도 두 helper에서 버려진다.

### F2 — EngineError 원문 유출 (P1 → P2)

- 근거: `extractor.py:769-772`가 `{exc}`를 그대로 `on_progress`로 보낸다.
  progress는 `as_status()`(`jobs.py:212-234`)를 통해 API/SSE로 나간다.
- **반론 시도**: "top-level은 이미 redaction된다" → 맞다.
  `jobs.py:_run`은 `summarize_failure(exc)`를 쓰고, 그 주석이 이유를 명시한다.
  즉 **정책은 이미 존재하고 chunk 경로만 누락**됐다.
- 노출면이 localhost UI이고 상위 경로가 이미 막혀 있어 **P2로 하향**.
  다만 `tests/test_error_disclosure.py`(253줄)에 `chunk`/`engine_error`
  매치가 **0건** — 정책은 있는데 이 경로만 미검증. 수정 가치 있음.

### F5 — `[object Object]` (P1 → P2)

- 근거: 422 body는 `{detail: [ {...} ]}`(배열). `app.js:3055`가
  `escapeHtml(res.detail)`로 **배열을 문자열화**해 `[object Object]`가 된다.
  `termErrorText()`만 normalization을 구현해 놓았다.
- **반론 시도**: "backend는 이미 안전하다" → 맞다. `app.py:64-94`가
  `input`/`ctx`를 지워 값 유출은 없다. 순수 표시 결함이라 **P2로 하향**.

### F7 — malformed manifest 모순

- 근거: `list_packs()`(`packbuilder.py:800-816`)는 manifest가 dict인지,
  `pack_id`가 있는지, SQLite가 유효한지 **검사하지 않고** 그대로 append.
- Aside 실측: phantom 행 `—000—.mcpb`, 빈 diff 옵션,
  `/api/packs` 200 vs `/api/mcp/status` 500 동시 발생. fixture 제거 후
  정상 복구까지 확인.

## 수정 계획

원칙: **불변식을 메서드가 아니라 경계에 건다.** 각 수정은 먼저 실패하는
테스트로 고정한 뒤 고친다(F4가 보여준 실패 양식을 반복하지 않기 위함).

### 1순위 — F4 pack read integrity (보안 불변식)

1. `PackSession`에 검증된 비활성 pack 열기 헬퍼를 하나 만들고,
   `get_schema`의 631-638 분기를 그것으로 교체 → `_verified_pack` 경유.
2. 테스트를 **표면 단위**로 재작성: 변조 pack에 대해 *모든* 비활성 read
   진입점이 `PackIntegrityError`를 던지는지 확인. 새 read 도구가 생기면
   자동으로 걸리도록 진입점을 열거해 검사한다.
3. 뮤테이션 확인: 검증 호출을 일부러 제거하고 새 테스트가 **실패하는지** 본다.

### 2순위 — F3 MCP 입력 검증

1. `_call_tool`에 **생성된 schema로 강제**하는 단계 추가: 타입 강제,
   미지 인자 거부, `limit`/`top_k`/`max_hops` 음수·범위 위반 거부.
2. 오류는 JSON-RPC `-32602` 규약으로 일관화하고 내부 시그니처 문구 비노출.
3. `limit=-1`이 unlimited가 되지 않도록 도구 경계에서 하한/상한 고정.

### 3순위 — F1 job 상태 정렬 + F6 busy 처리

- F1: `extract_documents`가 chunk 실패 수를 반환하고, `jobs.py`가
  실패분이 있으면 `complete`로 끝내지 않도록 정렬(`failed` 또는
  `completed_with_failures`). durable run status와 job status 일치가 수용 기준.
  UI는 재시도 안내를 표시.
- F6: `invalidateEdge`(및 merge 계열 3518-3546)의 가드를
  `res.ok === false`까지 포함하도록 수정, `Retry-After` 노출.

### 4순위 — F7 pack 목록 검증

- `list_packs()`가 manifest dict/`pack_id` 유무/SQLite 유효성을 확인하고,
  불량 항목은 목록에서 제외하거나 `unusable` 표시로 내려보낸다.
- `/api/mcp/status`가 500 대신 구조화 오류를 반환. unusable pack에는
  복사 가능한 serve command를 주지 않는다.

### 5순위 — F2/F5 표시·유출 정리

- F2: chunk 오류도 `summarize_failure()`를 거치게 하고,
  원문은 provenance(디스크)에만. `test_error_disclosure.py`에 chunk 경로 추가.
- F5: `apiSend` 소비자들이 쓰는 공용 normalizer로 422 detail 배열을
  field + message로 렌더. `termErrorText()` 로직을 공용화.

## 검증 방식

- 각 수정마다 **먼저 실패하는 테스트**를 쓰고, 고친 뒤 통과시킨다.
- 고친 코드를 일부러 되돌려 테스트가 실제로 실패하는지 확인(뮤테이션).
- 회귀: `pytest`(설정에 `-q`가 이미 있으므로 개수 확인 시 `-v` 또는 평문).
- UI 항목(F5/F6/F7)은 Aside로 실제 화면에서 재확인.
