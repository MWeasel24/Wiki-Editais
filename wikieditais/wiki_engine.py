from __future__ import annotations

import hashlib, json, re, shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .config import config
from .storage import edital_dir, load_catalog, update_catalog_entry
from .utils import clean_text, safe_slug, write_json, read_json, money_fmt, date_fmt, remove_tree, truncate
from .linting import lint_schema
from .llm import complete, extract_json

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

UF_SET = {'AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO'}
UF_NAME = {'AMAZONAS':'AM','PARANÁ':'PR','PARANA':'PR','SANTA CATARINA':'SC','MINAS GERAIS':'MG','RONDÔNIA':'RO','RONDONIA':'RO','SÃO PAULO':'SP','SAO PAULO':'SP','PARÁ':'PA','PARA':'PA','CEARÁ':'CE','CEARA':'CE'}

TOPICS = {
    'dados-principais': {
        'file':'dados-principais.md', 'title':'Dados principais',
        'terms':['edital','concurso público','prefeitura','município','universidade','conselho','banca','organização','execução','suspensão','prorrogação','retificação','comunicado'],
        'schema':'identity_status'
    },
    'inscricoes': {
        'file':'inscricoes.md', 'title':'Inscrições',
        'terms':['inscrição','inscrições','taxa','boleto','pagamento','isenção','cadúnico','gratuito','site','www','prazo','período'],
        'schema':'registration'
    },
    'cargos-e-vagas': {
        'file':'cargos-e-vagas.md', 'title':'Cargos e vagas',
        'terms':['anexo i','quadro de vagas','cargo/função','cargo','função','vagas','remuneração','vencimento','salário','carga horária','escolaridade','pré-requisito','requisitos'],
        'schema':'positions'
    },
    'cronograma': {
        'file':'cronograma.md', 'title':'Cronograma',
        'terms':['cronograma','calendário','evento','data','período','inscrições','prova','gabarito','recurso','resultado','homologação','prorrogação'],
        'schema':'timeline'
    },
    'provas-e-etapas': {
        'file':'provas-e-etapas.md', 'title':'Provas e etapas',
        'terms':['prova objetiva','prova prática','prova','etapas','questões','pontuação','eliminatório','classificatório','local de prova','documento','caneta'],
        'schema':'exams'
    },
    'conteudo-programatico': {
        'file':'conteudo-programatico.md', 'title':'Conteúdo programático',
        'terms':['conteúdo programático','conteudos especificos','conhecimentos gerais','conhecimentos específicos','língua portuguesa','informática','disciplina','cargo:'],
        'schema':'program'
    },
    'requisitos': {
        'file':'requisitos.md', 'title':'Requisitos e contratação',
        'terms':['requisitos','investidura','posse','nomeação','documentos','escolaridade','registro no conselho','convocação','prazo máximo'],
        'schema':'requirements'
    },
    'recursos': {
        'file':'recursos.md', 'title':'Recursos',
        'terms':['recurso','recursos','interposição','gabarito','resultado preliminar','impugnação','email','protocolo'],
        'schema':'appeals'
    },
    'retificacoes': {
        'file':'retificacoes.md', 'title':'Retificações e comunicados',
        'terms':['errata','retificação','suspensão','suspenso','prorrogação','comunicado urgente','onde se lê','leia-se','alteração'],
        'schema':'changes'
    }
}

PAGE_CONTRACTS = {
    'cargos-e-vagas': 'Cargo é a função/oportunidade oferecida, como Gari, Motorista, Enfermeiro ou Professor. Não é decreto, requisito, regra de prova, PcD, conteúdo programático, frase iniciada por candidato/deverá/poderá, nem texto jurídico. Vaga é quantidade ofertada ou cadastro reserva. Salário/remuneração é valor pago pelo cargo; auxílio, taxa e nota não são salário.',
    'cronograma': 'Cronograma é uma lista de eventos operacionais do concurso: inscrição, pagamento, isenção, prova, gabarito, recurso, resultado e homologação. Datas de leis, decretos, portarias, CNPJ, CEP e endereços não são cronograma.',
    'inscricoes': 'Inscrições incluem período, local/site, forma de inscrição, taxa, pagamento, isenção e documentos. Cancelamento de inscrição individual não é status do concurso.',
    'dados-principais': 'Dados principais identificam órgão, edital, banca, cidade/UF, situação oficial e resumo. Status do edital só muda com ato explícito: suspensão, cancelamento do certame, prorrogação ou retificação.',
    'provas-e-etapas': 'Provas e etapas explicam tipo de avaliação, data/horário, quantidade de questões, pontuação, caráter eliminatório/classificatório e regras de aplicação.',
    'retificacoes': 'Retificações explicam erratas, comunicados e o impacto prático para candidato. Deve resumir o que mudou, não copiar todo Onde se lê/Leia-se.',
    'conteudo-programatico': 'Conteúdo programático é guia de estudos com disciplinas e tópicos cobrados por cargo ou nível. Não é cargo nem regra administrativa.',
    'requisitos': 'Requisitos são escolaridade, formação, documentos, registro profissional, posse, investidura e condições para assumir o cargo.',
    'recursos': 'Recursos são prazos e forma para contestar gabarito, resultado, inscrição, isenção ou outros atos.'
}

BAD_DATE_CTX = ['lei','decreto','portaria','constituição','cnpj','cep','publicada em','alterada por','estatuto']

# Guia editorial forte: cada página da wiki tem função própria. Isso impede que
# o backend trate Markdown como simples depósito de texto extraído.
WIKI_PAGE_GUIDE = {
    'dados-principais': {
        'role': 'apresentar a identidade do edital e orientar a leitura inicial',
        'sections': ['Visão geral', 'Identificação do certame', 'Situação atual', 'Como usar esta wiki', 'Pontos de atenção'],
        'must': ['órgão/instituição', 'tipo e número do edital', 'banca/organizadora', 'cidade/UF', 'status do certame'],
        'not': ['copiar cabeçalho inteiro', 'listar documentos pessoais', 'usar comissão genérica como banca se houver organizadora explícita'],
    },
    'inscricoes': {
        'role': 'explicar como o candidato participa do certame, com prazo, canal, taxa, pagamento e isenção',
        'sections': ['Visão geral', 'Período de inscrição', 'Como se inscrever', 'Taxa, pagamento e isenção', 'Pontos de atenção'],
        'must': ['início/fim', 'site/local/canal', 'taxa', 'pagamento', 'isenção', 'prorrogação'],
        'not': ['confundir cancelamento de inscrição individual com cancelamento do concurso', 'copiar regras longas sem explicar'],
    },
    'cargos-e-vagas': {
        'role': 'transformar o quadro de cargos em uma página útil sobre oportunidades, vagas, carga horária, salário e requisitos',
        'sections': ['Visão geral', 'Resumo das oportunidades', 'Cargos identificados', 'Como interpretar cargos e vagas', 'Pontos de atenção'],
        'must': ['cargo/função', 'vagas', 'carga horária', 'salário/remuneração', 'requisito/escolaridade', 'cadastro reserva ou PcD quando houver'],
        'not': ['tratar lei, decreto, regra, PcD isolado, conteúdo programático ou frase com candidato deverá como cargo'],
    },
    'cronograma': {
        'role': 'organizar datas operacionais do processo seletivo sem confundir com datas jurídicas',
        'sections': ['Visão geral', 'Eventos identificados', 'Datas que exigem conferência', 'Como acompanhar atualizações'],
        'must': ['inscrição', 'pagamento', 'isenção', 'prova', 'gabarito', 'recurso', 'resultado', 'homologação'],
        'not': ['usar datas de lei/decreto/portaria/CNPJ/CEP como evento'],
    },
    'provas-e-etapas': {
        'role': 'explicar como o candidato será avaliado e quais etapas existem',
        'sections': ['Visão geral', 'Etapas da seleção', 'Prova ou avaliação', 'Pontuação e classificação', 'Pontos de atenção'],
        'must': ['tipo de prova', 'data se clara', 'quantidade de questões', 'disciplinas', 'pontuação', 'critérios de aprovação'],
        'not': ['usar prazo de recurso como data de prova', 'colar conteúdo programático inteiro aqui'],
    },
    'conteudo-programatico': {
        'role': 'transformar programa do edital em guia de estudos navegável',
        'sections': ['Visão geral', 'Disciplinas identificadas', 'Conteúdos por área', 'Como estudar por esta página'],
        'must': ['disciplinas', 'conhecimentos gerais', 'conhecimentos específicos', 'organização por cargo/nível quando houver'],
        'not': ['misturar posse, inscrição, documentos ou recursos com conteúdo de prova'],
    },
    'requisitos': {
        'role': 'explicar requisitos de participação, posse, contratação e documentos',
        'sections': ['Visão geral', 'Requisitos gerais', 'Documentos e posse', 'Requisitos por cargo', 'Pontos de atenção'],
        'must': ['escolaridade', 'registro profissional', 'CNH quando houver', 'documentos', 'posse/contratação'],
        'not': ['transformar documento em cargo ou copiar lista enorme sem síntese'],
    },
    'recursos': {
        'role': 'explicar como contestar atos do certame',
        'sections': ['Visão geral', 'Quando cabe recurso', 'Como interpor', 'Prazos e canais', 'Pontos de atenção'],
        'must': ['prazos', 'gabarito', 'resultado', 'canal', 'fundamentação'],
        'not': ['confundir recurso administrativo com dinheiro ou material'],
    },
    'retificacoes': {
        'role': 'explicar erratas, prorrogações, suspensões e impactos práticos',
        'sections': ['Visão geral', 'Alterações identificadas', 'Impacto para o candidato', 'O que conferir no edital original'],
        'must': ['suspensão', 'prorrogação', 'erratas', 'onde se lê/leia-se', 'impacto prático'],
        'not': ['copiar blocos inteiros de errata sem síntese'],
    },
}


# ---------------------------------------------------------------------
# API pública usada pelo Flask
# ---------------------------------------------------------------------


