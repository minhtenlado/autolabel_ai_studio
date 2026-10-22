#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
PIDFILE="$ROOT/workspace/server.pid"
if [[ ! -f "$PIDFILE" ]]; then echo 'Không có server PID.'; exit 0; fi
PID="$(cat "$PIDFILE")"
if [[ "$PID" =~ ^[0-9]+$ ]] && kill -0 "$PID" 2>/dev/null && \
   ps -p "$PID" -o command= 2>/dev/null | grep -q 'launch.py'; then
  kill -TERM "$PID"
  echo "Đã gửi tín hiệu dừng AutoLabel AI Studio (PID $PID)."
else
  echo 'PID cũ/không đúng tiến trình AutoLabel: không gửi tín hiệu.'
fi
rm -f "$PIDFILE"
