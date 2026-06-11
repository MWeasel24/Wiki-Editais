from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF


@dataclass
class ExtractedTable:
    id: str
    page: int
    order: int
    kind: str
    title_guess: str | None
    headers: list[str]
    rows: list[dict[str, str]]
    raw_rows: list[list[str]] = field(default_factory=list)
    ignored: bool = False
    ignore_reason: str | None = None
    inherited_from: str | None = None
    confidence: str = "media"
    scores: dict[str, int] = field(default_factory=dict)


def strip_accents(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def norm_cell(value: Any) -> str:
    if value is None:
        return ""
    value = str(value).replace("\x00", " ")
    value = re.sub(r"([A-Za-zÀ-ÿ])\s*-\s+([A-Za-zÀ-ÿ])", r"\1\2", value)
    return re.sub(r"\s+", " ", value).strip()


def canon(value: str) -> str:
    low = strip_accents(norm_cell(value)).lower()
    low = re.sub(r"[^a-z0-9]+", "_", low).strip("_")
    return low


def canonical_header(value: str, index: int) -> str:
    raw = norm_cell(value).strip(" .:-–—")[:90]
    c = canon(raw)
    if not c:
        return f"coluna_{index + 1}"
    mappings: list[tuple[tuple[str, ...], str]] = [
        (("item", "codigo", "cod", "n", "numero"), "item"),
        (("cargo", "emprego", "funcao", "funcao_publica"), "cargo"),
        (("municipio", "lotacao", "localidade", "atuacao", "local_de_atuacao"), "municipio_lotacao"),
        (("vagas", "vaga", "total_de_vagas"), "vagas"),
        (("ampla_concorrencia", "ampla", "ac"), "ampla_concorrencia"),
        (("pcd", "deficiencia"), "pcd"),
        (("ppp", "preto", "pardo", "negro"), "cotas_ppp"),
        (("pind", "indigena"), "cotas_indigena"),
        (("pqui", "quilombola"), "cotas_quilombola"),
        (("carga_horaria", "carga", "jornada", "horaria", "ch"), "carga_horaria"),
        (("remuneracao", "remuneracao_inicial", "salario", "vencimento", "vencimentos", "subsidio"), "remuneracao"),
        (("requisito", "requisitos", "escolaridade", "formacao", "habilitacao", "exigencia"), "requisito"),
        (("atividade", "evento", "etapa", "descricao", "procedimento"), "evento"),
        (("inicio",), "inicio"),
        (("fim", "termino"), "fim"),
        (("data", "periodo", "prazo"), "data_ou_periodo"),
        (("disciplina", "area", "materia", "conteudo"), "disciplina"),
        (("questoes", "questao", "numero_de_questoes"), "questoes"),
        (("pontos", "pontuacao", "peso", "valor", "nota"), "pontuacao"),
        (("taxa", "valor_da_taxa", "valor_inscricao"), "taxa"),
    ]
    for needles, label in mappings:
        for n in needles:
            if len(n) <= 3:
                if n == c:
                    return label
            elif n == c or n in c:
                return label
    return raw or f"coluna_{index + 1}"


def unique_headers(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, h in enumerate(headers):
        base = canonical_header(h, i)
        key = base.lower()
        if key in seen:
            seen[key] += 1
            base = f"{base}_{seen[key]}"
        else:
            seen[key] = 1
        out.append(base)
    return out


def rows_from_raw(raw_rows: list[list[str]], headers: list[str], start_idx: int = 0) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw_row in raw_rows[start_idx:]:
        if not any(raw_row):
            continue
        padded = raw_row + [""] * max(0, len(headers) - len(raw_row))
        row = {headers[i]: norm_cell(padded[i]) for i in range(len(headers))}
        if any(row.values()):
            rows.append(row)
    return rows


def blob(headers: list[str], rows: list[dict[str, str]], title_guess: str | None = None, limit: int = 16) -> str:
    text = " ".join(headers + ([title_guess] if title_guess else []))
    text += " " + " ".join(" ".join(row.values()) for row in rows[:limit])
    return strip_accents(text).lower()


def count_any(low: str, terms: list[str]) -> int:
    return sum(1 for term in terms if term in low)




def is_low_value_table(headers: list[str], rows: list[dict[str, str]], scores: dict[str, int]) -> bool:
    """Descarta tabelas degeneradas geradas pelo PDF: 1 linha, quase vazias e sem sinal útil.

    Mantém tabelas de uma linha quando elas têm evidência forte, por exemplo taxa,
    cronograma compacto ou uma linha real de cargo.
    """
    if not rows:
        return True
    cells = [norm_cell(v) for row in rows for v in row.values() if norm_cell(v)]
    if not cells:
        return True
    text = strip_accents(" ".join(headers + cells)).lower()
    useful_score = max([scores.get(k, 0) for k in [
        "quadro_de_vagas", "cronograma", "taxas", "conteudo_programatico",
        "pontuacao_prova", "avaliacao_titulos", "formulario"
    ]] or [0])
    # Uma linha curta sem evidência forte costuma ser artefato de layout.
    if len(rows) <= 1 and (len(cells) <= 4 or len(text) < 140) and useful_score < 6:
        return True
    # Linhas compostas só por numeração, separadores ou fragmentos muito curtos.
    alpha_chars = len(re.findall(r"[a-zA-ZÀ-ÿ]", text))
    digit_chars = len(re.findall(r"\d", text))
    if len(rows) <= 1 and alpha_chars < 18 and digit_chars < 8 and useful_score < 8:
        return True
    return False


def score_table(headers: list[str], rows: list[dict[str, str]], title_guess: str | None = None) -> dict[str, int]:
    low = blob(headers, rows, title_guess)
    header_low = strip_accents(" ".join(headers)).lower()
    scores = {
        "quadro_de_vagas": 0,
        "cronograma": 0,
        "taxas": 0,
        "conteudo_programatico": 0,
        "pontuacao_prova": 0,
        "avaliacao_titulos": 0,
        "formulario": 0,
        "tabela_irrelevante": 0,
    }

    # Formulario/anexo evidence. These should defeat weak cargo evidence such as "cargo para o qual concorre".
    form_terms = ["cpf", "rg", "telefone", "e_mail", "email", "endereco", "assinatura", "foto 3x4", "campo para foto", "data de nascimento", "filiacao", "estado civil", "naturalidade", "documento de identificacao", "nome do candidato", "nome completo", "procurador", "declaro", "declaracao", "requerimento", "laudo medico", "condicao especial", "pedido de isencao"]
    scores["formulario"] += 2 * count_any(low, form_terms)
    if "cargo para o qual concorre" in low:
        scores["formulario"] += 4

    # Titles and scoring tables.
    tit_terms = ["titulo de mestre", "titulo de doutor", "doutorado", "mestrado", "especializacao", "pos graduacao", "pós graduação", "lato sensu", "stricto sensu", "diploma", "certificado", "avaliacao de titulos", "avaliação de títulos", "prova de titulos", "prova de títulos"]
    scores["avaliacao_titulos"] += 3 * count_any(low, [strip_accents(t).lower() for t in tit_terms])
    if "cargo/funcao" in low or "cargo funcao" in low:
        scores["avaliacao_titulos"] += 2
    if any(x in low for x in ["pontuacao", "pontos", "nota", "valor"]):
        scores["avaliacao_titulos"] += 1

    # Strong quadro evidence: require multiple structural signs, not just "cargo".
    if "quadro de vagas" in low or "das vagas" in low:
        scores["quadro_de_vagas"] += 7
    if "cargo" in header_low or "emprego" in header_low or "funcao" in header_low:
        scores["quadro_de_vagas"] += 3
    scores["quadro_de_vagas"] += 2 * count_any(header_low, ["vagas", "remuneracao", "salario", "vencimento", "carga_horaria", "requisito", "escolaridade"])
    scores["quadro_de_vagas"] += count_any(low, ["cadastro reserva", " cr ", "ensino medio", "ensino fundamental", "ensino superior", "carga horaria", "remuneracao", "salario", "vencimento", "requisito"])
    # Row-like evidence: a line with cargo-ish words plus vacancy/money/workload.
    row_hits = 0
    for row in rows[:30]:
        r = strip_accents(" ".join(row.values())).lower()
        has_role = bool(re.search(r"\b(assistente|agente|auxiliar|analista|professor|tecnico|motorista|operador|enfermeiro|medico|contador|administrador|advogado|gari|fiscal)\b", r))
        has_quant = bool(re.search(r"\b(cr|\d+\s*\+\s*cr|\d{1,4})\b", r)) or "r$" in r or "40h" in r or "20h" in r
        if has_role and has_quant:
            row_hits += 1
    scores["quadro_de_vagas"] += min(row_hits * 2, 10)

    # Cronogram evidence.
    if "cronograma" in low:
        scores["cronograma"] += 7
    scores["cronograma"] += 2 * count_any(header_low, ["atividade", "evento", "data_ou_periodo", "inicio", "fim", "periodo", "prazo"])
    scores["cronograma"] += 2 * count_any(low, ["publicacao do edital", "impugnacao", "inscric", "resultado", "recurso", "gabarito", "homologacao", "convocacao", "pagamento", "isencao"])
    if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", low) and any(x in low for x in ["prova", "resultado", "recurso", "inscri", "publicacao", "gabarito"]):
        scores["cronograma"] += 4

    # Taxa evidence.
    scores["taxas"] += 4 * count_any(low, ["taxa de inscricao", "valor da inscricao", "valor da taxa", "boleto", "pagamento da inscricao"])
    if "taxa" in header_low and "r$" in low:
        scores["taxas"] += 4

    # Content/proof score.
    scores["conteudo_programatico"] += 4 * count_any(low, ["conteudo programatico", "conhecimentos basicos", "conhecimentos especificos", "programa de prova"])
    scores["pontuacao_prova"] += 3 * count_any(low, ["disciplina", "questoes", "prova objetiva", "prova pratica", "peso", "pontuacao", "total de pontos"])
    if "disciplina" in header_low and ("questoes" in header_low or "pontuacao" in header_low or "peso" in header_low):
        scores["pontuacao_prova"] += 5

    values = [v for row in rows for v in row.values() if v]
    if values and len(values) <= 4 and max(scores.values()) < 5:
        scores["tabela_irrelevante"] += 5

    # Negative corrections.
    if scores["formulario"] >= 8 and row_hits == 0:
        scores["quadro_de_vagas"] -= 6
    if scores["avaliacao_titulos"] >= 6:
        scores["quadro_de_vagas"] -= 5
    return scores


def guess_table_kind(headers: list[str], rows: list[dict[str, str]], title_guess: str | None = None) -> tuple[str, dict[str, int], str]:
    scores = score_table(headers, rows, title_guess)
    ordered = [
        "avaliacao_titulos",
        "quadro_de_vagas",
        "cronograma",
        "taxas",
        "conteudo_programatico",
        "pontuacao_prova",
        "formulario",
        "tabela_irrelevante",
    ]
    best = max(ordered, key=lambda k: scores.get(k, 0))
    best_score = scores.get(best, 0)

    # Explicit priority rules to avoid false positives.
    # Cronograma and quadro_de_vagas can mention prova/títulos/formulário terms,
    # so they win when their structural score is clearly stronger.
    if scores["quadro_de_vagas"] >= 7 and scores["quadro_de_vagas"] >= scores["formulario"] and scores["quadro_de_vagas"] >= scores["avaliacao_titulos"]:
        best = "quadro_de_vagas"
    elif scores["cronograma"] >= 7 and scores["cronograma"] >= scores["avaliacao_titulos"] and scores["cronograma"] >= scores["formulario"]:
        best = "cronograma"
    elif scores["avaliacao_titulos"] >= 6 and scores["avaliacao_titulos"] >= scores["quadro_de_vagas"] - 1:
        best = "avaliacao_titulos"
    elif scores["formulario"] >= 8 and scores["quadro_de_vagas"] < 8 and scores["cronograma"] < 8:
        best = "formulario"
    elif scores["taxas"] >= 5:
        best = "taxas"
    elif scores["conteudo_programatico"] >= 5:
        best = "conteudo_programatico"
    elif scores["pontuacao_prova"] >= 6:
        best = "pontuacao_prova"
    elif scores["formulario"] >= 6:
        best = "formulario"
    elif scores["tabela_irrelevante"] >= 5:
        best = "tabela_irrelevante"
    elif best_score < 5:
        best = "tabela_desconhecida"

    conf = "alta" if scores.get(best, 0) >= 10 else "media" if scores.get(best, 0) >= 6 else "baixa"
    return best, scores, conf


def title_guess_from_page_text(page_text: str, table_index: int) -> str | None:
    lines = [norm_cell(line) for line in page_text.splitlines() if norm_cell(line)]
    candidates: list[str] = []
    for line in lines[:80]:
        if len(line) < 8 or len(line) > 180:
            continue
        if re.search(r"cronograma|quadro|cargo|vagas|conteúdo|programático|inscri|taxa|prova|anexo|formul|títulos|pontuação|processo seletivo", line, re.I):
            candidates.append(line)
    if candidates:
        return candidates[min(table_index, len(candidates) - 1)]
    return None


def looks_like_header(row: list[str]) -> bool:
    b = strip_accents(" ".join(row)).lower()
    return bool(re.search(r"cargo|vaga|remuneracao|requisito|atividade|evento|data|periodo|questoes|disciplina|inicio|fim|pontuacao|taxa", b))


def post_process_tables(tables: list[ExtractedTable]) -> list[ExtractedTable]:
    processed: list[ExtractedTable] = []
    last_useful: ExtractedTable | None = None
    inheritable = {"quadro_de_vagas", "cronograma", "pontuacao_prova", "conteudo_programatico", "avaliacao_titulos"}
    for table in tables:
        kind, scores, confidence = guess_table_kind(table.headers, table.rows, table.title_guess)
        table.kind, table.scores, table.confidence = kind, scores, confidence

        if table.kind == "tabela_desconhecida" and last_useful and last_useful.kind in inheritable:
            # If the table follows immediately and has compatible width, treat it as continuation.
            width_ok = abs(len(table.headers) - len(last_useful.headers)) <= 3
            next_page = table.page in {last_useful.page, last_useful.page + 1}
            if width_ok and next_page:
                table.kind = last_useful.kind
                table.inherited_from = last_useful.id
                table.headers = last_useful.headers
                table.rows = rows_from_raw(table.raw_rows, table.headers, 0)
                table.confidence = "media"
                _, table.scores, _ = guess_table_kind(table.headers, table.rows, table.title_guess)

        if table.kind in {"formulario", "tabela_irrelevante"}:
            table.ignored = True
            table.ignore_reason = "Tabela classificada como formulário/anexo ou sem utilidade direta para a extração principal."
        elif table.kind == "avaliacao_titulos":
            # Useful for the wiki, but not for cargo extraction.
            table.ignored = False
        else:
            table.ignored = False

        if not table.ignored and table.kind != "tabela_desconhecida":
            last_useful = table
        processed.append(table)
    return processed


def extract_tables_from_pdf(pdf_path: str | Path, edital_id: str, progress=None) -> list[ExtractedTable]:
    pdf_path = Path(pdf_path)
    doc = fitz.open(pdf_path)
    total_pages = len(doc) or 1
    tables: list[ExtractedTable] = []
    for page_index, page in enumerate(doc, start=1):
        if progress:
            progress(page_index, total_pages)
        page_text = page.get_text("text") or ""
        try:
            found = page.find_tables()
        except Exception:
            found = None
        if not found or not getattr(found, "tables", None):
            continue
        for order, table in enumerate(found.tables, start=1):
            try:
                raw = table.extract()
            except Exception:
                continue
            raw_rows: list[list[str]] = [[norm_cell(cell) for cell in row] for row in raw if row]
            raw_rows = [row for row in raw_rows if any(row)]
            if not raw_rows:
                continue
            start_idx = 0
            if looks_like_header(raw_rows[0]):
                headers = unique_headers(raw_rows[0])
                start_idx = 1
            else:
                max_cols = max(len(r) for r in raw_rows)
                headers = [f"coluna_{i + 1}" for i in range(max_cols)]
            rows = rows_from_raw(raw_rows, headers, start_idx)
            if not rows:
                continue
            title = title_guess_from_page_text(page_text, order - 1)
            kind, scores, confidence = guess_table_kind(headers, rows, title)
            if is_low_value_table(headers, rows, scores):
                continue
            tables.append(ExtractedTable(
                id=f"{edital_id}-p{page_index:03d}-{order:02d}",
                page=page_index,
                order=order,
                kind=kind,
                title_guess=title,
                headers=headers,
                rows=rows,
                raw_rows=raw_rows,
                confidence=confidence,
                scores=scores,
            ))
    return post_process_tables(tables)


def save_tables(tables: list[ExtractedTable], json_path: str | Path, md_path: str | Path) -> None:
    json_path = Path(json_path)
    md_path = Path(md_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    data = [t.__dict__ for t in tables]
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    lines: list[str] = []
    for t in tables:
        flags = []
        if t.ignored:
            flags.append("ignorada")
        if t.inherited_from:
            flags.append(f"continuação de {t.inherited_from}")
        flag = f" ({'; '.join(flags)})" if flags else ""
        lines.append(f"## {t.id} — {t.kind} — página {t.page}{flag}\n")
        if t.title_guess:
            lines.append(f"**Título provável:** {t.title_guess}\n")
        lines.append(f"**Confiança:** {t.confidence}\n")
        if t.ignore_reason:
            lines.append(f"**Motivo:** {t.ignore_reason}\n")
        if t.headers:
            lines.append("| " + " | ".join(t.headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(t.headers)) + " |")
            for row in t.rows[:80]:
                lines.append("| " + " | ".join(str(row.get(h, "")).replace("|", "/") for h in t.headers) + " |")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
