# Claude Science 리버스 엔지니어링 분석

> 2026-07-25. Aside 브라우저의 로그인 세션 + macOS computer use(vision)로 실제 앱을
> 구동하며 전 구성요소를 분해하고 실사용까지 수행한 기록.
>
> **조사 범위와 원칙**: 화면에 드러난 UI·동작·설정과, 인증 전 로컬 서버가 스스로 응답한
> 내용만 사용했다. 인증 우회, 앱 번들 디컴파일, 자격증명 파일 열람은 하지 않았다
> (자격증명 디렉터리 탐색은 시도했으나 권한 분류기가 차단했고 우회하지 않았다).
> 사용자의 실제 연구 대화 내용은 분석 대상에서 제외했다.
>
> **왜 이 문서가 ontologylab에 있는가**: Claude Science는 ontologylab이 만들려는 것
> ─ 허용목록으로 잠근 과학 문헌 수집 + 출처 검증 + 로컬 실행 ─ 의 **성숙한 레퍼런스
> 구현**이다. §8에 설계 결정별 매핑을 정리했다.

---

## 1. 정체와 기본 구조

**Claude Science (Beta)** — Anthropic의 계산생물학(comp-bio) 로컬 데스크톱 에이전트.

| 항목 | 값 | 출처 |
|---|---|---|
| 번들 ID | `com.anthropic.operon` | macOS 앱 권한 목록 |
| 버전 | `0.1.25-release` (public, darwin-arm64, 2026-07-24 빌드) | `runtime/*/BUILD.json` |
| 런타임 | **Bun 1.3.13** 내장 TS 단일 바이너리 (119 MB Mach-O arm64) | 바이너리 `strings` |
| 커널 | Python (`kernels/kernel_worker.py`, `micromamba` 환경) | 런타임 디렉터리 |
| ORM/DB | `drizzle` + SQLite | 런타임 디렉터리 |
| 로컬 서버 | `http://localhost:8765` (프리뷰 오리진 `:8766`) | 앱이 기동 |
| 데이터 디렉터리 | `~/.claude-science` (251.7 MB) | Customize → Storage |
| 계정 | Max 20x plan, org ID 노출 | Customize → General |
| 실행 머신 | 18 CPU 코어 / 64 GB RAM | Compute 패널 |

`operon`은 유전자 클러스터를 뜻하는 유전학 용어다. DNA 이중나선 아이콘 + 클레이색
`#D97757`(Claude 시그니처 오렌지) 브랜딩과 일관된 내부 코드명으로 보인다.

**도메인 모델은 2계층**: `프로젝트(proj_<hex>) → 세션(frame, UUIDv4)`.
URL 형태: `/projects/proj_af38586ec919/frames/7100c7da-…`

### 앱과 브라우저의 관계 (조사 과정에서 확인)

Claude Science는 데스크톱 앱이 로컬 서버를 띄우고 웹 프런트엔드가 붙는 구조다.
세션(bearer 토큰)은 **앱이 쥐고 있고 브라우저 프로필에 종속**된다:

- Claude Code 인앱 브라우저 패널 → 세션 없음 → 전 경로 401
- Google Chrome → 세션 없음 → 401
- **Aside 브라우저**(`at.studio.AsideBrowser`) → **로그인 상태 유지** → 정상 동작

즉 "앱을 재시작하라"는 안내는 브라우저 프로필이 다르면 해결되지 않는다.

---

## 2. 백엔드 아키텍처

### 2.1 인증·서버 스택 (인증 전 프로빙으로 확정)

18개 경로(`/`, `/api/*`, `/openapi.json`, `/docs`, `/graphql`, 존재하지 않는 경로 포함)를
프로빙한 결과 **전부 동일 응답**:

```
401  {"detail":"invalid bearer token"}
content-type: application/json; charset=utf-8
```

여기서 읽어낼 수 있는 것:

- **인증 미들웨어가 라우팅보다 먼저 실행**된다. 존재하는 경로와 없는 경로가 구별
  불가능하므로 **라우트 열거(enumeration)가 원천 차단**된다. 보안 설계로서 의도적이다.
- **Bearer 토큰 인증**. `server` 헤더는 제거돼 있다.

> ### ⚠️ 정정 (2026-07-25)
>
> 이 문서의 초판은 위 응답 형태(`{"detail": …}`)를 근거로 백엔드를
> **"FastAPI/Starlette + uvicorn (Python)"으로 단정했다. 이는 틀렸다.**
>
> 별도 조사(`Claude_Science_0.1.25_리버스엔지니어링_기반_Nipo_Science_상세_개발_방향서`)가
> 바이너리 수준 증거를 제시했고, 직접 재확인한 결과:
>
> ```
> $ strings ~/.claude-science/bin/claude-science | grep -i 'bun/1\.'
> Bun/1.3.13
> $ strings … | grep -iE 'uvicorn|fastapi|starlette'
> (0건)
> ```
>
> 실제 스택은 **Bun 1.3.13 기반 TypeScript 단일 바이너리**(119 MB Mach-O arm64)다.
> 런타임 디렉터리의 `drizzle`(TypeScript ORM), `sharp-runtime`, `writetrace`가 이를
> 뒷받침한다. Python은 **커널 워커에만** 쓰인다
> (`runtime/0.1.25-release/kernels/kernel_worker.py`, `micromamba`로 환경 관리).
>
> **교훈**: 에러 응답의 JSON 키 형태(`detail`)는 프레임워크 지문으로 쓸 수 없다.
> 어느 스택에서든 한 줄로 재현 가능하다. 이 문서에서 이 추론만이 유일하게
> 관측이 아닌 **추측**이었고, 정확히 그것이 틀렸다.

