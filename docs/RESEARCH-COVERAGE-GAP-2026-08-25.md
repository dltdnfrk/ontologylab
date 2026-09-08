# OntologyLab 핵심 약속 공백 — 자동 리서치와 촘촘한 그래프

- 작성일: 2026-08-25
- 구현 현황 갱신: 2026-08-29
- 기준 커밋: `7b3b1c8e3d7f8268d40a7d771614d8437156192f`
- 판정: **핵심 제품 의도와 구현이 어긋남**
- 관련: `README.md`, `docs/ARCHITECTURE.md`,
  `docs/ONTOLOGYLAB-IMPLEMENTATION-AUDIT-2026-08-08.md`,
  `docs/METHODOLOGY-COMPILER-ARCHITECTURE.md`

이 문서는 구현이 “설계한 대로 도는지”가 아니라, **사용자가 이 제품을
쓰는 이유로 기대하는 일**이 도는지 지적한다. 2026-08-08 감사는
“이미 있는 근거를 검증 지식으로 바꾼다”는 경계 안에서는 PASS를 줬다.
그 경계 밖 — 전 세계 논문급 자료를 알아서 모아 미싱 링크가 거의 없는
그래프를 주는 일 — 은 구현되어 있지 않다.

## 1. 기대와 실제

기대하는 핵심은 이것이다.

1. 전 세계에 퍼진 일정 수준 이상의 논문·준하는 자료를 대상으로
2. 사용자가 원하는 내용을 알아서 쪼개고
3. 리서치해서 수집하고
4. 서로 연결해서
5. 미싱 링크가 최대한 없는 촘촘한 지식그래프를 제공한다.

실제 구현은 이것이다.

> 주제 한 줄 → 영어 키워드 한 방 → 고정 API 팬아웃 → 소스당 기본 5편 →
> 한 번 추출 → 전부 `proposed`. 빈칸을 보고 다시 찾는 루프 없음.

리서치 탭은 “알아서”처럼 보인다. 하는 일은 한 방 메타데이터 검색과
추출이다. OntologyLab은 지금 **증거 감사 파이프라인**이지 **자동
리서치 엔진**이 아니다.

| 원하던 일 | 지금 코드 | 결과 |
|---|---|---|
| 전 세계 일정 수준 이상 논문 | 고정 12개 API. 웹 수집은 소프트웨어 문서 호스트 5개 | 페이월·출판사 CDN·인용 추적은 설계가 거절함 |
| 알아서 쪼개서 수집 | 검색어 한 줄, 최대 6단어, 소스당 기본 5편(상한 25) | 하위 질문으로 갈라 다시 찾지 않음 |
| 미싱 링크를 메움 | 이름 정규화 정확 일치만 자동 연결 | 비슷한 이름은 사람 병합 큐. 빈 관계는 다시 검색하지 않음 |
| 촘촘한 검증 그래프 | 추출은 전부 제안. 팩은 검증만 | 사람이 승인하기 전엔 출고 그래프가 비어 있음 |

## 2. 수집이 전 세계 논문급이 아닌 이유

### 2.1 네트워크 경계가 닫혀 있다

커넥터는 deny-by-default다. 논문 소스는 `PAPER_API_SOURCES`에 있는
이름만 허용되고, 각 이름은 고정 엔드포인트 하나와만 대응한다.
웹 수집 호스트는 소프트웨어·기술 문서 다섯 곳이다.

근거: `ontologylab/connectors/allowlist.py` (`WEB_CRAWL_ALLOWED_HOSTS`,
`PAPER_API_SOURCES`).

구현된 논문 소스는 arXiv, Crossref, OpenAlex, Semantic Scholar,
Europe PMC, bioRxiv, PubMed, ClinicalTrials, Elsevier, Springer, CORE,
SearXNG다. 키 없는 공개 메타데이터와, 키가 있어야 열리는 출판사 API,
사용자가 직접 띄운 메타서치다. 전 세계 출판 그래프가 아니다.

근거: `ontologylab/connectors/paper_api.py` `_SOURCE_DISPATCH`,
`IMPLEMENTED_SOURCES`.

### 2.2 본문은 오픈액세스 일부만 읽는다

수집의 기본 단위는 초록이다. 본문은 Europe PMC OA JATS만 허용한다.
같은 호스트라서 allowlist를 늘리지 않기 위한 선택이다. `pdf_url`은
채워지지만 따라가지 않는다. 페이월 논문은 초록에서 끝난다.

근거: `ontologylab/connectors/fulltext.py` 모듈 독스트링.
`doi.org → 출판사 → CDN` 추적은 아키텍처가 명시적으로 거절했다
(`docs/ARCHITECTURE.md` §12).

