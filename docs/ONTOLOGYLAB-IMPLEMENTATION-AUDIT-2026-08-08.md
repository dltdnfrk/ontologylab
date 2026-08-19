# OntologyLab 제품 정체성·구현 감사

- 감사일: 2026-08-08
- 범위: 제품 목표, 수집→MCP 파이프라인, HITL 신뢰 경계, 검색·ML 알고리즘
- 기준 문서: `README.md`, `docs/PRODUCT_SPEC.md`,
  `docs/ARCHITECTURE.md`, `docs/DESIGN-RATIONALE.md`
- 판정: **핵심 제품 약속 구현됨 — calibration stream 혼합 1건과 운영·도메인
  품질 위험은 후속 조치 필요**

## 1. 제품 정체성 판정

OntologyLab의 목표는 이미 존재하는 근거를 에이전트가 재사용할 수 있는 검증 지식으로
바꾸는 것이다.

| 항목 | OntologyLab |
| --- | --- |
| 입력 | 문헌, 데이터, 공식 레지스트리 |
| 핵심 작업 | 수집, 추출, 검증, 정규화, 연결 |
| 출력 | 출처와 승인 이력이 있는 지식 팩 |
| 진실 기준 | 출처 span, provenance, 사람 승인 |
| 주요 품질 | 커버리지, 추적성, 정확도, 연결성, 검색 유용성 |

이 제품 정의는 현재 구현과 일치한다. LLM은 근거에서 후보를 추출하지만 사실을
승인하지 못하며, 검색·임베딩·critic·community 알고리즘도 순위나 검토 우선순위만
보조한다.

## 2. 구현 감사 결과

### A. 기존 근거의 수집과 보존 — PASS

- URL, 파일, 공개 논문 API 수집 경로가 구현되어 있다.
- connector는 deny-by-default allowlist를 적용한다.
- 문서와 job provenance가 저장된다.
- 원문과 출처를 이후 proposal 및 pack까지 추적할 수 있다.

근거:

- `ontologylab/connectors/web_crawl.py`
- `ontologylab/connectors/paper_api.py`
- `ontologylab/connectors/fulltext.py`
- `ontologylab/connectors/allowlist.py`
- `ontologylab/provenance.py`

### B. 근거 기반 추출 — PASS

- 문서를 약 3,000-token chunk와 150-token overlap으로 나눈다.
- LLM 출력은 fenced JSON으로 제한하고 ontology schema로 검증한다.
- 추출된 claim의 source span을 실제 chunk에서 확인하고 문서 좌표로 rebasing한다.
- grounded relation이 참조하지만 entity 배열에 없는 endpoint는 독립 span이 없는
  `proposed` placeholder가 될 수 있으며, 사람 검토 전에는 사실로 취급되지 않는다.
- schema 밖 결과와 잘못된 관계는 조용히 사실로 승격하지 않는다.
- 추출 결과는 모두 `proposed`로 저장된다.

근거:

- `ontologylab/extractor.py`
- `ontologylab/ontology_schema.py`
- `ontologylab/schemas.py`
- `ontologylab/kgstore.py`

### C. 사람 검증 신뢰 경계 — PASS

- 상태 전이는 `proposed → verified/rejected`이며 사람의 명시적 결정이 필요하다.
- `reopen`으로 기존 결정을 다시 검토할 수 있다.
- critic score, extractor confidence, conformal threshold는 자동 승인에 사용되지 않는다.
- 사람이 실행하는 `bulk_approve`는 extractor confidence를 대상 필터로 사용할 수
  있으므로 개별 판독과 동일한 보증으로 간주해서는 안 된다.
- enrichment와 merge도 사실을 자동 변경하지 않고 검토 가능한 후보를 만든다.

근거:

- `KGStore.approve`, `KGStore.reject`, `KGStore.reopen`
- `ontologylab/critic.py`
- `ontologylab/conformal.py`
- `ontologylab/enrichment.py`
- `ontologylab/merge.py`

### D. 기존 지식의 정규화와 연결 — PASS

- 이름·alias 기반 기본 entity resolution이 있다.
- 농화학 도메인은 EPPO, CAS, FRAC/IRAC/HRAC 계열 식별자를 사용할 수 있다.
- fuzzy name, containment, shared alias, embedding cosine을 이용해 merge 후보를
  생성하지만 자동 병합하지 않는다.
- 관계 endpoint와 출처가 함께 보존되어 단순 문서 검색보다 연결 가능한 그래프를
  만든다.

근거:

- `ontologylab/normalization.py`
- `ontologylab/registry.py`
- `ontologylab/merge.py`
- `ontologylab/kgstore.py`

### E. 검증된 지식의 배포 — PASS

- pack은 작업 DB와 분리된 새 SQLite 파일로 생성된다.
- 빌드 시점에 유효한 `verified` node/edge만 복사된다.
- FTS5를 다시 만들고, WAL을 종료하고, VACUUM 후 content hash를 기록한다.
- `proposed`와 `rejected`는 pack에 포함되지 않는다.
- manifest, schema, provenance가 pack 배포 단위에 함께 들어간다.

