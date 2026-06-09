from __future__ import annotations
import json, re
from typing import Any
from .config import config, ROOT
from .llm import complete, extract_json
from .utils import clean_text, date_fmt, money_fmt

TOPICS = [
    'visao_geral','inscricoes','cargos_vagas','cronograma','provas_etapas',
    'conteudo_programatico','requisitos_documentos','recursos_resultados','retificacoes','fontes_qualidade'
]

TOPIC_TITLES = {
    'visao_geral':'Visão geral',
    'inscricoes':'Inscrições',
    'cargos_vagas':'Cargos, vagas e remuneração',
    'cronograma':'Cronograma',
    'provas_etapas':'Provas e etapas',
    'conteudo_programatico':'Conteúdo programático',
    'requisitos_documentos':'Requisitos e documentos',
    'recursos_resultados':'Recursos, gabaritos e resultados',
    'retificacoes':'Retificações, prorrogações e comunicados',
    'fontes_qualidade':'Fontes e qualidade da extração',
}

KIND_TOPIC = {
    'meta':'visao_geral',
    'document_part':'visao_geral',
    'position':'cargos_vagas',
    'program':'conteudo_programatico',
    'requirement':'requisitos_documentos',
    'exam_rule':'provas_etapas',
    'resource':'recursos_resultados',
    'retification':'retificacoes',
}
KEY_TOPIC = {
    'registration_period':'inscricoes','registration_date':'inscricoes','fee_values':'inscricoes','fee_payment':'inscricoes','exemption_date':'inscricoes','exemption_period':'inscricoes',
    'exam_date':'provas_etapas','answer_key':'recursos_resultados','appeal':'recursos_resultados','result':'recursos_resultados','homologation':'recursos_resultados','timeline_date':'cronograma',
}

RAW_BAD = re.compile(r'(\[PÁGINA|\|\|\|\||ﬁ|ﬂ|não haverárecursos|sua jornada|preparatório ilimitado)', re.I)

def _page_ref(page: Any) -> str:
    return f"p. {page}" if page not in (None,'') else 'fonte não localizada'

def _fmt_value(v: Any) -> str:
    if isinstance(v, dict):
        if 'start' in v or 'end' in v:
            return f"{date_fmt(v.get('start'))} a {date_fmt(v.get('end'))}"
        return ', '.join(f"{k}: {_fmt_value(val)}" for k,val in v.items() if val not in (None,'',[]))
    if isinstance(v, list):
        vals=[]
        for x in v[:8]:
            if isinstance(x,(int,float)):
                vals.append(money_fmt(x) if x >= 1 else str(x))
            else:
                vals.append(_fmt_value(x))
        return ', '.join(vals)
    if isinstance(v,(int,float)):
        return str(int(v)) if isinstance(v,int) or float(v).is_integer() else str(v)
    if isinstance(v,str):
        # ISO date
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', v): return date_fmt(v)
        return clean_text(v)
    return str(v)

def evidence_by_topic(evidence: dict) -> dict[str, list[dict]]:
    grouped={t:[] for t in TOPICS}
    for e in evidence.get('evidence') or []:
        topic = KEY_TOPIC.get(e.get('key')) or KIND_TOPIC.get(e.get('kind')) or 'fontes_qualidade'
        grouped.setdefault(topic,[]).append(e)
    return grouped

def _short_evidence(evs: list[dict], limit:int=28) -> list[dict]:
    out=[]
    for e in evs[:limit]:
        txt=clean_text(str(e.get('text') or ''))
        if RAW_BAD.search(txt):
            txt='Trecho ignorado por parecer ruído/OCR cru.'
        out.append({'kind':e.get('kind'),'key':e.get('key'),'value':e.get('value'),'page':e.get('page'),'text':txt[:300],'confidence':e.get('confidence',0)})
    return out

def _fact(label, value, source=None, confidence=0.7):
    if value in (None,'',[]): return None
    val = _fmt_value(value)
    if isinstance(value, (int, float)) and re.search(r'sal[aá]rio|remunera|taxa|vencimento|bolsa', label, re.I):
        val = money_fmt(value)
    return {'label':label, 'value':val, 'source':_page_ref(source), 'confidence':confidence}