def as_list(value):
    """Normaliza campos que podem vir como lista, string ou None para lista.
    Evita erros do tipo list + str durante a indexação e relatórios.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]

def index_upload(file_storage, title_hint: str = '', model_id: str | None = None):
    raw_dir = config.p('raw'); raw_dir.mkdir(parents=True, exist_ok=True)
    tmp = raw_dir / safe_filename(file_storage.filename or 'edital.pdf')
    file_storage.save(tmp)
    return index_file(tmp, title_hint, model_id)

def download_url(url: str, title_hint: str = '') -> Path:
    downloads = config.p('downloads'); downloads.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(url)
    name = Path(parsed.path).name or safe_slug(title_hint or 'edital') + '.pdf'
    if not Path(name).suffix: name += '.pdf'
    dest = downloads / safe_filename(name)
    r = requests.get(url, timeout=80, headers={'User-Agent':'WikiEditais/2.0 academic project'})
    r.raise_for_status(); dest.write_bytes(r.content)
    return dest

def index_file(path: Path, title_hint: str = '', model_id: str | None = None, source_url: str | None = None):
    path = Path(path)
    file_hash = sha256_file(path)
    existing = existing_by_hash(file_hash)
    if existing and (edital_dir(existing['id'])/'schema.json').exists():
        return read_json(edital_dir(existing['id'])/'schema.json', existing) or existing

    model_id = model_id or config.data.get('models',{}).get('default_index_model','ollama:qwen2.5:7b')
    raw_pages = extract_pages(path)
    pages = remove_repeated_noise(raw_pages)
    chunks = build_chunks(pages)
    identity = detect_identity('\n'.join(p['text'] for p in pages[:6]), title_hint or path.stem)
    title = identity.get('title') or title_case(title_hint or path.stem)
    edital_id = f"{safe_slug(title,'edital')}-{file_hash[:10]}"
    d = edital_dir(edital_id)
    if d.exists(): remove_tree(d)
    d.mkdir(parents=True, exist_ok=True)

    raw_copy = config.p('raw') / f"{file_hash[:16]}{path.suffix or '.pdf'}"
    if path.resolve() != raw_copy.resolve(): shutil.copy2(path, raw_copy)

    section_hits = retrieve_topic_hits(chunks)
    sections = build_sections(section_hits)
    # Fatos determinísticos dão base e garantem funcionamento mesmo sem LLM.
    deterministic = deterministic_topic_facts(identity, pages, sections)
    # Fatos da LLM são obrigatórios para qualidade alta. Se falhar, a wiki é marcada como degradada.
    topic_facts, llm_report = llm_topic_facts(sections, deterministic, identity, model_id)
    merged_facts = merge_topic_facts(deterministic, topic_facts)
    evidence_cards = build_evidence_cards(merged_facts, sections)
    wiki_plan = build_wiki_plan(merged_facts, sections, identity)
    wiki_pages, wiki_report = build_true_wiki_pages(merged_facts, sections, identity, model_id, llm_report, wiki_plan)
    schema = build_public_schema(edital_id, identity, merged_facts, path, raw_copy, source_url, file_hash, llm_report, wiki_report)
    quality_report = build_quality_report(schema, merged_facts, sections, llm_report, wiki_report)
    lint = lint_schema(schema, wiki_pages.get('MASTER.md',''), evidence={'topic_facts':merged_facts,'sections':sections,'quality_report':quality_report})
    # Usa o menor dos dois para não maquiar resultado com lint antigo.
    score = min(int(lint.get('score',0)), int(quality_report.get('score',0)))
    schema['lint_score'] = score
    schema['quality'] = 'boa' if score >= 85 else ('revisar' if score >= 65 else 'crítica')
    schema['needs_review'] = sorted(set(str(x) for x in (as_list(lint.get('issues')) + as_list(lint.get('warnings')) + as_list(quality_report.get('issues')))))
    schema['display'] = make_display(schema)
    schema['wiki_strategy'] = 'v20_microcopy_template_safe'

    # Artefatos
    write_json(d/'manifest.json', {'id':edital_id,'file_hash':file_hash,'source_filename':path.name,'raw_file':schema.get('raw_file'),'created_at':datetime.now().isoformat(timespec='seconds'),'strategy':'v20_microcopy_template_safe','model_id':model_id})
    write_json(d/'pages.json', pages)
    write_json(d/'chunks.json', chunks)
    write_json(d/'section_hits.json', section_hits)
    write_json(d/'sections.json', sections)
    write_json(d/'deterministic_facts.json', deterministic)
    write_json(d/'llm_topic_facts.json', topic_facts)
    write_json(d/'topic_facts.json', merged_facts)
    write_json(d/'evidence_cards.json', evidence_cards)
    write_json(d/'wiki_plan.json', wiki_plan)
    write_json(d/'positions.json', merged_facts.get('cargos-e-vagas',{}).get('positions',[]))
    write_json(d/'timeline.json', merged_facts.get('cronograma',{}).get('events',[]))
    write_json(d/'llm_report.json', llm_report)
    write_json(d/'wiki_report.json', wiki_report)
    write_json(d/'quality_report.json', quality_report)
    write_json(d/'schema.json', schema)
    write_json(d/'public_schema.json', schema)
    write_json(d/'lint.json', lint)
    (d/'source.md').write_text(build_source_md(pages, merged_facts), encoding='utf-8')
    (d/'lint.md').write_text(render_lint_md({'score':score,'issues':schema['needs_review'],'warnings':quality_report.get('warnings',[]),'ok':score>=65}), encoding='utf-8')
    for fn, content in wiki_pages.items(): (d/fn).write_text(content, encoding='utf-8')
    update_catalog_entry(schema)
    return schema

# ---------------------------------------------------------------------
# Extração e armazenamento
# ---------------------------------------------------------------------
def safe_filename(name: str) -> str:
    return re.sub(r'[^\w\-. ()áéíóúàãõâêôçÁÉÍÓÚÀÃÕÂÊÔÇ]+','_', Path(name).name)[:180] or 'edital.pdf'

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for c in iter(lambda:f.read(1024*1024), b''): h.update(c)
    return h.hexdigest()

def existing_by_hash(file_hash: str):
    for item in load_catalog().get('editais',[]):
        if item.get('file_hash') == file_hash: return item
    return None

def extract_pages(path: Path) -> list[dict[str,Any]]:
    if path.suffix.lower() in ['.txt','.md']:
        txt = clean_text(path.read_text(encoding='utf-8', errors='ignore'))
        parts = [txt[i:i+4500] for i in range(0,len(txt),4500)] or ['']
        return [{'page':i+1,'text':p} for i,p in enumerate(parts)]
    if fitz is None: raise RuntimeError('PyMuPDF não instalado. Rode: pip install pymupdf')
    doc = fitz.open(str(path)); out=[]
    for i,p in enumerate(doc): out.append({'page':i+1,'text':clean_page_text(p.get_text('text') or '')})
    doc.close(); return out

def clean_page_text(t: str) -> str:
    t = t.replace('\x00',' ')
    t = re.sub(r'([A-Za-zÁÉÍÓÚÀÃÕÂÊÔÇáéíóúàãõâêôç])-\n([A-Za-zÁÉÍÓÚÀÃÕÂÊÔÇáéíóúàãõâêôç])', r'\1\2', t)
    t = re.sub(r'[ \t]+',' ',t)
    t = re.sub(r'\n{3,}','\n\n',t)
    return t.strip()

def normalize_line(l: str) -> str:
    return re.sub(r'\W+',' ',l.lower()).strip()

def remove_repeated_noise(pages: list[dict[str,Any]]) -> list[dict[str,Any]]:
    counts=Counter(); total=len(pages)
    for p in pages:
        seen=set()
        for line in p.get('text','').splitlines():
            n=normalize_line(line)
            if 8<=len(n)<=120: seen.add(n)
        counts.update(seen)
    repeated={x for x,c in counts.items() if c>=max(6,int(total*0.45))}
    out=[]
    for p in pages:
        lines=[l for l in p.get('text','').splitlines() if normalize_line(l) not in repeated]
        out.append({'page':p['page'],'text':'\n'.join(lines).strip()})
    return out

# ---------------------------------------------------------------------
# Identidade e recuperação
# ---------------------------------------------------------------------
def title_case(s: str) -> str:
    s = re.sub(r'[_\s]+',' ',s or '').strip(' -–—')
    small={'de','do','da','dos','das','e','em','no','na','para','com'}
    out=[]
    for w in s.split():
        raw=w.strip('.,;:()')
        if raw.upper() in UF_SET or raw.upper() in ['IPRO','IBADE','UFAM','FEPESE','CNPJ','CBO','AM','SC','PR','MG']:
            out.append(raw.upper())
        elif raw.lower() in small: out.append(raw.lower())
        else: out.append(w[:1].upper()+w[1:].lower())
    return ' '.join(out)

def detect_identity(first: str, fallback: str) -> dict[str,Any]:
    lines=[l.strip(' -–—') for l in first.splitlines() if l.strip()]
    blob='\n'.join(lines[:100])
    title=None
    for l in lines[:60]:
        if re.search(r'CONCURSO P[ÚU]BLICO|EDITAL\s+(?:DE\s+)?CONCURSO|PROCESSO SELETIVO|COMUNICADO URGENTE|ERRATA', l, re.I):
            title=title_case(l); break
    if not title: title=title_case(fallback)
    institution=None
    for l in lines[:80]:
        m=re.search(r'((?:PREFEITURA|MUNIC[IÍ]PIO|C[ÂA]MARA MUNICIPAL)\s+(?:MUNICIPAL\s+)?(?:DE|DO|DA)?\s*[A-ZÁÉÍÓÚÀÃÕÂÊÔÇ][A-ZÁÉÍÓÚÀÃÕÂÊÔÇ\s\-]{3,90})', l.upper())
        if m: institution=clean_entity(m.group(1)); break
        m=re.search(r'((?:UNIVERSIDADE|INSTITUTO FEDERAL|CONSELHO REGIONAL|TRIBUNAL|FUNDA[ÇC][ÃA]O)\s+[A-ZÁÉÍÓÚÀÃÕÂÊÔÇ][A-ZÁÉÍÓÚÀÃÕÂÊÔÇ\s\-]{3,110})', l.upper())
        if m: institution=clean_entity(m.group(1)); break
    city,state=detect_city_state(blob+'\n'+fallback)
    organizer=detect_organizer(first)
    status=detect_status(first+'\n'+fallback)
    doc_type='concurso_publico' if re.search(r'concurso p[úu]blico', first, re.I) else ('processo_seletivo' if re.search(r'processo seletivo', first, re.I) else 'edital')
    return {'title':title,'institution':institution,'city':city,'state':state,'organizer':organizer,'status':status,'document_type':doc_type}

def clean_entity(s: str) -> str:
    s=re.sub(r'\s+',' ',s or '').strip(' -–—.,;:')
    s=re.split(r'\b(EDITAL|CONCURSO|PROCESSO|CNPJ|CEP|RUA|AVENIDA|DECRETO|LEI|SECRETARIA)\b', s, maxsplit=1, flags=re.I)[0].strip(' -–—.,;:')
    return title_case(s)

def detect_city_state(text: str):
    m=re.search(r'(?:PREFEITURA(?: MUNICIPAL)?|MUNIC[IÍ]PIO)\s+(?:MUNICIPAL\s+)?(?:DE|DO|DA)?\s*([A-ZÁÉÍÓÚÀÃÕÂÊÔÇ][A-Za-zÁÉÍÓÚÀÃÕÂÊÔÇ\s\-]{2,60})\s*(?:-|–|/)\s*([A-Z]{2})\b', text, re.I)
    if m and m.group(2).upper() in UF_SET:
        return title_case(re.split(r'\b(ESTADO|CNPJ|EDITAL|CONCURSO|SECRETARIA)\b', m.group(1), flags=re.I)[0]), m.group(2).upper()
    for name,uf in UF_NAME.items():
        if re.search(r'\b'+name+r'\b', text, re.I): return None, uf
    return None, None

def detect_organizer(text: str):
    known={'IBADE':'Instituto Brasileiro de Apoio e Desenvolvimento Executivo - IBADE','IPRO':'Instituto de Apoio à Pesquisa Científica, Educacional e Tecnológica de Rondônia - IPRO','FEPESE':'Fundação de Estudos e Pesquisas Socioeconômicos - FEPESE','FGV':'FGV','CEBRASPE':'CEBRASPE','VUNESP':'VUNESP','FCC':'FCC'}
    up=text.upper()
    for k,v in known.items():
        if k in up: return v
    m=re.search(r'organiza[çc][ãa]o.{0,80}(?:cargo|responsabilidade|pelo|pela|a cargo d[eo a])\s+([^\.\n]{6,180})', text, re.I)
    if m: return clean_entity(m.group(1))
    return None

def detect_status(text: str):
    low=text.lower()
    # Remover contextos individuais para não virar status do certame.
    low=re.sub(r'inscri[çc][ãa]o.{0,35}cancelad[ao]|candidato.{0,35}cancelad[ao]|pedido.{0,35}cancelad[ao]','',low)
    if re.search(r'comunicado urgente\s*[-–]\s*suspens[ãa]o|concurso.{0,120}suspens[oa]|certame.{0,120}suspens[oa]', low): return 'suspenso'
    if re.search(r'cancelamento do concurso|concurso cancelado|certame cancelado|edital cancelado', low): return 'cancelado'
    if re.search(r'prorroga[çc][ãa]o\s+(?:das\s+)?inscri[çc][õo]es|inscri[çc][õo]es ficam prorrogadas|inscri[çc][õo]es prorrogadas', low): return 'prorrogado'
    if re.search(r'errata\s+[ivx]+|edital de retifica[çc][ãa]o|retifica[çc][ãa]o', low): return 'retificado'
    return 'indefinido'

def build_chunks(pages: list[dict[str,Any]], max_chars: int = 1800) -> list[dict[str,Any]]:
    chunks=[]
    for p in pages:
        paras=[x.strip() for x in re.split(r'\n\s*\n', p.get('text','')) if x.strip()]
        buf=''
        for para in paras or [p.get('text','')]:
            if len(buf)+len(para) > max_chars and buf:
                chunks.append({'id':len(chunks),'page':p['page'],'text':buf.strip()}); buf=''
            buf += ('\n\n' if buf else '') + para
        if buf.strip(): chunks.append({'id':len(chunks),'page':p['page'],'text':buf.strip()})
    return chunks

def score_chunk(text: str, terms: list[str]) -> int:
    low=(text or '').lower(); score=0
    for t in terms:
        if t in low: score += 4 + min(4, low.count(t))
    score += min(10, len(re.findall(r'R\$\s*[\d\.,]+', text)))
    score += min(10, len(re.findall(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', text)))
    return score

def retrieve_topic_hits(chunks: list[dict[str,Any]]) -> dict[str,Any]:
    hits={}
    for key,spec in TOPICS.items():
        ranked=[]
        for ch in chunks:
            sc=score_chunk(ch['text'], spec['terms'])
            if sc>0: ranked.append({'chunk_id':ch['id'],'page':ch['page'],'score':sc,'text':ch['text']})
        ranked=sorted(ranked, key=lambda x:x['score'], reverse=True)[:18]
        hits[key]={'pages':sorted(set(x['page'] for x in ranked), key=lambda p: min(i for i,x in enumerate(ranked) if x['page']==p))[:12], 'hits':ranked}
    return hits

def build_sections(section_hits: dict[str,Any]) -> dict[str,Any]:
    sections={}
    for key,h in section_hits.items():
        txt='\n\n'.join(f"[p. {x['page']}]\n{x['text']}" for x in h.get('hits',[])[:12])
        sections[key]={'title':TOPICS[key]['title'],'pages':h.get('pages',[]),'text':txt[:30000]}
    return sections

# ---------------------------------------------------------------------
# Fatos por tópico: determinístico + LLM JSON
# ---------------------------------------------------------------------
def deterministic_topic_facts(identity: dict, pages: list[dict[str,Any]], sections: dict[str,Any]) -> dict[str,Any]:
    all_text='\n'.join(p['text'] for p in pages)
    facts={k:{'topic':k,'confidence':0.35,'source':'deterministic'} for k in TOPICS}
    facts['dados-principais'].update(identity)
    facts['inscricoes'].update(extract_registration_facts((sections.get('inscricoes',{}).get('text','') or '') + '\n' + all_text))
    facts['cargos-e-vagas'].update(extract_positions_facts((sections.get('cargos-e-vagas',{}).get('text','') or '') + '\n' + all_text))
    facts['cronograma'].update({'events':extract_timeline_events((sections.get('cronograma',{}).get('text','') or '') + '\n' + all_text)})
    facts['provas-e-etapas'].update(extract_exam_facts(sections.get('provas-e-etapas',{}).get('text','') or all_text))
    facts['retificacoes'].update({'changes':extract_changes(sections.get('retificacoes',{}).get('text','') or all_text)})
    facts['recursos'].update({'summary_items':extract_bullets(sections.get('recursos',{}).get('text',''), ['recurso','email','protocolo','gabarito'], 8)})
    facts['requisitos'].update({'summary_items':extract_bullets(sections.get('requisitos',{}).get('text',''), ['requisito','posse','documento','nomeação','investidura'], 8)})
    facts['conteudo-programatico'].update({'summary_items':extract_bullets(sections.get('conteudo-programatico',{}).get('text',''), ['conteúdo','conhecimentos','disciplina','cargo:'], 10)})
    return facts

def llm_topic_facts(sections: dict, deterministic: dict, identity: dict, model_id: str) -> tuple[dict,dict]:
    report={'model_id':model_id,'topics':{},'llm_available':False,'used_topics':0,'errors':[]}
    out={}
    # Teste rápido: se falhar, não tenta 9 chamadas longas.
    try:
        test=complete('Responda em JSON: {"ok":true}', model_id=model_id, system='Teste.', temperature=0, timeout=45, json_mode=True)
        if extract_json(test,{}).get('ok') is True or 'ok' in test.lower(): report['llm_available']=True
    except Exception as e:
        report['errors'].append(f'LLM indisponível: {e}')
        return {}, report
    for key,spec in TOPICS.items():
        material=select_evidence_excerpt((sections.get(key) or {}).get('text',''), key, limit=3800)
        prompt=topic_json_prompt(key, spec['title'], material, deterministic.get(key,{}), identity)
        try:
            ans=complete(prompt, model_id=model_id, system='Você é um extrator/curador de fatos para uma LLM Wiki de concursos públicos. Responda apenas JSON válido.', temperature=0.02, timeout=360, json_mode=True)
            data=extract_json(ans,{})
            if isinstance(data,dict) and data:
                data['source']='llm_topic_extractor'; data['topic']=key
                out[key]=data; report['topics'][key]={'ok':True,'chars':len(ans)}; report['used_topics']+=1
            else:
                report['topics'][key]={'ok':False,'error':'JSON vazio'}
        except Exception as e:
            report['topics'][key]={'ok':False,'error':str(e)}
    return out, report

def topic_json_prompt(key: str, title: str, material: str, det: dict, identity: dict) -> str:
    contract=PAGE_CONTRACTS.get(key,'Extraia fatos úteis para uma wiki de concursos.')
    schemas={
        'cargos-e-vagas': '{"summary":"...","positions":[{"name":"Gari","vacancies":"02 + CR","workload":"40h","salary":"R$ 1.713,34","requirement":"Ensino Fundamental incompleto","source":"p. 4"}],"total_vacancies":"...","salary_min":"...","salary_max":"...","warnings":[]}',
        'inscricoes': '{"summary":"...","registration_start":"DD/MM/AAAA","registration_end":"DD/MM/AAAA","method":"site/presencial/...","fee":"gratuito ou R$...","fee_min":"...","fee_max":"...","payment":"...","exemption":"...","warnings":[]}',
        'cronograma': '{"summary":"...","events":[{"label":"Período de inscrições","date":"08/06/2026 a 22/06/2026","type":"inscrição","source":"p. 5"}],"warnings":[]}',
        'provas-e-etapas': '{"summary":"...","exam_date":"DD/MM/AAAA","exam_type":"prova objetiva/prática","rules":["..."],"subjects":["..."],"warnings":[]}',
        'dados-principais': '{"summary":"...","title":"...","institution":"...","organizer":"...","city":"...","state":"UF","status":"suspenso|prorrogado|retificado|cancelado|indefinido","warnings":[]}',
        'retificacoes': '{"summary":"...","changes":[{"type":"suspensão/prorrogação/errata","date":"...","impact":"...","source":"p. 1"}],"warnings":[]}'
    }
    schema=schemas.get(key, '{"summary":"...","items":["..."],"warnings":[]}')
    return f"""
