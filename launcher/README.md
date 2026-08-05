# ontologylab 실행 (macOS 앱)

앱 아이콘을 클릭하면 로컬 대시보드 서버가 뜨고 Aside에서 웹앱이 열립니다. macOS의 기본 브라우저 설정이 바뀌어도 다른 브라우저로 새지 않도록 Aside의 앱 식별자를 사용합니다.

## 0. 새 기계에 클론했다면 — iCloud부터

이 저장소를 `~/Documents` 아래에 두고 macOS의 **'Desktop & Documents' iCloud 동기화**가 켜져 있으면, 기본 경로(`ROOT/data`, `ROOT/packs`)에 쌓이는 지식그래프·원문·팩이 전부 Apple 서버로 올라갑니다. `~/Documents/...`와 CloudDocs 쪽 경로는 심볼릭 링크가 아니라 **같은 디렉터리**라서, 경로만 봐서는 알 수 없습니다.

```bash
bash launcher/move-data-out-of-icloud.sh
```

`data/`와 `packs/`를 `~/Library/Application Support/ontologylab/`(동기화 대상 아님)로 옮기고 원래 자리에 심볼릭 링크를 남깁니다. 그 링크는 `.gitignore` 대상이라 **클론에는 따라오지 않으므로, 기계마다 한 번씩 실행해야 합니다.**

잊어버려도 데이터가 새지는 않습니다 — 서버와 CLI가 동기화되는 경로를 거부하고 이 명령을 안내합니다(`ontologylab/paths.py`의 `icloud_refusal`). 의도적으로 그 경로를 쓰려면 `ONTOLOGYLAB_ALLOW_ICLOUD=1`을 설정하세요.

## 1. 앱 만들기 (최초 1회)

먼저 venv가 있어야 합니다:

```bash
cd ~/Documents/MUNI/ontologylab
python3.11 -m venv .venv
.venv/bin/pip install -e '.[server,mcp]'
```

그다음 앱을 빌드합니다:

```bash
bash launcher/build-macos-app.sh
```

→ `~/Applications/ontologylab.app` 과 `~/Applications/Stop ontologylab.command` 이 생깁니다.
(Launchpad·Spotlight에서 "ontologylab"으로 검색해도 뜹니다.)

## 2. 실행

**`ontologylab` 앱을 클릭**하면 끝입니다:

1. 대시보드 서버가 백그라운드로 뜨고
2. 준비되면 Aside의 새 탭에서 대시보드가 열립니다.

이미 서버가 떠 있으면 새 서버를 또 띄우지 않고 웹앱 탭만 엽니다.

화면의 영문 논문 제목·근거 문장·설명은 저장된 원문을 바꾸지 않고 한국어로 번역해 표시합니다. 번역은 사용 가능한 Claude·Codex·Gemini 엔진을 순서대로 사용하고 브라우저에 결과를 캐시합니다. 유전자·단백질·약물·식별자·코드 값은 원문 표기를 유지합니다.

## 3. 종료

**`Stop ontologylab`** 을 클릭하면 서버가 종료됩니다.
(서버는 백그라운드라 창을 닫아도 계속 돕니다 — 끄려면 이 Stop을 쓰세요.)

## 포트

- 기본 포트는 **8765**입니다. 다른 프로그램(예: Claude science가 8765를 씀)이 이미 쓰고 있으면, 앱이 **8766, 8767…로 자동으로 빈 포트를 찾아** 띄웁니다. 선택된 포트는 `.launcher.port`에 기록되고 다음 클릭 때 재사용됩니다.
- 특정 포트로 고정하려면 빌드 때 지정:
  ```bash
  bash launcher/build-macos-app.sh --port 8790
  ```

## 옵션

```bash
bash launcher/build-macos-app.sh \
  --port 8765 \                 # 선호 포트 (사용 중이면 위로 스캔)
  --out ~/Applications \        # 앱 설치 위치
  --repo ~/Documents/MUNI/ontologylab   # 이 저장소 경로
```

## 문제가 생기면

- 브라우저에 오류 페이지가 뜬다 → launchd 서버는 `~/Library/Logs/ontologylab-server.log`, 앱이 직접 시작한 서버는 `.launcher.log`(저장소 루트)에 로그가 남습니다.
- 저장소를 다른 곳으로 옮겼거나 포트를 바꾸고 싶다 → **빌드 스크립트를 다시 실행**하면 됩니다 (앱에 절대경로가 구워져 있음).
- "확인되지 않은 개발자" 경고 → 최초 실행 시 앱을 **우클릭 → 열기**로 한 번 허용하면 이후엔 그냥 클릭됩니다.

## 참고

- 빌드된 `.app`은 이 컴퓨터 전용(절대경로가 박힘)이라 저장소에 커밋하지 않습니다. **이 빌드 스크립트가 정본**이고, 언제든 다시 실행해 재생성합니다.
- CLI로 직접 쓰려면: `.venv/bin/python -m ontologylab.serve --port 8765` (대시보드) / `.venv/bin/python -m ontologylab.main --help` (파이프라인). 자세한 건 저장소 루트 `README.md` 참조.
