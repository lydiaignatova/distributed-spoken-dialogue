"""
client.py
WebSocket dialogue client — keyboard-controlled

Usage:
    python client.py --server 192.168.1.X:5050
    python client.py --server 192.168.1.X:5050 --topic hello

Press ENTER to start recording, ENTER again to stop.
"""

import io
import json
import os
import sys
import time
import argparse
import threading

import numpy as np
import sounddevice as sd
import soundfile as sf
from websocket import create_connection

# Config
DEFAULT_SERVER = os.environ.get("DIALOGUE_SERVER", "ws://localhost:5050/dialogue_ws")

SAMPLE_RATE = 16000
CHANNELS    = 1


# Audio Recording
def record_audio_toggle() -> np.ndarray:
    """Press ENTER → start recording.  Press ENTER again → stop."""
    input("\nPress ENTER to start recording...")
    print("🎤  Recording... press ENTER to stop.")

    frames = []

    def callback(indata, frame_count, time_info, status):
        if status:
            print("[audio]", status)
        frames.append(indata.copy())

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        callback=callback,
    ):
        time.sleep(0.1)   # brief debounce
        input()            # block until second ENTER

    if not frames:
        return np.array([], dtype=np.float32)

    return np.concatenate(frames, axis=0)


def audio_to_wav_bytes(audio: np.ndarray) -> bytes:
    """Convert a float32 numpy array to WAV bytes."""
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV")
    return buf.getvalue()


# Streaming Audio Playback
class AudioPlayer:
    """Plays raw PCM int16 chunks streamed from the server."""

    def __init__(self):
        self.stream = sd.RawOutputStream(
            samplerate=24000,
            channels=1,
            dtype="int16",
        )
        self.stream.start()

    def write(self, pcm_bytes: bytes):
        # Ensure even byte count (int16 = 2 bytes per sample)
        if len(pcm_bytes) % 2 == 1:
            pcm_bytes = pcm_bytes[:-1]
        self.stream.write(pcm_bytes)

    def close(self):
        self.stream.stop()
        self.stream.close()


# Websocket Client
class DialogueClient:
    """Manages a full-duplex WebSocket connection to the dialogue server."""

    def __init__(self, server_url: str):
        self.ws = create_connection(server_url)
        print("[client]  WebSocket connected")
        self.audio_player = AudioPlayer()

    # send
    def send_audio(self, audio: np.ndarray):
        wav = audio_to_wav_bytes(audio)
        self.ws.send_binary(wav)

    # receive
    def handle_message(self, msg) -> bool:
        """Process one incoming message.  Returns True when the turn is done."""
        if isinstance(msg, bytes):
            self.audio_player.write(msg)
            return False

        if not msg or not isinstance(msg, str):
            return False

        msg = msg.strip()
        if not msg:
            return False

        try:
            event = json.loads(msg)
        except json.JSONDecodeError:
            print(f"[WARN] Bad message from server: {repr(msg[:80])}")
            return False

        t = event.get("type")

        if t == "sentence":
            print(f"[client]  {event['text']}")
        elif t == "end_turn":
            return True

        return False

    def recv_loop(self):
        """Block until the server signals end_turn."""
        while True:
            msg = self.ws.recv()
            if self.handle_message(msg):
                break

    # turn flow 
    def run_turn(self, audio: np.ndarray):
        self.send_audio(audio)
        self.recv_loop()


# Main script 
def main(server: str, topic: str):
    url = f"ws://{server.replace('ws://','').replace('http://','')}/dialogue_ws"
    client = DialogueClient(url)

    # ── send preferences ──────────────────────
    print(f"[client]  Sending preferences (topic={topic})...")
    client.ws.send(json.dumps({
        "type": "set_preferences",
        "topic": topic,
    }))

    while True:
        msg = client.ws.recv()
        event = json.loads(msg)
        if event.get("type") == "preferences_set":
            print("[client] Server ready")
            break

    # ── receive intro ─────────────────────────
    print("⏳  Waiting for intro...\n")
    client.recv_loop()

    # ── conversation loop ─────────────────────
    print("\nReady! Press ENTER to talk.\n")

    while True:
        try:
            audio = record_audio_toggle()
            if len(audio) == 0:
                print("[skipped — no audio recorded]")
                continue

            print("[client]  Sending audio...")
            client.run_turn(audio)

        except KeyboardInterrupt:
            print("\nExiting.")
            break


# Running script 
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dialogue client")
    parser.add_argument("--server",  default=DEFAULT_SERVER,
                        help="Server address, e.g. 0.0.0.0:5050")
    parser.add_argument("--topic", default="hello",
                        help="Which topic to discuss")
    args = parser.parse_args()

    main(args.server, args.topic)