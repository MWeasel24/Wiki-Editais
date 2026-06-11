from __future__ import annotations
import re
from collections import Counter
from pathlib import Path
from typing import Any

STOPWORDS = set('''a o as os um uma uns umas de da do das dos em no na nos nas para por com sem sob sobre e ou que qual quais quando quanto quantos é são foi ser edital concurso público publica pública como onde existe tem possui informe quero saber'''.split())

QUERY_EXPANSIONS = {
    'caneta': ['caneta', 'esferográfica', 'tinta preta', 'tinta azul', 'material permitido', 'materiais permitidos', 'transparente', 'opaca', 'lápis', 'borracha'],
    'opaca': ['caneta', 'transparente', 'esferográfica', 'tinta preta', 'tinta azul', 'material permitido'],
    'material': ['material permitido', 'materiais permitidos', 'proibido', 'permitido', 'caneta', 'documento', 'comprovante'],
    'documento': ['documento oficial', 'identificação', 'rg', 'cpf', 'documento de identidade', 'comprovante'],
    'levar': ['portar', 'apresentar', 'material permitido', 'documento', 'caneta', 'comprovante'],
    'proibido': ['vedado', 'não será permitido', 'eliminado', 'proibido', 'impedido'],
    'elimina': ['eliminado', 'eliminação', 'desclassificado', 'não será permitido', 'vedado'],
    'faca': ['faca', 'objeto cortante', 'arma', 'objeto perigoso', 'proibido', 'vedado', 'material permitido', 'dia da prova', 'eliminação'],
    'arma': ['arma', 'objeto perigoso', 'faca', 'objeto cortante', 'proibido', 'vedado', 'eliminação'],
    'cortante': ['objeto cortante', 'faca', 'arma', 'proibido', 'vedado', 'eliminação'],
    'mortal': ['teste físico', 'aptidão física', 'prova prática', 'habilidade física', 'etapa prática'],
    'carpado': ['teste físico', 'aptidão física', 'prova prática', 'habilidade física', 'etapa prática'],
    'conteudo': ['conteúdo programático', 'conhecimentos básicos', 'conhecimentos específicos', 'disciplina', 'programa de prova'],
    'cai': ['conteúdo programático', 'conhecimentos básicos', 'conhecimentos específicos', 'disciplina', 'programa de prova'],
    'recurso': ['recurso', 'prazo recursal', 'interposição de recurso', 'resultado preliminar'],
}


def _norm(text: str) -> str:
    return (text or '').lower()


def tokenize(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[a-zA-ZáàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ0-9]{3,}", text or '') if w.lower() not in STOPWORDS]


def expand_query(question: str) -> str:
    q = _norm(question)
    extras: list[str] = []
    for key, terms in QUERY_EXPANSIONS.items():
        if key in q:
            extras.extend(terms)
    # Useful generic edital sections for small rules.
    if any(x in q for x in ['caneta', 'material', 'levar', 'documento', 'proibido', 'elimina']):
        extras.extend(['dia da prova', 'aplicação da prova', 'realização das provas', 'condições de realização', 'itens permitidos'])
    return question + ' ' + ' '.join(extras)


def search_chunks(question: str, chunks: list[dict], top_k: int = 6) -> list[dict]:
    expanded = expand_query(question)
    q_terms = Counter(tokenize(expanded))
    phrase_terms = [p for p in re.split(r"\s+", _norm(question)) if len(p) >= 4]
    results = []
    for c in chunks:
        hay = f"{c.get('text', '')} {c.get('section', '')} {c.get('kind', '')}"
        hay_norm = _norm(hay)
        terms = Counter(tokenize(hay))
        score = sum(min(count, terms.get(term, 0)) for term, count in q_terms.items())
        for p in phrase_terms:
            if p in hay_norm:
                score += 1.2
        # Give a small section boost.
        kind = c.get('kind', '')
        if any(x in _norm(question) for x in ['caneta','documento','material','proibido','elimina']) and any(x in hay_norm for x in ['prova', 'candidato', 'documento', 'material', 'caneta']):
            score += 2
        if any(x in _norm(question) for x in ['conteúdo','conteudo','cai','disciplina']) and kind == 'conteudo':
            score += 3
        if score > 0:
            item = dict(c)
            item['score'] = round(score, 2)
            item['source_type'] = 'chunk'
            results.append(item)
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:top_k]