Você está construindo uma LLM Wiki de editais de concursos públicos.
Página/tópico: {title}
Contrato do tópico: {contract}

REGRAS GERAIS:
- Não copie o PDF inteiro.
- Extraia apenas fatos pertencentes ao tópico.
- Se não houver certeza, deixe null ou adicione em warnings.
- Não trate texto jurídico, decreto, conteúdo programático ou regra de candidato como cargo.
- Não trate data de lei/decreto/CNPJ/CEP como cronograma.
- Não trate auxílio/taxa/nota/pontuação como salário.
- Não trate inscrição cancelada como concurso cancelado.
- Preserve fontes como p. X quando existirem.

Identidade detectada inicialmente:
{json.dumps(identity, ensure_ascii=False, indent=2)}

Fatos determinísticos preliminares:
{json.dumps(det, ensure_ascii=False, indent=2)[:3500]}

Formato JSON esperado:
{schema}

Material recuperado do edital:
{material[:3800]}

Responda SOMENTE JSON válido.
""".strip()

def merge_topic_facts(det: dict, llm: dict) -> dict:
    merged=json.loads(json.dumps(det, ensure_ascii=False))
    for k,v in (llm or {}).items():
        base=merged.get(k,{})
        # Listas importantes: preferir LLM se tiver conteúdo, senão determinístico.
        for key,val in v.items():
            if val in [None,'',[],{}]: continue
            if key in ['positions','events','changes','items','rules','summary_items'] and isinstance(val,list) and len(val)>0:
                base[key]=val
            elif key == 'summary' and isinstance(val,str) and len(val)>20:
                base[key]=val
            elif key not in ['source','topic']:
                base[key]=val
        base['confidence']=max(float(base.get('confidence') or 0.35), float(v.get('confidence') or 0.72))
        base['source']='merged_llm' if v else base.get('source')
        merged[k]=base
    # Normalizar posições e eventos depois da fusão.
    merged['cargos-e-vagas']['positions']=normalize_positions(merged.get('cargos-e-vagas',{}).get('positions',[]))
    merged['cronograma']['events']=normalize_events(merged.get('cronograma',{}).get('events',[]))
    return merged

# ---------------------------------------------------------------------
# Extratores determinísticos robustos, não perfeitos
# ---------------------------------------------------------------------

def normalize_pt_date(day: str, month: str, year: str) -> str | None:
    months={'janeiro':1,'fevereiro':2,'março':3,'marco':3,'abril':4,'maio':5,'junho':6,'julho':7,'agosto':8,'setembro':9,'outubro':10,'novembro':11,'dezembro':12}
    m=months.get((month or '').lower())
    if not m: return None
    return f"{int(day):02d}/{m:02d}/{year}"

def extract_registration_facts(text: str) -> dict:
    low=text.lower(); out={'summary_items':extract_bullets(text,['inscrição','taxa','isenção','pagamento','site'],10)}
    dates=re.findall(r'\b\d{1,2}/\d{1,2}/\d{4}\b', text)
    # Buscar frase de inscrições com duas datas.
    m=re.search(r'inscri[çc][õo]es?.{0,180}?(\d{1,2}/\d{1,2}/\d{4}).{0,120}?(\d{1,2}/\d{1,2}/\d{4})', text, re.I|re.S)
    if m: out['registration_start'], out['registration_end']=m.group(1), m.group(2)
    # Prorrogação costuma aparecer em comunicado/errata e deve vencer o prazo inicial.
    pr=re.search(r'inscri[çc][õo]es?.{0,120}prorrogad[ao]s?.{0,120}(?:at[ée]|dia)\s+(\d{1,2}/\d{1,2}/\d{4})', text, re.I|re.S)
    if pr:
        out['registration_end']=pr.group(1)
    pr2=re.search(r'inscri[çc][õo]es?.{0,120}prorrogad[ao]s?.{0,120}(?:at[ée]|dia)\s+(\d{1,2})\s+de\s+([a-zçã]+)\s+de\s+(\d{4})', text, re.I|re.S)
    if pr2:
        out['registration_end']=normalize_pt_date(pr2.group(1), pr2.group(2), pr2.group(3))
    if 'gratuit' in low:
        out['fee']='gratuito'; out['fee_min']=0; out['fee_max']=0
        return out
    # Taxa de inscrição deve vir em contexto de taxa/valor/escolaridade, nunca de salário/remuneração.
    fee_windows=[]
    for mtx in re.finditer(r'(taxa de inscri[çc][aã]o|valor(?:es)? correspondentes|escolaridade exigida|valor r\$)', text, re.I):
        fee_windows.append(text[mtx.start():mtx.start()+900])
    fee_text='\n'.join(fee_windows) if fee_windows else ''
    fees=[v for v in parse_money_values(fee_text) if v is not None and 0 <= v <= 500]
    if fees:
        out['fee_min'], out['fee_max']=min(fees), max(fees)
        out['fee']=money_fmt(max(fees)) if min(fees)==max(fees) else f'{money_fmt(min(fees))} a {money_fmt(max(fees))}'
    return out

def parse_money_values(text: str) -> list[float]:
    vals=[]
    for m in re.finditer(r'R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,\d{2}|[0-9]+,\d{2})', text):
        try: vals.append(float(m.group(1).replace('.','').replace(',','.')))
        except Exception: pass
    return vals

def extract_positions_facts(text: str) -> dict:
    positions=[]
    # Pattern A: linha ou sequência: Nº CBO CARGO ... 40 H 2 R$ 880,00
    # Trabalhar em janelas para capturar nomes quebrados.
    lines=[l.strip() for l in text.splitlines() if l.strip()]
    joined='\n'.join(lines)
    # Caso simples: cabeçalho em colunas seguido de linhas tipo: Gari 02 + CR 40h R$ ... Ensino...
    simple=re.finditer(r'(?P<name>Gari|Motorista|Operador de Máquinas|Operador De Maquinas|[A-ZÁÉÍÓÚÀÃÕÂÊÔÇ][A-Za-zÁÉÍÓÚÀÃÕÂÊÔÇ ]{3,60})\s+(?P<vagas>\d{1,3}\s*(?:\+\s*CR|CR)?)\s+(?P<workload>\d{1,2}\s*h)\s+(?P<salary>R\$\s*[\d\.]+,\d{2})(?P<req>[^\n]{0,160})', joined, re.I)
    for m in simple:
        add_position(positions, {'name':m.group('name'), 'vacancies':m.group('vagas'), 'workload':m.group('workload'), 'salary':m.group('salary'), 'requirement':m.group('req').strip(), 'source':source_near(joined,m.start())})
    # Caso Parintins: número + CBO + cargo multiline + requisito + carga + vagas + salário.
    pattern=re.compile(r'(?:^|\n)(?P<num>\d{1,3}(?:\s*-?A)?)\s+(?P<cbo>\d{3,4}\s*-\s*\d{2}|\d{4})\s+(?P<body>.{20,900}?)(?P<workload>\d{1,2}\s*H)\s+(?P<vagas>\d{1,4}|CR)\s+(?:-|CR|\d+)?\s*(?P<salary>R\$\s*[\d\.]+,\d{2})', re.I|re.S)
    for m in pattern.finditer(joined):
        body=clean_inline(m.group('body'))
        name=guess_position_name(body)
        req=body.replace(name,'',1).strip(' -–—.,;:') if name else ''
        add_position(positions, {'number':m.group('num').replace(' ',''), 'cbo':clean_inline(m.group('cbo')), 'name':name, 'vacancies':m.group('vagas'), 'workload':m.group('workload').upper(), 'salary':m.group('salary'), 'requirement':req[:220], 'source':source_near(joined,m.start())})
    positions=normalize_positions(positions)
    salaries=[money_to_float(p.get('salary')) for p in positions if money_to_float(p.get('salary')) is not None]
    total=extract_total_vacancies(text, positions)
    return {'positions':positions, 'positions_count':len(positions), 'total_vacancies':total, 'salary_min':min(salaries) if salaries else None, 'salary_max':max(salaries) if salaries else None, 'summary_items':extract_bullets(text,['total de vagas','nível fundamental','nível médio','nível superior','salário'],8)}

def source_near(text: str, idx: int) -> str:
    before=text[max(0,idx-120):idx]
    m=list(re.finditer(r'\[p\.\s*(\d+)\]', before, re.I))
    return f"p. {m[-1].group(1)}" if m else ''

def clean_inline(s: str) -> str:
    return re.sub(r'\s+',' ',s or '').strip(' -–—.,;:')

def guess_position_name(body: str) -> str:
    b=clean_inline(body)
    # Divide antes de escolaridade/requisito.
    cut=re.split(r'\b(Ensino|Curso|Gradua[çc][ãa]o|Superior|Médio|Fundamental|Formação|Carteira|Registro|Licenciatura)\b', b, maxsplit=1, flags=re.I)[0].strip()
    # Remove sobras iniciais genéricas.
    cut=re.sub(r'^(CARGOS? DE [A-ZÁÉÍÓÚÀÃÕÂÊÔÇ ]+|CADASTRO DE RESERVA|PcD\*)\s+', '', cut, flags=re.I)
    return title_case(cut) if valid_position_name(cut) else ''

def valid_position_name(name: str) -> bool:
    if not name or len(name)<3 or len(name)>120: return False
    low=name.lower()
    bad=['deverá','poderá','candidato','inscrição','documento','edital','decreto','lei','conteúdo','programático','cadastro de reserva','salário','remuneração','vagas','requisito']
    if any(b in low for b in bad): return False
    if len(re.findall(r'[A-Za-zÁÉÍÓÚÀÃÕÂÊÔÇáéíóúàãõâêôç]', name)) < 3: return False
    return True

def add_position(out: list, p: dict):
    name=clean_inline(p.get('name',''))
    if not valid_position_name(name): return
    p['name']=title_case(name)
    out.append(p)

def normalize_positions(pos: list) -> list:
    out=[]; seen=set()
    if not isinstance(pos,list): return []
    for p in pos:
        if isinstance(p,str): p={'name':p}
        if not isinstance(p,dict): continue
        name=clean_inline(p.get('name') or p.get('cargo') or p.get('função') or '')
        if not valid_position_name(name): continue
        salary=p.get('salary') or p.get('remuneracao') or p.get('remuneração') or p.get('vencimento')
        vac=p.get('vacancies') or p.get('vagas') or p.get('vaga')
        key=(name.lower(),str(vac),str(salary))
        if key in seen: continue
        seen.add(key)
        out.append({'number':p.get('number') or p.get('nº') or p.get('n'), 'name':title_case(name), 'vacancies':vac, 'workload':p.get('workload') or p.get('carga_horaria') or p.get('carga horária'), 'salary':salary, 'requirement':p.get('requirement') or p.get('requisito') or p.get('escolaridade'), 'source':p.get('source') or p.get('fonte')})
    return out[:250]

def money_to_float(x):
    if x is None or isinstance(x,(int,float)): return x
    m=re.search(r'([0-9]{1,3}(?:\.[0-9]{3})*,\d{2}|[0-9]+,\d{2})', str(x))
    if not m: return None
    try: return float(m.group(1).replace('.','').replace(',','.'))
    except Exception: return None

def extract_total_vacancies(text: str, positions: list) -> int | None:
    m=re.search(r'TOTAL\s+(?:GERAL\s+)?DE\s+VAGAS(?:\s+PARA\s+O\s+CONCURSO\s+P[ÚU]BLICO)?\s+([0-9\.]+)', text, re.I)
    if m:
        try: return int(m.group(1).replace('.',''))
        except Exception: pass
    nums=[]
    for p in positions:
        v=str(p.get('vacancies') or '')
        m=re.search(r'\d+', v)
        if m: nums.append(int(m.group()))
    return sum(nums) if nums else None

def extract_timeline_events(text: str) -> list[dict[str,Any]]:
    events=[]
    for m in re.finditer(r'(.{0,120}?)(\d{1,2}/\d{1,2}/\d{4})(?:\s*(?:a|até|à|-)\s*(\d{1,2}/\d{1,2}/\d{4}))?(.{0,80})', text, re.I|re.S):
        ctx=clean_inline(m.group(1)+' '+m.group(4))
        low=ctx.lower()
        if any(b in low for b in BAD_DATE_CTX): continue
        typ=None
        # Ordem importa: gabarito/recurso/resultado não podem virar prova só porque mencionam prova no contexto.
        if 'gabarito' in low: typ='gabarito'
        elif 'recurso' in low: typ='recurso'
        elif 'resultado' in low or 'classifica' in low: typ='resultado'
        elif 'homolog' in low: typ='homologação'
        elif 'pagamento' in low or 'boleto' in low: typ='pagamento'
        elif 'isen' in low: typ='isenção'
        elif 'inscri' in low: typ='inscrição'
        elif 'prova' in low:
            # Só aceita prova quando o contexto fala de aplicação/realização/data prevista.
            if re.search(r'(prova objetiva|provas serão aplicadas|provas ser[aã]o realizadas|data prevista para aplica|realiza[çc][aã]o da prova|aplica[çc][aã]o da prova|data da prova)', low):
                typ='prova'
        if not typ: continue
        if typ == 'prova' and re.search(r'(gabarito|recurso|resultado|t[íi]tulo|classifica[çc][aã]o|entrega dos t[íi]tulos|pontua[çc][aã]o final)', low):
            continue
        label=make_event_label(ctx, typ)
        events.append({'label':label,'start':m.group(2),'end':m.group(3),'date':m.group(2)+((' a '+m.group(3)) if m.group(3) else ''),'type':typ,'source':source_near(text,m.start())})
    return normalize_events(events)

def make_event_label(ctx: str, typ: str) -> str:
    if typ=='inscrição': return 'Período de inscrições'
    if typ=='prova': return 'Aplicação da prova'
    if typ=='pagamento': return 'Pagamento da taxa/boleto'
    return title_case(typ)

def normalize_events(events: list) -> list:
    out=[]; seen=set()
    if not isinstance(events,list): return []
    for e in events:
        if not isinstance(e,dict): continue
        label=clean_inline(e.get('label') or e.get('event') or e.get('evento') or e.get('type') or '')
        date=e.get('date') or e.get('start') or e.get('data')
        if not label or not date: continue
        key=(label.lower(),str(date))
        if key in seen: continue
        seen.add(key)
        out.append({'label':label,'date':date,'start':e.get('start') or date,'end':e.get('end'),'type':e.get('type'),'source':e.get('source') or e.get('fonte')})
    return out[:80]

def extract_exam_facts(text: str) -> dict:
    out={'rules':extract_bullets(text,['prova','questões','pontuação','documento','caneta','horário'],10)}
    m=re.search(r'prova(?:s)?[^\n\.]{0,150}?(\d{1,2}/\d{1,2}/\d{4})', text, re.I|re.S)
    if m: out['exam_date']=m.group(1)
    if 'prova prática' in text.lower(): out['exam_type']='prova prática'
    elif 'prova objetiva' in text.lower(): out['exam_type']='prova objetiva'
    return out

def extract_changes(text: str) -> list[dict[str,str]]:
    out=[]
    for typ in ['suspensão','prorrogação','errata','retificação']:
        for b in extract_bullets(text,[typ],3): out.append({'type':typ,'impact':b})
    return out[:10]

def extract_bullets(text: str, terms: list[str], limit: int) -> list[str]:
    pieces=[]
    for sent in re.split(r'(?<=[\.\;])\s+|\n+', text or ''):
        s=clean_inline(sent)
        if len(s)<25 or len(s)>420: continue
        low=s.lower()
        if any(t.lower() in low for t in terms): pieces.append(s)
    # manter diversidade
    seen=set(); out=[]
    for p in pieces:
        k=p[:90].lower()
        if k in seen: continue
        seen.add(k); out.append(p)
        if len(out)>=limit: break
    return out


def build_evidence_cards(facts: dict, sections: dict) -> list[dict[str,Any]]:
    """Transforma fatos estruturados em cartões de conhecimento auditáveis.
    A base de conhecimento final não é só source.md; estes cards são a camada intermediária da LLM Wiki.
    """
    cards=[]
    for topic, fact in (facts or {}).items():
        pages=(sections.get(topic) or {}).get('pages', [])
        if topic == 'cargos-e-vagas':
            for p in (fact.get('positions') or [])[:300]:
                cards.append({'topic':topic,'type':'cargo','title':p.get('name'),'data':p,'source_pages':pages,'confidence':fact.get('confidence',0.5)})
        elif topic == 'cronograma':
            for ev in (fact.get('events') or [])[:120]:
                cards.append({'topic':topic,'type':'evento','title':ev.get('label') or ev.get('type'),'data':ev,'source_pages':pages,'confidence':fact.get('confidence',0.5)})
        elif topic == 'retificacoes':
            for ch in (fact.get('changes') or [])[:80]:
                cards.append({'topic':topic,'type':'alteracao','title':ch.get('type') if isinstance(ch,dict) else 'alteração','data':ch,'source_pages':pages,'confidence':fact.get('confidence',0.5)})
        else:
            compact={k:v for k,v in fact.items() if k not in {'topic','source'} and v not in [None,'',[],{}]}
            if compact:
                cards.append({'topic':topic,'type':'fato_topico','title':TOPICS.get(topic,{}).get('title',topic),'data':compact,'source_pages':pages,'confidence':fact.get('confidence',0.5)})
    return cards

def build_wiki_plan(facts: dict, sections: dict, identity: dict) -> dict[str,Any]:
    plan={}
    for key,spec in TOPICS.items():
        guide=WIKI_PAGE_GUIDE.get(key,{})
        fact=facts.get(key,{})
        pages=(sections.get(key) or {}).get('pages', [])
        completeness=[]
        if key == 'cargos-e-vagas':
            completeness.append(f"{len(fact.get('positions') or [])} cargos estruturados")
            if not fact.get('positions'): completeness.append('quadro de cargos precisa de revisão')
        if key == 'cronograma':
            completeness.append(f"{len(fact.get('events') or [])} eventos estruturados")
        if key == 'inscricoes':
            completeness.append('período identificado' if fact.get('registration_start') or fact.get('registration_end') else 'período não consolidado')
        plan[key]={
            'title':spec['title'],
            'purpose':guide.get('role','organizar conhecimento do edital'),
            'required_sections':guide.get('sections',[]),
            'must_cover':guide.get('must',[]),
            'must_not_include':guide.get('not',[]),
            'source_pages':pages,
            'known_completeness':completeness,
            'writing_policy':'escrever como guia interpretado para candidato; fatos primeiro; evidências como apoio; nunca despejar source.md',
        }
    return plan

def select_evidence_excerpt(text: str, key: str, limit: int = 7000) -> str:
    """Reduz evidências brutas para não induzir a LLM a copiar páginas inteiras."""
    if not text: return ''
    terms = TOPICS.get(key,{}).get('terms', [])
    pieces=[]
    for block in re.split(r'\n\s*\n+', text):
        b=clean_text(block)
        if len(b) < 40: continue
        low=b.lower()
        if terms and not any(t in low for t in terms[:12]): continue
        # remove blocos enormes que parecem dump completo
        if len(b) > 1100: b=b[:1100].rstrip()+'...'
        pieces.append(b)
        if sum(len(x) for x in pieces) > limit: break
    return '\n\n'.join(pieces)[:limit]

# ---------------------------------------------------------------------
# Escrita da wiki real
# ---------------------------------------------------------------------
def build_true_wiki_pages(facts: dict, sections: dict, identity: dict, model_id: str, llm_report: dict, wiki_plan: dict | None = None) -> tuple[dict,str]:
    pages={}
    report={'llm_pages':0,'fallback_pages':0,'scores':{},'issues':[], 'editorial_mode':'v20_microcopy_template_renderer'}
    wiki_plan = wiki_plan or build_wiki_plan(facts, sections, identity)
    pages['MASTER.md']=write_master_page(facts, identity, model_id, llm_report, report)
    for key,spec in TOPICS.items():
        pages[spec['file']]=write_topic_page(key, spec, facts.get(key,{}), sections.get(key,{}), model_id, llm_report, report, wiki_plan.get(key,{}))
    pages['fontes.md']=write_sources_page(sections, facts)
    return pages, report

def write_master_page(facts: dict, identity: dict, model_id: str, llm_report: dict, report: dict) -> str:
    schema_preview={'identity':identity,'inscricoes':facts.get('inscricoes',{}),'cargos':summary_positions(facts.get('cargos-e-vagas',{}).get('positions',[])),'cronograma':facts.get('cronograma',{}).get('events',[])[:8],'retificacoes':facts.get('retificacoes',{})}
    if llm_report.get('llm_available'):
        prompt=f"""
