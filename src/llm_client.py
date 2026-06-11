from __future__ import annotations
import requests


def ollama_generate(prompt: str, model: str = "qwen2.5:7b-instruct", base_url: str = "http://localhost:11434", timeout: int = 120) -> str:
    url = base_url.rstrip("/") + "/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False}
    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json().get("response", "").strip()
