from __future__ import annotations
from pathlib import Path
from collections import defaultdict
from .config import config
from .utils import read_json

METRIC_LABELS={
 'wiki':{'coverage':'Cobertura','field_accuracy':'Acurácia dos campos','structure_quality':'Estrutura','source_traceability':'Rastreabilidade','synthesis_quality':'Síntese','noise_reduction':'Redução de ruído','consistency':'Consistência'},
 'chat':{'answer_accuracy':'Acurácia da resposta','context_selection':'Seleção de contexto','faithfulness':'Fidelidade','source_use':'Uso de fonte','insufficient_info_handling':'Tratamento de ausência','clarity':'Clareza'},
 'workflow':{'ingest_completeness':'Completude da ingestão','web_fetch_relevance':'Relevância da busca web','lint_detection':'Detecção de lint','update_safety':'Segurança de atualização','model_selection_correctness':'Seleção de modelo'},
 'agentic':{'workflow_routing':'Roteamento','tool_use_correctness':'Uso correto','fallback_behavior':'Fallback','lint_detection':'Lint','update_safety':'Segurança'}
}

def load_evaluations():
    out=[]
    for p in sorted(config.p('evaluations').glob('*.json')):
        data=read_json(p,{})
        if data: data['_file']=p.name; out.append(data)
    return out

def summarize():
    evals=load_evaluations()
    groups=defaultdict(list); metric_scores=defaultdict(lambda: defaultdict(list))
    for ev in evals:
        for item in ev.get('items',[]):
            typ=item.get('type','wiki')
            vals=list((item.get('metrics') or {}).values())
            if vals: groups[typ].extend(vals)
            for k,v in (item.get('metrics') or {}).items():
                if isinstance(v,(int,float)): metric_scores[typ][k].append(v)
    type_scores={k:round(sum(v)/len(v)*100) if v else 0 for k,v in groups.items()}
    overall=round(sum(type_scores.values())/len(type_scores)) if type_scores else 0
    by_metric={}
    for typ,metrics in metric_scores.items():
        by_metric[typ]={k:round(sum(vals)/len(vals)*100) for k,vals in metrics.items() if vals}
    return {'overall':overall,'type_scores':type_scores,'by_metric':by_metric,'evaluations':evals,'labels':METRIC_LABELS}
