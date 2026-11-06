"""Offline real audio decode + model inference; no provider calls or chat messages."""
import os
from pathlib import Path
import sys
import tempfile
import wave
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app/backend'))
from utils.voice_sheet import transcribe
from utils.gigachat_client import AIServiceError

with tempfile.TemporaryDirectory() as directory:
    text=transcribe(Path(__file__).resolve().parents[1]/'tests/fixtures/voice-request.wav',directory)
    assert 'математик' in text and 'класс' in text, 'Russian audio recognition failed'
    silent=Path(directory)/'silent.wav'
    with wave.open(str(silent),'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\x00'*32000)
    try:transcribe(silent,directory)
    except AIServiceError as exc:assert exc.code=='voice_brief_invalid'
    else:raise AssertionError('Silence must not invent a request')
print('Offline speech smoke: real decode/model inference and silence rejection passed. Accuracy is not measured.')