def deterministic_cards(schema: dict, evidence: dict) -> dict[str, dict]:
    grouped=evidence_by_topic(evidence)
    cards={}
    # visão geral
    facts=[]
    for label,key in [('Título','title'),('Instituição','institution'),('Organizador/Banca','organizer'),('Tipo de edital','document_type'),('Status','status'),('Localidade','city'),('Estado','state')]:
        f=_fact(label, schema.get(key), None, .75)
        if f: facts.append(f)
    summary_parts=[]
    if schema.get('institution'):
        summary_parts.append(f"{schema.get('institution')} é a instituição principal identificada neste edital.")
    if schema.get('document_type'):
        summary_parts.append(f"O documento foi classificado como {str(schema.get('document_type')).replace('_',' ')}.")
    if schema.get('status') and schema.get('status')!='indefinido':
        summary_parts.append(f"Há indicação de status consolidado como {str(schema.get('status')).replace('_',' ')}.")
    if not summary_parts:
        summary_parts.append('O documento foi indexado, mas os dados gerais precisam de revisão porque nem todos os campos principais foram identificados com segurança.')
    cards['visao_geral']={
        'topic':'visao_geral','title':TOPIC_TITLES['visao_geral'],'confidence':0.7,
        'summary':' '.join(summary_parts),'facts':facts,'rules':[],
        'warnings':[n.get('message') for n in schema.get('needs_review') or [] if isinstance(n,dict) and n.get('message')][:8],
        'sources':sorted({_page_ref(e.get('page')) for e in grouped.get('visao_geral',[]) if e.get('page')})[:12]
    }
    # inscrições
    facts=[]
    f=_fact('Período de inscrição', {'start':schema.get('registration_start'),'end':schema.get('registration_end')}, None, .8)
    if f and 'não identificado' not in f['value']: facts.append(f)
    f=_fact('Taxa de inscrição', schema.get('fee_text') or schema.get('fee'), None, .8)
    if f: facts.append(f)
    rules=[]
    for e in grouped.get('inscricoes',[])[:12]:
        txt=clean_text(e.get('text') or '')
        if 30 <= len(txt) <= 380 and not RAW_BAD.search(txt): rules.append(txt)
    summary='As informações de inscrição foram organizadas a partir das evidências localizadas no edital. '
    if schema.get('registration_start') or schema.get('registration_end'):
        summary += f"O período identificado vai de {date_fmt(schema.get('registration_start'))} a {date_fmt(schema.get('registration_end'))}. "
    if schema.get('fee_text') or schema.get('fee'):
        summary += f"A taxa identificada foi {schema.get('fee_text') or money_fmt(schema.get('fee'))}."
    if not facts and not rules:
        summary='A wiki não encontrou um bloco de inscrições confiável. O campo deve ser revisado manualmente antes de ser usado como informação pública.'
    cards['inscricoes']={'topic':'inscricoes','title':TOPIC_TITLES['inscricoes'],'confidence':0.72 if facts else 0.35,'summary':summary,'facts':facts,'rules':rules[:8],'warnings':[] if facts else ['Período/taxa de inscrição não identificados com segurança.'],'sources':sorted({_page_ref(e.get('page')) for e in grouped.get('inscricoes',[]) if e.get('page')})[:12]}
    # cargos
    positions=schema.get('positions') or []
    facts=[]
    for label,key in [('Total de vagas','total_vacancies'),('Menor remuneração','salary_min'),('Maior remuneração','salary_max')]:
        f=_fact(label, schema.get(key), None, .8)
        if f: facts.append(f)
    if positions:
        top=sorted([p for p in positions if isinstance(p.get('salary'),(int,float))], key=lambda x:x.get('salary') or 0, reverse=True)[:5]
        rules=[f"{p.get('name')} — {p.get('vacancies','—')} vaga(s), {money_fmt(p.get('salary'))}" for p in top]
        summary=f"Foram identificados {len(positions)} cargos/funções ou linhas de vaga com segurança suficiente. A tabela da página apresenta os cargos extraídos, com remuneração e requisitos quando disponíveis."
    else:
        rules=[]; summary='Nenhum quadro de cargos/vagas foi interpretado com segurança. Isso pode acontecer quando o edital não possui cargos, quando a tabela está em imagem ou quando a extração tabular falhou.'
    cards['cargos_vagas']={'topic':'cargos_vagas','title':TOPIC_TITLES['cargos_vagas'],'confidence':0.78 if positions else 0.3,'summary':summary,'facts':facts,'rules':rules,'warnings':[] if positions else ['Cargos/vagas não identificados com segurança.'],'sources':sorted({_page_ref(p.get('source_page')) for p in positions if p.get('source_page')})[:20]}
    # cronograma
    timeline=schema.get('timeline') or []
    rules=[f"{t.get('label')}: {date_fmt(t.get('start'))}" + (f" a {date_fmt(t.get('end'))}" if t.get('end') and t.get('end')!=t.get('start') else '') for t in timeline[:12]]
    summary='O cronograma abaixo reúne apenas datas que passaram por validação contextual, priorizando seções de cronograma, inscrições, provas, recursos e resultados.' if timeline else 'Nenhum cronograma confiável foi consolidado. Datas soltas de leis, decretos ou referências históricas não foram publicadas como etapas do edital.'
    cards['cronograma']={'topic':'cronograma','title':TOPIC_TITLES['cronograma'],'confidence':0.75 if timeline else 0.35,'summary':summary,'facts':[],'rules':rules,'warnings':[] if timeline else ['Cronograma não identificado com segurança.'],'sources':sorted({_page_ref(t.get('source_page')) for t in timeline if t.get('source_page')})[:20]}
    # provas
    rules=list(schema.get('exam_rules') or [])[:12]
    facts=[]
    f=_fact('Data de prova/etapa principal', schema.get('exam_date'), None, .78)
    if f: facts.append(f)
    f=_fact('Local de prova', schema.get('exam_location'), None, .68)
    if f: facts.append(f)
    summary='A página reúne data, local e regras de prova/etapas quando essas informações foram localizadas com segurança.' if (facts or rules) else 'Não foram identificadas regras ou datas de prova com segurança.'
    cards['provas_etapas']={'topic':'provas_etapas','title':TOPIC_TITLES['provas_etapas'],'confidence':0.72 if (facts or rules) else 0.35,'summary':summary,'facts':facts,'rules':rules,'warnings':[] if (facts or rules) else ['Provas/etapas não identificadas com segurança.'],'sources':sorted({_page_ref(e.get('page')) for e in grouped.get('provas_etapas',[]) if e.get('page')})[:16]}
    # program
    program=schema.get('program') or []
    rules=[f"{p.get('subject')}" + (f" — {p.get('questions')} questão(ões)" if p.get('questions') else '') for p in program[:30]]
    summary=f"Foram identificados {len(program)} itens de conteúdo programático ou disciplinas." if program else 'Nenhum conteúdo programático foi identificado com segurança.'
    cards['conteudo_programatico']={'topic':'conteudo_programatico','title':TOPIC_TITLES['conteudo_programatico'],'confidence':0.72 if program else 0.35,'summary':summary,'facts':[],'rules':rules,'warnings':[] if program else ['Conteúdo programático ausente ou não interpretado.'],'sources':sorted({_page_ref(e.get('page')) for e in grouped.get('conteudo_programatico',[]) if e.get('page')})[:16]}
    # lists
    for topic, field, empty in [
        ('requisitos_documentos','requirements','Requisitos e documentos não foram identificados com segurança.'),
        ('recursos_resultados','resources','Regras de recursos/resultados não foram identificadas com segurança.'),
        ('retificacoes','retifications','Retificações, prorrogações ou comunicados não foram identificados com segurança.'),
    ]:
        items=list(schema.get(field) or [])[:12]
        cards[topic]={'topic':topic,'title':TOPIC_TITLES[topic],'confidence':0.72 if items else 0.35,'summary':('Foram identificadas informações relevantes para este tópico.' if items else empty),'facts':[],'rules':items,'warnings':[] if items else [empty],'sources':sorted({_page_ref(e.get('page')) for e in grouped.get(topic,[]) if e.get('page')})[:16]}
    cards['fontes_qualidade']={'topic':'fontes_qualidade','title':TOPIC_TITLES['fontes_qualidade'],'confidence':0.75,'summary':f"A indexação gerou {schema.get('evidence_count') or len(evidence.get('evidence') or [])} evidências rastreáveis. As páginas públicas evitam despejar texto bruto; os trechos completos ficam preservados nos arquivos de extração.",'facts':[_fact('Evidências extraídas', schema.get('evidence_count') or len(evidence.get('evidence') or []), None, .9)],'rules':[],'warnings':[],'sources':[]}
    return cards

