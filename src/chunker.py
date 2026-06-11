from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from pathlib import Path
import json


SECTION_RE = re.compile(
    r"(?m)^(\d+(?:\.\d+)*\s*[-–.]?\s+.+|[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9\s,;:()\-/]{8,})$"
)


@dataclass
class Chunk:
    id: str
    order: int
    section: str
    page_start: int | None
    page_end: int | None
    text: str
    char_count: int
    kind: str = "geral"


def _count_hits(low: str, words: list[str]) -> int:
    return sum(1 for w in words if w in low)


def _guess_kind(text: str) -> str:
    low = text.lower()
    # Priority-based classification to avoid "conteúdo por cargo" becoming "cargos_vagas".
    if _count_hits(low, ["conteúdo programático", "conhecimentos básicos", "conhecimentos específicos", "programa de prova"]):
        return "conteudo"
    if _count_hits(low, ["cronograma", "calendário", "anexo", "atividade", "data"] ) >= 2 and _count_hits(low, ["inscri", "resultado", "prova", "recurso", "gabarito", "publicação"]):
        return "cronograma"
    if _count_hits(low, ["quadro de vagas", "cód.", "código", "cargo", "vagas", "remuneração", "salário", "requisito", "lotação", "município de atuação"]) >= 2:
        return "cargos_vagas"
    if _count_hits(low, ["inscrição", "inscrições", "taxa", "boleto", "isenção", "pagamento", "cadastro"]):
        return "inscricao"
    if _count_hits(low, ["prova objetiva", "prova discursiva", "títulos", "taf", "etapa", "eliminatório", "classificatório"]):
        return "etapas"
    if _count_hits(low, ["recurso", "impugnação", "gabarito", "interposição"]):
        return "recursos"
    return "geral"


def _page_number_near(text: str) -> tuple[int | None, int | None]:
    pages = [int(x) for x in re.findall(r"<!--\s*page:(\d+)\s*-->", text)]
    if not pages:
        return None, None
    return min(pages), max(pages)


def _split_long_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        window = text[start:end]
        cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("; "))
        if cut > int(max_chars * 0.55):
            end = start + cut + 1
            window = text[start:end]
        parts.append(window.strip())
        if end >= len(text):
            break
        start = max(0, end - overlap_chars)
    return [p for p in parts if p]


def _merge_tiny_sections(sections: list[tuple[str, str]], min_chars: int = 350) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
    pending_title: str | None = None
    pending_body = ""
    for title, body in sections:
        body = body.strip()
        if not body:
            continue
        if len(body) < min_chars:
            if pending_body:
                pending_body = pending_body.rstrip() + "\n" + body
            else:
                pending_title = title
                pending_body = body
            continue
        if pending_body:
            merged.append((pending_title or title, pending_body.rstrip() + "\n" + body))
            pending_body = ""
            pending_title = None
        else:
            merged.append((title, body))
    if pending_body:
        merged.append((pending_title or "Trecho curto", pending_body))
    return merged


def chunk_markdown(markdown: str, edital_id: str, max_chars: int = 4800, overlap_chars: int = 350) -> list[Chunk]:
    """Semantic-ish chunking: sections first, fixed max size second.

    Important rule: bigger edital => more chunks, never unbounded larger chunks.
    Tiny sections are merged so the retrieval index is not polluted by empty headings.
    """
    lines = markdown.splitlines()
    sections: list[tuple[str, str]] = []
    current_title = "Início do edital"
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        is_title = bool(SECTION_RE.match(stripped)) and len(stripped) < 160 and not stripped.startswith("<!-- page:")
        if is_title and current_lines:
            sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = stripped
            current_lines = [line]
        else:
            if is_title:
                current_title = stripped
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))

    sections = _merge_tiny_sections(sections)
    chunks: list[Chunk] = []
    order = 1
    for title, body in sections:
        for part in _split_long_text(body, max_chars=max_chars, overlap_chars=overlap_chars):
            if len(part.strip()) < 120:
                continue
            page_start, page_end = _page_number_near(part)
            chunk = Chunk(
                id=f"{edital_id}-chunk-{order:04d}",
                order=order,
                section=title[:140],
                page_start=page_start,
                page_end=page_end,
                text=part,
                char_count=len(part),
                kind=_guess_kind(part),
            )
            chunks.append(chunk)
            order += 1
    return chunks


def save_chunks(chunks: list[Chunk], output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps([asdict(c) for c in chunks], ensure_ascii=False, indent=2), encoding="utf-8")
