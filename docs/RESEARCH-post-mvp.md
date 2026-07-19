# ontologylab — post-MVP 이후 방향 리서치 (2026-07-14)

> 4개 병렬 리서치 종합: ① GraphRAG 생태계 동향 ② MCP 지식서버 설계 패턴
> ③ HITL 큐레이션 UX ④ OpenCrab(레퍼런스 제품) 기능 표면 비교.
> 근거 URL은 각 리서치 브리프 원문 참조 (`.claude/agent-memory/second-claude-code-researcher/`).

## 현재 위치 (강점 재확인)

리서치 결과, ontologylab이 생태계 대비 **이미 앞서 있는 지점**이 셋 있다 — 이건 지키고 강화할 차별점이다:

1. **검증된 것만 출고 (verified-only immutable pack)** — OpenCrab조차 데이터 팩 스냅샷이 없다(스키마 팩만 있음). GraphRAG 계열 어디에도 "사람이 승인한 것만 서빙" 구조가 없다.
2. **char-span 인용 무결성** — 저장된 모든 팩트가 원문 좌표로 역추적된다. OpenCrab은 chunk 단위 추적뿐.
3. **deny-by-default allowlist 인제스트** — 레퍼런스 제품에도 없음.

또한 "증분 인제스트 vs 불변 출고" 문제(생태계 공통 난제)는 ontologylab의 **working DB(스테이징) → 팩 freeze** 구조가 이미 권장 패턴과 일치한다.

## 우선순위 제안 (3 웨이브)

### Wave 1 — 저비용 즉효 (각 S, 며칠 단위)

| 항목 | 근거 |
|---|---|
| **W1. MCP 도구 8종에 outputSchema 추가** | 2025-06 스펙 네이티브. 토큰 효율 + 클라이언트 구조적 후처리. 가장 싼 승리 |
| **W2. 모든 도구 응답에 provenance 필드 내장** (pack id/hash, source doc id, span, score) | RAG 인용 정확도 문제(~74%)의 정석 해법. 우리는 데이터가 이미 있어 노출만 하면 됨 |
| **W3. 리뷰 큐 confidence 정렬 + 조정 가능한 임계값** | HITL 리서치 1순위. 기존 bulk-filter 배관 위에 정렬만 추가 |
| **W4. 키보드 단축키 리뷰 플로우** (approve/reject/skip 단일 키) | Prodigy 계열 검증된 관례 |
| **W5. 평가 골드셋 + triple P/R/F1 회귀 테스트** | 엔진(claude/codex/gemini) 교체 시 추출 품질 회귀 감지. MINE 벤치마크 어휘 차용 |

### Wave 2 — 핵심 역량 (각 M, 1~2주 단위)

| 항목 | 근거 |
|---|---|
| **W6. tier-2 시맨틱 검색 완성: sqlite-vec + 소형 CPU 임베딩 + RRF 융합** | 전 리서치 최고 합의 항목. all-MiniLM-L6-v2(46MB, ~83ms) 또는 nomic-embed-text. BM25+벡터 RRF는 "3줄짜리" 융합. 기존 LLM 쿼리확장과 3-신호 하이브리드가 됨 (OpenCrab의 RRF 재랭커와 동급). 주의: sqlite-vec 포크 상황 유동적 — 채택 전 직접 테스트 |
| **W7. 엔티티 병합 리뷰 UI (fuzzy 중복 제안 → 사람 승인)** | **생태계 공백 = 차별화 기회**: MS GraphRAG·LightRAG·HippoRAG 어디도 사람 병합 리뷰 UI를 안 실었다. proposed/verified 옆에 merge-candidate 상태 추가, 나란히 비교 + 근거 표시. OpenCrab identity 엔진(alias/tombstone) 설계 참고 |
| **W8. 크리틱 모델 트리아지** (별도 모델이 추출을 사전 채점 → 큐 정렬·불일치 플래그 전용) | 리뷰 부하 50%+ 감소 근거. **주의: 자동 승인 금지, 사전 체크된 승인 버튼 금지** — 앵커링 편향 연구(HDSR 2026, n=2,784)가 rubber-stamping 위험 실증 |
| **W9. MCP 2단 응답 + resources 노출** | 컴팩트 기본 응답(id/label/score/스니펫) + 상세 후속 조회 = 토큰 ~2/3 절감. `pack://{id}/entity/{id}` resource로 엔티티·스키마 주소화 |
| **W10. 팩 배포: .mcpb 번들** (팩 sqlite + 서버를 단일 파일로) | 2025-11 공식 채택 포맷. Claude Desktop/Code에 드래그앤드롭 설치. "공유 가능한 지식 팩"의 표준 경로 — 데이터 팩 마켓은 아직 아무도 안 풀었음 |
| **W11. 엔티티 중심 리뷰 모드** (한 엔티티의 모든 멘션·관계를 한 화면에서) | row-by-row 대비 직접 A/B 근거는 없으나(공백), 엔티티 정보의 ~63%가 직접 멘션 밖에 있다는 방증 |

### Wave 3 — 구조적 확장 (각 L, 이후 판단)

