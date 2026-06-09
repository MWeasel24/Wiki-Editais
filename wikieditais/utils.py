from __future__ import annotations
import re, json, unicodedata, shutil
from datetime import date, datetime
from pathlib import Path
try:
    from slugify import slugify
except Exception:
    def slugify(value):
        value = unicodedata.normalize('NFKD', str(value or '')).encode('ascii','ignore').decode('ascii')
        value = re.sub(r'[^a-zA-Z0-9]+', '-', value).strip('-').lower()
        return value

def clean_text(text:str)->str:
    if not text: return ''
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\x00',' ')
    text = re.sub(r'[ \t]+',' ',text)
    text = re.sub(r'\n{3,}','\n\n',text)
    # un-hyphenate line breaks
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
    return text.strip()

def safe_slug(value:str, fallback='edital')->str:
    s = slugify(value or '')[:80].strip('-')
    return s or f'{fallback}-{datetime.now().strftime("%Y%m%d%H%M%S")}'

def read_json(path:Path, default=None):
    try:
        if path.exists(): return json.loads(path.read_text(encoding='utf-8'))
    except Exception: pass
    return default

def write_json(path:Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def money_fmt(value):
    if value in (None,'',[]): return '—'
    try:
        v=float(value); return 'R$ ' + f'{v:,.2f}'.replace(',','X').replace('.',',').replace('X','.')
    except Exception: return str(value)

def date_fmt(value):
    if not value: return '—'
    try:
        d=datetime.fromisoformat(str(value)[:10]).date()
        return d.strftime('%d/%m/%Y')
    except Exception: return str(value)

def today_iso(): return date.today().isoformat()

def parse_date(value):
    if not value: return None
    try: return datetime.fromisoformat(str(value)[:10]).date()
    except Exception: return None

def truncate(s:str, n:int=80):
    s = str(s or '')
    return s if len(s)<=n else s[:n-1]+'…'

def remove_tree(path:Path):
    if path.exists() and path.is_dir(): shutil.rmtree(path)
    elif path.exists(): path.unlink()
