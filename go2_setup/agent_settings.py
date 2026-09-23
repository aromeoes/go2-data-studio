"""Provider configuration for the DimOS agent. Credentials never enter public state."""

import json
import importlib.util
import os
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlparse

from dotenv import dotenv_values

PROVIDERS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "ollama": "",
}


class AgentSettings:
    def __init__(self, root):
        self.path = root / "humancli.json"
        self.legacy = root / "vision.json"
        self.lock = threading.RLock()
        self.values = {}
        if self.path.exists():
            self.values = json.loads(self.path.read_text())
        self.env = {
            k: v
            for k, v in dotenv_values(Path(__file__).resolve().parent.parent / ".env").items()
            if v
        }
        self.env.update(os.environ)

    def resolve(self):
        with self.lock:
            legacy = json.loads(self.legacy.read_text()) if self.legacy.exists() else {}
            provider = self.env.get("HUMANCLI_PROVIDER", self.values.get("provider", "openai"))
            matching_provider = provider == self.values.get("provider")
            model = self.env.get(
                "HUMANCLI_MODEL",
                self.values.get("model", "")
                if matching_provider
                else ("gpt-4.1-mini" if provider == "openai" else ""),
            )
            endpoint = self.env.get(
                "HUMANCLI_BASE_URL", self.values.get("base_url", "") if matching_provider else ""
            )
            matching_endpoint = matching_provider and endpoint == self.values.get("base_url", "")
            key = (
                self.env.get(PROVIDERS.get(provider, ""), "")
                or (self.values.get("api_key", "") if matching_endpoint else "")
                or (legacy.get("api_key", "") if provider == "openai" and not endpoint else "")
            )
            saved_vision = (
                self.values.get("vision", False)
                if matching_endpoint
                else (
                    legacy.get("enabled", False) if provider == "openai" and not endpoint else False
                )
            )
            vision = self.env.get("HUMANCLI_VISION", str(saved_vision)).lower() in {
                "1",
                "true",
                "yes",
            }
            self.validate(provider, model, endpoint)
            return dict(
                provider=provider, model=model, api_key=key, base_url=endpoint, vision=vision
            )

    @staticmethod
    def validate(provider, model, endpoint):
        if provider not in PROVIDERS:
            raise ValueError("Choose OpenAI, Anthropic, Google, or Ollama")
        if (
            len(model) > 160
            or any(c.isspace() for c in model)
            or model.split(":", 1)[0] in PROVIDERS
        ):
            raise ValueError("Enter a model ID without a provider prefix or spaces")
        if endpoint:
            parsed = urlparse(endpoint)
            if (
                parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or not parsed.hostname
            ):
                raise ValueError("Use an endpoint URL without credentials, query or fragment")
            if parsed.scheme != "https" and not (
                parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            ):
                raise ValueError("Model endpoints require HTTPS, except local servers")
            if provider not in {"openai", "ollama"}:
                raise ValueError(
                    "Custom endpoints are supported for OpenAI-compatible servers and Ollama"
                )

    def status(self):
        try:
            cfg = self.resolve()
            package = {
                "openai": "langchain_openai",
                "anthropic": "langchain_anthropic",
                "google_genai": "langchain_google_genai",
                "ollama": "langchain_ollama",
            }[cfg["provider"]]
            available = importlib.util.find_spec(package) is not None
            configured = available and bool(
                cfg["model"] and (cfg["api_key"] or cfg["provider"] == "ollama")
            )
            return {k: v for k, v in cfg.items() if k != "api_key"} | {
                "configured": configured,
                "error": None
                if available
                else f"Install {package.replace('_', '-')} in the DimOS Python environment to use this provider.",
                "environment_managed": any(
                    k in self.env
                    for k in [
                        "HUMANCLI_PROVIDER",
                        "HUMANCLI_MODEL",
                        "HUMANCLI_BASE_URL",
                        "HUMANCLI_VISION",
                        PROVIDERS.get(cfg["provider"], ""),
                    ]
                ),
            }
        except ValueError as error:
            return dict(
                configured=False,
                error=str(error),
                provider="",
                model="",
                base_url="",
                vision=False,
                environment_managed=True,
            )

    def configure(self, provider, model, api_key="", base_url="", vision=False):
        model, base_url, api_key = model.strip(), base_url.strip(), api_key.strip()
        self.validate(provider, model, base_url)
        if not model:
            raise ValueError("Enter a model ID")
        if any(c.isspace() for c in api_key):
            raise ValueError("API keys cannot contain whitespace")
        with self.lock:
            old = self.resolve()
            # Never silently forward a saved credential to a different endpoint.
            if not api_key and provider == old["provider"] and base_url == old["base_url"]:
                api_key = old["api_key"]
            values = dict(
                provider=provider, model=model, api_key=api_key, base_url=base_url, vision=vision
            )
            fd, name = tempfile.mkstemp(prefix=".humancli-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w") as out:
                    json.dump(values, out)
                os.replace(name, self.path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
            self.values = values
            return self.status()
