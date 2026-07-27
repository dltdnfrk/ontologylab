#!/bin/bash
# data/ 와 packs/ 를 iCloud 동기화 범위 밖으로 옮긴다.
#
# 왜: 이 저장소는 ~/Documents 아래에 있고 macOS의 'Desktop & Documents' iCloud
# 동기화가 켜져 있다. 확인된 사실 —
#   ~/Documents/MUNI/ontologylab/data 와
#   ~/Library/Mobile Documents/com~apple~CloudDocs/Documents/MUNI/ontologylab/data
# 의 inode가 동일하다. 즉 지식그래프(kg.sqlite), 원문(documents/), 빌드된 팩,
# 그리고 앞으로 넣을 출판사 API 키가 전부 Apple 서버로 업로드된다.
# ~/Library 는 iCloud 동기화 대상이 아니다.
#
# 하는 일:
#   1) 서버를 멈춘다 (이동 중 SQLite 쓰기 방지)
#   2) data/ packs/ 를 ~/Library/Application Support/ontologylab/ 로 옮긴다
#   3) 원래 자리에 심볼릭 링크를 남긴다 (CLI·기존 스크립트가 그대로 동작하도록)
#   4) 서버를 다시 띄운다 (plist는 이미 새 경로를 명시하도록 갱신됨)
#
# 되돌리려면: 서버를 멈추고, 심볼릭 링크를 지우고, 두 디렉터리를 원래 자리로
# 옮긴 뒤, plist에서 --data-dir/--packs-dir 두 쌍을 지우고 다시 로드하면 된다.

set -euo pipefail

# Derived from this script's own location, not typed. The guard's error
# message points every user here, including on a fresh clone, so a path
# baked in from one machine would send them to someone else's checkout.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HOME/Library/Application Support/ontologylab"
AGENT="at.ontologylab.server"
UID_NUM="$(id -u)"

say() { printf '\n== %s\n' "$*"; }

say "1) 서버 정지"
if /bin/launchctl print "gui/$UID_NUM/$AGENT" >/dev/null 2>&1; then
  /bin/launchctl bootout "gui/$UID_NUM/$AGENT" 2>/dev/null || true
fi
for _ in $(seq 1 15); do
  pgrep -f "ontologylab.serve" >/dev/null 2>&1 || break
  sleep 1
done
if pgrep -f "ontologylab.serve" >/dev/null 2>&1; then
  echo "   서버가 아직 살아 있습니다. 중단합니다 (데이터 이동은 정지 상태에서만)." >&2
  exit 1
fi
echo "   정지됨"

say "2) 이동"
mkdir -p "$DEST"
for name in data packs; do
  src="$REPO/$name"
  dst="$DEST/$name"
  if [ -L "$src" ]; then
    echo "   $name — 이미 심볼릭 링크, 건너뜀"
    continue
  fi
  if [ ! -d "$src" ]; then
    echo "   $name — 원본 없음, 건너뜀"
    continue
  fi
  if [ -e "$dst" ]; then
    echo "   $name — 목적지에 이미 존재합니다. 덮어쓰지 않고 중단합니다." >&2
    exit 1
  fi
  mv "$src" "$dst"
  ln -s "$dst" "$src"
  echo "   $name → $dst  (원래 자리에 링크)"
done

say "3) 검증 — 실제 데이터가 iCloud 트리 밖인가"
real_data="$(readlink "$REPO/data" || echo "$REPO/data")"
case "$real_data" in
  "$HOME/Library/"*) echo "   OK  실경로: $real_data" ;;
  *) echo "   !! 아직 iCloud 범위일 수 있음: $real_data" >&2 ;;
esac

say "4) 서버 재시작"
/bin/launchctl bootstrap "gui/$UID_NUM" "$HOME/Library/LaunchAgents/$AGENT.plist"
sleep 4
if curl -sf -o /dev/null "http://127.0.0.1:8799/api/engines"; then
  echo "   서버 응답 정상"
else
  echo "   !! 서버가 아직 안 뜹니다. 로그: ~/Library/Logs/ontologylab-server.log" >&2
fi

say "완료"
echo "데이터 위치: $DEST"
echo "확인:  ls -l $REPO/data   (심볼릭 링크로 보이면 정상)"
