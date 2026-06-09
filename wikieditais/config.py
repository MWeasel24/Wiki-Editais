from __future__ import annotations
import os
from pathlib import Path
from typing import Any
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')

DEFAULT_CONFIG = {
    'app': {'host':'127.0.0.1','port':5000,'debug':True},
    'paths': {'raw':'data/raw/editais','wiki':'data/wiki/editais','extracted':'data/extracted','evaluations':'data/evaluations','downloads':'data/downloads','logs':'data/logs'},
    'models': {'default_index_model':'ollama:qwen2.5:7b','default_chat_model':'ollama:qwen2.5:7b','default_compare_model':'ollama:qwen2.5:7b','available':[]},
    'indexing': {'max_section_chars':9000,'max_merge_chars':36000,'request_timeout_seconds':180,'temperature':0.15},
    'chat': {'max_context_chars':24000,'temperature':0.2},
    'web_fetch': {'enabled':False,'default_days_back':3,'user_agent':'WikiEditais/1.0'}
}

def deep_merge(a:dict,b:dict)->dict:
    out=dict(a)
    for k,v in (b or {}).items():
        if isinstance(v,dict) and isinstance(out.get(k),dict): out[k]=deep_merge(out[k],v)
        else: out[k]=v
    return out

class Config:
    def __init__(self):
        self.path = ROOT / 'config.yaml'
        self.data = self.load()
        self.ensure_dirs()
    def load(self)->dict:
        if self.path.exists():
            try:
                return deep_merge(DEFAULT_CONFIG, yaml.safe_load(self.path.read_text(encoding='utf-8')) or {})
            except Exception:
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()
    def save(self):
        self.path.write_text(yaml.safe_dump(self.data, allow_unicode=True, sort_keys=False), encoding='utf-8')
    def ensure_dirs(self):
        for rel in self.data.get('paths',{}).values():
            (ROOT / rel).mkdir(parents=True, exist_ok=True)
    def p(self,key:str)->Path:
        return ROOT / self.data['paths'][key]
    def models(self, role:str|None=None)->list[dict[str,Any]]:
        models = self.data.get('models',{}).get('available',[])
        if role:
            return [m for m in models if role in str(m.get('role','')).split(',')]
        return models
    def model_label(self, model_id:str)->str:
        for m in self.models():
            if m.get('id') == model_id: return m.get('label') or model_id
        return model_id

config = Config()
