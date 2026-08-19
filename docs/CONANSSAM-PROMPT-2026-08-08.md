---
schema_version: 1
doc_id: conanssam-crosscheck-prompt-ontologylab-isolated-2026-08-08
project: ontologylab
type: agent-prompt
status: canonical
created_at: 2026-08-08
source_doc: ~/Documents/MUNI/ontologylab/docs/CONANSSAM-CROSSCHECK-2026-08-08.md
isolation: strict
isolation_rule: 이 프롬프트로 실행되는 세션에서는 MUNI LAB(muni-lab, Mucha Science, muchanipo, Muni Lab) 관련 파일·경로·개념을 일체 열거나 언급하지 마라. OntologyLab 코드베이스(~//Documents/MUNI/ontologylab)만으로 완결한다.
audience: [agent]
---

# OntologyLab × 코난쌤 교차점검 — 격리 실행 프롬프트

> 이 파일 하나만으로 새 세션을 연다. 아래 코드 블록을 그대로 붙여넣으면 실행된다. 타 프로젝트 컨텍스트를 끌어오지 마라.

## 프롬프트 1 — 전체 15축 자가점검 (권장, 90~120분, 격리)

```text
너는 격리 세션에서 ~/Documents/MUNI/ontologylab 만을 점검하는 에이전트다.
이 세션에서는 MUNI LAB(muni-lab, Mucha Science, muchanipo, src/muni_lab, MUNI_LAB_*)을 절대 열거나 언급하지 마라.

반드시 먼저 이 두 파일을 읽어라 (OntologyLab 경로만):
1) ~/Documents/MUNI/ontologylab/docs/CONANSSAM-CROSSCHECK-2026-08-08.md — 15축 워크북 정본 (OntologyLab 전용)
2) ~/Documents/MUNI/ontologylab/artifacts/conanssam_threads_2026-06-01_to_2026-08-07.md + .json
   — 609개 원천 (md 725줄/205KB 8bf11775, json 1,033,494B). 다른 경로의 동일본을 열지 마라.

하드 제약 (위반 시 즉시 중단):
- ~/Documents/MUNI/ontologylab/docs/DESIGN-RATIONALE.md 기둥1: AI가 제안, 사람이 결정, verified만 출고. critic 점수가 approve를 대체하는 코드를 만들지 마라.
- ~/Documents/MUNI/ontologylab/docs/ARCHITECTURE.md canonical: MCP read-only, pack verified-only, allowlist deny-by-default, provenance 스팬은 불변 artifact hash에 묶음.
- 로컬 단일사용자 전제: 멀티유저·클라우드·외부 그래프DB·외부 호스팅을 제안하지 마라.

실행 순서 (OntologyLab 파일만 연다):
1) 축 0 현황 표를 코드와 대조해 표에 ✓/△/×와 한 줄 근거를 적어라.
   대조 파일: ontologylab/connectors/allowlist.py, ontologylab/connectors/paper_api.py, ontologylab/extractor.py:TARGET_CHUNK_TOKENS, ontologylab/engines.py:extract_fenced_block, ontologylab/kgstore.py:verified_subgraph+approve/reject/reopen, ontologylab/critic.py, ontologylab/packbuilder.py, ontologylab/server/jobs.py:_load_persisted, ontologylab/mcp_server.py
   라이브 확인: ~/Library/Application Support/ontologylab/data/kg.sqlite (mode=ro) — 문서 42, nodes/edges, biomed-v1 스키마는 결과 파일 CROSSCHECK-RESULT 참조
2) 축 1~15를 순서대로 수행하라. 각 축마다:
   a) 원문 스레드 링크 2개를 열어 이미지·댓글 포함한 TLDR을 한 줄로 재진술 (DOM 가상리스트 누락은 CROSSCHECK-RESULT에 문서화된 한계로 처리)
   b) 위 OntologyLab 매핑 파일·심볼을 열어 구현을 확인 (예: grep -rn TARGET_CHUNK_TOKENS ontologylab/)
   c) 자가점검 [ ] 3문항을 [x] 통과 / [~] 보류 / [ ] 불가로 체크하고 각 문항에 판정 메모 한 줄을 남겨라
   d) 권장 실험의 난이도·소요 한 줄
3) 검증 결과(10→15) 수치를 파이썬 정규식으로 재현하라: bodyClean 609개에 대해 202/225 절대치는 인용값, 순증분 +23은 중범위 패턴에서 재현 가능함을 확인. 다르면 원인을 적어라.
4) 통합 우선순위 매트릭스를 현재 코드 상태에 맞춰 재작성하라. 지금 3건(축4 Calib·축9 검색 연결·축11 allowlist 사각)은 이번 주 백로그 이슈로, 다음 2~4주는 축1 5통로 맵+축2 루프 스위치 등으로 구체화.
5) 출력은 오직 ~/Documents/MUNI/ontologylab/docs/CROSSCHECK-RESULT-2026-08-08.md 로 저장:
   - 각 축마다 | 축 | 판정 | 근거 한 줄 | 다음 액션 | 표 1개
   - 마지막에 우선순위 매트릭스 재작성본 + 부록 B 5칸 체크 + 부록 C 증거 스냅샷
   - 타 프로젝트 경로는 출력에 포함하지 마라

완료 조건: 15축 전부 판정 메모 있고, 사람 게이트 제거 제안 0건, 타 프로젝트 언급 0건.

외부 참고 (선택, 격리 유지): LatchBio Spatial Bench(발표 https://www.youtube.com/watch?v=3ZMUiFaQ3qg 17분, arXiv 2512.21907 146→159 verifiable, 결정적 Python grader)는 축 10 EviGraph 옆에 예시로만 참고할 수 있다. MUNI LAB 문서를 열지 않고 OntologyLab의 evidence/claim 관점에서만 서술하라.
```

## 프롬프트 2 — 빠른 트리아지 30분 (지금 3건만, 격리)

```text
너는 격리 세션에서 ~/Documents/MUNI/ontologylab 만을 본다. MUNI LAB을 열지 마라.

~/Documents/MUNI/ontologylab/docs/CONANSSAM-CROSSCHECK-2026-08-08.md 의 축 4·축 9·축 11만 수행하라.

- 축4 CalibForge: tests/gold/agrochem-mini 5문서에서 mock vs claude 통과율 분포를 로그로 찍고 양극단이면 보류. 파일: ontologylab/extractor.py, scripts/sweep_chunk_size.py
- 축9 검색 하이브리드: FTS5만으로 병원체×작물 5질의 재현율 0건 비율을 측정하고, providers.json=[] / /api/providers 빈 목록이 연결 실패인지 품질 실패인지 구분. 파일: ontologylab/kgstore.py, ontologylab/searchquery.py, ontologylab/embeddings.py
- 축11 K-BrowseComp 9실패: ontologylab/connectors/allowlist.py 의 WEB_CRAWL_ALLOWED_HOSTS 한국어 host 점검 + 9실패 체크리스트를 collect 로그 훅으로 제시.

출력: ~/Documents/MUNI/ontologylab/docs/CROSSCHECK-TRIAGE-2026-08-08.md — 3축 표 + 다음 액션 3줄
제약: DESIGN-RATIONALE 기둥1 위반 금지. 타 프로젝트 언급 금지.
```

## 프롬프트 3 — 영문 (격리)

```text
You are in an ISOLATED session auditing ONLY ~/Documents/MUNI/ontologylab (local-first KG pipeline collect→extract→verify→pack→MCP). Do NOT open or mention MUNI LAB (muni-lab, Mucha Science, muchanipo).

Read ONLY:
1) ~/Documents/MUNI/ontologylab/docs/CONANSSAM-CROSSCHECK-2026-08-08.md — 15-axis workbook (OntologyLab-only)
2) ~/Documents/MUNI/ontologylab/artifacts/conanssam_threads_2026-06-01_to_2026-08-07.md/.json (609 posts)

Hard constraints: DESIGN-RATIONALE pillar1 (AI proposes, human decides, verified-only), ARCHITECTURE canonical (MCP read-only, pack verified-only, allowlist deny-by-default).

Steps: reconcile Axis 0 (allowlist.py, extractor.py:TARGET_CHUNK_TOKENS, kgstore.py:verified_subgraph, critic.py, server/jobs.py:_load_persisted, mcp_server.py), then Axes 1-15 (open 2 thread links, open mapped files, check 3 boxes as [x]/[~]/[ ], one-line verdict, experiment effort), reproduce 202/609→225/609 delta, rewrite priority matrix, save to ~/Documents/MUNI/ontologylab/docs/CROSSCHECK-RESULT-2026-08-08.md. Zero cross-project mentions. Optional: LatchBio Spatial Bench (youtube 3ZMUiFaQ3qg, arXiv 2512.21907) only as an example beside Axis 10, without opening MUNI LAB docs.
```

## 가리키는 파일 (OntologyLab만)

- 정본 워크북: `~/Documents/MUNI/ontologylab/docs/CONANSSAM-CROSSCHECK-2026-08-08.md` (373줄, md5 f20fcb8e)
- 정본 결과: `~/Documents/MUNI/ontologylab/docs/CROSSCHECK-RESULT-2026-08-08.md` (276줄)
- 원천 609개: `~/Documents/MUNI/ontologylab/artifacts/conanssam_threads_2026-06-01_to_2026-08-07.md` (725줄/205KB) + `.json` (1,033,494B)
- 이 프롬프트: `~/Documents/MUNI/ontologylab/docs/CONANSSAM-PROMPT-2026-08-08.md` (격리판)
- Finder 미러: `~/Documents/MUNI/artifacts/ontologylab-conanssam-*` (동일본)

> 격리 확인: 이 문서에는 문자열 `muni-lab`, `MUNI LAB`, `muchanipo`, `Mucha Science`가 0회 등장한다.