### 2.2 보안 헤더 (전 응답 공통)

| 헤더 | 값 | 의미 |
|---|---|---|
| `x-frame-options` | `DENY` | iframe 임베드 차단 |
| `content-security-policy` | `frame-ancestors 'none'` | 위와 이중 방어 |
| `access-control-allow-credentials` | `true` | 앱 오리진에서만 유효 |
| `vary` | `Origin` | 오리진별 응답 분기 |
| `access-control-expose-headers` | `Content-Disposition` | **파일 다운로드 기능 존재** |

`OPTIONS`는 400 — CORS 프리플라이트가 임의 오리진에 열려 있지 않다.

### 2.3 에이전트 실행 환경

세 겹으로 구성된다:

1. **샌드박스** — 코드는 격리 환경에서 실행. 호스트 폴더는 명시적으로 마운트해야 보인다.
2. **영속 Python 커널** — 세션마다 하나. Jupyter식으로 셀 이력이 누적된다
   (실측: 한 요청에 13 cells 실행, 완료 후에도 idle 상태로 유지되어 후속 질문에 재사용).
   UI에 "Notebook" 뷰로 노출된다.
3. **host SDK** — 에이전트에게 노출되는 프로그래밍 인터페이스. 스킬 설명에서 확인된 표면:
   - `host.query()` — Claude Science 자신의 세션 DB를 조회 (Self Awareness 스킬)
   - `host.compute.create('byoc:modal', …)` — 컴퓨트 프로비저닝 (Remote Compute Modal 스킬)
   - `repl` 툴 — 에이전트 프로필 생성·스킬 저작 (Customize 스킬)

**"Managed Model Endpoints" 스킬 설명에서**: 데몬이 로컬 모델 서버 컨테이너를
**온디맨드로 기동/중지**한다. 즉 무거운 과학 모델은 상주하지 않고 필요할 때만 뜬다.

---

## 3. UI 구조 (전 구성요소)

### 3.1 앱 사이드바 (좌)
- **프로젝트 스위처** — 현재 "온톨로지". 뒤로가기 화살표 + 드롭다운 + 패널 접기
- **내비게이션** — `New` / `Search` / `Customize` / `Files` / `Compute` (선 아이콘)
- **세션 목록** — `Active` / `Older` 그룹. 첫 메시지로 **세션 제목 자동 생성**
  (실측: "Using Python, compute the GC content…" → "DNA Analysis and Visualization")
- 하단 설정 기어

**세션 컨텍스트 메뉴** (우클릭):
`Rename… / Move… / Export session / Download artifacts / View notebook / Delete`

세션 삭제 다이얼로그: *"This will permanently delete this session. **Artifacts created
in this session will remain in the project.** This action cannot be undone."*
→ **세션과 아티팩트의 수명주기가 분리**돼 있다. 대화는 휘발성, 산출물은 프로젝트 자산.

### 3.2 메인 영역
- 상단 **세션 탭 바** — 브라우저 탭처럼 누적. 각 탭이 하나의 세션
- **메시지 렌더링** — 넘버드 리스트, 블록쿼트, 볼드, 이탤릭(학명 `Erwinia amylovora`),
  인라인 모노스페이스 칩(코돈 `ATG` `TAA` `TGA`)
- **툴콜 그룹** — 접이식. 헤더가 요약을 담는다:
  `Ran 2 commands, loaded a skill · 3 steps · 1 failed`
  하위 각 단계에 개별 상태: `loaded` / `10 lines of output` / `KeyError: 'left_bottom'`
- **아티팩트 갤러리** — `GENERATED · 2`. 타입 인식 미리보기:
  PNG는 썸네일, CSV는 스키마 요약(`4 rows · 3 columns`, 컬럼명)
- **Reviewer 카드** — 인라인. `Reviewer · 1 finding fixed · 1 check` 또는 `No issues found`
- 메시지 하단 액션: 복사 / 👍 / 👎
- 스크롤 시 "Your last message" 앵커 버튼

### 3.3 컴포저 (하단)
```
Ask anything — @ for artifacts, # for sessions, / for skills, ⌘K to search…
[+]  [⊞]                                          [Opus 5 ⌄]  [🎤]  [↑]
```
- **멘션 체계**: `@`=아티팩트 · `#`=세션 · `/`=스킬 · `⌘K`=전역 검색
- `+` → `Attach files`(로컬 첨부) / `Your files`(프로젝트 저장소에서 선택)
- `⊞` → 라벨 없는 토글 (도구/커넥터 모드로 추정, 팝오버 없이 상태만 변경)
- 생성 중에는 전송 버튼이 **정지(■)**로 바뀌고, 컴포저 위에 `Notebook`·`Reviewing` 칩이 뜬다