Escreva o MASTER.md de uma LLM Wiki de edital de concurso público.
A página deve parecer escrita por um editor humano para candidatos.
Não copie texto bruto. Explique o edital, situação, inscrições, cargos, provas, retificações e como navegar na wiki.
Use Markdown. Comece com # {identity.get('title') or 'Edital'}.
Se um dado estiver incerto, diga 'não identificado com segurança'.

Fatos disponíveis:
{json.dumps(schema_preview, ensure_ascii=False, indent=2)[:12000]}
"""
        try:
            md=complete(prompt, model_id=model_id, system='Você é editor-chefe de uma LLM Wiki de concursos públicos.', temperature=0.05, timeout=360)
            if score_page(md)>55: report['llm_pages']+=1; return ensure_sources(md, [])
        except Exception as e: report['issues'].append(f'MASTER via LLM falhou: {e}')
    report['fallback_pages']+=1
    return deterministic_master(facts, identity, llm_report)

def write_topic_page(key: str, spec: dict, fact: dict, section: dict, model_id: str, llm_report: dict, report: dict, page_plan: dict | None = None) -> str:
    """Renderiza a página como LLM Wiki estável.

    A v19 pedia para modelos 7B/8B escreverem páginas inteiras com prompts enormes.
    Isso fazia o modelo copiar texto bruto ou colapsar. Na v20, Python monta a página
    com fatos determinísticos/estruturados e a LLM só escreve microcopy curta
    (introdução e orientação). Assim o resultado fica mais previsível e ainda ganha
    linguagem editorial.
    """
    pages = section.get('pages') or []
    # Página-base sempre vem de fatos estruturados + templates. Nunca de dump de PDF.
    md = deterministic_topic_page(key, spec, fact, section)

    micro = None
    if llm_report.get('llm_available') and model_id:
        try:
            micro = generate_microcopy(key, spec, fact, pages, model_id)
        except Exception as e:
            report['issues'].append(f'{key}: microcopy LLM falhou: {e}')
            micro = None

    if micro:
        md = apply_microcopy_to_page(md, micro)
        report['llm_pages'] += 1
        report['scores'][key] = score_editorial_page(md, key)
        return ensure_sources(sanitize_wiki_markdown(md, spec['title']), pages)

    report['fallback_pages'] += 1
    report['scores'][key] = score_editorial_page(md, key)
    return ensure_sources(sanitize_wiki_markdown(md, spec['title']), pages)


def compact_facts_for_microcopy(key: str, fact: dict) -> dict:
    """Reduz fatos para caber em prompts pequenos de modelos 7B/8B."""
    f = fact or {}
    if key == 'cargos-e-vagas':
        positions = f.get('positions') or []
        return {
            'summary': f.get('summary'),
            'total_vacancies': f.get('total_vacancies'),
            'salary_min': f.get('salary_min'),
            'salary_max': f.get('salary_max'),
            'positions_count': len(positions),
            'examples': positions[:8],
            'warnings': as_list(f.get('warnings'))[:5],
        }
    if key == 'cronograma':
        return {
            'summary': f.get('summary'),
            'events_count': len(f.get('events') or []),
            'events': (f.get('events') or [])[:10],
            'warnings': as_list(f.get('warnings'))[:5],
        }
    if key == 'inscricoes':
        return {k: f.get(k) for k in ['summary','registration_start','registration_end','method','fee','payment','exemption','warnings'] if f.get(k) not in [None,'',[],{}]}
    if key == 'dados-principais':
        return {k: f.get(k) for k in ['summary','title','institution','organizer','city','state','status','warnings'] if f.get(k) not in [None,'',[],{}]}
    if key == 'provas-e-etapas':
        return {'summary': f.get('summary'), 'exam_date': f.get('exam_date'), 'exam_type': f.get('exam_type'), 'rules': (f.get('rules') or [])[:8], 'subjects': (f.get('subjects') or [])[:8], 'warnings': as_list(f.get('warnings'))[:5]}
    if key == 'retificacoes':
        return {'summary': f.get('summary'), 'changes': (f.get('changes') or [])[:8], 'warnings': as_list(f.get('warnings'))[:5]}
    return {'summary': f.get('summary'), 'items': (f.get('items') or f.get('summary_items') or f.get('rules') or [])[:10], 'warnings': as_list(f.get('warnings'))[:5]}


def generate_microcopy(key: str, spec: dict, fact: dict, pages: list[int], model_id: str) -> dict | None:
    guide = WIKI_PAGE_GUIDE.get(key, {})
    compact = compact_facts_for_microcopy(key, fact)
    # Prompt propositalmente pequeno: tarefa compatível com Qwen/Llama/Mistral 7B/8B.
    prompt = f"""
