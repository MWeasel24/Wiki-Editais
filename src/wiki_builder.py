from __future__ import annotations
from pathlib import Path
try:
    from slugify import slugify
except Exception:
    import re, unicodedata
    def slugify(value: str) -> str:
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
        return re.sub(r"[^a-z0-9]+", "-", value).strip("-")
from .schemas import ConcursoResumo
from .llm_wiki import generate_wiki_narrative
from .content_extractor import extract_content_programatico


def _src(label: str | None, tipo: str | None = None, pagina: int | None = None) -> str:
    if not label:
        return ""
    pieces = []
    if tipo:
        pieces.append(tipo)
    pieces.append(label)
    if pagina:
        pieces.append(f"p. {pagina}")
    return " _Fonte: " + " — ".join(pieces) + "_"


def _status_md(summary: ConcursoResumo) -> str:
    if not getattr(summary, "campos_status", None):
        return "- Sem status detalhado dos campos.\n"
    out = []
    for nome, st in summary.campos_status.items():
        out.append(f"- **{nome}:** {st.valor or 'Não encontrado'} — `{st.status}`" + (f" — {st.motivo}" if st.motivo else ""))
    return "\n".join(out) + "\n"


def _quality_md(summary: ConcursoResumo) -> str:
    q = summary.qualidade
    quality_md = f"""- **Chunks:** {q.total_chunks}
- **Tabelas:** {q.total_tabelas}
- **Tabelas úteis:** {q.tabelas_uteis}
- **Tabelas ignoradas:** {q.tabelas_ignoradas}
- **Continuações:** {q.tabelas_continuacao}
- **Tabelas suspeitas:** {q.tabelas_suspeitas}
- **Cargos suspeitos:** {q.cargos_suspeitos}
"""
    if q.avisos:
        quality_md += "\n### Avisos\n" + "\n".join(f"- {a}" for a in q.avisos) + "\n"
    if q.campos_suspeitos:
        quality_md += "\n### Campos suspeitos\n" + "\n".join(f"- {a}" for a in q.campos_suspeitos) + "\n"
    return quality_md