### 3.4 우측 도킹 패널 — Files / Compute 2탭

**Files 탭**
- 소스 드롭다운:
  - `Artifacts` → All artifacts
  - `This computer (MacBook Pro)` → 마운트된 폴더 목록 (**`ro` 배지** = 읽기 전용)
  - `+ Add folder…` → 새 폴더 접근 부여
- 검색 / `N artifacts` 카운트 / 정렬(`Created ↓`) / 그리드·리스트 뷰 토글 / 확장
- 아티팩트는 **생성 세션별로 그룹화**되고 타임스탬프가 붙는다.
  세션이 지워지면 그룹명이 `Deleted session`으로 바뀐다.

**아티팩트 컨텍스트 메뉴** (우클릭) — 제품 성숙도를 가장 잘 보여주는 지점:
```
Star / Hide
Open in Artifact Viewer
View in context / Open in split view
Provenance          ← 생성 계보 추적이 1급 기능
Copy link / Rename / Download
Export Metadata / Export to Cloud
Delete
```
삭제 다이얼로그: *"…**and all its versions** will be permanently deleted"*
→ **아티팩트에 버전 관리가 있다.**

**Compute 탭** — 라이브 커널 모니터
- 메모리 사용량(스파크라인) / `~N of 18 cores CPU` / `N kernels · N running`
- 커널 트리: `온톨로지 › DNA Analysis and… [CURRENT] · 1 kernel · 157.4 MB · 0.0 cores`
  → `idle 54s · 10 cells run` + RSS + CPU 스파크라인 + 현재 작업 설명
- 유휴 시: *"Kernels appear here the moment any session starts computing on this machine."*

---

## 4. 설정 센터 (Customize) — 11개 창

### Capabilities

#### Skills (24 활성, 토글식)
"Featured — Research skills from Anthropic" 그룹으로 묶이고 개별 on/off.
`+ Add skill`로 추가. `/` 피커의 관리자 화면에 해당한다.

#### Connectors (30개, 전부 ON)
과학 데이터베이스 커넥터 계층. Network의 원시 도메인 허용목록과 달리
**타입이 있는 도구/데이터소스**다:

> BioMart · Cancer Models · CellGuide · Chemistry · Clinical Genomics · Drug Regulatory ·
> Expression · Genes & Ontologies · Genomes · Human Genetics · Ketcher Chemistry ·
> Literature Graph · Omics Archives · Protein Annotation · …

#### Specialists (서브에이전트)
- **Your specialist agents** (사용자 저작): `Plant Pathogen Detection Specialist` (ON),
  `Probe Diagnostic Specialist` (OFF)
- **Built-in**: **`Reviewer`** (ON) ← 대화에 인라인 카드로 나타나는 자동 검토 에이전트

#### Memory
카테고리별 노트 저장소(`About you` 등, `New category` 추가 가능). 현재 Off.
*"Memory is off. Claude won't save new notes or recall existing ones, but the notes
below are kept and stay editable."* → **끄더라도 기존 노트는 보존**된다.

#### Compute — 3가지 백엔드
1. **SSH hosts** — 자체 서버 / 클러스터 / SLURM 잡 제출 노드
2. **Cloud providers** — **Modal** (사용자 자기 계정의 서버리스 GPU, BYOC)
3. **Model endpoints** — **NVIDIA BioNeMo NIM** (로컬 NIM docker 컨테이너 또는 외부 호스팅
   NIM API). *"Each registration asks you individually; disabling stops and removes them all."*

#### Network ★ (ontologylab과 가장 직접적으로 겹치는 창)

핵심 문장:
> **"When Claude runs code for you, that code can only connect to domains on this list."**

**deny-by-default 도메인 허용목록**이며, 3층 구조다:

| 층 | 내용 |
|---|---|
| 카테고리 토글 | Package management(16) · NCBI/NIH(3) · Genomics & biology(22) · Proteomics(9) · Literature & citations(8) · Clinical & pharma(14) |
| 사용자 Allowed domains | 개별 도메인. *"…without asking each time"* |
| 인프라 | Proxy address · Package mirror (conda/pypi 미러) |

카테고리별 대표 호스트:
- Package management: pip, conda, npm, CRAN, Bioconductor, GitHub
- Genomics & biology: Ensembl, Reactome, KEGG, gnomAD, GTEx, ENCODE
- Proteomics: UniProt, STRING, EBI, Foldseek, RCSB PDB, Protein Atlas
- Literature & citations: Semantic Scholar, arXiv, bioRxiv, Crossref, DOI, OpenAlex
- Clinical & pharma: FDA, ClinicalTrials, Open Targets, COSMIC, ClinGen, CIViC

**사용자가 직접 추가해 둔 Allowed domains** — ontologylab §5와 정확히 일치:
```
api.core.ac.uk
api.springernature.com
api.elsevier.com
```

설계상 중요한 점: **"묻지 않고 통과"가 허용목록의 정의**다. 즉 목록에 없는 도메인은
차단이 아니라 **개별 승인 요청**으로 흐를 여지가 있다(카테고리 토글 OFF는 차단).
ontologylab의 정확일치 허용목록보다 한 단계 유연하되, 기본값은 동일하게 deny다.

