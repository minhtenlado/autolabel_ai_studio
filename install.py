"""Portable bootstrap: Python 3.10+ / Windows, macOS, Linux.

Core UI can be installed without torch (--mode web); --mode auto chooses a
conservative CPU build unless an NVIDIA driver is present. For ROCm/CUDA
variants, use --torch-index per the current PyTorch installation selector.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
VENV = ROOT / '.venv'


def run(args, **kwargs):
    print('>', ' '.join(map(str, args)), flush=True)
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def venv_python():
    return VENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def existing_nvidia():
    return shutil.which('nvidia-smi') is not None


def install(mode, torch_index=None, optional=False):
    if not (3, 10) <= sys.version_info[:2] <= (3, 13):
        raise SystemExit('Dùng Python 3.10–3.13 (khuyến nghị Python 3.11 hoặc 3.12).')
    if not (VENV / 'pyvenv.cfg').is_file():
        print('Tạo môi trường mới, độc lập với máy nguồn:', VENV)
        venv.EnvBuilder(with_pip=True).create(VENV)
    py = venv_python()
    run([py, '-m', 'pip', 'install', '-r', ROOT / 'requirements.txt'])
    if mode == 'web':
        print('WEB mode: chỉ có quản lý, review thủ công và export. Không chạy AI.')
        return
    gpu = mode == 'gpu' or (mode == 'auto' and existing_nvidia())
    # For CPU environments avoid downloading many GiB of NVIDIA CUDA wheels.
    # macOS uses the standard wheel to enable Apple MPS if supported.
    torch_args = [py, '-m', 'pip', 'install', 'torch', 'torchvision']
    if torch_index:
        torch_args += ['--index-url', torch_index]
    elif not gpu and platform.system() in ('Linux', 'Windows'):
        torch_args += ['--index-url', 'https://download.pytorch.org/whl/cpu']
    try:
        run(torch_args)
    except subprocess.CalledProcessError:
        if torch_index or gpu or platform.system() not in ('Linux', 'Windows'):
            raise
        print('CPU wheel index không phù hợp với hệ thống này, thử PyPI mặc định...')
        run([py, '-m', 'pip', 'install', 'torch', 'torchvision'])
    run([py, '-m', 'pip', 'install', '-r', ROOT / 'requirements-ai.txt'])
    if optional:
        run([py, '-m', 'pip', 'install', '-r', ROOT / 'requirements-optional-ai.txt'])
    print('\nKIỂM TRA PHẦN CỨNG:')
    run([py, '-m', 'scripts.doctor'], cwd=ROOT)
    if gpu:
        check = subprocess.run([str(py), '-c', 'import torch; print(torch.cuda.is_available())'],
                               text=True, capture_output=True)
        if check.returncode or check.stdout.strip() != 'True':
            print('CẢNH BÁO: có thể có GPU nhưng torch không chạy được CUDA/ROCm. '
                  'App sẽ dùng CPU khi chọn Auto. Kiểm tra driver và --torch-index phù hợp.')
    print('\nCài đặt xong. Chạy: python launch.py  (Windows: .venv\\Scripts\\python launch.py)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Cài AutoLabel AI Studio vào .venv sạch, không phụ thuộc máy cũ')
    parser.add_argument('--mode', choices=('auto', 'cpu', 'gpu', 'web'), default='auto')
    parser.add_argument('--torch-index', default=None, help='URL index PyTorch chính thức (CUDA / ROCm / CPU)')
    parser.add_argument('--optional', action='store_true', help='Cài Transformers và Hugging Face cho DINO/SAM')
    args = parser.parse_args()
    try:
        install(args.mode, args.torch_index, args.optional)
    except subprocess.CalledProcessError as e:
        raise SystemExit(f'Cài đặt bị lỗi (exit {e.returncode}); kiểm tra mạng/Python/wheel/driver.') from e
