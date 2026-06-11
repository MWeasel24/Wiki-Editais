from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    from slugify import slugify
except Exception:
    import unicodedata
    def slugify(value: str) -> str:
        value = unicodedata.normalize('NFKD', value).encode('ascii','ignore').decode().lower()
        return re.sub(r'[^a-z0-9]+','-',value).strip('-')

THEMES = [
    {
        'id': 'visao-geral',
        'title': 'Visão geral do edital',
        'description': 'Síntese dos dados centrais, escopo do edital e pontos de atenção.',
        'keywords': ['titulo','orgao','banca','ano','inscricao','taxa','prova','vagas','cargos'],
    },
    {
        'id': 'inscricoes-taxas-isencao',
        'title': 'Inscrições, taxas e isenção',
        'description': 'Período de inscrição, valor da taxa, pagamento, isenção e regras relacionadas.',
        'keywords': ['inscri','taxa','pagamento','boleto','isenção','isencao','hipossuficiente','deferimento','indeferimento'],
    },
    {
        'id': 'cargos-escolaridade-remuneracao',
        'title': 'Cargos, escolaridade e remuneração',
        'description': 'Cargos, vagas, requisitos, carga horária, remuneração e alertas de extração.',
        'keywords': ['cargo','vaga','vagas','remuneração','remuneracao','requisito','escolaridade','ensino','carga horária','salário'],
    },
    {
        'id': 'provas-etapas',
        'title': 'Provas e etapas',
        'description': 'Tipos de prova, datas, etapas, caráter eliminatório/classificatório e estrutura de avaliação.',
        'keywords': ['prova','objetiva','prática','pratica','títulos','titulos','etapa','eliminatório','classificatório','pontuação'],
    },
    {
        'id': 'regras-dia-prova',
        'title': 'Regras do dia da prova',
        'description': 'Materiais permitidos, documentos, condutas proibidas, eliminação e regras de permanência.',
        'keywords': ['dia da prova','caneta','documento','identificação','identificacao','material','permitido','vedado','proibido','eliminado','celular','aparelho','caderno','local de prova','portar','faca','arma','objeto'],
    },
    {
        'id': 'conteudo-programatico',
        'title': 'Conteúdo programático',
        'description': 'Disciplinas, conhecimentos básicos, conhecimentos específicos e tópicos de estudo.',
        'keywords': ['conteúdo programático','conteudo programatico','conhecimentos básicos','conhecimentos especificos','língua portuguesa','matemática','informática','legislação','programa de prova'],
    },
    {
        'id': 'recursos-resultados',
        'title': 'Recursos, gabaritos e resultados',
        'description': 'Prazos de recurso, gabaritos, resultados preliminares/finais e homologação.',
        'keywords': ['recurso','gabarito','resultado','preliminar','final','homologação','homologacao','interposição','interposicao'],
    },
    {
        'id': 'incertezas-revisao',
        'title': 'Incertezas e revisão humana',
        'description': 'Campos ausentes, suspeitos, possíveis conflitos e pontos que devem ser conferidos no PDF original.',
        'keywords': ['suspeito','não encontrado','nao encontrado','baixa','conferir','revisão','revisao','incerteza'],
    },
]