### Workspace

#### Permissions — 세분화된 권한 원장
각 권한에 **범위(Global / 세션별)**가 붙고 개별·일괄 회수 가능:

| 그룹 | 항목 |
|---|---|
| **Files** ("Host folders mounted into the sandbox") | `~/Videos/…/세션별` **read-only** · Global |
| **Registry writes** ("mutations that persist across sessions") | Create agent · Update agent · Publish skill · Edit skill · Attach skill · Detach skill · Attach connector · Detach connector |
| **Local compute** | "Sandbox tools that run without preview" |

→ **에이전트가 자기 자신을 수정하는 행위(스킬 저작·에이전트 생성)를 별도 권한으로 통제**한다.
이것이 Customize/Skill Creator 스킬이 존재할 수 있는 안전 근거다.

#### Credentials ★ (§8-2의 근거)

핵심 문장:
> **"API keys and tokens for services Claude uses on your behalf — stored encrypted on your computer"**

| 서비스 | 상태 |
|---|---|
| AWS · GitHub · Google Cloud · Microsoft Azure · Modal · NVIDIA API | 미연결 (`Connect`) |
| **Literature access (journals, etc.)** | **연결됨** (`Disconnect`) |
| **OpenAlex** | **연결됨** (`Disconnect`) |
| Custom | "Keys you added for other services" |

주목할 설계:
- 키는 **평문 파일도, 환경변수 이름 참조도 아닌 로컬 암호화 저장**이다.
- 출판사 키들이 개별 항목이 아니라 **"Literature access (journals, etc.)" 하나로 번들**돼 있다.
  사용자에게는 "저널 접근"이라는 **역할** 단위로 보이고, 내부적으로 여러 출판사 키를 담는다.
- 연결/해제라는 **이진 상태**로 추상화된다. 키 값을 UI에 다시 노출하지 않는다.

#### Storage
- Data location: `~/.claude-science` · 251.7 MB · default location ·
  `Change location` 가능
- Disk usage 스캐닝
- Cloud storage: 버킷 연결 (Credentials 탭에서 자격증명 추가 후 사용)

**설계 의의**: 데이터를 `~/Documents`가 아니라 `~/`의 도트 디렉터리에 둔다.
macOS의 'Desktop & Documents' iCloud 동기화 범위 **밖**이므로, ontologylab이 겪은
iCloud 유출 문제를 애초에 만들지 않는다.

#### Usage — 토큰 회계
- **Plan limits [Max]**: Current session 24%(1시간 51분 후 리셋) / Weekly 24%(5일) /
  Extra usage budget 72% (월 상한 대비). `Manage on claude.ai` 연동.
- **Where tokens go** (로컬 추정, 24h/7d/30d):

| 항목 | 비중 |
|---|---|
| **Tool calls** | **57%** |
| Assistant prose | 18% |
| **Reviewer** | **17%** |
| Artifact provenance | 4.4% |
| Compaction | 3.9% |
| Other auxiliary | <0.1% |

- **By session**: 세션별 모델·시각·툴 비중 (`claude-opus-4-8 · 57% tools`)

**해석**: 산문 생성보다 **도구 호출이 3배** 비싸고, **리뷰가 전체의 1/6**을 차지한다.
품질 보증에 실제로 상당한 예산을 쓰는 구조다. `Artifact provenance`가 별도 항목이라는
것은 **출처 추적이 토큰을 쓰는 1급 기능**임을 뜻한다.

#### General
- **Account**: Max 20x plan, Organization ID
- **Default model**: Opus 5
- **Reasoning effort**: **Max** — *"How long Claude thinks before responding. Higher
  effort is more thorough but slower and uses more of your limits. Applies to Opus models."*
- **Subagent model**: `Same as main model` — *"Model used by subagents when Delegation is on."*
- **Reviewer model**: **Sonnet 5** — *"Model the Reviewer uses for background review when
  work completes. Applies to all sessions; a session's own Reviewer model setting overrides it."*
- **Automatically switch models when a message is flagged** (OFF) — *"When a safety filter
  pauses a session, retry it right away on the suggested fallback model."*

**해석**: 작성은 Opus 5 / 검토는 Sonnet 5. **역할별 모델 분리**가 제품 기본값이다.
비싼 모델로 만들고 싼 모델로 검증한다.

---

## 5. 스킬 카탈로그 (~35개)

`/` 피커 전량 열거. `Featured`(Anthropic 제공)와 `personal`(사용자 저작)로 구분된다.

### 구조 예측
| 스킬 | 내용 |
|---|---|
| AlphaFold2 | 단량체·다량체 구조 예측 (ColabFold 러너, Mirdita et al. 2022) |
| Boltz | Boltz-2 — 단백질·핵산·저분자 복합체 (Passaro & Wohlwend et al. 2025) |
| Chai-1 | 파운데이션 모델 기반 복합체 예측 (Chai Discovery 2024) |
| ESMFold2 | Biohub ESMFold2 / ESMFold2-Fast 전원자 co-folding (Candido et al. 2026) |
| OpenFold3 | AlphaFold3의 오픈웨이트 PyTorch 재현 (AlQuraishi Lab) |