def build_concurso_markdown(summary: ConcursoResumo, chunks: list[dict], wiki_root: str | Path, tables: list[dict] | None = None) -> Path:
    tables = tables or []
    wiki_root = Path(wiki_root)
    concurso_dir = wiki_root / "concursos"
    cargo_dir = wiki_root / "cargos" / (slugify(summary.edital_id)[:90] or "edital")
    cron_dir = wiki_root / "cronogramas"
    conteudo_dir = wiki_root / "conteudos"
    fonte_dir = wiki_root / "fontes"
    tabela_dir = wiki_root / "tabelas"
    for d in [concurso_dir, cargo_dir, cron_dir, conteudo_dir, fonte_dir, tabela_dir]:
        d.mkdir(parents=True, exist_ok=True)

    slug = slugify(summary.edital_id or summary.titulo)[:90]
    path = concurso_dir / f"{slug}.md"

    resumo_text, resumo_mode = generate_wiki_narrative(summary, "resumo")
    cargos_intro, cargos_mode = generate_wiki_narrative(summary, "cargos")
    cron_intro, cron_mode = generate_wiki_narrative(summary, "cronograma")
    conteudo_intro, conteudo_mode = generate_wiki_narrative(summary, "conteudo")

    # Cargo pages and index
    cargos_lines = []
    for c in summary.cargos:
        cargo_slug = slugify(c.nome)[:80] or "cargo"
        badge = " ⚠️" if c.suspeito or c.confianca == "baixa" else ""
        cargos_lines.append(
            f"- [[../cargos/{slug}/{cargo_slug}|{c.nome}]]{badge}"
            + (f" — vagas: {c.vagas}" if c.vagas else "")
            + (f" — remuneração: {c.remuneracao}" if c.remuneracao else "")
            + _src(c.fonte, c.fonte_tipo, c.pagina)
        )
        cargo_text = f"""# {c.nome}

{c.nome} aparece no edital **{summary.titulo}**. As informações abaixo foram consolidadas a partir das fontes detectadas.

## Dados

- **Vagas:** {c.vagas or 'Não encontrado'}
- **Remuneração:** {c.remuneracao or 'Não encontrado'}
- **Carga horária:** {c.carga_horaria or 'Não encontrado'}
- **Requisito:** {c.requisito or 'Não encontrado'}
- **Confiança:** {c.confianca}

## Revisão

{'⚠️ ' + (c.motivo_suspeita or 'baixa confiança') if c.suspeito or c.confianca == 'baixa' else 'Sem alerta crítico na extração inicial.'}

## Fonte

{_src(c.fonte, c.fonte_tipo, c.pagina) or 'Fonte não registrada.'}
"""
        (cargo_dir / f"{cargo_slug}.md").write_text(cargo_text, encoding="utf-8")

    cargos_table = "| Cargo | Vagas | Remuneração | Carga horária | Requisito | Fonte |\n| --- | --- | --- | --- | --- | --- |\n"
    for c in summary.cargos:
        source = (c.fonte or "") + (f" p. {c.pagina}" if c.pagina else "")
        cargos_table += f"| {c.nome.replace('|','/')} | {c.vagas or '-'} | {c.remuneracao or '-'} | {c.carga_horaria or '-'} | {(c.requisito or '-').replace('|','/')} | {source} |\n"
    cargos_page = f"# Cargos — {summary.titulo}\n\n{cargos_intro}\n\n{cargos_table if summary.cargos else 'Nenhum cargo consolidado.'}\n"
    (cargo_dir / "index.md").write_text(cargos_page, encoding="utf-8")

    # Cronograma page
    cron_table = "| Evento | Data/período | Fonte |\n| --- | --- | --- |\n"
    for e in summary.cronograma:
        src = (e.fonte or "") + (f" p. {e.pagina}" if e.pagina else "")
        cron_table += f"| {e.evento.replace('|','/')} | {e.data_ou_periodo.replace('|','/')} | {src} |\n"
    cron_page = f"# Cronograma — {summary.titulo}\n\n{cron_intro}\n\n{cron_table if summary.cronograma else 'Nenhum cronograma consolidado.'}\n"
    (cron_dir / f"{slug}-cronograma.md").write_text(cron_page, encoding="utf-8")

    # Conteúdo page: structured topics only, never raw chunks.
    conteudo = extract_content_programatico(chunks, tables)
    conteudo_md = f"# Conteúdo programático — {summary.titulo}\n\n{conteudo_intro}\n\n"
    if conteudo.get('sections'):
        for sec in conteudo.get('sections', []):
            conteudo_md += f"## {sec.get('titulo')}\n\n"
            for topic in sec.get('topicos', []):
                conteudo_md += f"- {str(topic).replace('|','/')}\n"
            if sec.get('pagina'):
                conteudo_md += f"\n_Fonte: p. {sec.get('pagina')}_\n"
            conteudo_md += "\n"
    else:
        conteudo_md += "Conteúdo programático não estruturado automaticamente.\n"
    (conteudo_dir / f"{slug}-conteudo.md").write_text(conteudo_md, encoding="utf-8")

    cargos_nav = "\n".join(cargos_lines) or "- Não encontrado na extração inicial."
    cron_nav = "\n".join(
        f"- **{e.evento}** — {e.data_ou_periodo}" + _src(e.fonte, e.fonte_tipo, e.pagina)
        for e in summary.cronograma[:20]
    ) or "- Não encontrado na extração inicial."

    missing_md = "\n".join(f"- {x}" for x in summary.campos_nao_encontrados) or "- Nenhum campo crítico marcado como ausente."

    md = f"""# {summary.titulo}

{resumo_text}

## Páginas

- [[../cargos/{slug}/index|Cargos]]
- [[../cronogramas/{slug}-cronograma|Cronograma]]
- [[../conteudos/{slug}-conteudo|Conteúdo programático]]
- [[../fontes/{slug}-fontes|Fontes]]
- [[../tabelas/{slug}-tabelas|Tabelas]]

## Dados principais

- **Órgão:** {summary.orgao or 'Não encontrado'}
- **Banca:** {summary.banca or 'Não encontrado'}
- **Ano:** {summary.ano or 'Não encontrado'}
- **Inscrição:** {summary.inscricao or 'Não encontrado'}
- **Taxa:** {summary.taxa or 'Não encontrado'}
- **Prova:** {summary.prova or 'Não encontrado'}

## Cargos

{cargos_nav}

## Cronograma

{cron_nav}

## Revisão

{missing_md}

## Status dos campos

{_status_md(summary)}

## Diagnóstico

{_quality_md(summary)}
"""
    path.write_text(md, encoding="utf-8")

    # Sources and tables remain technical pages
    fonte_lines = [f"# Fontes — {summary.titulo}\n"]
    for c in chunks:
        page = ""
        if c.get("page_start"):
            page = f"p. {c.get('page_start')}" if c.get("page_start") == c.get("page_end") else f"p. {c.get('page_start')}-{c.get('page_end')}"
        fonte_lines.append(f"## {c['id']} — {c.get('kind', 'geral')} — {page}\n")
        fonte_lines.append(f"**Seção:** {c.get('section', 'Sem seção')}\n")
        snippet = c.get("text", "")[:1200].strip()
        fonte_lines.append(f"```text\n{snippet}\n```\n")
    (fonte_dir / f"{slug}-fontes.md").write_text("\n".join(fonte_lines), encoding="utf-8")

    tabela_lines = [f"# Tabelas — {summary.titulo}\n"]
    for t in tables:
        tabela_lines.append(f"## {t.get('id')} — {t.get('kind')} — página {t.get('page')}" + (" — ignorada" if t.get('ignored') else "") + "\n")
        if t.get("title_guess"):
            tabela_lines.append(f"**Título provável:** {t.get('title_guess')}\n")
        if t.get("ignore_reason"):
            tabela_lines.append(f"**Motivo:** {t.get('ignore_reason')}\n")
        headers = t.get("headers", [])
        if headers:
            tabela_lines.append("| " + " | ".join(headers) + " |")
            tabela_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for row in t.get("rows", [])[:100]:
                tabela_lines.append("| " + " | ".join(str(row.get(h, "")).replace("|", "/") for h in headers) + " |")
        tabela_lines.append("")
    (tabela_dir / f"{slug}-tabelas.md").write_text("\n".join(tabela_lines), encoding="utf-8")
    _update_index(wiki_root, summary, slug)
    return path


def _update_index(wiki_root: Path, summary: ConcursoResumo, slug: str) -> None:
    index_path = wiki_root / "index.md"
    existing = index_path.read_text(encoding="utf-8") if index_path.exists() else "# WikiEditais\n\n## Concursos\n"
    entry = f"- [{summary.titulo}](concursos/{slug}.md)\n"
    if entry not in existing:
        existing = existing.rstrip() + "\n" + entry
    index_path.write_text(existing, encoding="utf-8")
