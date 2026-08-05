# 온톨로지랩 — Claude Science 구조 이식 참조 (docs/claude-science-reference)

> 2026-08-05 정리. 이 폴더는 온톨로지랩 전용 문서·사진만 담는다.
> 공통 역설계/클론은 `~/Documents/MUNI/artifacts/claude-science-clone-reference-2026-08-04/` (1차: `nipo-science/apps/web/claude-shell`) 참조.

## 문서 (읽는 순서)

| 순서 | 파일 | 내용 |
|---|---|---|
| 1 | `Claude_Science_0.1.25_UI_UX_기능_역설계_및_온톨로지랩_MUNI_lab_이식_구현_명세_2026-08-04.md` | **공통 역설계** — Project→Session→Run→ArtifactVersion→Provenance→Reviewer 하니스 구조 (저장소 내 버전 관리) |
| 2 | `온톨로지랩_MUNI_lab_UI_UX_분석과_Claude_Science_구조_이식_방안_2026-08-04.md` | **실측 분석** — 온톨로지랩 CS 구조 근접도 40%, 검토 큐·팩·증거 패널 평가 (저장소 내 버전 관리) |
| 3 | `온톨로지랩_Claude_Science_구조_이식_구현_명세_2026-08-04.md` | **앱 전용 구현 명세** — Project/Session/Run/Artifact 스키마, 검토 큐 가상화, 팩=Release Snapshot, app.js 분해, P0–P2 로드맵 |
| 4 | `온톨로지랩_시운전_버그리포트_재검수_2026-08-05.md` | **버그리포트 재검수** — P1~P3 재검증 + 빠진 결함 5건(GAP-O1~O5) |
| 5 | (외부) `../ONTOLOGYLAB-SMOKE-TEST-KO.md` | 시운전 시나리오 6개 + 결과 원본 |

> **버전 관리**: 1~4번 문서는 2026-08-05부터 저장소 안(`docs/claude-science-reference/`)에 있어 git 추적 대상이다. artifacts의 사본은 배포용이며, 수정 시 저장소 문서를 정본으로 한다.

## 이미지 (images/)

| 파일 | 내용 | 시점 |
|---|---|---|
| `onto-01-home.png` | 홈(대화) 화면 | 2026-08-05 신규 |
| `onto-02-review-queue-327.png` | **검토 큐 327건 전체 렌더** (GAP-O1 — 200행/451버튼) | 2026-08-05 신규 |
| `onto-03-graph.png` | 그래프 (P2 수정 후) | 2026-08-05 신규 |
| `onto-04-settings.png` | 설정 화면 | 2026-08-05 신규 |
| `ontology-review-queue-327.png` | 비교용 (클론 패키지) | 2026-08-04 |
| `ontology-settings.png` | 비교용 (클론 패키지) | 2026-08-04 |

## 핵심 이슈 요약 (2026-08-05 재검수 기준)

1. **GAP-O1 (High)**: 검토 큐 327건 전체 렌더 — DOM 4,231 노드·버튼 451개·scroll 7,818px (`app.js:694` limit=200). 스모크 리포트에 미기재 — **수정 확인(미커밋)**: keyset 커서 페이지네이션(기본 50·상한 100) + 스크롤/키보드 추가 로드
2. **GAP-O2 (Medium)**: Job 메모리 영속 — 서버 재시작 시 실행 이력 소실
3. **GAP-O3 (Medium)**: 팩·중간 산출물 아티팩트 라이브러리 부재
4. **P1~P3 수정 유지 확인**: 홈 새 세션 / 그래프 라벨·한국어화 / 제목 HTML 태그 — 모두 수정 확인
5. **수정사항 전부 미커밋**: git 작업 트리 기준 — 커밋 필요

## 관련 자료

- 공통 클론 패키지: `~/Documents/MUNI/artifacts/claude-science-clone-reference-2026-08-04/`
- 통합 역설계: `~/Documents/MUNI/artifacts/Claude_Science_0.1.25_UI_UX_기능_역설계_및_온톨로지랩_MUNI_lab_이식_구현_명세_2026-08-04.md`
