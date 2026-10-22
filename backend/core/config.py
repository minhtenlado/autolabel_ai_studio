from pathlib import Path
import os

APP_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get('AUTOLABEL_DATA_DIR', str(APP_ROOT / 'workspace'))).expanduser().resolve()
DB_PATH = DATA_ROOT / 'autolabel.sqlite3'
# The model is deliberately *not* bundled: supply a checkpoint trained for
# bus/car/container/motorcycle/truck before attempting automatic labeling.
DEFAULT_MODEL = Path(os.environ.get('AUTOLABEL_YOLO_MODEL', str(APP_ROOT / 'models' / 'best.pt'))).expanduser().resolve()
CLASSES = ['bus', 'car', 'container', 'motorcycle', 'truck']
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