Você é microeditor de uma LLM Wiki de concursos públicos.
Não escreva a página inteira. Escreva apenas textos curtos para encaixar em um template Python.

TÓPICO: {spec['title']}
FUNÇÃO DA PÁGINA: {guide.get('role', PAGE_CONTRACTS.get(key, 'organizar informação do edital'))}
DEFINIÇÃO: {PAGE_CONTRACTS.get(key, 'Informação temática do edital.')}

FATOS ESTRUTURADOS, JÁ VALIDADOS:
{json.dumps(compact, ensure_ascii=False, indent=2)[:3200]}

Responda SOMENTE JSON válido neste formato:
{{
  "intro": "3 a 5 frases explicando o tema para o candidato, sem copiar o edital.",
  "interpretation": "2 a 4 frases sobre como interpretar os dados desta página.",
  "attention": ["até 3 pontos de atenção práticos, sem inventar dados"]
}}

Regras:
- Não invente datas, cargos, vagas ou valores.
- Não copie listas inteiras.
- Não use markdown.
- Se faltar informação, diga que não foi identificada com segurança.
""".strip()
    ans = complete(
        prompt,
        model_id=model_id,
        system='Você escreve microtextos curtos e seguros para uma LLM Wiki. Responda só JSON.',
        temperature=0.08,
        timeout=120,
        json_mode=True,
    )
    data = extract_json(ans, {})
    if not isinstance(data, dict):
        return None
    intro = clean_text(str(data.get('intro') or ''))
    interpretation = clean_text(str(data.get('interpretation') or ''))
    attention = data.get('attention') or []
    if isinstance(attention, str):
        attention = [attention]
    attention = [clean_text(str(x)) for x in attention if clean_text(str(x))][:3]
    # Aceitar somente se realmente veio microcopy curta, não página inteira/dump.
    if not intro or len(intro) < 70 or len(intro) > 900:
        return None
    if '```' in intro or 'trechos recuperados' in intro.lower() or 'texto extraído' in intro.lower():
        return None
    return {'intro': intro, 'interpretation': interpretation[:700], 'attention': attention, 'source_pages': pages[:20]}


def apply_microcopy_to_page(md: str, micro: dict) -> str:
    intro = micro.get('intro') or ''
    interpretation = micro.get('interpretation') or ''
    attention = micro.get('attention') or []
    # Substitui apenas a introdução da seção Visão geral; o restante continua templateado.
    if intro and '## Visão geral' in md:
        md = re.sub(r'(## Visão geral\n\n)(.*?)(\n\n## )', lambda m: m.group(1) + intro + m.group(3), md, count=1, flags=re.S)
    if interpretation and '## Leitura editorial' not in md:
        insert = f'\n\n## Leitura editorial\n\n{interpretation}\n'
        if '\n\n## Pontos de atenção' in md:
            md = md.replace('\n\n## Pontos de atenção', insert + '\n## Pontos de atenção', 1)
        elif '\n\n## Fontes usadas' in md:
            md = md.replace('\n\n## Fontes usadas', insert + '\n## Fontes usadas', 1)
        else:
            md += insert
    if attention:
        bullets = '\n'.join('- ' + safe_md_cell(x, 240) for x in attention)
        if '## Pontos de atenção' in md:
            md = re.sub(r'(## Pontos de atenção\n)(.*?)(\n\n## Fontes usadas|$)', lambda m: m.group(1) + bullets + m.group(3), md, count=1, flags=re.S)
    return md

def sanitize_wiki_markdown(md: str, title: str) -> str:
    md=(md or '').strip()
    md=re.sub(r'^```(?:markdown)?\s*', '', md, flags=re.I).strip()
    md=re.sub(r'\s*```$', '', md, flags=re.I).strip()
    md=md.replace('```markdown','').replace('```','').strip()
    if not md.startswith('#'):
        md=f'# {title}\n\n'+md
    # Remove títulos duplicados comuns de resposta de chatbot.
    md=re.sub(r'(?im)^\s*(aqui está|segue)\b.*$', '', md).strip()
    return md.strip()+"\n"

def score_editorial_page(md: str, key: str) -> int:
    if not md: return 0
    low=md.lower(); score=25
    score += min(25, len(md)//160)
    score += 12 if md.startswith('#') else 0
    score += 12 if md.count('\n## ') >= 3 else 0
    score += 8 if '## fontes usadas' in low else 0
    score += 8 if any(w in low for w in ['visão geral','como interpretar','pontos de atenção','o candidato']) else 0
    score -= 25 if 'trechos recuperados' in low or 'texto extraído' in low or 'material bruto' in low else 0
    score -= 25 if '```' in md else 0
    score -= 20 if re.search(r'\[p\.\s*\d+\].{180,}', md, re.I) else 0
    score -= 15 if len(md) < 650 else 0
    if key == 'cargos-e-vagas':
        score += 10 if '| Cargo' in md or 'cargo' in low and 'vaga' in low else 0
        score -= 20 if re.search(r'cargo[^\n]{0,100}(deverá|devera|comparecer|documento|defici[eê]ncia)', low) else 0
    if key == 'cronograma':
        score += 8 if 'evento' in low and ('data' in low or 'período' in low) else 0
        score -= 12 if re.search(r'lei n[ºo]|decreto|portaria|cnpj|cep', low[:2500]) else 0
    return max(0, min(100, score))

def repair_wiki_page(md: str, key: str, spec: dict, fact: dict, material: str, pages: list[int], guide: dict, model_id: str) -> str | None:
    prompt=f"""