| 항목 | 근거 |
|---|---|
| **W12. 커뮤니티 감지 + 계층 요약 + global 쿼리 모드** | BFS로 못 답하는 "이 코퍼스의 주요 테마는?" 질의 해결 (GraphRAG/DRIFT의 핵심 우위, 승률 78-81%). **팩 빌드 타임에 1회 계산** → 불변 팩 철학과 정합. Leiden 클러스터링은 LLM 불필요, 요약만 LLM |
| **W13. bitemporal 엣지** (event-time/ingestion-time 분리, 삭제 대신 valid-until) | Graphiti/Zep 패턴. 모순 팩트를 역사 보존하며 공존 — 삭제 없는 불변 철학과 궁합. 스키마 작업 위주(컬럼 2개+무효화 로직) |
| **W14. 재추출/팩 diff** | 변경 문서 재추출 시 기존 verified와 조화, 팩 간 manifest diff. LightRAG 서브그래프 병합 패턴 참고 |

## 명시적으로 보류

- **MCP prompts** — 에이전트가 자율 호출 불가(사용자 UI 전용), 스펙 커뮤니티가 deprecation 논의 중. ROI 없음
- **외부 그래프/벡터 DB** — 로컬 단일 sqlite 유지 (fidx/vstash가 이 패턴의 2026년 유효성 실증)
- **멀티테넌시/billing/ReBAC** — OpenCrab의 영역. 로컬 단일 사용자 비목표 유지
- **sampling/elicitation** — 읽기전용 로컬 서버에 복잡도 대비 이득 없음

## 리서치 공백 (추후 확인)

- 엔티티 중심 리뷰 vs row-by-row 직접 비교 연구 부재 (유추 근거만)
- sqlite-vec vs sqlite-vector 유지보수 상황 — 채택 전 직접 벤치 필요
- GraphRAG `graphrag.append` 증분 커맨드 출시 여부 재확인
- 임베딩 모델 수치는 애그리게이터 출처 — MTEB 리더보드 직접 확인 권장

## 설계 철학의 학술적 근거 (외부 문헌 dossier)

ontologylab의 핵심 명제 — **"AI가 제안하고, 사람이 검증하며, verified-only만 출고한다"** — 를 Nature·Science·SCI급 저널 **36편**으로 뒷받침한 근거 문헌 dossier가 저장소에 정리되어 있다:

> **정본: [`docs/DESIGN-RATIONALE.md`](./DESIGN-RATIONALE.md)** (36편 전문 + 기둥별 구현 매핑)
> (미러: Obsidian vault `~/Documents/Hyunjun/Idea Note/decisions/2026-07-19-ontologylab-human-verification-설계근거-문헌.md`)

계기: Nature 사설 "Why AI cannot do good science without humans" (*Nature* 653, 650, 2026; doi:10.1038/d41586-026-01551-3)와 동시 게재된 두 자율 AI-과학자 논문(Google Co-Scientist doi:10.1038/s41586-026-10644-y, FutureHouse Robin doi:10.1038/s41586-026-10652-y). 사설의 결론 — *"AI scientists can and should empower human researchers. They cannot and should not replace them."* — 이 ontologylab 설계와 동형.

6개 기둥 ↔ 구현 매핑 (각 기둥별 검증 논문은 dossier 참조):

| 기둥 | 근거 요지 | 구현 |
|---|---|---|
| 1. 사람 검증 필수 | AI "이해 착각"(Messeri&Crockett *Nature* 2024), human+AI 메타분석(*Nat Hum Behav* 2024) | verified-only 게이트 (ARCHITECTURE §1.2/1.3) |
| 2. 자동화·앵커링 편향 | 자문 점수가 전문가를 앵커링(Dratsch *Radiology* 2023, Jabbour *JAMA* RCT 2023) | **W8 크리틱 anti-anchoring** (자문 전용, 점수→상태전이 경로 없음) |
| 3. LLM 환각·provenance | 조작된 인용 정량화(Chelli *JMIR* 2024), Med-PaLM(*Nature* 2023) | **W2 char-span provenance** |
| 4. 학술 기록 무결성 (AI slop) | Nature 저자성 정책(2023), fake-paper 규모(2023) | verified-only 불변 pack + deny-by-default 인제스트 |
| 5. 자율 AI 과학자 | A-Lab도 모호 결과엔 사람 필요(*Nature* 2023), GNoME 후보는 검증 요구 | ontologylab = the **verify stage** |
| 6. KG 사람 큐레이션 | PrimeKG/Hetionet/CKG의 provenance·큐레이션 전제 | **W7 엔티티 병합 리뷰** (사람만 병합) |

검증 방법: dossier의 36개 DOI는 전량 Crossref REST API로 독립 재검증(제목·저널·연도·volume/page·저자수 대조, 모두 `journal-article` resolve)했다. arXiv/프리프린트·컨퍼런스 전용 논문은 엄격 기준에서 제외. 이 서지 자체가 "AI 제안 → 검증 게이트 → verified-only 등재" 파이프라인의 산물이다.