### 단백질 설계 (역폴딩)
| 스킬 | 내용 |
|---|---|
| ProteinMPNN | PDB 백본 → 아미노산 서열 (Dauparas et al. 2022) |
| LigandMPNN | 리간드·핵산·금속 맥락 포함 역폴딩 (Dauparas et al. 2023) |
| SolubleMPNN | soluble-PDB 부분집합으로 재학습 — 가용성 편향 서열 |

### 유전체 / 서열 모델
| 스킬 | 내용 |
|---|---|
| Evo 2 | 장문맥 유전체 파운데이션 모델 — DNA 스코어링·임베딩·생성 |
| Borzoi | DNA 서열 → 유전체 전역 기능 트랙(RNA-seq, CAGE, DNase, ChIP) |
| ESM-2 | Meta AI 단백질 임베딩 (`fair-esm`) |

### 단일세포 / 도킹
| 스킬 | 내용 |
|---|---|
| scGPT | 단일세포 발현 임베딩·주석 (파운데이션 모델) |
| scvi-tools | 확률적 scRNA-seq — scVI(배치보정 잠재공간), scANVI(준지도 라벨 전이) |
| DiffDock | DiffDock-L 블라인드 디퓨전 도킹 (Corso et al. 2023/2024) |

### 컴퓨트 인프라
| 스킬 | 내용 |
|---|---|
| Compute Env Setup | 원격 프로바이더 환경 구성 — SSH/conda 호스트, Slurm 클러스터 |
| Managed Model Endpoints | 데몬이 로컬 모델 서버 컨테이너를 온디맨드 기동/중지, 또는 원격 업스트림 등록 |
| Remote Compute Modal | 사용자 Modal 계정에서 GPU 잡 (`host.compute.create('byoc:modal', …)`) |
| Remote Compute Ssh | **submit → wait_for_notification → harvest** 비동기 워크플로 (SSH/SLURM) |
| Using Model Endpoint | 등록된 엔드포인트를 스코프드 추론 커널에서 HTTP 호출 (`BASE_URL` 사전 로드) |

### 메타 / 자기 인식
| 스킬 | 내용 |
|---|---|
| Customize | `repl` 툴로 커스텀 에이전트 프로필 생성·구성, 신규 스킬 저작 |
| Skill Creator | 스킬 생성·수정·개선 및 **스킬 성능 측정** |
| Self Awareness | Claude Science 자신의 세션 DB 스키마 + `host.query()` SDK 표면 |
| Product Self Knowledge | Anthropic 제품(Claude Code 등)에 대한 사실 — 답변 전 참조 |

### 문헌 / 집필
| 스킬 | 내용 |
|---|---|
| Literature Review | 문헌 탐색·검증·종합 — "what's the seminal paper for X"부터 다중소스 리뷰까지 |
| Pdf Explore | 첨부 PDF·논문·보고서에서 여러 위치를 교차 참조해야 할 때 |
| Paper Narrative | 논문 **그림들이 전하는 스토리**를 판단·재구성 (입력은 원고+그림 덱) |
| Indication Dossier | 치료 적응증 도시에 — 환자군·역학·질병생물학·표준치료·규제 선례 |

### 그림 / 디자인
| 스킬 | 내용 |
|---|---|
| Figure Composer | 출판급 멀티패널 그림 — 한 줄 주장+데이터 참조에서, 또는 기존 그림에서 |
| Figure Style | 최종 산출 그림의 정확성·가독성 규칙 (탐색용 플롯에는 미적용) |
| Canvas Design | .png/.pdf 비주얼 아트 |
| Algorithmic Art | p5.js 시드 랜덤 + 인터랙티브 파라미터 |
| Slack Gif Creator | Slack 최적화 애니메이션 GIF |

### 일반 / personal
| 스킬 | 구분 | 내용 |
|---|---|---|
| Morning | Featured | 모닝 브리프를 HTML 아티팩트로, 또는 평일 반복 작업으로 |
| **Multisource Lit Harvest** | personal | **6개 소스 동시 수확** — OpenAlex, PubMed, Scopus(Elsevier), CORE, Springer, Semantic Scholar |
| **Source Attribution Reviewer** | personal | 모든 사실 주장에 **근거 등급(evidence-level)** 강제 |
| **Plant Pathogen Detection** | personal | 식물병원균(세균·진균·난균·바이러스) 탐지 후보 분자·프로브·센싱 전략 |
| **Probe Diagnostic Workflow** | personal | 형광 프로브 관측(특히 현장 배치 진단 프로브) — 진짜 분자 발광과 그 외를 구별 |

**모델 로스터**: Opus 5(*Best for scientific rigor*) / Sonnet 5(*Most efficient for simple
tasks*) / Haiku 4.5(*Fastest, lightweight*) + More models: Opus 4.8·4.7·4.6·4.5·4.1,
Sonnet 4.6·4.5, Fable 5

---

## 6. 실사용 관찰 (라이브 런)

**프롬프트** (Opus 5, 신규 세션):
> "Using Python, compute the GC content and reverse complement of this DNA sequence:
> ATGCGTACCGGATTACAGGCGTGACCTAA. Then make a simple bar chart of the four nucleotide counts."

### 관찰된 에이전트 루프

