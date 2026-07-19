# ontologylab 실행 (macOS 앱)

앱 아이콘을 클릭하면 로컬 대시보드 서버가 뜨고 브라우저가 자동으로 열립니다 — Claude science처럼 로컬 페이지로 넘어가는 방식입니다.

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
2. 준비되면 기본 브라우저에서 대시보드가 열립니다.

이미 떠 있으면 새 서버를 또 띄우지 않고 브라우저만 다시 엽니다.

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

- 앱이 브라우저를 열었는데 에러 페이지가 뜬다 → `.launcher.log`(저장소 루트)에 서버 로그가 남습니다.
- 저장소를 다른 곳으로 옮겼거나 포트를 바꾸고 싶다 → **빌드 스크립트를 다시 실행**하면 됩니다 (앱에 절대경로가 구워져 있음).
- "확인되지 않은 개발자" 경고 → 최초 실행 시 앱을 **우클릭 → 열기**로 한 번 허용하면 이후엔 그냥 클릭됩니다.

## 참고

- 빌드된 `.app`은 이 컴퓨터 전용(절대경로가 박힘)이라 저장소에 커밋하지 않습니다. **이 빌드 스크립트가 정본**이고, 언제든 다시 실행해 재생성합니다.
- CLI로 직접 쓰려면: `.venv/bin/python -m ontologylab.serve --port 8765` (대시보드) / `.venv/bin/python -m ontologylab.main --help` (파이프라인). 자세한 건 저장소 루트 `README.md` 참조.
