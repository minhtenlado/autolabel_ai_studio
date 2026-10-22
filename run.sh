#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then echo 'Chưa cài đặt. Chạy ./setup.sh --mode auto' >&2; exit 1; fi
mkdir -p "$ROOT/workspace"
PIDFILE="$ROOT/workspace/server.pid"
if [[ -f "$PIDFILE" ]]; then
  PID="$(cat "$PIDFILE")"
  if [[ "$PID" =~ ^[0-9]+$ ]] && kill -0 "$PID" 2>/dev/null && \
     ps -p "$PID" -o command= 2>/dev/null | grep -q 'launch.py'; then
     echo "App đang chạy (PID $PID)."; exit 0
  fi
  rm -f "$PIDFILE"
fi
cd "$ROOT"
nohup "$PY" launch.py >> "$ROOT/workspace/server.log" 2>&1 &
PID=$!
echo "$PID" > "$PIDFILE"
URL="http://127.0.0.1:${AUTOLABEL_PORT:-8000}/api/health"
for _ in $(seq 1 60); do
  if ! kill -0 "$PID" 2>/dev/null; then break; fi
  if "$PY" -c 'import sys,urllib.request;urllib.request.urlopen(sys.argv[1], timeout=2).read()' "$URL" >/dev/null 2>&1; then
    echo "AutoLabel AI Studio đang chạy: http://127.0.0.1:${AUTOLABEL_PORT:-8000}"; exit 0
  fi
  sleep .25
done
echo "Không khởi động được. Xem $ROOT/workspace/server.log" >&2
tail -n 20 "$ROOT/workspace/server.log" >&2 || true
rm -f "$PIDFILE"
exit 1
