#!/bin/bash
# usage: qa-server.sh start [data_dir] | stop | token | url
set -u
cd "$(dirname "$0")/../.."
STATE=/tmp/ol-w1-data; PORT=18899
case "${1:-}" in
  start)
    DATA=${2:-$(mktemp -d /tmp/ol-w1-XXXXXX)}; mkdir -p "$DATA/packs"; echo "$DATA" > $STATE
    nohup .venv/bin/python -P -m ontologylab.serve --host 127.0.0.1 --port $PORT --data-dir "$DATA" --packs-dir "$DATA/packs" > "$DATA/serve.log" 2>&1 &
    echo $! > "$DATA/serve.pid"
    for i in $(seq 1 40); do curl -fsS --max-time 1 http://127.0.0.1:$PORT/healthz >/dev/null 2>&1 && break; sleep 0.25; done
    curl -fsS --max-time 2 http://127.0.0.1:$PORT/healthz >/dev/null 2>&1 && echo "READY data=$DATA pid=$(cat "$DATA/serve.pid")" || { echo "NOT_READY"; tail -20 "$DATA/serve.log"; exit 1; } ;;
  token) cat "$(cat $STATE)/session.token" ;;
  url) echo "http://127.0.0.1:$PORT" ;;
  stop)
    DATA=$(cat $STATE 2>/dev/null || true)
    PID=$( [ -n "$DATA" ] && cat "$DATA/serve.pid" 2>/dev/null || true)
    [ -n "$PID" ] && kill "$PID" 2>/dev/null; for p in $(lsof -ti tcp:$PORT 2>/dev/null); do kill "$p" 2>/dev/null; done
    sleep 0.5
    for p in $(lsof -ti tcp:$PORT 2>/dev/null); do kill -9 "$p" 2>/dev/null; done
    [ -n "$DATA" ] && rm -rf "$DATA"; rm -f $STATE
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then echo "STOP_FAIL pid=$PID"; exit 1; fi
    [ -z "$(lsof -ti tcp:$PORT 2>/dev/null)" ] && echo "cleanup: killed ${PID:-none}; port $PORT free; rm -rf ${DATA:-none}" || { echo "PORT_BUSY"; exit 1; } ;;
  *) echo "usage: $0 start|stop|token|url"; exit 2 ;;
esac