def refine_card_with_llm(topic: str, card: dict, schema: dict, evs: list[dict], model_id: str) -> dict:
    max_evs=int(config.data.get('indexing',{}).get('max_card_evidence',28))
    prompt=f"""
Você é o compilador da LLM Wiki WikiEditais.
Sua tarefa NÃO é copiar evidências. Sua tarefa é transformar evidências em uma página de conhecimento coerente.

Tema: {TOPIC_TITLES.get(topic, topic)}

Regras obrigatórias:
- Escreva em português natural, como uma wiki/guia para candidato.
- Não invente informação ausente.
- Não publique datas de leis/decretos como cronograma do certame.
- Não copie OCR cru nem grandes blocos literais.
- Mantenha fatos curtos com fonte quando houver.
- Se houver incerteza, coloque em warnings.
- Responda somente JSON válido.

Retorne:
{{
  "summary": "parágrafo explicativo com entendimento do tópico",
  "facts": [{{"label":"...","value":"...","source":"p. X","confidence":0.0}}],
  "rules": ["regras/observações importantes, reescritas e curtas"],
  "warnings": ["pendências ou incertezas"],
  "confidence": 0.0
}}

SCHEMA COMPACTO:
{json.dumps({k:schema.get(k) for k in ['title','document_type','institution','organizer','state','city','status','total_vacancies','salary_min','salary_max','fee_text','registration_start','registration_end','exam_date','exam_location']}, ensure_ascii=False)}

CARD DETERMINÍSTICO:
{json.dumps(card, ensure_ascii=False)[:6000]}

EVIDÊNCIAS DO TÓPICO:
{json.dumps(_short_evidence(evs, max_evs), ensure_ascii=False)[:9000]}
"""
    raw=complete(prompt, model_id=model_id, system='Você escreve knowledge cards para uma LLM Wiki de editais.', temperature=0.08, json_mode=True, timeout=config.data.get('indexing',{}).get('request_timeout_seconds',600))
    data=extract_json(raw,{})
    if not isinstance(data,dict): return card
    new=dict(card)
    for key in ['summary','facts','rules','warnings','confidence']:
        if key in data and data[key] not in (None,''):
            new[key]=data[key]
    # normalize to avoid malformed local JSON silently breaking pages
    if not isinstance(new.get('facts'), list): new['facts']=card.get('facts',[])
    if not isinstance(new.get('rules'), list): new['rules']=card.get('rules',[])
    if not isinstance(new.get('warnings'), list): new['warnings']=card.get('warnings',[])
    try: new['confidence']=max(0,min(1,float(new.get('confidence',card.get('confidence',0.5)))))
    except Exception: new['confidence']=card.get('confidence',0.5)
    return new

