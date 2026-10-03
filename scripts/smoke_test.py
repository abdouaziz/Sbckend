"""End-to-end success tests against a running Sbckend server (local or deployed).

Usage:
    export SBCKEND_URL=http://localhost:8000 SBCKEND_API_KEY=sk-kiriku-...
    python scripts/smoke_test.py [--voices wolof,pulaar] [--skip-stt]

Requires `requests` and `openai` (pip install openai). Exits with code 1 if a test fails.
"""
import argparse
import os
import sys
import time

import requests
from openai import OpenAI

STT_MODEL = "m-kiriku-asr"
TTS_MODEL = "kiriku-tts"
SAMPLE_TEXT = {"wolof": "Salaam aleekum, naka nga def?", "pulaar": "A jaraama, no mbaɗ-ɗaa?"}
TIMEOUT = 600

results = []


def check(name, fn):
    start = time.time()
    try:
        detail = fn()
        results.append(True)
        print(f"PASS  {name} ({time.time() - start:.1f}s){f'  {detail}' if detail else ''}")
    except Exception as e:
        results.append(False)
        print(f"FAIL  {name} ({time.time() - start:.1f}s)  {e}")


def assert_wav(content: bytes) -> str:
    assert content[:4] == b"RIFF" and content[8:12] == b"WAVE", f"not a WAV file: {content[:40]!r}"
    return f"{len(content) / 1024:.0f} KB of WAV"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", default="wolof,pulaar", help="TTS languages to test")
    parser.add_argument("--skip-stt", action="store_true", help="skip speech-to-text tests")
    args = parser.parse_args()

    base_url = os.environ.get("SBCKEND_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("SBCKEND_API_KEY")
    if not api_key:
        sys.exit("Set SBCKEND_API_KEY to a valid sk-kiriku-... key")

    auth = {"Authorization": f"Bearer {api_key}"}
    client = OpenAI(api_key=api_key, base_url=f"{base_url}/v1", timeout=TIMEOUT)
    voices = [v for v in args.voices.split(",") if v]
    audio = {}

    print(f"Testing {base_url}\n")

    def ping():
        r = requests.get(f"{base_url}/ping", timeout=30)
        # "loading" (503) while the models load at startup; "degraded" if one failed.
        assert r.status_code == 200 and r.json()["status"] == "ok", f"{r.status_code} {r.text}"

    def rejects_missing_key():
        r = requests.post(f"{base_url}/synthesize", params={"text": "test"}, timeout=30)
        assert r.status_code == 401, f"expected 401, got {r.status_code}"

    def rejects_invalid_key():
        r = requests.post(f"{base_url}/synthesize", params={"text": "test"},
                          headers={"Authorization": "Bearer sk-kiriku-invalid"}, timeout=30)
        assert r.status_code == 401, f"expected 401, got {r.status_code}"

    def models():
        ids = {m.id for m in client.models.list()}
        assert {STT_MODEL, TTS_MODEL} <= ids, f"got {ids}"
        return ", ".join(sorted(ids))

    check("GET /ping", ping)
    check("missing key is rejected (401)", rejects_missing_key)
    check("invalid key is rejected (401)", rejects_invalid_key)
    check("SDK models.list", models)

    for voice in voices:
        def synthesize(voice=voice):
            r = requests.post(f"{base_url}/synthesize", params={"text": SAMPLE_TEXT[voice], "language": voice},
                              headers=auth, timeout=TIMEOUT)
            assert r.status_code == 200, f"{r.status_code} {r.text}"
            audio[voice] = r.content
            return assert_wav(r.content)

        def sdk_speech(voice=voice):
            speech = client.audio.speech.create(model=TTS_MODEL, voice=voice, input=SAMPLE_TEXT[voice],
                                                extra_body={"pitch": 0.2})
            return assert_wav(speech.content)

        check(f"POST /synthesize ({voice})", synthesize)
        check(f"SDK audio.speech ({voice})", sdk_speech)

    if not args.skip_stt:
        # Round trip: transcribe the audio synthesized above. The first call may load the STT model.
        for voice, wav in audio.items():
            def transcribe(voice=voice, wav=wav):
                r = requests.post(f"{base_url}/transcribe", params={"language": voice}, headers=auth,
                                  files={"file": ("speech.wav", wav, "audio/wav")}, timeout=TIMEOUT)
                assert r.status_code == 200, f"{r.status_code} {r.text}"
                text = r.json()["text"]
                assert text.strip(), "empty transcription"
                return f'"{text}"'

            def sdk_transcription(voice=voice, wav=wav):
                result = client.audio.transcriptions.create(model=STT_MODEL, file=("speech.wav", wav),
                                                            language=voice)
                assert result.text.strip(), "empty transcription"
                return f'"{result.text}"'

            check(f"POST /transcribe ({voice}, sent: \"{SAMPLE_TEXT[voice]}\")", transcribe)
            check(f"SDK audio.transcriptions ({voice})", sdk_transcription)

    print(f"\n{sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
