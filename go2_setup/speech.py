"""Short microphone clips to text. Robot actions remain in HumanCLI."""

import threading

import requests

MAX_AUDIO_BYTES = 2 * 1024 * 1024
AUDIO_TYPES = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/wav": "wav"}


class Speech:
    def __init__(self, config):
        self.config = config
        self.lock = threading.Lock()

    def transcribe(self, audio, content_type):
        if content_type not in AUDIO_TYPES or not audio or len(audio) > MAX_AUDIO_BYTES:
            raise ValueError("Record a short audio clip (maximum 2 MB)")
        cfg = self.config.resolve()
        if cfg["provider"] != "openai" or cfg["base_url"] or not cfg["api_key"]:
            raise ValueError("Voice requires an OpenAI key and the default OpenAI endpoint in HumanCLI settings")
        if not self.lock.acquire(blocking=False):
            raise ValueError("A voice transcription is already running")
        try:
            try:
                response = requests.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": "Bearer " + cfg["api_key"]},
                    data={"model": "gpt-4o-mini-transcribe", "response_format": "json"},
                    files={"file": ("voice." + AUDIO_TYPES[content_type], audio, content_type)},
                    timeout=(10, 45),
                    allow_redirects=False,
                )
            except requests.RequestException:
                raise ValueError("Could not reach OpenAI transcription. Try again.") from None
            if not response.ok:
                messages = {
                    401: "OpenAI rejected the API key. Update HumanCLI settings.",
                    429: "OpenAI transcription quota or rate limit reached. Check your API account.",
                }
                raise ValueError(messages.get(response.status_code, "OpenAI could not transcribe this clip. Try again."))
            try:
                text = response.json().get("text", "")
            except (ValueError, AttributeError):
                text = ""
            if not isinstance(text, str) or not text.strip():
                raise ValueError("No speech recognized. Hold R1 and try again.")
            if len(text.strip()) > 2000:
                raise ValueError("Voice instruction is too long. Use a shorter phrase.")
            return text.strip()
        finally:
            self.lock.release()