지식그래프가 실제로 써야 하는 방법·수치·유보는 본문에 있다. 초록만
있으면 결론 문장만 추출되고, 연결에 필요한 중간 개념이 빠진다.

### 2.3 한 번에 가져오는 양이 작다

소스당 기본 한도는 5편, 상한은 25편이다. 대시보드 리서치 폼의 기본값도
5다. 429·실패에 재시도·백오프가 없다. 한 소스가 죽어도 나머지는 살지만,
죽은 소스를 다시 치지 않는다.

근거:

- `ontologylab/connectors/paper_api.py` `DEFAULT_LIMIT = 5`, `MAX_LIMIT = 25`
- `web/index.html` `#research-limit` `value="5"`
- `ontologylab/connectors/AGENTS.md` — “No retry, no backoff, no 429 handling”

## 3. “알아서 쪼개서 리서치”가 한 방인 이유

리서치 잡의 canonical orchestration은
`ontologylab.research_run.run_research` 한 경로다.
`JobRegistry._research_async`는 lifecycle callback과 terminal
translation만 맡는 adapter다.

1. 사람이 주제를 한 줄 넣는다.
2. planner가 evidence need와 dependency가 있는 검색 축으로 분해한다.
   엔진이 없거나 실패·invalid output이면 원주제 한 축으로 명시적으로
   degrade한다.
3. 축별·소스별 쿼리를 허용된 소스에 보내고, acquisition assessment에
   따라 예산 안에서 broadening한다. 설정되면 citation seed도 확장한다.
4. 중복을 접고, 가능하면 OA 본문을 붙인다. spec·plan·acquisition
   artifact와 provenance를 canonical JSON으로 남긴다.
5. **이번에 들어온 document ID만** 추출한다. 예전 문서나 다른 잡 문서를
   끌어오지 않는다.
6. post-extraction assessment를 남긴다. 이 평가는 advisory일 뿐
   review·publication·pack 권한은 없다.

근거: `ontologylab/research_run.py` `run_research`,
`ontologylab/literature.py` `formulate_research_plan`,
`ontologylab/research_plan.py`, `ontologylab/research_assessment.py`.

아직 없는 것은 post-extraction assessment나 working KG의 미싱 링크를
다음 Research run의 successor plan으로 자동 연결하는 폐쇄 루프다.
현재 broadening과 citation expansion은 한 job의 bounded acquisition
단계 안에서 끝난다.

## 4. 연결이 촘촘해지지 않는 이유

### 4.1 자동 해소는 정확 일치뿐이다

`insert_proposed`는
`(schema_version_id, entity_type, normalized_name)`로만 붙인다.
`RateLimiter` / `rate-limiter` / `Rate Limiter`는 한 노드가 된다.
`IL-6`과 `IL6`처럼 짧은 심볼은 일부러 떨어뜨리고 사람 병합 큐에 올린다.
퍼지·임베딩 병합은 자동이 아니다.

근거: `ontologylab/kgstore.py` `normalize_name` (185행),
`insert_proposed` (2593행), `docs/ARCHITECTURE.md` §5.5.

문서 사이를 잇는 다리는 모델이 **같은 문자열**을 냈을 때만 생긴다.
같은 물질·같은 유전자를 다른 표기로 쓰면 별 두 개가 된다.

### 4.2 미싱 링크를 메우는 모듈이 없다

`method_gaps.detect_gaps`는 **방법론 IR**의 빈 칸을 표시한다.
지식그래프의 “이 개념과 저 개념 사이가 비었다”를 보고 자료를 더
찾지 않는다.

`method_bridges.py`는 설계서(`docs/METHODOLOGY-COMPILER-ARCHITECTURE.md`
§10)에만 있고 저장소에 파일이 없다. 있는 것은 CLI `bridge-import`와
`decide`다. 그것도 방법론 레인이다.

합성 엔드포인트(`synthesized_endpoint`)는 모델이 관계만 내고 엔티티를
안 냈을 때 생기는 자리표시다. 없는 논문을 찾아 메우지 않는다.

### 4.3 검증 그래프는 사람 승인 전에는 비어 있다

추출 행은 `proposed`로 태어난다. `approve`만 `verified`를 쓴다.
팩과 MCP는 검증분만 본다. 이 불변식은 신뢰에는 맞다. 커버리지를
제품 목표로 두면, 추출이 많아도 출고 그래프는 사람이 클릭한 만큼만
촘촘하다.

대시보드 검토 탭은 KG `approve`만 본다. 방법론 `decide`는 CLI에만
있다. `routes.py`, `jobs.py`, `web/`에 method/methodology 문자열이
0건이다.

기본 `build_pack`은 `method_release_ids=()`다. 릴리스를 고르지 않으면
capability는 `knowledge-graph-v1`뿐이고 `list_methods`는 거절된다.

