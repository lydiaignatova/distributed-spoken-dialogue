# Dialogue System

A two-machine (or single-machine) streaming dialogue system.

```
Client machine                        Server machine
──────────────────────────────        ────────────────────────────────
microphone → record audio      →      Whisper.cpp  (speech → text)
speaker    ← play response     ←      Ollama LLM   (text → text)
                                       Kokoro TTS   (text → speech)
```

Communication happens over a single WebSocket connection. Audio streams both ways as raw PCM; events (sentence text, end-of-turn) are JSON messages on the same socket.

---

## Server Setup

### 1. Install Python dependencies

```bash
pip install flask flask-sock kokoro soundfile numpy ollama websocket-client
```

### 2. Build whisper.cpp

```bash
git clone https://github.com/ggml-org/whisper.cpp
cd whisper.cpp
cmake -B build && cmake --build build --config Release

# Download a model — base.en is fast and accurate enough for conversation
./models/download-ggml-model.sh base.en
```

The model ends up at `whisper.cpp/models/ggml-base.en.bin`.

Update `server.py` with the appropriate file paths for `WHISPER_BIN` and `WHISPER_MODEL`, or update your system to know where your whisper binary and model if they're not on PATH / default paths. 
```bash
export WHISPER_BIN=/path/to/whisper.cpp/build/bin/whisper-cli
export WHISPER_MODEL=/path/to/whisper.cpp/models/ggml-base.en.bin
```

### 3. Install and start Ollama

Download from https://ollama.com, then:

```bash
ollama pull llama3.1
ollama serve          # runs in the background on port 11434
```

Swap `llama3.1` for any model you like (`mistral`, `gemma3`, `phi3`, etc.).

### 4. Add your prompts

Edit `prompts.py` to include topics that you want to seed your server with as options. 

```python
SYSTEM_PROMPTS["new_topic"] = "You are a [system description] explaining [topic]"

OPENING_PROMPTS["new_topic"] = "Please introduce [topic]"
```

### 5. Run the server

On your powerful machine,
```bash
python server.py
```

Optional environment variables:

| Variable        | Default              | Description                        |
|-----------------|----------------------|------------------------------------|
| `WHISPER_BIN`   | `whisper-cli`        | Path to the whisper-cli binary     |
| `WHISPER_MODEL` | `models/ggml-base.en.bin` | Path to the GGML model file   |
| `OLLAMA_MODEL`  | `llama3.1`           | Ollama model name                  |
| `KOKORO_VOICE`  | `af_heart`           | TTS voice. Options available on [huggingface.com](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md)              |
| `KOKORO_LANG`   | `a`                  | Kokoro language code               |


Find your machine's local IP:

```bash
hostname -I   # or: ip addr show
```

---

## Client Setup

### 1. Install Python dependencies

```bash
pip install sounddevice soundfile numpy websocket-client
```

### 2. Run the client

```bash
python client.py --server [hostmachine IP address]:5050
```

Or set a default via environment variable:

```bash
export DIALOGUE_SERVER=ws://[hostmachine IP address]:5050
python client.py
```

### 3. Talk

```
Press ENTER to start recording...
🎤  Recording... press ENTER to stop.
         [speak]
         [press ENTER]
📡  Sending audio...
🤖  I'd love to talk to you today!...
```

Choose a topic with `--topic`:

```bash
python client.py --server [hostmachine IP address]:5050 --topic hello
```

---

## Running on a single machine

Both scripts can run on the same computer — just use `localhost`:

```bash
# Terminal 1
python server.py

# Terminal 2
python client.py --server localhost:5050
```