근거:

- `ontologylab/packbuilder.py`
- `tests/test_packbuilder.py`
- `tests/test_pipeline_e2e.py`

### F. 읽기 전용 재사용 표면 — PASS

- MCP는 pack SQLite를 read-only/immutable mode로 연다.
- entity lookup, 상세 조회, search, graph query, relation traversal, path finding,
  community 조회를 제공한다.
- `load_pack`은 활성 파일을 바꾸는 메모리 상태 변경일 뿐 KG를 수정하지 않는다.
- 선택적 live store도 staleness 계산을 위해 read-only로만 연다.

근거:

- `ontologylab/mcp_server.py`
- `ontologylab/semantic_staleness.py`
- `tests/test_mcp_session.py`
- `tests/test_mcp_two_tier.py`

## 3. ML·알고리즘 역할 감사

| 기법 | 구현 상태 | 제품 목표에서의 역할 | 신뢰 경계 |
| --- | --- | --- | --- |
| LLM schema extraction | 구현 | 문헌에서 entity/relation 후보 생성 | proposal만 생성 |
| FTS5/BM25 | 구현 | 근거의 lexical 검색 | 읽기 전용 |
| Hashing embedding | 구현 | offline lexical-overlap proxy | semantic model로 표시하지 않음 |
| SentenceTransformer | 선택 구현 | 의미 검색 recall 향상 | 로컬 모델, 자동 승인 없음 |
| RRF | 구현 | lexical/vector 순위 결합 | 검색 순위만 변경 |
| Cross-encoder reranker | 선택 구현 | shortlist 정밀 재정렬 | 검색 순위만 변경 |
| Leiden/CPM | 선택 구현 | graph community 추출 | pack build 결과에 고정 |
| Label propagation | 구현 fallback | community deterministic fallback | pack build 결과에 고정 |
| LLM community summary | 선택 구현 | 연결된 지식의 주제 요약 | extractive fallback 유지 |
| Critic model | 구현 | 검토 우선순위·불일치 표시 | 승인·거절 권한 없음 |
| ECE/isotonic regression | 구현 | confidence 측정·보정 | 자동 판정 없음 |
| Split conformal triage | 구현 | reject-worthy 항목의 검토선 제시 | 자동 승인선으로 사용하지 않음 |
| Fuzzy/embedding merge | 구현 | 중복 entity 후보 생성 | 사람 검토 후 병합 |
| Bootstrap PRF/F1 | 구현 | 추출 품질 측정 | gold set 품질에 의존 |

판정: 머신러닝은 “없는 지식을 만드는 엔진”이 아니라 **기존 근거의 추출,
검색, 연결, 검토 효율을 높이는 보조층**으로 배치되어 있다.

## 4. 발견 사항과 잔여 위험

### I1. Confidence calibration이 extractor stream을 섞는다 — Medium

`conformal.py`는 exchangeability를 지키기 위해 최신
`(engine, model, prompt_version)` critic stream만 사용한다. 반면
`calibration.py::review_outcomes`는 extractor engine/model/prompt version이 다른
review 결과를 하나의 ECE·isotonic fit으로 합친다. extractor나 prompt가 바뀐 뒤에는
서로 다른 confidence scale을 하나의 확률처럼 보정할 수 있다.

권고: conformal과 같은 기준으로 최신 extractor stream을 선택하거나, stream별
calibration report를 분리한다.

### I2. 낮은 위험의 구현 정합성 항목

- `conformal.py`의 최신 stream 선택은 engine/model/prompt_version을 독립 subquery로
  가져온다. 동일 `created_ts`가 있으면 실제 존재하지 않은 조합이 만들어져 calibration이
  비어 보일 수 있다. 세 필드를 한 행에서 선택해야 한다.
- relation이 언급했지만 entity 배열에 없는 endpoint는 `extractor.py`가 proposed
  placeholder로 합성할 수 있다. 독립 span이 없다는 사실은 보이지만 “edge가 요구해
  합성됨”이라는 flag는 node row에 영속화되지 않는다.
- `bulk_approve(min_confidence=...)`는 사람이 명시적으로 실행하지만 extractor
  confidence로 승인 대상을 거를 수 있다. 자동 승인은 아니지만 score가 status 변경
  범위에 영향을 주는 예외로 문서화해야 한다.
- pack-only MCP의 일부 `include_proposed` 인자는 pack에 proposed row가 없으므로
  실질적으로 동작하지 않는다.
- chat intent의 `research`와 `enrich`는 별도 confirmation 없이 network fan-out을
  시작할 수 있다. 승인 경계를 우회하지는 않지만 LLM intent 판정만으로 외부 요청이
  나가는 경로이므로 명시적 확인 gate를 검토해야 한다.
- pack 불변성은 `mode=ro&immutable=1` open mode와 content hash에 의존한다.
  `pack.sqlite` 자체가 filesystem read-only는 아니며, MCP load 시 manifest hash를
  다시 검증하지 않는다.