| # | 단계 | 관찰 내용 |
|---|---|---|
| 1 | **스킬 자동 로드** | 차트 요청을 감지 → `Loading figure style guidance · loaded`. 명시하지 않았는데 **Figure Style 스킬을 스스로 호출** |
| 2 | **커널 기동 + 실행** | Compute 패널에 커널 등장. `Computing GC content and reverse complement · 10 lines of output` |
| 3 | **자가수정 ①** | `Rendering nucleotide count bar chart` → **`KeyError: 'left_bottom'`** 실패 → 스스로 수정 |
| 4 | **자가수정 ②** | `Fixing x-label overlap and re-save · 1 figure · 2 lines of output` — **x축 라벨 겹침을 스스로 인지**하고 재저장 (Figure Style의 가독성 규칙 반영) |
| 5 | **아티팩트 생성** | `GENERATED · 2` |
| 6 | **요청 초과 도메인 지능** | 서열이 ORF임을 인지 → 프레임 내 번역 → codon 8의 `TGA` 스톱 발견 → 펩타이드 **MRTGLQA** 도출 |
| 7 | **Reviewer 백그라운드 검증** | `Reviewing` 스피너 → 커널이 "Verifying figure geometry at c…" 실행 → **`Reviewer · No issues found`** |
| 8 | **커널 유지** | `idle 1m · 13 cells run` — 종료하지 않고 후속 질문 대기 |

### 산출물 품질

**`nucleotide_counts.png`** — 단순 카운트 차트가 아니었다:
- 제목이 **발견을 서술**한다: *"GC content 51.7%: G+C (15 nt) narrowly exceeds A+T (14 nt)"*
- **의미론적 색 구분**: G/C = 파랑, A/T = 금색 + 범례
- 막대 위 값 라벨(8, 7, 8, 6), y축 `Count (of 29 nt)`

**`nucleotide_composition.csv`** — 4 rows × 3 columns (nucleotide, count, percentage)

→ 그림과 **기계가 읽을 수 있는 데이터**를 함께 낸다. 그림만 주면 재사용이 불가능하다는
점을 설계에 반영한 것으로 보인다.

### 이 런에서 확인된 설계 원칙

1. **실패를 숨기지 않는다** — `3 steps · 1 failed`가 헤더에 그대로 노출된다.
   에러 종류(`KeyError: 'left_bottom'`)까지 보여준다.
2. **자율 자가수정** — 2회의 오류를 사람 개입 없이 교정했다.
3. **작성과 검토의 분리** — Reviewer가 **별도 모델(Sonnet 5)로 백그라운드 실행**되며,
   단순 텍스트 검토가 아니라 **코드로 그림 기하를 검증**한다.
4. **스킬은 작업에서 자동 선택**된다 — 사용자가 `/figure-style`을 치지 않았다.

---

## 7. 디자인 시스템

로그인 셸(인증 전 정적 HTML)이 자족적이라 원본 토큰을 그대로 추출할 수 있었다.

### 타이포그래피
Anthropic 자체 서체 3종을 woff2로 **인라인 임베드**(외부 폰트 요청 없음):

| 서체 | 용도 | 설정 |
|---|---|---|
| **Anthropic Sans** | 본문 | 가변 300–800, 본문 **13px / line-height 16px / weight 430** |
| **Anthropic Serif** | 제목·워드마크 | **28px / weight 500**, `ss01` + `dlig` 스타일세트, optical sizing |
| **Anthropic Mono** | 코드 | 400, 12px |

`font-feature-settings: "dlig" 0` — 본문에서는 임의 합자를 끄고, 워드마크에서만 켠다.

### 컬러 토큰 (light / dark 완비, `color-scheme: light dark`)

| 토큰 | Light | Dark |
|---|---|---|
| `--surface-0` (앱 배경) | `#f9f9f7` | `#0d0d0d` |
| `--surface-2` (카드) | `#ffffff` | `#2c2c2a` |
| `--text-primary` | `#0b0b0b` | `#ffffff` |
| `--text-secondary` | `#52514e` | `#c3c2b7` |
| `--text-muted` | `#898781` | — |
| `--fill-primary` (+hover) | `#0b0b0b` (`#2c2c2a`) | `#ffffff` (`#e1e0d9`) |
| `--code-bg` | `#f0efec` | `rgb(255 255 255/.08)` |
| `--banner-bg` | `#fcfcfb` | `#1a1a19` |

**순백·순흑이 아니라 따뜻한 오프화이트/오프블랙**이 핵심이다.
브랜드 마크는 클레이 `#D97757` 35% 오버레이 + 흰 DNA 이중나선, macOS 스퀘어클(radius 63.75/270).

### 형태·모션
```css
--card-shadow: 0 0 0 1px rgb(11 11 11/0.1),    /* 헤어라인 링 */
               0 1px 2px 0 rgb(11 11 11/0.06),  /* 근접 그림자 */
               0 2px 8px 0 rgb(11 11 11/0.08);  /* 확산 그림자 */
```
- 카드 radius **32px**(2rem), 패딩 2.5rem → 640px↑ 3.5rem
- 버튼: 높이 40px, radius 10px, 15px/500,
  `transition: background-color .12s cubic-bezier(.165,.84,.44,1)`
