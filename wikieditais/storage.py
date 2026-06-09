from __future__ import annotations
from pathlib import Path
from .config import config, ROOT
from .utils import read_json, write_json, safe_slug, remove_tree
import shutil, os

CATALOG = ROOT / 'data' / 'catalog.json'

def load_catalog(): return read_json(CATALOG, {'editais':[]}) or {'editais':[]}
def save_catalog(c): write_json(CATALOG,c)

def list_editais():
    c=load_catalog(); items=c.get('editais',[])
    return sorted(items, key=lambda x:(x.get('title') or '').lower())

def edital_dir(edital_id:str)->Path: return config.p('wiki') / edital_id
def schema_path(edital_id:str)->Path: return edital_dir(edital_id) / 'schema.json'
def master_path(edital_id:str)->Path: return edital_dir(edital_id) / 'MASTER.md'

def load_schema(edital_id:str): return read_json(schema_path(edital_id), {}) or {}
def save_schema(edital_id:str, schema:dict): write_json(schema_path(edital_id), schema); update_catalog_entry(schema)

def update_catalog_entry(schema:dict):
    c=load_catalog(); eid=schema.get('id')
    if not eid: return
    # O catálogo alimenta a home. Ele precisa carregar também os campos já tratados
    # para exibição, senão a tela inicial volta a mostrar valores brutos/legados.
    item={k:schema.get(k) for k in ['id','title','document_type','institution','short_institution','organizer','state','city','status','summary','total_vacancies','salary_min','salary_max','fee','fee_min','fee_max','fee_text','registration_start','registration_end','exam_date','exam_location','positions_count','quality','lint_score','raw_file','source_url']}
    item['display']=schema.get('display') or {}
    item['highlights']=schema.get('highlights') or []
    item['needs_review_count']=len(schema.get('needs_review') or [])
    found=False
    for i,e in enumerate(c.get('editais',[])):
        if e.get('id')==eid: c['editais'][i]=item; found=True; break
    if not found: c.setdefault('editais',[]).append(item)
    save_catalog(c)

def delete_edital(edital_id:str):
    c=load_catalog(); c['editais']=[e for e in c.get('editais',[]) if e.get('id')!=edital_id]; save_catalog(c)
    remove_tree(edital_dir(edital_id))
    remove_tree(config.p('extracted')/edital_id)

def raw_path(rel:str)->Path:
    rel=(rel or '').replace('\\','/').lstrip('/')
    base=config.p('raw').resolve(); p=(config.p('raw') / Path(rel).name).resolve() if rel.startswith('editais/') else (ROOT/rel).resolve()
    if not str(p).startswith(str((ROOT/'data').resolve())): raise ValueError('Caminho inválido')
    return p

def get_markdown_pages(edital_id:str)->dict[str,str]:
    d=edital_dir(edital_id); out={}
    if d.exists():
        for p in sorted(d.glob('*.md')): out[p.name]=p.read_text(encoding='utf-8',errors='ignore')
    return out

def save_markdown_page(edital_id:str, filename:str, content:str):
    if not filename.endswith('.md'): raise ValueError('Arquivo precisa ser .md')
    p=edital_dir(edital_id)/filename; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(content,encoding='utf-8')
