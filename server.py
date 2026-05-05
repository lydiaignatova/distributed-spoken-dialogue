"""
dialogue_server/server.py
WebSocket streaming dialogue system — no robot, no gesture generation.

Pipeline:
    user audio (WAV) → Whisper.cpp (STT) → Ollama LLM → Kokoro TTS → PCM audio stream
"""

import os
import re
import json
import time
import tempfile
import subprocess
import threading
from datetime import datetime

import numpy as np
import soundfile as sf
from flask import Flask
from flask_sock import Sock
from kokoro import KPipeline
import ollama

from prompts import SYSTEM_PROMPTS, OPENING_PROMPTS

app = Flask(__name__)
sock = Sock(app)

# Config
# WHISPER_BIN   = os.environ.get("WHISPER_BIN",   "whisper-cli")
# WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "models/ggml-base.en.bin")
WHISPER_BIN   = os.environ.get("WHISPER_BIN", "/home/lydia/docs/whisper.cpp/build/bin/whisper-cli")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "/home/lydia/docs/whisper.cpp/models/ggml-large-v3-turbo.bin")

OLLAMA_MODEL  = os.environ.get("OLLAMA_MODEL",  "llama3.1")

KOKORO_VOICE  = os.environ.get("KOKORO_VOICE",  "af_heart")
KOKORO_LANG   = os.environ.get("KOKORO_LANG",   "a")

print("Loading Kokoro TTS pipeline...")
tts_pipeline = KPipeline(lang_code=KOKORO_LANG)
print("Kokoro ready.")


# Dialogue Session State 
class DialogueSession:
    def __init__(self, ws):
        self.ws = ws
        self.history = []
        self.lock = threading.Lock()
        self.topic = None
        self.system_prompt = None
        self.opening_prompt = None

    # sending helpers

    def send_json(self, obj):
        self.ws.send(json.dumps(obj))

    def send_audio(self, pcm_bytes: bytes):
        self.ws.send(pcm_bytes)

    # session start 

    def set_preferences(self, topic: str):
        self.topic = topic
        self.system_prompt = SYSTEM_PROMPTS[topic]
        self.opening_prompt = OPENING_PROMPTS.get(topic, "Hi, let's start a conversation.")

    def send_intro(self):
        print("[server] Generating intro...")
        text = self._generate_intro()
        self._stream_text(text)

    def _generate_intro(self) -> str:
        res = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system",  "content": self.system_prompt},
                {"role": "user",    "content": self.opening_prompt},
            ],
        )
        text = res["message"]["content"]
        self.history.append({"role": "assistant", "content": text})
        return text

    #  main dialogue turn 

    def handle_user_audio(self, audio_bytes: bytes):
        transcript = transcribe(audio_bytes)
        print(f"[USER] {transcript}")

        self.history.append({"role": "user", "content": transcript})

        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "system", "content": self.system_prompt}] + self.history,
        )
        text = response["message"]["content"]
        self.history.append({"role": "assistant", "content": text})

        self._stream_text(text)

    def _stream_text(self, text: str):
        """Split text into sentences, TTS each one and stream PCM to client."""
        for i, sentence in enumerate(split_sentences(text)):
            sentence = sentence.strip()
            if not sentence:
                continue

            self.send_json({"type": "sentence", "i": i, "text": sentence})

            for _, _, audio in tts_pipeline(sentence, voice=KOKORO_VOICE):
                self.send_audio(to_pcm(audio))
                time.sleep(0.01)

        self.send_json({"type": "end_turn"})


# WEBSOCKET SETUP 
@sock.route("/dialogue_ws")
def ws_handler(ws):
    session = DialogueSession(ws)
    print("[server] Client connected")

    # receive preferences from client to start 
    while True:
        msg = ws.receive()
        if msg is None:
            return
        try:
            event = json.loads(msg)
            if event.get("type") == "set_preferences":
                topic = event.get("topic", "hello")
                session.set_preferences(topic)
                session.send_json({"type": "preferences_set", "topic": topic})
                print(f"[server] Topic set to '{topic}'")
                break
        except (json.JSONDecodeError, KeyError):
            print("[server] Ignored bad JSON during preference setting")

    #  send opening intro 
    session.send_intro()

    #  main conversation loop 
    try:
        while True:
            msg = ws.receive()
            if msg is None:
                break

            if isinstance(msg, bytes):
                session.handle_user_audio(msg)
            else:
                try:
                    event = json.loads(msg)
                    if event.get("type") == "reset":
                        session.history = []
                        print("[server] Conversation history reset")
                except json.JSONDecodeError:
                    pass

    finally:
        print("[server] Client disconnected — saving transcript")
        save_transcript(session.history, session.topic)


# Helper functions 
def to_pcm(audio) -> bytes:
    audio = np.asarray(audio, dtype=np.float32)
    audio = np.clip(audio, -1.0, 1.0)
    return (audio * 32767).astype(np.int16).tobytes()


def transcribe(wav_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes)
        tmp_path = f.name

    try:
        cmd = [WHISPER_BIN, "-m", WHISPER_MODEL, "-f", tmp_path, "--output-txt"]
        subprocess.run(cmd, capture_output=True)
        txt_path = tmp_path + ".txt"
        if os.path.exists(txt_path):
            text = open(txt_path).read().strip()
            os.remove(txt_path)
            return text
    finally:
        os.remove(tmp_path)

    return ""


def split_sentences(text: str) -> list[str]:
    return re.findall(r'[^.!?]+[.!?]?', text)


def save_transcript(history: list, topic: str = None, save_dir: str = "transcripts"):
    os.makedirs(save_dir, exist_ok=True)
    date_str  = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    topic_str = topic or "unknown"
    path = os.path.join(save_dir, f"{date_str}_{topic_str}.txt")
    with open(path, "w") as f:
        for turn in history:
            f.write(f"{turn['role'].upper()}: {turn['content']}\n\n")
    print(f"[server] Transcript saved → {path}")


# Running script 
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5050)
    args = parser.parse_args()

    print(f"Starting dialogue server on {args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)