def _norm(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()


def _read_llm_cfg(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config or {}
    return config.get('llm') or {'enabled': False}


def _table_text(table: dict[str, Any], limit_rows: int = 30) -> str:
    headers = table.get('headers') or []
    lines = []
    if table.get('title_guess'):
        lines.append(str(table.get('title_guess')))
    lines.append(f"tipo: {table.get('kind') or 'tabela'}; página: {table.get('page') or ''}")
    for row in (table.get('rows') or [])[:limit_rows]:
        vals = []
        if headers:
            for h in headers:
                v = str(row.get(h, '')).strip()
                if v:
                    vals.append(f'{h}: {v}')
        else:
            for k, v in row.items():
                if str(v).strip():
                    vals.append(f'{k}: {v}')
        if vals:
            lines.append('; '.join(vals))
    return _norm('\n'.join(lines))


def _structured_context(summary: dict[str, Any], theme_id: str = "visao-geral") -> str:
    lines = []
    for label, key in [('Título','titulo'),('Órgão','orgao'),('Banca','banca'),('Ano','ano'),('Inscrição','inscricao'),('Taxa','taxa'),('Prova','prova')]:
        if summary.get(key):
            lines.append(f'{label}: {summary.get(key)}')
    cargos = [c for c in (summary.get('cargos') or []) if not c.get('suspeito')]
    if cargos and theme_id in {'visao-geral','cargos-escolaridade-remuneracao'}:
        lines.append('\nCargos consolidados:')
        for c in cargos[:80]:
            details = []
            for k in ['vagas','remuneracao','carga_horaria','requisito']:
                if c.get(k):
                    details.append(f'{k}: {c.get(k)}')
            lines.append(f"- {c.get('nome')}" + (" — " + '; '.join(details) if details else ''))
    cron = summary.get('cronograma') or []
    if cron and theme_id in {'visao-geral','provas-etapas','recursos-resultados','inscricoes-taxas-isencao'}:
        lines.append('\nCronograma consolidado:')
        for e in cron[:50]:
            lines.append(f"- {e.get('evento')}: {e.get('data_ou_periodo')}")
    content = summary.get('conteudo_programatico') or {}
    sections = content.get('sections') if isinstance(content, dict) else []
    if sections and theme_id in {'visao-geral','conteudo-programatico'}:
        lines.append('\nConteúdo programático estruturado:')
        for sec in sections[:12]:
            lines.append(f"## {sec.get('titulo') or 'Seção'}")
            for t in (sec.get('topicos') or [])[:25]:
                lines.append(f'- {t}')
    q = summary.get('qualidade') or {}
    alerts = (q.get('avisos') or []) + (q.get('campos_suspeitos') or [])
    if (alerts or summary.get('campos_nao_encontrados')) and theme_id in {'visao-geral','incertezas-revisao'}:
        lines.append('\nAvisos/incertezas:')
        for a in alerts[:20]:
            lines.append(f'- {a}')
        for a in (summary.get('campos_nao_encontrados') or [])[:20]:
            lines.append(f'- Campo não encontrado: {a}')
    return _norm('\n'.join(lines))


def _evidence_for_theme(theme: dict[str, Any], summary: dict[str, Any], chunks: list[dict[str, Any]], tables: list[dict[str, Any]], max_chars: int = 8500) -> tuple[str, list[dict[str, Any]]]:
    keywords = [k.lower() for k in theme['keywords']]
    snippets: list[dict[str, Any]] = []
    # Always include compact structured data; it is the reliable wiki memory.
    snippets.append({'kind': 'dados estruturados', 'id': 'json:resumo', 'page': None, 'text': _structured_context(summary, theme['id'])[:3500]})
    scored = []
    for c in chunks:
        hay = (str(c.get('section','')) + ' ' + str(c.get('kind','')) + ' ' + str(c.get('text',''))).lower()
        score = sum(1 for k in keywords if k in hay)
        if score:
            scored.append((score, {'kind': 'chunk', 'id': c.get('id'), 'page': c.get('page_start'), 'text': _norm(c.get('text',''))[:1800]}))
    for t in tables:
        if theme['id'] == 'regras-dia-prova' and t.get('kind') in {'quadro_de_vagas','avaliacao_titulos'}:
            continue
        if theme['id'] == 'conteudo-programatico' and t.get('kind') not in {'conteudo_programatico','pontuacao_prova','tabela_desconhecida'}:
            continue
        text = _table_text(t)
        hay = text.lower()
        score = sum(1 for k in keywords if k in hay)
        if score:
            scored.append((score + (2 if t.get('kind') in ['quadro_de_vagas','cronograma','conteudo_programatico','pontuacao_prova'] else 0), {'kind': 'tabela', 'id': t.get('id'), 'page': t.get('page'), 'text': text[:1800]}))
    scored.sort(key=lambda x: x[0], reverse=True)
    snippets.extend([x[1] for x in scored[:8]])
    parts = []
    used = []
    size = 0
    for s in snippets:
        text = s.get('text') or ''
        block = f"Fonte {s.get('id')} ({s.get('kind')}, p. {s.get('page') or '-'})\n{text}"
        if size + len(block) > max_chars:
            continue
        parts.append(block)
        used.append(s)
        size += len(block)
    return '\n\n'.join(parts), used


def _fallback_page(theme: dict[str, Any], summary: dict[str, Any], evidence: str, used: list[dict[str, Any]]) -> str:
    title = theme['title']
    edital_title = summary.get('titulo') or 'Edital'
    lines = [f'# {title}\n', f'**Edital:** {edital_title}\n', '## Síntese\n']
    tid = theme['id']
    if tid == 'visao-geral':
        lines += [
            f"- Órgão: {summary.get('orgao') or 'não encontrado'}",
            f"- Banca: {summary.get('banca') or 'não encontrada'}",
            f"- Inscrição: {summary.get('inscricao') or 'não encontrada'}",
            f"- Taxa: {summary.get('taxa') or 'não encontrada'}",
            f"- Prova: {summary.get('prova') or 'não encontrada'}",
            f"- Cargos consolidados: {len([c for c in (summary.get('cargos') or []) if not c.get('suspeito')])}",
        ]
    elif tid == 'cargos-escolaridade-remuneracao':
        cargos = [c for c in (summary.get('cargos') or []) if not c.get('suspeito')]
        if cargos:
            for c in cargos[:60]:
                lines.append(f"- **{c.get('nome')}** — vagas: {c.get('vagas') or '-'}; remuneração: {c.get('remuneracao') or '-'}; requisito: {c.get('requisito') or '-'}")
        else:
            lines.append('- Não foram consolidados cargos confiáveis.')
    elif tid == 'conteudo-programatico':
        sections = ((summary.get('conteudo_programatico') or {}).get('sections') if isinstance(summary.get('conteudo_programatico'), dict) else []) or []
        if sections:
            for sec in sections:
                lines.append(f"### {sec.get('titulo') or 'Seção'}")
                for t in (sec.get('topicos') or [])[:30]:
                    lines.append(f'- {t}')
        else:
            lines.append('- Conteúdo programático não estruturado automaticamente.')
    elif tid == 'incertezas-revisao':
        q = summary.get('qualidade') or {}
        alerts = (q.get('avisos') or []) + (q.get('campos_suspeitos') or []) + (summary.get('campos_nao_encontrados') or [])
        if alerts:
            for a in alerts[:40]:
                lines.append(f'- {a}')
        else:
            lines.append('- Nenhum alerta crítico registrado na extração automática.')
    else:
        # Summarize evidence without dumping entire chunks.
        compact = []
        for s in used[:6]:
            text = _norm(s.get('text') or '')[:450]
            compact.append(f"- {text}")
        lines.extend(compact or ['- Não encontrei evidências suficientes para consolidar esta página.'])
    lines += ['\n## O que não foi encontrado / limites\n', '- Esta página só consolida informações com evidência nos dados extraídos, tabelas ou chunks do edital.', '- Ausências não significam permissão ou proibição; consulte o PDF original em caso de dúvida.']
    lines += ['\n## Fontes usadas\n']
    for s in used[:10]:
        page = f", p. {s.get('page')}" if s.get('page') else ''
        lines.append(f"- {s.get('kind')} `{s.get('id')}`{page}")
    return '\n'.join(lines).strip() + '\n'


def _llm_page(theme: dict[str, Any], summary: dict[str, Any], evidence: str, config: dict[str, Any] | None) -> str | None:
    llm = _read_llm_cfg(config)
    if not llm.get('enabled'):
        return None
    try:
        from .llm_client import ollama_generate
        prompt = f"""Você é o mantenedor de uma LLM Wiki de editais públicos.
Sua tarefa é ASSIMILAR evidências de um edital e escrever uma página temática persistente da wiki.

Regras obrigatórias:
- Use somente as evidências fornecidas.
- Não despeje texto cru; sintetize em tópicos úteis.
- Separe: Síntese, Fatos consolidados, O que não foi encontrado/limites, Fontes usadas, Links relacionados.
- Quando uma pergunta não puder ser respondida, diga explicitamente que não há evidência no edital.
- Não diga que "foi transformado por IA". Não use tom promocional.
- Para objetos perigosos/proibidos, nunca afirme permissão se o edital não trouxer evidência explícita.

Edital: {summary.get('titulo') or 'Edital'}
Página temática: {theme['title']}
Descrição: {theme['description']}

Evidências:
{evidence[:9000]}

Escreva a página em Markdown:"""
        model = str(llm.get('model') or 'qwen2.5:14b-instruct')
        base_url = str(llm.get('base_url') or 'http://localhost:11434')
        text = ollama_generate(prompt, model=model, base_url=base_url, timeout=180)
        if text and len(text.strip()) > 80:
            return text.strip() + '\n'
    except Exception:
        return None
    return None


def build_semantic_wiki(summary: dict[str, Any], chunks: list[dict[str, Any]], tables: list[dict[str, Any]], root: Path, config: dict[str, Any] | None = None) -> dict[str, Any]:
    edital_id = summary.get('edital_id') or slugify(summary.get('titulo') or 'edital')[:80]
    wiki_root = root / 'wiki'
    data_root = root / 'data' / 'wiki_memory'
    page_dir = wiki_root / 'temas' / edital_id
    page_dir.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    pages = []
    for theme in THEMES:
        evidence, used = _evidence_for_theme(theme, summary, chunks, tables)
        page_text = _llm_page(theme, summary, evidence, config) or _fallback_page(theme, summary, evidence, used)
        page_slug = theme['id']
        rel = Path('temas') / edital_id / f'{page_slug}.md'
        path = wiki_root / rel
        path.write_text(page_text, encoding='utf-8')
        pages.append({
            'id': page_slug,
            'title': theme['title'],
            'description': theme['description'],
            'path': str(rel).replace('\\','/'),
            'sources': [{'id': s.get('id'), 'kind': s.get('kind'), 'page': s.get('page')} for s in used[:10]],
            'llm': page_text[:20].strip().startswith('#') and ('## Síntese' in page_text or '## Fatos' in page_text),
        })
    # Index page that links the persistent semantic memory.
    index_lines = [f"# LLM Wiki — {summary.get('titulo') or edital_id}\n", 'Esta área reúne páginas temáticas persistentes do edital. Elas são usadas pelo chat antes dos chunks brutos.\n']
    for p in pages:
        index_lines.append(f"- [{p['title']}]({p['id']}.md) — {p['description']}")
    (page_dir / 'index.md').write_text('\n'.join(index_lines) + '\n', encoding='utf-8')
    manifest = {
        'edital_id': edital_id,
        'titulo': summary.get('titulo'),
        'mode': 'llm_wiki_semantica',
        'pages': pages,
        'total_pages': len(pages),
        'definition': 'Páginas temáticas persistentes, atualizadas a cada ingestão/revisão, usadas como memória de conhecimento antes dos chunks brutos.',
    }
    (data_root / f'{edital_id}.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def load_semantic_manifest(root: Path, edital_id: str) -> dict[str, Any]:
    path = root / 'data' / 'wiki_memory' / f'{edital_id}.json'
    if not path.exists():
        return {'pages': [], 'total_pages': 0}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {'pages': [], 'total_pages': 0}


def read_semantic_page(root: Path, edital_id: str, page_id: str) -> str:
    path = root / 'wiki' / 'temas' / edital_id / f'{slugify(page_id)}.md'
    if not path.exists():
        return ''
    return path.read_text(encoding='utf-8')