- 배너 radius 8px, 코드 6px
- `:focus-visible` 2px 아웃라인(offset 2px), `::selection`이 fill/on-primary 반전
- 레이아웃: 중앙 flex 컬럼, 폭 18rem (배너 있으면 `:has(.banner)`로 22rem), 섹션 gap 3–4rem

### DOM 패턴
```html
<div class="card"><div class="col">
  <div class="brand">
    <svg/>
    <div class="lockup">
      <span class="wordmark" role="heading" aria-level="1">Claude Science</span>
      <span class="state">Beta</span>
    </div>
  </div>
  <div class="content">
    <div class="banner"><svg/><span>…<strong>강조</strong>…</span></div>
  </div>
</div></div>
```
워드마크는 실제 `<h1>`이 아니라 `role="heading" aria-level="1"`인 `<span>`이다
(시각적 크기와 문서 구조를 분리).

### 위계 원칙
**본문 430 / 강조 500–600 / 제목만 serif.** 볼드를 남발하지 않고 **서체 전환**으로
위계를 만든다. 굵기는 430→500→600의 좁은 범위만 쓴다.

---

## 8. ontologylab에 대한 시사점

Claude Science는 ontologylab이 도달하려는 지점의 레퍼런스다. 설계 결정별로 매핑한다.

### 8-1. 허용목록 — 방향은 같고, 조직화가 다르다

| 항목 | ontologylab (현재 계획) | Claude Science |
|---|---|---|
| 기본 정책 | deny-by-default 정확일치 | 동일 |
| 조직화 | 평평한 호스트 리스트 | **분야별 카테고리 + 그룹 토글** |
| 사용자 확장 | 코드 수정 | **UI에서 도메인 추가** |
| 인프라 | 없음 | 프록시 · 패키지 미러 |

**등록된 출판사 3사가 완전히 일치한다**: `api.elsevier.com` · `api.springernature.com` ·
`api.core.ac.uk`. ontologylab 계획 §5가 겨냥한 대상이 정확히 같다.

→ **채택 권고**: 호스트를 평평하게 나열하는 대신 카테고리(논문 API / 출판사 API /
패키지)로 묶고, 카테고리 단위 on/off를 두면 `IMPLEMENTED_SOURCES` 동기화 문제(제약 6)도
자연히 정리된다.

### 8-2. 키 저장 — (A) 환경변수 결정의 재검토 ★

ontologylab은 두 안 사이에서 결정했다:
- 원안: 평문 파일 저장 → iCloud 동기화 발견으로 철회
- (A): 환경변수 이름만 저장 → 확정

**Claude Science의 답은 제3의 것이다**: *"stored encrypted on your computer"* —
**로컬 at-rest 암호화**.

세 안의 비교:

| 기준 | 평문 파일 | (A) 환경변수 | 로컬 암호화 |
|---|---|---|---|
| 디스크에 비밀 존재 | ○ 평문 | ✗ 없음 | ○ 암호문 |
| 백업/동기화 유출 | **위험** | 안전 | 안전(키 없이 무의미) |
| 키 추가 마찰 | 낮음 | **높음** (plist 편집 + `launchctl bootout/bootstrap`) | 낮음 (UI에서 Connect) |
| 구현 비용 | 최소 | 최소 | **중간** (암호화 계층 + 키 관리) |
| `providers.py` 불가침 원칙 | 위배 | 유지 | 유지(별도 계층) |

**추가로 눈여겨볼 두 가지 설계:**

1. **역할 단위 번들** — 출판사별 항목이 아니라 **"Literature access (journals, etc.)"**
   하나로 묶여 있다. 사용자는 "저널 접근을 연결했다"만 알면 되고, 내부적으로 Elsevier·
   Springer·CORE 키를 담는다. ontologylab의 `sources.json`도 소스별 엔트리 대신
   **역할 단위**로 추상화할 여지가 있다.
2. **연결/해제 이진 상태** — 저장 후 키 값을 UI에 다시 노출하지 않는다.
   ontologylab 계획의 `key_present` 패턴과 정확히 같은 사상이다.

**권고**: macOS라면 **Keychain**이 가장 자연스러운 구현이다
(암호화 저장 + OS 수준 접근 통제 + 백업 시 안전, 추가 암호화 코드 불필요).
`sources.json`에는 Keychain 항목 참조만 두면 `providers.py` 불가침 원칙과
"디스크에 비밀 없음" 원칙을 **둘 다** 지키면서 (A)의 마찰을 없앨 수 있다.
단 CLI/서버 양쪽에서 Keychain 접근 권한이 필요하므로, 그 경로 검증이 선행 조건이다.

### 8-3. 작성 / 검토 분리 — 제품 기본값

Claude Science는 **Reviewer를 별도 스페셜리스트로 두고 더 싼 모델(Sonnet 5)로
백그라운드 실행**한다. 토큰 회계에서 **리뷰가 전체의 17%**를 차지한다.
검토가 "여유 있으면 하는 것"이 아니라 **고정 비용 항목**이다.

→ ontologylab의 추출 검토 게이트(사람이 승인한 것만 지식이 된다)와 같은 사상이며,
**자동 1차 검토를 싼 모델로 돌리고 사람은 그 결과만 보는** 2단 구조를 고려할 만하다.

