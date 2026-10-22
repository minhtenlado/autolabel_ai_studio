"""Diagnostics without requiring GPU or optional AI packages."""
import argparse
import json
import struct
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import APP_ROOT, DEFAULT_MODEL
from backend.core.hardware import detect_runtime


def safetensors_valid(path):
    """Detect incomplete/sparse checkpoint placeholders before attempting a model load."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 16:
        return False, 'missing file or too small'
    try:
        with path.open('rb') as f:
            n = struct.unpack('<Q', f.read(8))[0]
            if n <= 0 or n >= path.stat().st_size or n > 32 * 1024 * 1024:
                return False, 'invalid safetensors header'
            header = json.loads(f.read(n))
            end = max((obj['data_offsets'][1] for key, obj in header.items() if key != '__metadata__'), default=0)
            if end + 8 + n != path.stat().st_size:
                return False, f'truncated tensor bytes ({path.stat().st_size - 8 - n}/{end})'
        return True, 'ok'
    except (KeyError, ValueError, OSError, UnicodeDecodeError, TypeError) as exc:
        return False, str(exc)


def diagnostic():
    h = detect_runtime()
    h['yolo_checkpoint'] = {'path': str(DEFAULT_MODEL), 'present': DEFAULT_MODEL.is_file()}
    h['optional_checkpoints'] = {}
    for name in ('grounding-dino-tiny', 'sam-vit-base'):
        loc = APP_ROOT / 'checkpoints' / name / 'model.safetensors'
        valid, reason = safetensors_valid(loc)
        h['optional_checkpoints'][name] = {'path': str(loc), 'valid': valid, 'reason': reason}
    return h


if __name__ == '__main__':
    print(json.dumps(diagnostic(), ensure_ascii=False, indent=2))