- 사람이 annotation을 accept하면 이미 verified인 node의 `properties_json`이
  갱신된다. 결정 주체는 사람이지만 verified content가 별도 재검증 단계 없이
  바뀌는 예외다.

### R1. 도메인 유용성은 구조 테스트만으로 증명되지 않는다

테스트는 verified-only, read-only, span validation 같은 시스템 불변식을 강하게
검증한다. 그러나 실제 농화학 corpus에서의 coverage, precision/recall, graph
connectivity, 검색 만족도는 별도 gold set과 시운전 결과가 필요하다.

권고: corpus별 extraction PRF/F1, source coverage, orphan-node 비율, 검색
nDCG/Recall@k, reviewer correction rate를 release gate로 유지한다.

### R2. 선택 ML 기능은 환경에 따라 비활성화된다

SentenceTransformer, sqlite-vec, cross-encoder, Leiden은 선택 의존성이다.
미설치 환경에서는 hashing, brute-force cosine, label propagation 또는 lexical
검색으로 내려간다. 이것은 의도된 fail-open이지만, pack manifest와 운영 UI가
실제 사용 algorithm/model을 항상 보여줘야 성능 차이를 오해하지 않는다.

### R3. 로컬 `.venv` console script는 현재 독립 실행되지 않는다

저장소의 `.venv/bin/ontologylab*` console script를 `PYTHONPATH` 없이 실행하면
`ModuleNotFoundError: ontologylab`이 발생한다. `.venv`에 프로젝트가 설치되지 않은
것처럼 동작하지만, 실제 원인은 macOS hidden flag가 붙은 `.pth` 파일을 Python 3.12의
`site` 초기화가 건너뛰어 editable finder가 로드되지 않는 작업공간 상태다.
`PYTHONPATH=.` 또는 정본 launch 설정처럼 저장소 루트에서
`python -m ontologylab.serve`를 실행하면 정상 동작한다.

판정: pipeline 코드 결함보다는 로컬 설치·entrypoint 상태 문제다. 다만 README가
console script 실행을 안내한다면 editable install 또는 실행 wrapper를 운영
절차에 명시해야 한다.

### R4. 생성형 보조 기능은 근거 경계를 계속 감시해야 한다

query rewrite, query expansion, LLM community summary는 원문 claim을 승인하지 않지만
사용자에게 생성 텍스트를 보여준다. 원문 사실과 검색 보조 문구가 혼동되지 않도록
현재의 fail-open·advisory labeling을 유지해야 한다.

## 5. 검증 기록

### 표적 테스트

```text
77 passed
```

실행 범위:

- `tests/test_pipeline_e2e.py`
- `tests/test_packbuilder.py`
- `tests/test_mcp_session.py`
- `tests/test_extraction_quality.py`
- `tests/test_critic.py`
- `tests/test_conformal.py`
- `tests/test_algorithm_upgrades.py`

### 전체 회귀 테스트

```text
1,702 tests collected
1,696 passed, 6 skipped, exit 0
```

경고는 기존 의존성 경고 2종이다.

- Starlette `TestClient`의 `httpx` 사용 deprecation
- Pydantic `LoadPackResult.schema` 이름 shadowing

### 제품 상태 evidence 검사

```text
EVIDENCE: 13 canonical pytest nodes passed
PASS: 4 statuses, 9 paths
```

`scripts/check_product_status.py`가 canonical evidence contract와 제품 상태 경로를
검사했다.

### 실제 표면 확인

- `PYTHONPATH=. .venv/bin/ontologylab --help`: 정상
- 잘못된 subcommand: usage와 함께 exit 2
- `python -m ontologylab.serve --help`: 정상, loopback 기본값과 remote 경고 확인
- `python -m ontologylab.mcp_server --help`: 정상, read-only와 live staleness 옵션 확인

### 독립 검토

5개 검토 관점이 모두 핵심 제품 판정을 `PASS`로 확인했다.

- 목표·제약 정합성: PASS
- 아키텍처·알고리즘 품질: PASS, I1/I2 발견
- 보안·신뢰 경계: PASS, 낮은 위험의 egress/pack/annotation 예외 발견
- 실제 CLI·테스트 evidence QA: PASS
- 기존 문서·의사결정 context 정합성: PASS

## 6. 최종 판정

OntologyLab은 현재 **“이미 존재하는 근거를 쓸 만한 검증 지식으로 엮는다”**는
제품 정체성을 구조적으로 구현하고 있다. 수집·추출·출처 grounding·사람 검증·정규화·
연결·불변 pack·읽기 전용 MCP가 하나의 신뢰 파이프라인을 이룬다.

다음 품질 단계는 새 기능 추가보다 실제 농화학 corpus를 대상으로 한 정량 평가와
웹앱 시운전이다. 구조는 목적에 맞고, 이제 측정해야 할 대상은 **얼마나 많이,
정확하게, 연결성 있게, 검색 가능하게 엮어내는가**다.

이번 감사는 구현 상태를 판정하고 문서와 실제 동작을 정렬하는 범위다. I1/I2의
코드 수정은 별도 변경으로 수행하고 회귀 테스트를 추가해야 한다.