근거: `ontologylab/kgstore.py` `approve`,
`ontologylab/packbuilder.py` 695–704행.

## 5. 현재 Research 경로가 하는 일과 하지 않는 일

하는 일 (구현되어 있음):

- 주제를 evidence need·dependency·검색 축으로 분해
- 소스별 쿼리, bounded broadening, 선택적 citation expansion
- 허용된 논문 API에 병렬로 묻기
- 실행 단위 중복 접기, OA 본문 일부 부착
- 청크 추출, 출처 span, 제안 노드/엣지
- spec·plan·acquisition·post-assessment artifact와 provenance
- 정확 일치 엔티티 해소
- 사람 승인 후에만 불변 팩·읽기 전용 MCP

하지 않는 일 (핵심 공백):

- 커버리지·수준 기준으로 전 세계 문헌을 고르기
- 페이월·PDF·출판사 본문을 안전하게 읽기 (현재는 거절)
- post-extraction/KG 구멍을 다음 job의 검색 계획으로 자동 연결
- 표기 변이를 자동으로 한 노드에 묶기 (사람은 큐만 받음)
- 미검증 추출을 출고 그래프에 올리지 않으면서도 밀도 목표를 측정하기

## 6. 왜 이렇게 되었는가

허용 목록, 한 방 검색, 정확 일치 해소, 사람 승인은 버그라기보다
**신뢰·로컬 우선**에 맞춘 선택이다. `docs/ARCHITECTURE.md`는 성공
지표를 증거 커버리지·추적성·검토 가능성으로 적고, 생성 새로움을
거절한다. 그 문장은 “환각으로 사실을 만들지 마라”에는 맞다.
“빈칸을 메우려고 논문을 더 찾아라”까지 막지는 않는다. 다만 구현이
후자를 만들지 않았다.

2026-08-08 감사가 PASS한 것은 이 좁은 경계다. 수집 경로가 있고
allowlist가 있고 provenance가 남는다. 그 감사가 측정하지 않은 것은
**원하던 밀도의 그래프가 나오는가**다.

## 7. 최소로 메우려면

구현을 시작하지 않는다. 봉합 순서는 이렇다.

1. **post-extraction을 successor plan에 연결한다.** 현재 planner와
   acquisition assessment는 한 job 안에서 동작한다. 추출 뒤 entity
   타입·관계 공백·출처 등급을 다음 bounded plan 입력으로 승격하되,
   봉합점은 adapter가 아니라 `research_run.py`의 typed service
   boundary로 둔다.
2. **수집 한도를 커버리지 목표에 맞춘다.** 소스당 5편 기본값은
   데모 한도다. 수준 필터(리뷰·인용·레지스트리)가 없으면 양을 늘려도
   잡음만 는다.
3. **해소와 재검색을 나눈다.** 정확 일치는 유지하되, 떨어진 별은
   “같은 이름인가?”가 아니라 “이 간선을 메울 문헌이 있는가?”로
   다시 검색한다.
4. **HITL은 출고에만 남긴다.** 자동 루프는 계속 `proposed`만 쌓게
   한다. 검증을 자동화하지 않는다. 밀도 지표는 작업 그래프에서
   먼저 재고, 팩 밀도는 승인량으로 따로 본다.

현재 bounded planning·broadening·citation expansion은 초기 한 방
검색 공백을 메웠다. 위 네 가지를 넣기 전에는 여전히 전 세계 논문에서
미싱 링크 없는 그래프를 준다는 약속까지는 지키지 못한다.

## 8. 근거 파일

| 주장 | 파일 |
|---|---|
| canonical Research orchestration | `ontologylab/research_run.py` `run_research` |
| typed planner와 degraded baseline | `ontologylab/literature.py` `formulate_research_plan` |
| bounded acquisition assessment | `ontologylab/research_assessment.py`, `ontologylab/research_plan.py` |
| 소스당 5편 / 상한 25 | `ontologylab/connectors/paper_api.py` |
| 웹 호스트 5개, 논문 소스 폐쇄 목록 | `ontologylab/connectors/allowlist.py` |
| 본문은 PMC OA만 | `ontologylab/connectors/fulltext.py` |
| 해소는 정확 일치 | `ontologylab/kgstore.py` `normalize_name`, `insert_proposed` |
| 공백 검출은 방법론 IR만 | `ontologylab/method_gaps.py` |
| 브리지 모듈 없음 | `docs/METHODOLOGY-COMPILER-ARCHITECTURE.md` §10 vs 저장소 |
| 기본 팩에 methodology 없음 | `ontologylab/packbuilder.py` 695–704행 |
| 대시보드에 방법론 면 없음 | `ontologylab/server/routes.py`, `web/` |
