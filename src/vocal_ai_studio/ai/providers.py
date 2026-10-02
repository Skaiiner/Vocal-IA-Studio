from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


class LocalRulesProvider:
    name = "Reglas locales"
    is_local = True

    def is_available(self) -> bool:
        return True

    def complete(self, prompt: str, **options) -> str:
        return prompt


class OllamaProvider:
    name = "Ollama"
    is_local = True

    def __init__(self, endpoint: str, model: str, temperature: float = 0.7, timeout: float = 20.0):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def is_available(self) -> bool:
        if not self.model:
            return False
        try:
            req = urllib.request.Request(f"{self.endpoint}/api/tags")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def complete(self, prompt: str, **options) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": options.get("temperature", self.temperature)},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.endpoint}/api/generate", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body.get("response", "").strip()
