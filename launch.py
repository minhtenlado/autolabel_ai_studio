"""Cross-platform foreground launcher: python launch.py."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

if __name__ == '__main__':
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit('Chưa cài backend. Hãy chạy: python install.py --mode auto') from exc
    from backend.core.config import DATA_ROOT
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    host = os.environ.get('AUTOLABEL_HOST', '127.0.0.1')
    port = int(os.environ.get('AUTOLABEL_PORT', '8000'))
    # Binding outside loopback exposes paths, files and mutation APIs.
    if host not in ('127.0.0.1', 'localhost', '::1') and os.getenv('AUTOLABEL_INSECURE_REMOTE') != '1':
        raise SystemExit('Không cho phép mở API ra mạng công cộng thiếu xác thực. '
                         'Dùng SSH tunnel hoặc đặt AUTOLABEL_INSECURE_REMOTE=1 nếu chấp nhận rủi ro.')
    print(f'AutoLabel AI Studio: http://{host}:{port} | Ctrl+C để dừng', flush=True)
    uvicorn.run('backend.api.app:app', host=host, port=port, reload=False, workers=1)
