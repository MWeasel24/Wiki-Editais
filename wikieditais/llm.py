from __future__ import annotations
import json, os, re, requests
from typing import Any
from .config import config

class LLMError(RuntimeError):
    pass

def _parse_model(model_id: str):
    if ':' not in model_id:
        return 'ollama', model_id
    provider, name = model_id.split(':', 1)
    return provider, name

def model_label(model_id: str) -> str:
    return config.model_label(model_id)

def complete(prompt: str, model_id: str | None = None, system: str = '', temperature: float | None = None, timeout: int | None = None, json_mode: bool = False) -> str:
    model_id = model_id or config.data['models'].get('default_chat_model', 'ollama:qwen2.5:7b')
    provider, model = _parse_model(model_id)
    temperature = config.data.get('chat', {}).get('temperature', 0.2) if temperature is None else temperature
    timeout = timeout or config.data.get('indexing', {}).get('request_timeout_seconds', 240)
    if provider == 'groq':
        return _groq(model, prompt, system, temperature, timeout, json_mode)
    if provider == 'ollama':
        return _ollama(model, prompt, system, temperature, timeout, json_mode)
    if provider == 'openrouter':
        return _openrouter(model, prompt, system, temperature, timeout, json_mode)
    raise LLMError(f'Provider não suportado: {provider}')

def _messages(system, prompt):
    msgs = []
    if system:
        msgs.append({'role': 'system', 'content': system})
    msgs.append({'role': 'user', 'content': prompt})
    return msgs

def _groq(model, prompt, system, temperature, timeout, json_mode):
    key = os.getenv('GROQ_API_KEY', '').strip()
    if not key:
        raise LLMError('GROQ_API_KEY não encontrada no .env')
    payload = {
        'model': model,
        'messages': _messages(system, prompt),
        'temperature': float(temperature),
    }
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}
    r = requests.post(
        'https://api.groq.com/openai/v1/chat/completions',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        json=payload,
        timeout=timeout,
    )
    if r.status_code >= 400:
        raise LLMError(f'Groq erro {r.status_code}: {r.text[:700]}')
    data = r.json()
    return data['choices'][0]['message']['content'].strip()

def _openrouter(model, prompt, system, temperature, timeout, json_mode):
    key = os.getenv('OPENROUTER_API_KEY', '').strip()
    if not key:
        raise LLMError('OPENROUTER_API_KEY não encontrada no .env')
    payload = {'model': model, 'messages': _messages(system, prompt), 'temperature': float(temperature)}
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}
    r = requests.post(
        'https://openrouter.ai/api/v1/chat/completions',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json', 'HTTP-Referer': 'http://localhost:5000', 'X-Title': 'WikiEditais'},
        json=payload,
        timeout=timeout,
    )
    if r.status_code >= 400:
        raise LLMError(f'OpenRouter erro {r.status_code}: {r.text[:700]}')
    return r.json()['choices'][0]['message']['content'].strip()

def _ollama(model, prompt, system, temperature, timeout, json_mode):
    payload = {'model': model, 'messages': _messages(system, prompt), 'options': {'temperature': float(temperature)}, 'stream': False}
    if json_mode:
        payload['format'] = 'json'
    r = requests.post('http://localhost:11434/api/chat', json=payload, timeout=timeout)
    if r.status_code >= 400:
        raise LLMError(f'Ollama erro {r.status_code}: {r.text[:700]}')
    return r.json().get('message', {}).get('content', '').strip()

def extract_json(text: str, default=None):
    if default is None:
        default = {}
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    starts = [i for i in [text.find('{'), text.find('[')] if i >= 0]
    if starts:
        start = min(starts)
        end = max(text.rfind('}'), text.rfind(']'))
        if end > start:
            try:
                return json.loads(text[start:end+1])
            except Exception:
                pass
    return default

def available_models_config(role: str | None = None):
    return config.models(role)

def test_model(model_id: str) -> tuple[bool, str]:
    try:
        out = complete('Responda apenas: OK', model_id=model_id, system='Teste de conexão.', temperature=0, timeout=30)
        return True, out[:200] or 'OK'
    except Exception as e:
        return False, str(e)
