
from __future__ import annotations
import re
from typing import Any

CONTENT_MARKERS = re.compile(
    r"conte[uú]do\s+program[aá]tico|conte[uú]dos\s+program[aá]ticos|programa\s+de\s+prova|conhecimentos\s+b[aá]sicos|conhecimentos\s+espec[ií]ficos",
    re.I,
)
DISCIPLINE_RE = re.compile(
    r"^(?:\d+\.?\s*)?(l[ií]ngua\s+portuguesa|portugu[eê]s|matem[aá]tica|racioc[ií]nio\s+l[oó]gico|inform[aá]tica|legisla[cç][aã]o|conhecimentos\s+gerais|conhecimentos\s+b[aá]sicos|conhecimentos\s+espec[ií]ficos|atualidades|direito\s+constitucional|direito\s+administrativo|sa[uú]de\s+p[uú]blica|ética|administra[cç][aã]o\s+p[uú]blica)\b\s*[:\-–]?(.*)$",
    re.I,
)
CARGO_CONTENT_RE = re.compile(r"^(?:cargo|fun[cç][aã]o|emprego)\s*[:\-–]\s*(.+)$", re.I)
NOISE_RE = re.compile(r"^(anexo|p[aá]gina|edital|concurso|processo seletivo|prefeitura|munic[ií]pio|universidade|comiss[aã]o)\b", re.I)


def _clean(line: str) -> str:
    line = re.sub(r"\s+", " ", line or "").strip(" \t-–•●▪▫")
    line = re.sub(r"^\d+(?:\.\d+){0,4}\s*[-.)]?\s*", "", line)
    line = re.sub(r"^[a-z]\)\s*", "", line, flags=re.I)
    return line.strip()


def _split_topics(text: str) -> list[str]:
    parts: list[str] = []
    # First split by semicolon because many syllabi are written in one long line.
    for piece in re.split(r";|\u2022|•", text):
        piece = _clean(piece)
        if not piece:
            continue
        # Also split very long comma-heavy lines into smaller readable topic groups only when safe.
        if len(piece) > 220 and piece.count(',') >= 4:
            sub = [_clean(x) for x in piece.split(',')]
            parts.extend([x for x in sub if 6 <= len(x) <= 160])
        else:
            parts.append(piece)
    return parts


def _looks_like_topic(line: str) -> bool:
    if not (5 <= len(line) <= 220):
        return False
    if NOISE_RE.search(line) and len(line) < 80:
        return False
    if re.search(r"inscri[cç][aã]o|cronograma|homologa[cç][aã]o|resultado|recurso|taxa|boleto", line, re.I):
        return False
    # Prefer concrete syllabus nouns.
    if re.search(r"texto|interpreta[cç][aã]o|ortografia|acentua[cç][aã]o|pontua[cç][aã]o|concord[aâ]ncia|reg[eê]ncia|crase|porcentagem|fra[cç][oõ]es|equa[cç][oõ]es|racioc[ií]nio|windows|word|excel|internet|constitui[cç][aã]o|lei|licita[cç][aã]o|administra[cç][aã]o|[eé]tica|sa[uú]de|seguran[cç]a|tr[aâ]nsito|primeiros socorros", line, re.I):
        return True
    # Numbered/short list items after a discipline are acceptable.
    return bool(re.search(r"[,;]", line))


def _add_section(sections: list[dict[str, Any]], title: str, topics: list[str], source: dict[str, Any]):
    seen = set()
    clean_topics = []
    for t in topics:
        t = _clean(t)
        key = t.lower()
        if key in seen or not _looks_like_topic(t):
            continue
        seen.add(key)
        clean_topics.append(t)
        if len(clean_topics) >= 40:
            break
    if clean_topics:
        sections.append({
            'titulo': title[:140] or 'Conteúdo programático',
            'topicos': clean_topics,
            'pagina': source.get('page_start') or source.get('page'),
            'fonte': source.get('id'),
        })


def extract_content_programatico(chunks: list[dict], tables: list[dict]) -> dict[str, Any]:
    """Return public-safe structured syllabus content: no raw chunks exposed."""
    sections: list[dict[str, Any]] = []
    # 1) Tables explicitly classified as content.
    content_tables = [t for t in tables if t.get('kind') == 'conteudo_programatico' and not t.get('ignored')]
    for t in content_tables[:8]:
        headers = t.get('headers') or []
        topics_by_title: dict[str, list[str]] = {}
        for row in (t.get('rows') or [])[:80]:
            vals = [str(row.get(h, '')).strip() for h in headers]
            vals = [v for v in vals if v]
            if not vals:
                continue
            joined = ' — '.join(vals)
            title = 'Conteúdo programático'
            for v in vals[:2]:
                m = DISCIPLINE_RE.match(_clean(v))
                if m:
                    title = _clean(m.group(1)).title()
                    if m.group(2):
                        joined = m.group(2)
                    break
            topics_by_title.setdefault(title, []).extend(_split_topics(joined))
        for title, topics in topics_by_title.items():
            _add_section(sections, title, topics, {'id': t.get('id'), 'page': t.get('page')})

    # 2) Text chunks. We parse only candidates around syllabus markers.
    candidates = []
    for c in chunks:
        probe = f"{c.get('section','')}\n{c.get('text','')}"
        if c.get('kind') == 'conteudo' or CONTENT_MARKERS.search(probe):
            candidates.append(c)

    for c in candidates[:18]:
        text = c.get('text', '')
        lines = [_clean(x) for x in text.splitlines()]
        current_title = None
        current_topics: list[str] = []
        source = {'id': c.get('id'), 'page_start': c.get('page_start')}

        def flush():
            nonlocal current_title, current_topics
            if current_title and current_topics:
                _add_section(sections, current_title, current_topics, source)
            current_topics = []

        for line in lines:
            if len(line) < 3:
                continue
            cargo_match = CARGO_CONTENT_RE.match(line)
            disc_match = DISCIPLINE_RE.match(line)
            if cargo_match:
                flush()
                current_title = 'Conhecimentos específicos — ' + _clean(cargo_match.group(1))[:90]
                continue
            if disc_match:
                flush()
                base = _clean(disc_match.group(1)).title()
                current_title = base
                rest = _clean(disc_match.group(2) or '')
                if rest:
                    current_topics.extend(_split_topics(rest))
                continue
            if CONTENT_MARKERS.search(line) and len(line) < 120:
                # Marker only. Do not show it as topic.
                if not current_title:
                    current_title = 'Conteúdo programático'
                continue
            if current_title:
                current_topics.extend(_split_topics(line))
        flush()

    # Merge same section titles.
    merged: dict[str, dict[str, Any]] = {}
    for sec in sections:
        title = sec['titulo']
        slot = merged.setdefault(title, {'titulo': title, 'topicos': [], 'pagina': sec.get('pagina'), 'fonte': sec.get('fonte')})
        seen = {x.lower() for x in slot['topicos']}
        for t in sec.get('topicos') or []:
            if t.lower() not in seen:
                slot['topicos'].append(t)
                seen.add(t.lower())
        if not slot.get('pagina') and sec.get('pagina'):
            slot['pagina'] = sec.get('pagina')
    final = [v for v in merged.values() if v.get('topicos')]
    # Keep it readable on public page.
    for sec in final:
        sec['topicos'] = sec['topicos'][:35]
    return {'sections': final[:12], 'tables_count': len(content_tables)}