def _table_text(table: dict) -> str:
    headers = table.get('headers') or []
    lines = []
    if table.get('title_guess'):
        lines.append(str(table.get('title_guess')))
    lines.append('tipo da tabela: ' + str(table.get('kind') or ''))
    for row in (table.get('rows') or [])[:40]:
        vals = []
        for h in headers:
            v = str(row.get(h, '')).strip()
            if v:
                vals.append(f"{h}: {v}")
        if vals:
            lines.append('; '.join(vals))
    return '\n'.join(lines)


def search_tables(question: str, tables: list[dict], top_k: int = 4) -> list[dict]:
    expanded = expand_query(question)
    q_terms = Counter(tokenize(expanded))
    results = []
    for t in tables:
        if t.get('ignored') and t.get('kind') not in {'formulario', 'tabela_desconhecida'}:
            continue
        text = _table_text(t)
        if not text.strip():
            continue
        hay_norm = _norm(text)
        terms = Counter(tokenize(text))
        score = sum(min(count, terms.get(term, 0)) for term, count in q_terms.items())
        kind = t.get('kind', '')
        qn = _norm(question)
        if any(x in qn for x in ['caneta','documento','material','proibido','elimina']) and any(x in hay_norm for x in ['prova','candidato','documento','caneta','material','permitido','vedado']):
            score += 3
        if any(x in qn for x in ['conteúdo','conteudo','cai','disciplina']) and kind == 'conteudo_programatico':
            score += 5
        if any(x in qn for x in ['cargo','vaga','salário','salario','remunera']) and kind == 'quadro_de_vagas':
            score += 4
        if score > 0:
            results.append({
                'id': t.get('id'),
                'section': kind or 'tabela',
                'text': text,
                'score': round(score, 2),
                'source_type': 'tabela',
                'page_start': t.get('page'),
            })
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:top_k]



def search_semantic_wiki(question: str, summary: dict, root: Path | None, top_k: int = 4) -> list[dict]:
    """Search persistent LLM Wiki pages before raw chunks.

    This is the main difference between a plain extractor and the LLM Wiki mode:
    the chat first uses thematic wiki memory, then falls back to raw evidence.
    """
    if root is None:
        return []
    edital_id = str(summary.get('edital_id') or '')
    if not edital_id:
        return []
    try:
        from .semantic_wiki import load_semantic_manifest, read_semantic_page
        manifest = load_semantic_manifest(root, edital_id)
    except Exception:
        return []
    expanded = expand_query(question)
    q_terms = Counter(tokenize(expanded))
    qn = _norm(question)
    boosted_pages = []
    if any(x in qn for x in ['faca','arma','cortante','caneta','documento','material','levar','proibido','permitido','elimina']):
        boosted_pages.append('regras-dia-prova')
    if any(x in qn for x in ['conteúdo','conteudo','cai','disciplina','estudar']):
        boosted_pages.append('conteudo-programatico')
    if any(x in qn for x in ['cargo','vaga','salário','salario','requisito','escolaridade','ensino']):
        boosted_pages.append('cargos-escolaridade-remuneracao')
    if any(x in qn for x in ['recurso','gabarito','resultado','homolog']):
        boosted_pages.append('recursos-resultados')
    if any(x in qn for x in ['prova','etapa','objetiva','prática','pratica','título','titulo']):
        boosted_pages.append('provas-etapas')
    out = []
    for p in manifest.get('pages') or []:
        pid = p.get('id')
        text = read_semantic_page(root, edital_id, pid)
        if not text:
            continue
        hay = (text + ' ' + p.get('title','') + ' ' + p.get('description','')).lower()
        terms = Counter(tokenize(hay))
        score = sum(min(count, terms.get(term, 0)) for term, count in q_terms.items())
        if pid in boosted_pages:
            score += 8
        if score > 0:
            out.append({'id': f'wiki:{pid}', 'section': p.get('title') or pid, 'text': text[:3000], 'score': score + 0.5, 'source_type': 'llm_wiki', 'page_start': None})
    out.sort(key=lambda x: x.get('score',0), reverse=True)
    return out[:top_k]