def build_knowledge_cards(schema: dict, evidence: dict, model_id: str | None = None) -> dict:
    cards=deterministic_cards(schema,evidence)
    if not config.data.get('indexing',{}).get('use_llm_for_knowledge_cards', True):
        return cards
    model_id=model_id or config.data.get('models',{}).get('default_index_model')
    if not model_id:
        return cards
    grouped=evidence_by_topic(evidence)
    # Only refine topics with evidence/cards. If local Ollama is offline, errors are recorded in visao_geral.
    errors=[]
    for topic in TOPICS:
        # fontes_qualidade does not need LLM
        if topic == 'fontes_qualidade': continue
        if not grouped.get(topic) and not cards.get(topic,{}).get('facts') and not cards.get(topic,{}).get('rules'):
            continue
        try:
            cards[topic]=refine_card_with_llm(topic,cards[topic],schema,grouped.get(topic,[]),model_id)
        except Exception as e:
            errors.append(f"{topic}: {str(e)[:180]}")
            # if first call failed due ollama down, don't spam the whole indexing
            if 'Connection refused' in str(e) or 'Max retries' in str(e) or 'Ollama' in str(e):
                break
    if errors:
        cards['visao_geral'].setdefault('warnings',[]).append('LLM local não refinou todos os knowledge cards; wiki foi escrita com cards determinísticos seguros. Erros: ' + ' | '.join(errors[:4]))
    return cards

