"""CPU/CUDA/ROCm/MPS detection and safe inference configuration.

This module deliberately does not import torch until queried so the web UI can
start on machines where only the core dependencies have been installed.
"""
from __future__ import annotations

import os
import platform
from importlib.util import find_spec

SUPPORTED = ('auto', 'cpu', 'cuda', 'mps')


class DeviceUnavailable(ValueError):
    pass


def preference(value: str | None = None) -> str:
    value = (value if value is not None else os.getenv('AUTOLABEL_DEVICE', 'auto')).strip().lower()
    if value not in SUPPORTED:
        raise DeviceUnavailable('Device phải là auto, cpu, cuda hoặc mps.')
    return value


def select_device(torch, requested: str | None = None) -> str:
    desired = preference(requested)
    if desired == 'cpu':
        return 'cpu'
    cuda = bool(torch.cuda.is_available())
    mps = bool(getattr(getattr(torch, 'backends', None), 'mps', None) and torch.backends.mps.is_available())
    if desired == 'cuda':
        if not cuda:
            raise DeviceUnavailable('PyTorch không phát hiện CUDA/ROCm. Chọn Auto/CPU hoặc cài bản torch GPU tương thích.')
        return 'cuda:0'
    if desired == 'mps':
        if not mps:
            raise DeviceUnavailable('PyTorch MPS không khả dụng trên máy này.')
        return 'mps'
    return 'cuda:0' if cuda else ('mps' if mps else 'cpu')


def is_accelerator_error(exc: BaseException) -> bool:
    """Retry CPU only on typical driver/OOM/device failures, never on model/data errors."""
    message = str(exc).lower()
    patterns = ('out of memory', 'cuda error', 'cudnn', 'cublas', 'device-side assert',
                'mps backend', 'not implemented for mps', 'mps out of memory', 'hip error', 'invalid device ordinal',
                'no kernel image is available', 'driver version is insufficient',
                'no cuda gpus are available', 'no gpu is available', 'torch not compiled with cuda')
    return any(term in message for term in patterns)


def configure_cpu_threads(torch):
    raw = os.getenv('AUTOLABEL_CPU_THREADS', '').strip()
    n = max(1, min(32, int(raw))) if raw else min(8, max(1, (os.cpu_count() or 2) - 1))
    torch.set_num_threads(n)
    return n


def detect_runtime() -> dict:
    info = {'python': platform.python_version(), 'os': platform.platform(),
            'architecture': platform.machine(), 'cpu_count': os.cpu_count(),
            'preference': preference(), 'torch_available': False,
            'ultralytics_available': find_spec('ultralytics') is not None,
            'transformers_available': find_spec('transformers') is not None,
            'available_devices': ['cpu'], 'device': 'cpu', 'gpu': None,
            'cuda': False, 'mps': False, 'rocm': False,
            'vram_used_mb': None, 'vram_total_mb': None,
            'gpu_utilization': None, 'warnings': []}
    try:
        import torch
        info['torch_available'] = True
        info['torch_version'] = torch.__version__
        if torch.cuda.is_available():
            info['cuda'] = True
            info['rocm'] = bool(getattr(torch.version, 'hip', None))
            info['available_devices'].append('cuda')
            info['gpu'] = torch.cuda.get_device_name(0)
            try:
                props = torch.cuda.get_device_properties(0)
                info['vram_total_mb'] = round(props.total_memory/1048576)
                info['vram_used_mb'] = round(torch.cuda.memory_allocated(0)/1048576)
            except Exception:
                pass
        if getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available():
            info['mps'] = True
            info['available_devices'].append('mps')
            if not info['gpu']:
                info['gpu'] = 'Apple Silicon GPU (MPS)'
        try:
            info['device'] = select_device(torch)
        except DeviceUnavailable as exc:
            info['warnings'].append(str(exc))
    except (ImportError, OSError, RuntimeError) as exc:
        info['warnings'].append(f'PyTorch chưa sẵn sàng: {exc}')
    try:
        import psutil
        m = psutil.virtual_memory()
        info['ram_used_mb'] = round(m.used/1048576)
        info['ram_total_mb'] = round(m.total/1048576)
    except ImportError:
        info['ram_used_mb'] = None
        info['ram_total_mb'] = None
    if not info['ultralytics_available']:
        info['warnings'].append('Chưa cài ultralytics; cài bằng setup để inference YOLO.')
    return info
