#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"
if [[ -n "${AUTOLABEL_PYTHON:-}" ]]; then
  PYTHON="$AUTOLABEL_PYTHON"
else
  PYTHON=""
  for candidate in python3.11 python3.12 python3.13 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert (3,10) <= sys.version_info[:2] <= (3,13)' >/dev/null 2>&1; then
      PYTHON="$candidate"; break
    fi
  done
fi
if [[ -z "$PYTHON" ]]; then echo 'Không tìm thấy Python 3.10–3.13; hãy cài Python 3.11 hoặc 3.12.' >&2; exit 1; fi
"$PYTHON" install.py "$@"
