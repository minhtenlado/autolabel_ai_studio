import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from backend.core.hardware import DeviceUnavailable, is_accelerator_error, select_device
from backend.detection.models import ModelHub
from scripts.doctor import safetensors_valid


class HardwareTests(unittest.TestCase):
    def test_cpu_without_gpu(self):
        fake = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False),
                               backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)))
        with patch.dict(os.environ, {'AUTOLABEL_DEVICE': 'auto'}):
            self.assertEqual(select_device(fake), 'cpu')
            with self.assertRaises(DeviceUnavailable): select_device(fake, 'cuda')
            with self.assertRaises(DeviceUnavailable): select_device(fake, 'mps')

    def test_gpu_and_mps_auto(self):
        fake = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True),
                               backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)))
        self.assertEqual(select_device(fake, 'auto'), 'cuda:0')
        self.assertEqual(select_device(fake, 'cpu'), 'cpu')
        self.assertEqual(select_device(fake, 'mps'), 'mps')
        fake.cuda.is_available = lambda: False
        self.assertEqual(select_device(fake, 'auto'), 'mps')

    def test_only_accelerator_failures_retry(self):
        self.assertTrue(is_accelerator_error(RuntimeError('CUDA out of memory')))
        self.assertTrue(is_accelerator_error(RuntimeError('MPS backend error')))
        self.assertFalse(is_accelerator_error(RuntimeError('model class mismatch')))

    def test_yolo_retry_cpu_on_gpu_oom(self):
        calls = []
        class FakeModel:
            names = {0: 'car'}
            def predict(self, image, *, device, **kw):
                calls.append((device, kw['imgsz']))
                if device != 'cpu':
                    raise RuntimeError('CUDA out of memory')
                return [SimpleNamespace(boxes=None)]
        hub = ModelHub()
        hub.yolo = FakeModel()
        hub.device = 'cuda:0'
        hub.device_preference = 'auto'
        with patch.dict(os.environ, {'AUTOLABEL_DEVICE': 'auto'}):
            self.assertEqual(hub.yolo_predict(Image.new('RGB', (64, 64)), imgsz=960), [])
        self.assertEqual(hub.device, 'cpu')
        self.assertEqual(calls, [('cuda:0', 960), ('cpu', 640)])

    def test_corrupt_weight_detection(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'x.safetensors'
            header = json.dumps({'tensor': {'data_offsets': [0, 100], 'dtype': 'F32', 'shape': [25]}}).encode()
            p.write_bytes(struct.pack('<Q', len(header)) + header + b'a'*5)
            valid, reason = safetensors_valid(p)
            self.assertFalse(valid)
            self.assertIn('truncated', reason)
            p.write_bytes(struct.pack('<Q', len(header)) + header + b'a'*100)
            self.assertTrue(safetensors_valid(p)[0])


if __name__ == '__main__': unittest.main()
