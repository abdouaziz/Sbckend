"""Speed and pitch bounds of the TTS service, and GPU out-of-memory handling, with stub torch and Coqui.

Run: uv run --no-project --with fastapi --with python-multipart --with httpx --with pytest --with anyio pytest tests
"""
import importlib
import sys
import types

import pytest


class OutOfMemoryError(RuntimeError):
    pass


@pytest.fixture
def tts(monkeypatch):
    calls = []
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(OutOfMemoryError=OutOfMemoryError, is_available=lambda: False,
                                       empty_cache=lambda: calls.append("empty_cache"))
    synthesizer_module = types.ModuleType("TTS.utils.synthesizer")
    synthesizer_module.Synthesizer = object
    for name, module in {"torch": torch, "librosa": types.ModuleType("librosa"), "TTS": types.ModuleType("TTS"),
                         "TTS.utils": types.ModuleType("TTS.utils"), "TTS.utils.synthesizer": synthesizer_module}.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "backend.services.tts", raising=False)
    module = importlib.import_module("backend.services.tts")
    monkeypatch.delitem(sys.modules, "backend.services.tts")

    class FakeSynthesizer:
        tts_model = types.SimpleNamespace(length_scale=1.0)

        def tts(self, text):
            calls.append(("tts", self.tts_model.length_scale))
            if module.FAIL_WITH_OOM:
                raise OutOfMemoryError("CUDA out of memory. Tried to allocate 7.49 GiB")
            return [0.0]

        def save_wav(self, wavs, path):
            calls.append("save")

    module.FAIL_WITH_OOM = False
    monkeypatch.setattr(module, "get_synthesizer", lambda language: calls.append("load") or FakeSynthesizer())
    monkeypatch.setitem(module._synthesizer_locks, "wolof", __import__("threading").Lock())
    module.calls = calls
    return module


@pytest.mark.parametrize("speed", [0.0, 0.1, 0.49, 2.01, -1.0])
def test_out_of_range_speed_is_refused_before_synthesis(tts, speed):
    with pytest.raises(tts.TTSException, match="Invalid speed"):
        tts.tts_vocalizer("salaam aleekum", "wolof", speed=speed)
    assert tts.calls == []


@pytest.mark.parametrize("pitch", [-1.5, 1.01])
def test_out_of_range_pitch_is_refused_before_synthesis(tts, pitch):
    with pytest.raises(tts.TTSException, match="Invalid pitch"):
        tts.tts_vocalizer("salaam aleekum", "wolof", speed=1.0, pitch=pitch)
    assert tts.calls == []


@pytest.mark.parametrize("speed, length_scale", [(0.5, 2.0), (1.0, 1.0), (2.0, 0.5)])
def test_valid_speed_sets_length_scale(tts, speed, length_scale):
    tts.tts_vocalizer("salaam aleekum", "wolof", speed=speed)
    assert ("tts", length_scale) in tts.calls


def test_gpu_out_of_memory_frees_the_cache_and_hides_the_details(tts):
    tts.FAIL_WITH_OOM = True
    with pytest.raises(tts.TTSOverloaded) as excinfo:
        tts.tts_vocalizer("salaam aleekum", "wolof", speed=1.0)
    assert "empty_cache" in tts.calls
    assert "GiB" not in str(excinfo.value)