def _money_float(value: str | None) -> float | None:
    if not value:
        return None
    m = re.search(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", str(value))
    if not m:
        return None
    return float(m.group(1).replace('.', '').replace(',', '.'))




def _looks_like_requirement_name(name: str | None) -> bool:
    text = (name or '').strip().lower()
    if not text:
        return True
    patterns = [
        r"^ensino\s+(fundamental|m[eé]dio|superior)\b",
        r"^curso\s+(t[eé]cnico|superior|de)\b",
        r"^registro\s+no\s+conselho\b",
        r"^gradua[cç][aã]o\b",
        r"^experi[eê]ncia\b",
        r"^habilita[cç][aã]o\b",
    ]
    if len(text) > 115 and any(x in text for x in ['ensino', 'curso', 'registro', 'conselho', 'habilitação', 'cnh']):
        return True
    return any(re.search(p, text, re.I) for p in patterns)


def _public_cargos(summary: dict) -> list[dict]:
    return [c for c in (summary.get('cargos') or []) if not c.get('suspeito') and not _looks_like_requirement_name(c.get('nome'))]

def _compact_item(item: dict) -> str:
    parts = []
    for k, v in item.items():
        if k in {'fonte', 'fonte_tipo', 'pagina', 'confianca', 'suspeito', 'motivo_suspeita'}:
            continue
        if v:
            parts.append(f"{k}: {v}")
    return '; '.join(parts)


def _source_from_item(item: dict, kind: str) -> dict:
    return {
        'id': item.get('fonte') or item.get('id') or kind,
        'section': kind,
        'text': _compact_item(item),
        'score': 10,
        'source_type': item.get('fonte_tipo') or kind,
        'page_start': item.get('pagina'),
    }


def _tool_cargos(question: str, summary: dict) -> tuple[str | None, list[dict]]:
    q = _norm(question)
    cargos = _public_cargos(summary)
    if not cargos:
        return "Não encontrei cargos consolidados para este edital.", []
    m_money = re.search(r"(?:acima|maior|mais|superior)\s+(?:de\s+)?(?:r\$\s*)?(\d+(?:\.\d{3})*(?:,\d{2})?)", q)
    filtered = cargos
    if m_money and any(x in q for x in ['salario', 'salário', 'remunera', 'vencimento', 'r$']):
        raw = m_money.group(1)
        threshold = float(raw.replace('.', '').replace(',', '.'))
        filtered = [c for c in cargos if (_money_float(c.get('remuneracao')) or 0) > threshold]

    # Educational/requisite questions should filter by requisito, but the answer
    # must list cargo names instead of repeating requisito text.
    edu_terms = []
    if any(x in q for x in ['ensino medio', 'ensino médio', 'nivel medio', 'nível médio']):
        edu_terms.extend(['ensino médio', 'ensino medio', 'nível médio', 'nivel medio', 'técnico', 'tecnico'])
    if any(x in q for x in ['ensino fundamental', 'fundamental']):
        edu_terms.extend(['ensino fundamental', 'fundamental'])
    if any(x in q for x in ['ensino superior', 'superior', 'graduação', 'graduacao']):
        edu_terms.extend(['ensino superior', 'superior', 'graduação', 'graduacao'])
    if edu_terms or any(x in q for x in ['exige', 'exigem', 'requisito', 'escolaridade']):
        terms = edu_terms or [t for t in tokenize(question) if len(t) > 4]
        by_req = []
        for c in filtered:
            hay = _norm((c.get('requisito') or '') + ' ' + (c.get('nome') or ''))
            if any(t in hay for t in terms):
                by_req.append(c)
        if by_req:
            filtered = by_req
    else:
        terms = [t for t in tokenize(question) if len(t) > 3]
        named = []
        for c in filtered:
            name = _norm(c.get('nome', ''))
            if terms and any(t in name for t in terms):
                named.append(c)
        if named:
            filtered = named

    lines = []
    for c in filtered[:20]:
        line = f"- {c.get('nome')}"
        details = []
        for label, key in [('vagas', 'vagas'), ('remuneração', 'remuneracao'), ('carga horária', 'carga_horaria'), ('requisito', 'requisito')]:
            if c.get(key):
                details.append(f"{label}: {c.get(key)}")
        if details:
            line += " — " + "; ".join(details)
        lines.append(line)
    if not lines:
        return "Não encontrei cargos que correspondam ao filtro da pergunta.", []
    return "\n".join(lines), [_source_from_item(c, 'cargo') for c in filtered[:5]]


def _tool_cronograma(question: str, summary: dict) -> tuple[str | None, list[dict]]:
    eventos = summary.get('cronograma') or []
    if not eventos:
        return "Não encontrei cronograma consolidado para este edital.", []
    q = _norm(question)
    if any(x in q for x in ['inscri', 'prazo']):
        keys = ['inscri']
    elif any(x in q for x in ['prova', 'gabarito', 'resultado', 'recurso', 'homolog']):
        keys = [x for x in ['prova','gabarito','resultado','recurso','homolog'] if x in q] or ['prova']
    elif any(x in q for x in ['data', 'quando', 'cronograma']):
        keys = []
    else:
        keys = []
    filtered = eventos
    if keys:
        filtered = [e for e in eventos if any(k in _norm(e.get('evento', '') + ' ' + e.get('data_ou_periodo', '')) for k in keys)]
    if not filtered:
        filtered = eventos[:8]
    lines = [f"- {e.get('evento')}: {e.get('data_ou_periodo')}" for e in filtered[:12]]
    return "\n".join(lines), [_source_from_item(e, 'cronograma') for e in filtered[:5]]


def _tool_dados(question: str, summary: dict) -> tuple[str | None, list[dict]]:
    q = _norm(question)
    fields = []
    if any(x in q for x in ['taxa', 'valor', 'pagar', 'pagamento']): fields.append(('Taxa', 'taxa'))
    if any(x in q for x in ['inscri', 'prazo']): fields.append(('Inscrição', 'inscricao'))
    if any(x in q for x in ['banca', 'organizadora']): fields.append(('Banca', 'banca'))
    if any(x in q for x in ['órgão', 'orgao', 'prefeitura', 'universidade', 'conselho']): fields.append(('Órgão', 'orgao'))
    if any(x in q for x in ['ano']): fields.append(('Ano', 'ano'))
    if not fields:
        return None, []
    lines = [f"- {label}: {summary.get(key) or 'não encontrado'}" for label, key in fields]
    return "\n".join(lines), [{'id': 'dados_gerais', 'section': 'dados estruturados', 'text': '\n'.join(lines), 'score': 10, 'source_type': 'json'}]


def _tool_conteudo(question: str, chunks: list[dict], tables: list[dict]) -> tuple[str | None, list[dict]]:
    q = _norm(question)
    if not any(x in q for x in ['conteudo', 'conteúdo', 'programatico', 'programático', 'cai', 'disciplina']):
        return None, []
    try:
        from .content_extractor import extract_content_programatico
        content = extract_content_programatico(chunks, tables)
        sections = content.get('sections') or []
        if sections:
            lines = []
            sources = []
            for sec in sections[:5]:
                lines.append(f"{sec.get('titulo')}")
                for topico in (sec.get('topicos') or [])[:10]:
                    lines.append(f"- {topico}")
                if sec.get('fonte') or sec.get('pagina'):
                    sources.append({'id': sec.get('fonte') or 'conteudo', 'section': sec.get('titulo'), 'text': '; '.join((sec.get('topicos') or [])[:12]), 'score': 9, 'source_type': 'conteudo', 'page_start': sec.get('pagina')})
            return "\n".join(lines), sources
    except Exception:
        pass
    return "Não encontrei conteúdo programático estruturado para este edital.", []


def _fallback_answer(question: str, sources: list[dict]) -> str:
    if not sources:
        return "Não encontrei informação suficiente para responder com segurança."
    lines = ["Informações encontradas:"]
    for c in sources[:4]:
        snippet = re.sub(r"\s+", " ", c.get('text', '')).strip()[:500]
        page = f" página {c.get('page_start')}" if c.get('page_start') else ""
        lines.append(f"- Fonte {c.get('id')} ({c.get('section')}{page}): {snippet}")
    return "\n".join(lines)


def _llm_answer(question: str, context: str) -> str | None:
    try:
        from .llm_wiki import _read_llm_config
        from .llm_client import ollama_generate
        cfg = _read_llm_config()
        if not cfg.get('enabled'):
            return None
        prompt = f"""Você é o chat da WikiEditais.
Responda apenas com base no contexto fornecido.
Não invente datas, cargos, valores, requisitos ou etapas.
Se o contexto não responder, diga que não foi encontrado.
Use tom direto.
Priorize páginas da LLM Wiki quando existirem no contexto.
Se a pergunta envolver objetos perigosos/proibidos e o edital não trouxer regra explícita, não assuma permissão; diga que não há evidência e recomende consultar edital/banca.
Se a pergunta for absurda ou fora do escopo, responda brevemente que não há evidência no edital.

Pergunta: {question}

Contexto:
{context}

Resposta:"""
        return ollama_generate(prompt, model=str(cfg.get('model')), base_url=str(cfg.get('base_url')), timeout=90)
    except Exception:
        return None


def answer_hybrid(question: str, summary: dict, chunks: list[dict], tables: list[dict], root: Path | None = None, config: dict[str, Any] | None = None) -> tuple[str, list[dict]]:
    q = _norm(question)
    tool_answer = None
    tool_sources: list[dict] = []
    for tool in (_tool_dados,):
        tool_answer, tool_sources = tool(question, summary)
        if tool_answer:
            break
    if not tool_answer and any(x in q for x in ['cargo', 'vaga', 'salario', 'salário', 'remunera', 'requisito', 'carga horaria', 'carga horária']):
        tool_answer, tool_sources = _tool_cargos(question, summary)
    if not tool_answer and any(x in q for x in ['cronograma', 'quando', 'data', 'prova', 'resultado', 'recurso', 'inscri', 'gabarito']):
        tool_answer, tool_sources = _tool_cronograma(question, summary)
    if not tool_answer:
        tool_answer, tool_sources = _tool_conteudo(question, chunks, tables)

    # LLM Wiki memory first: persistent thematic pages created during assimilation.
    semantic_sources = search_semantic_wiki(question, summary, root, top_k=5)

    # Vector RAG: ChromaDB + bge-m3/nomic via Ollama when available.
    vector_sources: list[dict] = []
    if root is not None:
        try:
            from .vector_store import search_vector
            edital_id = str(summary.get('edital_id') or '')
            vector_sources = search_vector(expand_query(question), edital_id, root, config or {}, top_k=8)
        except Exception:
            vector_sources = []

    # Textual RAG backup for nuanced rules and small details.
    rag_query = expand_query(question)
    rag_sources = semantic_sources + vector_sources + search_chunks(rag_query, chunks, top_k=8) + search_tables(rag_query, tables, top_k=5)
    rag_sources.sort(key=lambda x: x.get('score', 0), reverse=True)
    used = {x.get('id') for x in tool_sources}
    sources = (tool_sources or []) + [s for s in rag_sources if s.get('id') not in used]
    context_parts = []
    if tool_answer:
        context_parts.append('Dados estruturados/ferramentas:\n' + tool_answer)
    for s in sources[:7]:
        context_parts.append(f"Fonte {s.get('id')} ({s.get('section')}): " + re.sub(r"\s+", " ", s.get('text', '')).strip()[:1000])
    context = "\n\n".join(context_parts)
    llm_text = _llm_answer(question, context) if context else None
    if llm_text:
        return llm_text, sources[:8]
    if tool_answer and (tool_sources or not rag_sources):
        return tool_answer, sources[:8]
    # For open questions, include RAG evidence instead of failing too early.
    return _fallback_answer(question, sources), sources[:8]