A página abaixo falhou como LLM Wiki porque parece dump, curta ou pouco interpretada.
Reescreva como página editorial de wiki para candidato.

PÁGINA: {spec['title']}
FUNÇÃO: {guide.get('role','organizar conhecimento do edital')}
SEÇÕES: {', '.join(guide.get('sections', ['Visão geral','Informações principais','Pontos de atenção','Fontes usadas']))}
NÃO PERTENCE: {', '.join(guide.get('not', []))}

FATOS ESTRUTURADOS:
{json.dumps(fact, ensure_ascii=False, indent=2)[:9000]}

PÁGINA FRACA:
{md[:7000]}

EVIDÊNCIAS DE APOIO, NÃO COPIAR:
{material[:5000]}

Regras: não copie texto cru, não use ```markdown, explique o que significa, escreva para candidato e finalize com fontes: {', '.join('p. '+str(p) for p in pages) or 'não identificadas'}.
"""
    try:
        out=complete(prompt, model_id=model_id, system='Você reescreve páginas ruins de LLM Wiki em páginas editoriais úteis.', temperature=0.03, timeout=360)
        return sanitize_wiki_markdown(out, spec['title'])
    except Exception:
        return None

def ensure_sources(md: str, pages: list[int]) -> str:
    if '## Fontes usadas' not in md:
        md += '\n\n## Fontes usadas\n' + (', '.join(f'p. {p}' for p in pages) if pages else 'Não identificadas com segurança.')
    return md.strip()+'\n'

def score_page(md: str) -> int:
    if not md: return 0
    score=30
    score+=min(30, len(md)//120)
    score+=10 if md.count('## ')>=3 else 0
    score+=10 if 'não identificado com segurança' in md.lower() or 'Fontes usadas' in md else 0
    score-=20 if len(md)<500 else 0
    score-=20 if md.count('[p.')>10 and len(md)<2500 else 0
    return max(0,min(100,score))

def deterministic_master(facts, identity, llm_report):
    pos=facts.get('cargos-e-vagas',{}).get('positions',[]); events=facts.get('cronograma',{}).get('events',[])
    ins=facts.get('inscricoes',{})
    note='A LLM não respondeu durante a indexação; esta é uma versão degradada, gerada por recuperação e regras. Ative Ollama/Groq para gerar a wiki editorial completa.' if not llm_report.get('llm_available') else ''
    return f"""# {identity.get('title') or 'Edital'}

## Visão geral

Esta wiki organiza o edital em páginas temáticas para facilitar a leitura por candidatos. O objetivo é transformar o PDF em uma base de conhecimento navegável, com fontes e indicação de incertezas.

{note}

## Identificação do edital

- **Instituição:** {identity.get('institution') or 'não identificada com segurança'}
- **Localidade:** {identity.get('city') or '—'} / {identity.get('state') or '—'}
- **Organização/banca:** {identity.get('organizer') or 'não identificada com segurança'}
- **Status:** {identity.get('status') or 'indefinido'}

## Principais informações recuperadas

- **Inscrições:** {ins.get('registration_start') or 'não identificado'} a {ins.get('registration_end') or 'não identificado'}
- **Taxa:** {ins.get('fee') or 'não identificada com segurança'}
- **Cargos estruturados:** {len(pos)}
- **Eventos de cronograma:** {len(events)}

## Como navegar

Use as páginas **Inscrições**, **Cargos e vagas**, **Cronograma**, **Provas e etapas**, **Recursos** e **Retificações** para consultar o edital por tema. Quando a wiki não tiver segurança, ela mostra a pendência em vez de publicar um dado como verdade.
"""

def deterministic_topic_page(key, spec, fact, section):
    """Modo sem LLM: ainda escreve como mini-wiki, não como dump de texto."""
    title=spec['title']; pages=section.get('pages') or []
    guide=WIKI_PAGE_GUIDE.get(key,{})
    body=[f'# {title}', '', '## Visão geral', '', human_intro_for_topic(key, title, fact), '']
    if key=='cargos-e-vagas': body += render_positions_md(fact.get('positions',[]), fact)
    elif key=='cronograma': body += render_events_md(fact.get('events',[]))
    elif key=='inscricoes': body += render_registration_md(fact)
    elif key=='dados-principais': body += render_identity_md(fact)
    elif key=='provas-e-etapas': body += render_exam_md(fact)
    elif key=='retificacoes': body += render_changes_md(fact)
    else: body += render_items_md(fact, key)
    body += ['', '## Pontos de atenção']
    body += deterministic_attention_points(key, fact)
    body += ['', '## Fontes usadas', ', '.join(f'p. {p}' for p in pages) if pages else 'Não identificadas com segurança.']
    return '\n'.join(body).strip()+'\n'

def human_intro_for_topic(key: str, title: str, fact: dict) -> str:
    if fact.get('summary') and len(str(fact.get('summary'))) > 40:
        return str(fact.get('summary')).strip()
    intros={
        'dados-principais':'Esta página funciona como a porta de entrada da wiki. Ela identifica o edital, o órgão responsável, a banca e a situação atual do certame antes das páginas específicas.',
        'inscricoes':'Esta página traduz as regras de inscrição para uma leitura prática: período, forma de inscrição, taxa, pagamento e pontos que podem impedir a participação do candidato.',
        'cargos-e-vagas':'Esta página organiza as oportunidades do edital. Em concursos, cargo é a função para a qual o candidato concorre; vaga é a quantidade ofertada; salário é a remuneração do cargo.',
        'cronograma':'Esta página reúne datas operacionais do certame. Ela prioriza eventos como inscrição, prova, gabarito, recurso e resultado, evitando datas jurídicas soltas.',
        'provas-e-etapas':'Esta página explica como o candidato será avaliado, quais etapas existem, como a prova é composta e quais critérios podem eliminar ou classificar.',
        'conteudo-programatico':'Esta página transforma o conteúdo programático em guia de estudos. O objetivo é ajudar o candidato a localizar disciplinas e tópicos cobrados.',
        'requisitos':'Esta página separa requisitos de participação, requisitos dos cargos, documentos e regras de posse ou contratação.',
        'recursos':'Esta página explica como contestar decisões do certame, como gabarito, resultado, inscrição ou classificação.',
        'retificacoes':'Esta página destaca comunicados, erratas, prorrogações e suspensões, explicando o impacto prático para quem vai acompanhar o edital.',
    }
    return intros.get(key, f'Esta página organiza o tópico {title.lower()} em formato de wiki para consulta.')

def render_positions_md(pos, fact):
    out=['## Resumo das oportunidades']
    out.append(f"- **Total de vagas:** {fact.get('total_vacancies') or 'não consolidado com segurança'}")
    out.append(f"- **Cargos estruturados:** {len(pos or [])}")
    salary_vals=[money_to_float(p.get('salary')) for p in (pos or []) if money_to_float(p.get('salary')) is not None]
    if any(v >= 800 for v in salary_vals):
        salary_vals=[v for v in salary_vals if v >= 600]
    if salary_vals:
        out.append(f"- **Faixa salarial:** {money_fmt(min(salary_vals))} a {money_fmt(max(salary_vals))}")
    elif fact.get('salary_min') or fact.get('salary_max'):
        smin = money_fmt(fact.get('salary_min')) if fact.get('salary_min') else 'não identificado'
        smax = money_fmt(fact.get('salary_max')) if fact.get('salary_max') else 'não identificado'
        out.append(f"- **Faixa salarial:** {smin} a {smax}")
    out += ['', '## Cargos identificados']
    if pos:
        out += ['| Cargo/Função | Vagas | Carga horária | Remuneração | Requisito |','|---|---:|---:|---:|---|']
        for p in pos[:120]:
            out.append(f"| {safe_md_cell(p.get('name') or '—')} | {safe_md_cell(p.get('vacancies') or '—')} | {safe_md_cell(p.get('workload') or '—')} | {safe_md_cell(p.get('salary') or '—')} | {safe_md_cell(truncate(p.get('requirement') or '', 140) or '—')} |")
        if len(pos) > 120:
            out.append(f"\n> A tabela possui mais cargos estruturados ({len(pos)}). A wiki mostra os primeiros 120 para manter a leitura organizada.")
    else:
        out.append('Nenhum cargo foi estruturado com segurança. Isso indica que a tabela do edital pode estar quebrada, em imagem ou com formatação difícil. A página não inventa cargos para evitar erro.')
    out += ['', '## Como interpretar cargos, vagas e salário', 'Cargo é a função oferecida pelo edital, como Gari, Motorista, Professor ou Enfermeiro. Regras de PcD, documentos, leis, comparecimento ou conteúdo programático não são cargos. Remuneração é o valor pago pelo cargo; taxa de inscrição, auxílio e pontuação não entram como salário base.']
    return out

def render_events_md(events):
    out=['## Eventos identificados']
    if events:
        out += ['| Evento | Data/período | Tipo | Fonte |','|---|---:|---|---|']
        for e in events[:60]: out.append(f"| {safe_md_cell(e.get('label') or 'Evento')} | {safe_md_cell(e.get('date') or e.get('start') or '—')} | {safe_md_cell(e.get('type') or '—')} | {safe_md_cell(e.get('source') or '—')} |")
    else: out.append('Nenhum evento de cronograma foi estruturado com segurança. A wiki prefere deixar vazio a publicar datas soltas sem evento claro.')
    out += ['', '## Como interpretar o cronograma', 'Apenas datas ligadas a atos operacionais do concurso devem aparecer aqui: inscrição, pagamento, prova, gabarito, recurso, resultado e homologação. Datas de leis, portarias, CNPJ, CEP ou assinatura não são cronograma.']
    return out

def render_registration_md(f):
    return ['## Período de inscrição', f"- **Início:** {f.get('registration_start') or 'não identificado com segurança'}", f"- **Fim:** {f.get('registration_end') or 'não identificado com segurança'}", '', '## Taxa, pagamento e isenção', f"- **Taxa:** {f.get('fee') or 'não identificada com segurança'}", f"- **Forma/local:** {f.get('method') or 'não identificada com segurança'}", f"- **Isenção:** {f.get('exemption') or 'não identificada com segurança'}", '', '## Como interpretar', 'A inscrição é a etapa em que o candidato solicita participação no certame. O prazo de inscrição é diferente de prazo de recurso, homologação ou resultado.']

def render_identity_md(f):
    return ['## Identificação do certame', '| Campo | Informação |','|---|---|', f"| Instituição | {safe_md_cell(f.get('institution') or 'não identificada com segurança')} |", f"| Banca/organização | {safe_md_cell(f.get('organizer') or 'não identificada com segurança')} |", f"| Cidade/UF | {safe_md_cell((f.get('city') or '—') + '/' + (f.get('state') or '—'))} |", f"| Status | {safe_md_cell(f.get('status') or 'indefinido')} |", '', '## Como interpretar', 'Esta página consolida a identidade do edital. Em caso de suspensão, prorrogação ou errata, o impacto prático deve ser conferido na página de retificações.']

def render_exam_md(f):
    return ['## Etapas da seleção', f"- **Data de prova/avaliação:** {f.get('exam_date') or 'não identificada com segurança'}", f"- **Tipo de prova:** {f.get('exam_type') or 'não identificado com segurança'}", '', '## Regras e composição', *['- '+safe_md_cell(x) for x in (f.get('rules') or f.get('subjects') or [])[:12]], '', '## Como interpretar', 'Esta página deve reunir o que realmente avalia o candidato: tipo de prova, questões, disciplinas, pontuação, critérios de aprovação e eventuais títulos ou prova prática.']

def render_changes_md(f):
    changes=f.get('changes') or []
    out=['## Alterações identificadas']
    if changes:
        for c in changes[:20]:
            if isinstance(c,dict): out.append(f"- **{safe_md_cell(c.get('type') or 'Alteração')}:** {safe_md_cell(c.get('impact') or c.get('summary') or c.get('date') or 'alteração identificada')}")
            else: out.append('- '+safe_md_cell(c))
    else: out.append('Nenhuma retificação ou comunicado foi estruturado com segurança.')
    out += ['', '## Impacto para o candidato', 'Retificações podem alterar prazo, cargo, vaga, requisito, prova ou status do certame. Quando houver “Onde se lê / Leia-se”, a versão “Leia-se” normalmente substitui a informação anterior.']
    return out

def render_items_md(f, key=None):
    items=f.get('items') or f.get('summary_items') or f.get('rules') or f.get('changes') or []
    out=['## Informações principais']
    if isinstance(items,list) and items:
        for it in items[:14]:
            if isinstance(it,dict): it = it.get('impact') or it.get('summary') or it.get('label') or json.dumps(it, ensure_ascii=False)
            out.append('- '+safe_md_cell(str(it), 260))
    else: out.append('Nenhuma informação foi estruturada com segurança para este tópico.')
    out += ['', '## Como interpretar', 'Esta página apresenta apenas o que pôde ser organizado no tópico. Quando houver dúvida, confira a página de fontes e o documento original.']
    return out

def deterministic_attention_points(key: str, fact: dict) -> list[str]:
    pts=[]
    if key == 'cargos-e-vagas' and not fact.get('positions'):
        pts.append('- A tabela de cargos não foi consolidada; revisar o anexo de cargos no PDF original.')
    if key == 'cronograma' and not fact.get('events'):
        pts.append('- O cronograma não foi consolidado; datas soltas foram evitadas para não gerar informação falsa.')
    if key == 'inscricoes' and not (fact.get('registration_start') or fact.get('registration_end')):
        pts.append('- O período de inscrição não foi identificado com segurança.')
    if fact.get('warnings'):
        for w in as_list(fact.get('warnings'))[:5]: pts.append('- '+safe_md_cell(w, 220))
    if not pts: pts.append('- Conferir a fonte oficial quando houver retificação, suspensão, prorrogação ou divergência entre páginas do edital.')
    return pts

def safe_md_cell(v: Any, limit: int = 180) -> str:
    s=clean_text(str(v or '—')).replace('|','/').replace('\n',' ')
    return truncate(s, limit)

def write_sources_page(sections, facts):
    out=['# Fontes e auditoria','','## Páginas recuperadas por tópico']
    for key,s in sections.items(): out.append(f"- **{TOPICS[key]['title']}**: {', '.join('p. '+str(p) for p in s.get('pages',[])) or 'não identificadas'}")
    out += ['','## Artefatos de conhecimento','- `pages.json`: texto por página;','- `sections.json`: trechos recuperados por tópico;','- `topic_facts.json`: fatos extraídos por tópico;','- `positions.json`: cargos estruturados quando possível;','- `timeline.json`: eventos do cronograma quando possível.']
    return '\n'.join(out)+'\n'

def summary_positions(pos): return [{'name':p.get('name'),'vacancies':p.get('vacancies'),'salary':p.get('salary')} for p in (pos or [])[:15]]

# ---------------------------------------------------------------------
# Schema público e qualidade
# ---------------------------------------------------------------------
def build_public_schema(edital_id, identity, facts, path, raw_copy, source_url, file_hash, llm_report, wiki_report):
    ins=facts.get('inscricoes',{}); pos=facts.get('cargos-e-vagas',{}); cron=facts.get('cronograma',{}); provas=facts.get('provas-e-etapas',{})
    positions=pos.get('positions') or []
    salary_vals=[money_to_float(p.get('salary')) for p in positions if money_to_float(p.get('salary')) is not None]
    # LLM facts podem trazer salário em string.
    if not salary_vals:
        for x in [pos.get('salary_min'),pos.get('salary_max')]:
            v=money_to_float(x)
            if v: salary_vals.append(v)
    # Em concursos, valores muito baixos geralmente são adicional/auxílio quando existe salário maior.
    if any(v and v >= 800 for v in salary_vals):
        salary_vals=[v for v in salary_vals if v is not None and v >= 600]
    events=cron.get('events') or []
    exam_date=provas.get('exam_date')
    if not exam_date:
        for e in events:
            if 'prova' in str(e.get('type','')+e.get('label','')).lower(): exam_date=e.get('start') or e.get('date'); break
    total=pos.get('total_vacancies') or extract_total_vacancies('', positions)
    schema={
        'id':edital_id, 'file_hash':file_hash, 'title':identity.get('title'), 'institution':identity.get('institution'), 'organizer':identity.get('organizer'), 'city':identity.get('city'), 'state':identity.get('state'), 'status':identity.get('status') or 'indefinido', 'document_type':identity.get('document_type') or 'edital',
        'registration_start':ins.get('registration_start'), 'registration_end':ins.get('registration_end'), 'fee_text':ins.get('fee'), 'fee_min':ins.get('fee_min'), 'fee_max':ins.get('fee_max'), 'exam_date':exam_date,
        'total_vacancies':total, 'positions_count':len(positions), 'salary_min':min(salary_vals) if salary_vals else None, 'salary_max':max(salary_vals) if salary_vals else None,
        'summary':make_summary(identity, ins, pos, cron), 'highlights':make_highlights(identity, ins, pos, cron, provas), 'timeline':events[:80], 'raw_positions':positions[:250], 'raw_timeline':events[:80], 'validated_facts':facts,
        'raw_file':Path(raw_copy).name, 'source_url':source_url, 'created_at':datetime.now().isoformat(timespec='seconds'), 'llm_available':llm_report.get('llm_available'), 'llm_used_topics':llm_report.get('used_topics',0), 'wiki_llm_pages':wiki_report.get('llm_pages',0)
    }
    schema['display']=make_display(schema)
    return schema

def make_summary(identity, ins, pos, cron):
    parts=[identity.get('institution') or 'O edital']
    if identity.get('city') or identity.get('state'): parts.append(f"de {identity.get('city') or ''}/{identity.get('state') or ''}")
    base=' '.join(parts).replace(' /','/').strip()+'.'
    if identity.get('status') and identity.get('status')!='indefinido': base += f" Situação identificada: {identity.get('status')}."
    if pos.get('total_vacancies'): base += f" A base identificou {pos.get('total_vacancies')} vagas."
    if ins.get('registration_start'): base += f" Inscrições de {ins.get('registration_start')} a {ins.get('registration_end') or 'data final não identificada'}."
    return base

def make_highlights(identity, ins, pos, cron, provas):
    h=[]
    if identity.get('status') and identity.get('status')!='indefinido': h.append(f"Status: {identity.get('status')}")
    if pos.get('total_vacancies'): h.append(f"{pos.get('total_vacancies')} vagas identificadas")
    if pos.get('positions'): h.append(f"{len(pos.get('positions'))} cargos estruturados")
    if ins.get('registration_start'): h.append(f"Inscrições: {ins.get('registration_start')} a {ins.get('registration_end')}")
    if provas.get('exam_date'): h.append(f"Prova: {provas.get('exam_date')}")
    return h[:6]

def make_display(s):
    loc='Não identificado com segurança'
    if s.get('city') and s.get('state'): loc=f"{s['city']}/{s['state']}"
    elif s.get('state'): loc=s['state']
    reg='Não identificado com segurança'
    if s.get('registration_start') or s.get('registration_end'): reg=f"{date_fmt(s.get('registration_start'))} a {date_fmt(s.get('registration_end'))}"
    salary='Não identificado com segurança'
    if s.get('salary_min') and s.get('salary_max'):
        salary=money_fmt(s['salary_max']) if s['salary_min']==s['salary_max'] else f"{money_fmt(s['salary_min'])} a {money_fmt(s['salary_max'])}"
    return {'institution':s.get('institution') or 'Não identificado com segurança','location':loc,'registration':reg,'exam_date':date_fmt(s.get('exam_date')) if s.get('exam_date') else 'Não identificado com segurança','salary':salary,'vacancies':s.get('total_vacancies') or s.get('positions_count') or 'Não identificado com segurança','fee':s.get('fee_text') or 'Não identificada com segurança'}

def build_quality_report(schema, facts, sections, llm_report, wiki_report):
    score=100; issues=[]; warnings=[]
    if not llm_report.get('llm_available'):
        score=min(score,55); issues.append('LLM indisponível durante a indexação: wiki gerada em modo degradado.')
    if llm_report.get('used_topics',0) < 5 and llm_report.get('llm_available'):
        score-=15; warnings.append('Poucos tópicos foram estruturados pela LLM.')
    if not facts.get('cargos-e-vagas',{}).get('positions'):
        if sections.get('cargos-e-vagas',{}).get('text'): score=min(score,65); issues.append('Há indícios de cargos/vagas, mas nenhum cargo foi estruturado com segurança.')
    if not facts.get('cronograma',{}).get('events'):
        if sections.get('cronograma',{}).get('text'): score=min(score,75); warnings.append('Há trechos de cronograma, mas eventos estruturados são poucos ou inexistentes.')
    if not schema.get('institution'):
        score=min(score,60); issues.append('Instituição não identificada com segurança.')
    if wiki_report.get('fallback_pages',0) > 4:
        score=min(score,68); issues.append('Muitas páginas caíram no escritor determinístico; a wiki não está plenamente editorial.')
    return {'score':max(0,int(score)),'issues':issues,'warnings':warnings,'llm_report':llm_report,'wiki_report':wiki_report}

def render_lint_md(lint):
    lines=[f"# Relatório de qualidade\n\n**Score:** {lint.get('score',0)}/100\n"]
    if lint.get('issues'):
        lines.append('\n## Problemas críticos')
        for x in lint.get('issues',[]): lines.append(f'- {x}')
    if lint.get('warnings'):
        lines.append('\n## Alertas')
        for x in lint.get('warnings',[]): lines.append(f'- {x}')
    if not lint.get('issues') and not lint.get('warnings'): lines.append('\nNenhum problema crítico identificado automaticamente.')
    return '\n'.join(lines)+'\n'

def build_source_md(pages, facts):
    lines=['# Fonte extraída do edital','','> Arquivo bruto organizado por página. A wiki deve usar isto como evidência, não como texto final.','','## Resumo de fatos estruturados','','```json',json.dumps({k:{kk:vv for kk,vv in v.items() if kk in ['summary','positions','events','registration_start','registration_end','fee','status','institution']} for k,v in facts.items()}, ensure_ascii=False, indent=2)[:12000],'```','']
    for p in pages:
        lines += [f"## Página {p['page']}", p.get('text','')[:12000], '']
    return '\n'.join(lines)