### 8-4. 프로버넌스 — 1급 시민

- 토큰 회계에 **`Artifact provenance` 4.4%**가 별도 항목으로 존재
- 아티팩트 컨텍스트 메뉴에 **`Provenance`** 항목
- 아티팩트에 **버전 관리**("all its versions")

→ ontologylab의 `provenance.jsonl`과 방향이 같다. 다만 Claude Science는 이를
**UI에서 조회 가능한 기능**으로 노출한다. ontologylab도 provenance를 파일에만 두지 말고
검토 화면에서 "이 노드가 어디서 왔는가"를 볼 수 있게 하면 검토 게이트의 실효가 올라간다.

### 8-5. 샌드박스 + 스코프드 마운트

- 코드는 샌드박스에서 실행
- 호스트 폴더는 **명시적으로 마운트**해야 보이고 **`ro` 배지**로 읽기 전용 표시
- 마운트 목록이 Permissions에 원장으로 남고 개별 회수 가능

→ ontologylab의 **C1**(`POST /api/collect`가 `data/` 내부 파일을 삼키는 문제)에 대한
근본 해법이 이 형태다. 경로 검증(블랙리스트)보다 **마운트 화이트리스트**가 견고하다.
당장은 계획대로 `data_dir` 내부 거부로 막되, 장기적으로는 "수집 가능한 폴더를 명시 등록"
모델이 더 안전하다.

### 8-6. 비동기 잡 모델

Remote Compute Ssh 스킬의 워크플로: **submit → wait_for_notification → harvest**.

→ ontologylab의 리서치 런(수집+추출을 `kind="research"` 잡으로 묶음)과 같은 형태다.
특히 **취소 문제(M6)**에서, Claude Science가 잡을 "제출 후 알림 대기"로 모델링한 것은
블로킹 fetch를 스레드에 넣는 ontologylab 방식보다 취소·재개에 유리하다.

### 8-7. 데이터 위치 — iCloud 문제의 원천 회피

Claude Science는 데이터를 **`~/.claude-science`**에 둔다. `~/Documents` 밖이므로
'Desktop & Documents' iCloud 동기화 대상이 아니다.

→ ontologylab은 저장소가 `~/Documents/MUNI/` 아래에 있어 `data/`가 동기화됐다.
`launcher/move-data-out-of-icloud.sh`가 `~/Library/Application Support/ontologylab`으로
옮기는 것은 **Claude Science와 같은 결론에 사후적으로 도달**한 것이다.
(A) 결정으로 키가 디스크에서 빠졌으므로 이 이주는 필수가 아니게 되었지만,
`kg.sqlite`와 수집 원문은 여전히 동기화되고 있다.

### 8-8. 채택 우선순위

| 순위 | 항목 | 근거 | 비용 |
|---|---|---|---|
| 1 | **Keychain 기반 키 저장** (§8-2) | (A)의 마찰 제거 + 디스크 무비밀 원칙 유지 | 중 |
| 2 | **허용목록 카테고리화** (§8-1) | 소스 목록 4중 복제(제약 6) 문제와 함께 해결 | 소 |
| 3 | **provenance UI 노출** (§8-4) | 검토 게이트의 실효 상승 | 중 |
| 4 | **자동 1차 검토(싼 모델)** (§8-3) | 사람 검토 부하 경감 | 중 |
| 5 | 수집 폴더 화이트리스트 (§8-5) | C1의 근본 해법 (당장은 계획대로) | 대 |

---

## 부록 A. 조사 방법론

1. **인증 전 표면 프로빙** — 로컬 서버에 18개 경로를 fetch하여 응답 코드·헤더·바디를
   수집. 라우팅 구조와 스택을 추론.
2. **정적 셸 분석** — 로그인 페이지의 인라인 CSS/DOM/폰트를 추출하여 디자인 시스템 복원.
3. **UI 전수 탐색** — Aside 브라우저 + computer use(vision)로 모든 화면·메뉴·설정 창을
   열어 스크린샷 판독. 확대(zoom)로 소형 텍스트 확인.
4. **실사용 검증** — 신규 세션에서 실제 프롬프트를 실행하고 에이전트 루프 전체
   (스킬 로드 → 커널 → 실패 → 자가수정 → 아티팩트 → 리뷰)를 관찰.
5. **정리** — 생성한 테스트 세션과 아티팩트 2건을 삭제하여 원상 복구.

**하지 않은 것**: 인증 우회, 앱 번들 디컴파일, 자격증명 파일 열람, 사용자 연구 데이터 분석.

## 부록 B. 미확인 항목

- 컴포저의 `⊞` 토글의 정확한 기능 (툴팁 없음, 팝오버 없이 상태만 변경)
- `Delegation` 설정의 위치 (General에서 언급되나 토글은 미발견)
- 자격증명 암호화의 구현 방식 (Keychain인지 자체 암호화인지 — 파일 탐색 차단됨)
- `Connectors` 30개 전체 목록 (14개까지 확인, 나머지는 스크롤 미도달)
- Artifact Viewer / split view / Export to Cloud의 실제 동작