def _fact_lines(card: dict) -> list[str]:
    lines=[]
    for f in card.get('facts') or []:
        if isinstance(f,dict):
            label=clean_text(str(f.get('label') or 'Fato'))
            value=clean_text(str(f.get('value') or ''))
            source=clean_text(str(f.get('source') or ''))
            if value: lines.append(f"- **{label}:** {value}" + (f" ({source})" if source and source!='fonte não localizada' else ''))
        else:
            lines.append(f"- {clean_text(str(f))}")
    return lines

def _rule_lines(card: dict, limit:int=18) -> list[str]:
    out=[]
    for r in (card.get('rules') or [])[:limit]:
        if isinstance(r,dict): r=json.dumps(r,ensure_ascii=False)
        txt=clean_text(str(r))
        if not txt or RAW_BAD.search(txt): continue
        out.append(f"- {txt[:550]}")
    return out

def _source_lines(card: dict) -> list[str]:
    sources=[]
    for s in card.get('sources') or []:
        if s and s not in sources: sources.append(s)
    if not sources: return []
    return ['## Fontes usadas neste tópico'] + [f"- {s}" for s in sources[:20]]

def _warnings_lines(card:dict)->list[str]:
    warns=[]
    for w in card.get('warnings') or []:
        txt=clean_text(str(w))
        if txt: warns.append(f"- {txt[:350]}")
    return warns

def topic_page(title:str, card:dict, empty:str='Informação não identificada com segurança.') -> str:
    lines=[f"# {title}", '', card.get('summary') or empty, '']
    facts=_fact_lines(card)
    if facts:
        lines += ['## Fatos consolidados'] + facts + ['']
    rules=_rule_lines(card)
    if rules:
        lines += ['## O que isso significa na prática'] + rules + ['']
    warns=_warnings_lines(card)
    if warns:
        lines += ['## Pendências e cuidados'] + warns + ['']
    src=_source_lines(card)
    if src:
        lines += src + ['']
    return '\n'.join(lines).strip()+'\n'

def md_table_positions(schema:dict, card:dict)->str:
    lines=["# Cargos e vagas", '', card.get('summary') or 'Cargos e vagas não identificados com segurança.', '']
    facts=_fact_lines(card)
    if facts: lines += ['## Síntese'] + facts + ['']
    pos=schema.get('positions') or []
    if pos:
        lines += ['## Tabela consolidada', '| Cargo | Vagas | Salário | Requisitos | Fonte |', '|---|---:|---:|---|---|']
        for p in pos[:350]:
            lines.append(f"| {clean_text(p.get('name') or '—')} | {p.get('vacancies','—')} | {money_fmt(p.get('salary'))} | {clean_text(p.get('requirements') or '—')[:170]} | p. {p.get('source_page','—')} |")
        lines.append('')
    else:
        lines.append('Nenhum cargo, função ou vaga foi identificado com segurança na extração atual. Consulte o PDF original ou edite esta página manualmente se necessário.\n')
    warns=_warnings_lines(card)
    if warns: lines += ['## Pendências'] + warns + ['']
    return '\n'.join(lines).strip()+'\n'

