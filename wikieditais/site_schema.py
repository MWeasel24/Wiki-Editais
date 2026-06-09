from __future__ import annotations
# Compatibilidade com rotas antigas: reconstruir schema agora só aplica a camada conservadora.
from .wiki_engine import make_display

def build_site_schema(schema, pages, sections, facts, positions, timeline, model=None):
    out=dict(schema or {})
    out['positions']=(positions or out.get('positions') or [])[:30]
    out['timeline']=(timeline or out.get('timeline') or [])[:40]
    out['positions_count']=len(out['positions'])
    out['display']=make_display(out)
    artifact={'strategy':'v14_rebuild_from_existing_safe_schema','note':'Schema público conservador reconstruído sem extração agressiva.'}
    return out, artifact