def md_timeline(schema:dict, card:dict)->str:
    lines=['# Cronograma','', card.get('summary') or 'Cronograma não identificado com segurança.', '']
    if schema.get('timeline'):
        lines += ['| Etapa | Início | Fim | Tipo | Fonte |','|---|---|---|---|---|']
        for ev in schema.get('timeline')[:120]:
            lines.append(f"| {clean_text(ev.get('label') or '—')} | {date_fmt(ev.get('start'))} | {date_fmt(ev.get('end'))} | {ev.get('type','—')} | p. {ev.get('source_page','—')} |")
        lines.append('')
    rules=_rule_lines(card)
    if rules: lines += ['## Observações'] + rules + ['']
    warns=_warnings_lines(card)
    if warns: lines += ['## Pendências'] + warns + ['']
    return '\n'.join(lines).strip()+'\n'

def md_program(schema:dict, card:dict)->str:
    lines=['# Conteúdo programático','', card.get('summary') or 'Conteúdo programático não identificado com segurança.', '']
    if schema.get('program'):
        lines += ['| Matéria/tema | Questões |','|---|---:|']
        for p in schema.get('program')[:400]:
            lines.append(f"| {clean_text(p.get('subject') or '—')} | {p.get('questions') or '—'} |")
        lines.append('')
    rules=_rule_lines(card,30)
    if rules: lines += ['## Itens destacados'] + rules + ['']
    return '\n'.join(lines).strip()+'\n'

def md_sources(schema:dict, evidence:dict, cards:dict)->str:
    lines=['# Fontes e rastreabilidade','']
    lines.append(f"Arquivo original: `{schema.get('raw_file') or 'não identificado'}`")
    if schema.get('source_url'): lines.append(f"URL original: {schema.get('source_url')}")
    lines += ['', '## Qualidade da indexação']
    lines.append(f"- Evidências extraídas: {schema.get('evidence_count') or len(evidence.get('evidence') or [])}")
    lines.append(f"- Knowledge cards: {len(cards)}")
    avg=sum(float(c.get('confidence') or 0) for c in cards.values())/max(1,len(cards))
    lines.append(f"- Confiança média dos cards: {avg:.2f}")
    lines += ['', '## Páginas mapeadas']
    for src in (schema.get('sources') or evidence.get('sources') or [])[:650]:
        lines.append(f"- p. {src.get('page')}: {src.get('topic') or src.get('role') or 'geral'} — {src.get('title') or 'sem título'}")
    lines += ['', '## Observação']
    lines.append('As páginas públicas da wiki não despejam texto bruto do PDF. As evidências completas ficam salvas em `evidence.json` para auditoria e revisão manual.')
    return '\n'.join(lines).strip()+'\n'

def write_wiki_pages_from_cards(schema: dict, evidence: dict, cards: dict, llm_notes: dict | None = None) -> dict[str,str]:
    title=schema.get('title') or 'Edital'
    pages={}
    pages['index.md']=f"""# {title}

Esta é a wiki Markdown consolidada do edital. A página principal é `MASTER.md`; as demais páginas organizam tópicos específicos.

## Páginas
- [MASTER](MASTER.md)
- [Dados principais](dados-principais.md)
- [Cargos e vagas](cargos-e-vagas.md)
- [Inscrições](inscricoes.md)
- [Cronograma](cronograma.md)
- [Provas e etapas](provas-e-etapas.md)
- [Conteúdo programático](conteudo-programatico.md)
- [Requisitos](requisitos.md)
- [Recursos](recursos.md)
- [Retificações](retificacoes.md)
- [Fontes](fontes.md)
"""
    overview=cards.get('visao_geral',{})
    kp=[]
    for t in ['inscricoes','cargos_vagas','cronograma','provas_etapas','conteudo_programatico','recursos_resultados','retificacoes']:
        c=cards.get(t,{})
        if c.get('summary'):
            kp.append(f"- **{TOPIC_TITLES.get(t,t)}:** {clean_text(c.get('summary'))[:420]}")
    warnings=[]
    for c in cards.values():
        for w in c.get('warnings') or []:
            w=clean_text(str(w))
            if w and w not in warnings: warnings.append(w)
    pages['MASTER.md'] = f"""# {title}

## Visão geral

{overview.get('summary') or schema.get('summary') or 'Resumo não identificado com segurança.'}

## Leitura consolidada do edital

{chr(10).join(kp) if kp else 'A extração não encontrou informações suficientes para criar uma leitura consolidada completa. Revise o PDF original e os arquivos de evidência.'}

## Situação e confiabilidade

O status consolidado registrado é **{str(schema.get('status') or 'indefinido').replace('_',' ')}**. Esta wiki prioriza informações com evidência rastreável; campos sem fonte segura ficam como pendência em vez de serem apresentados como verdade.

## Pontos que exigem atenção

{chr(10).join('- '+w for w in warnings[:10]) if warnings else '- Nenhuma pendência grave foi identificada pelos cards de conhecimento.'}

## Como usar esta wiki

- Use `dados-principais.md` para conferir o schema em formato humano.
- Use `cargos-e-vagas.md`, `inscricoes.md`, `cronograma.md` e `provas-e-etapas.md` para informações operacionais.
- Use `fontes.md` para rastrear de quais páginas vieram as informações.
- Edite manualmente as páginas se o PDF tiver tabela escaneada, OCR ruim ou informação que o sistema marcou como incerta.
"""
    # dados principais
    rows=[('Instituição',schema.get('institution')),('Banca/organizador',schema.get('organizer')),('Tipo',str(schema.get('document_type') or '').replace('_',' ')),('Localidade',f"{schema.get('city') or '—'}/{schema.get('state') or '—'}"),('Status',schema.get('status')),('Vagas totais',schema.get('total_vacancies')),('Salário mínimo',money_fmt(schema.get('salary_min'))),('Salário máximo',money_fmt(schema.get('salary_max'))),('Taxa',schema.get('fee_text') or money_fmt(schema.get('fee'))),('Inscrições',f"{date_fmt(schema.get('registration_start'))} a {date_fmt(schema.get('registration_end'))}"),('Prova',date_fmt(schema.get('exam_date'))),('Local de prova',schema.get('exam_location'))]
    pages['dados-principais.md']='# Dados principais\n\n| Campo | Valor |\n|---|---|\n'+'\n'.join(f"| {a} | {b if b not in (None,'') else 'não identificado com segurança'} |" for a,b in rows)+'\n'
    pages['cargos-e-vagas.md']=md_table_positions(schema,cards.get('cargos_vagas',{}))
    pages['inscricoes.md']=topic_page('Inscrições',cards.get('inscricoes',{}),'Inscrições não identificadas com segurança.')
    pages['cronograma.md']=md_timeline(schema,cards.get('cronograma',{}))
    pages['provas-e-etapas.md']=topic_page('Provas e etapas',cards.get('provas_etapas',{}),'Provas e etapas não identificadas com segurança.')
    pages['conteudo-programatico.md']=md_program(schema,cards.get('conteudo_programatico',{}))
    pages['requisitos.md']=topic_page('Requisitos e documentos',cards.get('requisitos_documentos',{}),'Requisitos e documentos não identificados com segurança.')
    pages['recursos.md']=topic_page('Recursos, gabaritos e resultados',cards.get('recursos_resultados',{}),'Recursos/resultados não identificados com segurança.')
    pages['retificacoes.md']=topic_page('Retificações, prorrogações e comunicados',cards.get('retificacoes',{}),'Retificações/comunicados não identificados com segurança.')
    pages['fontes.md']=md_sources(schema,evidence,cards)
    return {k:v.strip()+"\n" for k,v in pages.items()}
