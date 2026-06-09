from __future__ import annotations
import re, unicodedata
from pathlib import Path
from .utils import clean_text, write_json
from .config import config

TOPIC_PATTERNS = {
    'capa': r'(edital|concurso|processo seletivo|chamada pública|retifica|errata|comunicado|suspens)',
    'inscricoes': r'(inscri[çc][õo]es?|taxa|isen[çc][ãa]o|boleto|pagamento|cadastro|requerimento)',
    'cargos_vagas': r'(cargos?|empregos?|fun[çc][õo]es?|vagas?|remunera[çc][ãa]o|vencimento|sal[aá]rio|requisitos?|escolaridade|carga hor[áa]ria)',
    'provas_etapas': r'(provas?|objetiva|discursiva|pr[aá]tica|t[ií]tulos|cart[ãa]o|local de prova|gabarito|elimina[çc][ãa]o|classifica[çc][ãa]o|permitido|proibido|caneta|documento)',
    'conteudo_programatico': r'(conte[uú]do program[aá]tico|programa|conhecimentos b[aá]sicos|conhecimentos espec[ií]ficos|disciplinas?|mat[eé]rias?|quest[õo]es)',
    'cronograma': r'(cronograma|calend[aá]rio|datas?|per[ií]odo|prazo|resultado|homologa[çc][ãa]o|divulga[çc][ãa]o)',
    'recursos': r'(recursos?|impugna[çc][ãa]o|gabarito preliminar|resultado preliminar|interpor)',
    'retificacoes': r'(errata|retifica[çc][ãa]o|prorroga[çc][ãa]o|suspens[ãa]o|comunicado|onde se l[eê]|leia-se)',
    'documentos_requisitos': r'(documentos?|requisitos?|posse|contrata[çc][ãa]o|matr[ií]cula|admiss[ãa]o|condi[çc][õo]es)',
}

SECTION_HEADINGS = re.compile(
    r'(?im)^\s*(?:\d+(?:\.\d+)*\s*[\-–—.)]?\s*)?(DAS?\s+[A-ZÁÉÍÓÚÃÕÇ ]{4,}|DOS?\s+[A-ZÁÉÍÓÚÃÕÇ ]{4,}|DA\s+[A-ZÁÉÍÓÚÃÕÇ ]{4,}|DO\s+[A-ZÁÉÍÓÚÃÕÇ ]{4,}|ANEXO\s+[IVXLCDM]+|CRONOGRAMA|CONTE[ÚU]DO PROGRAM[ÁA]TICO|CARGOS?\s+E\s+VAGAS?|RETIFICA[ÇC][ÃA]O|ERRATA|COMUNICADO)\s*$'
)


def _fix_mojibake(text: str) -> str:
    text = clean_text(text or '')
    text = text.replace('ﬁ', 'fi').replace('ﬂ', 'fl')
    # Fix glued words that appear after extraction.
    text = re.sub(r'([a-záéíóúãõç])([A-ZÁÉÍÓÚÃÕÇ])', r'\1 \2', text)
    text = re.sub(r'(recursos)(são|sao)', r'\1 \2', text, flags=re.I)
    text = re.sub(r'(Não haverá)(recursos)', r'\1 \2', text, flags=re.I)
    return text.strip()


def extract_pdf(path: Path, out_dir: Path) -> dict:
    """Extract text from every page quickly with PyMuPDF and tables only from relevant pages.

    pdfplumber is accurate but can be very slow on long public notices. The extractor
    therefore first scans all pages with PyMuPDF, then runs table extraction only on
    pages that look relevant for cargos/vagas/salários/conteúdo/cronograma.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict] = []
    tables: list[dict] = []
    errors: list[str] = []

    try:
        import fitz
        doc = fitz.open(str(path))
        for i, page in enumerate(doc, start=1):
            text = _fix_mojibake(page.get_text('text') or '')
            pages.append({'page': i, 'text': text, 'chars': len(text)})
        doc.close()
    except Exception as e:
        errors.append(f'PyMuPDF falhou: {e}')

    # Identify likely table pages from fast text scan. This keeps indexing scalable.
    table_hint = re.compile(r'(cargo|vagas?|remunera|vencimento|sal[aá]rio|requisito|escolaridade|carga hor[aá]ria|conte[uú]do program[aá]tico|quest[õo]es|cronograma|calend[aá]rio)', re.I)
    candidate_pages = [int(p.get('page')) for p in pages if table_hint.search(p.get('text','')[:8000])]
    max_table_pages = int(config.data.get('indexing', {}).get('pdfplumber_max_pages', 80))
    candidate_pages = candidate_pages[:max_table_pages]

    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            # fallback text if PyMuPDF extracted nothing
            if (not pages or not any(p.get('text') for p in pages)):
                pages = []
                for i, p in enumerate(pdf.pages, start=1):
                    pages.append({'page': i, 'text': _fix_mojibake(p.extract_text() or ''), 'chars': 0})
            for i in candidate_pages:
                if i < 1 or i > len(pdf.pages):
                    continue
                p = pdf.pages[i-1]
                try:
                    for t_idx, table in enumerate(p.extract_tables() or [], start=1):
                        rows = []
                        for row in table or []:
                            cells = [_fix_mojibake(str(c or '')) for c in row]
                            if any(cells):
                                rows.append(cells)
                        if rows:
                            tables.append({'page': i, 'table': t_idx, 'rows': rows, 'columns': max(len(r) for r in rows)})
                except Exception as e:
                    errors.append(f'pdfplumber tabela p.{i} falhou: {e}')
                    continue
    except Exception as e:
        errors.append(f'pdfplumber falhou: {e}')

    write_json(out_dir / 'pages.json', pages)
    write_json(out_dir / 'tables.json', tables)
    write_json(out_dir / 'extract_errors.json', errors)
    (out_dir / 'full_text.txt').write_text(pages_to_text(pages), encoding='utf-8')
    return {'pages': pages, 'tables': tables, 'errors': errors}

def extract_text_file(path: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    text = _fix_mojibake(path.read_text(encoding='utf-8', errors='ignore'))
    pages = [{'page': 1, 'text': text, 'chars': len(text)}]
    tables: list[dict] = []
    write_json(out_dir / 'pages.json', pages)
    write_json(out_dir / 'tables.json', tables)
    (out_dir / 'full_text.txt').write_text(text, encoding='utf-8')
    return {'pages': pages, 'tables': tables, 'errors': []}


def pages_to_text(pages: list[dict]) -> str:
    return '\n\n'.join(f"[PÁGINA {p.get('page')}]\n{p.get('text','')}" for p in pages if p.get('text'))


def classify_text_topic(text: str) -> str:
    low = (text or '').lower()
    best = ('geral', 0)
    for topic, pat in TOPIC_PATTERNS.items():
        score = len(re.findall(pat, low, flags=re.I))
        if score > best[1]:
            best = (topic, score)
    return best[0]


def page_inventory(pages: list[dict]) -> list[dict]:
    inv = []
    for p in pages:
        text = p.get('text') or ''
        head = text[:2500]
        topic = classify_text_topic(head)
        title = ''
        for line in head.splitlines():
            line = clean_text(line)
            if 8 <= len(line) <= 160 and re.search(r'edital|concurso|processo seletivo|anexo|errata|retifica|comunicado|cronograma|conte[uú]do', line, re.I):
                title = line
                break
        inv.append({'page': p.get('page'), 'topic': topic, 'title': title, 'chars': len(text)})
    return inv


def detect_document_parts(pages: list[dict]) -> list[dict]:
    parts = []
    current = None
    for item in page_inventory(pages):
        topic = item['topic']
        p = item['page']
        title = item.get('title') or ''
        typ = None
        low = (title + ' ' + topic).lower()
        if topic == 'retificacoes':
            if 'suspens' in low: typ = 'suspensao'
            elif 'prorroga' in low: typ = 'prorrogacao'
            elif 'errata' in low or 'retifica' in low: typ = 'retificacao'
            else: typ = 'comunicado'
        elif re.search(r'edital|concurso|processo seletivo|chamada', title, re.I):
            typ = 'edital_ou_anexo'
        elif topic == 'conteudo_programatico': typ = 'conteudo_programatico'
        elif topic == 'cargos_vagas': typ = 'cargos_vagas'
        if typ:
            current = {'type': typ, 'start_page': p, 'end_page': p, 'title': title}
            parts.append(current)
        elif current:
            current['end_page'] = p
    return parts


def split_by_headings(page_text: str) -> list[tuple[str, str]]:
    matches = list(SECTION_HEADINGS.finditer(page_text or ''))
    if not matches:
        return []
    out = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(page_text)
        heading = clean_text(m.group(1)).title()
        body = page_text[start:end].strip()
        out.append((heading, body))
    return out


def sectionize(pages: list[dict], tables: list[dict], max_chars: int = 12000, overlap: int = 0) -> list[dict]:
    """Generic section map for any edital. Prefer real headings; fallback to page groups."""
    sections: list[dict] = []
    sid = 1
    for p in pages:
        text = p.get('text') or ''
        page = p.get('page')
        if not text.strip():
            continue
        sub = split_by_headings(text)
        if sub:
            for heading, body in sub:
                topic = classify_text_topic(heading + '\n' + body[:3000])
                # chunk long bodies but keep heading
                chunks = [body[i:i+max_chars] for i in range(0, len(body), max_chars)] or [body]
                for j, chunk in enumerate(chunks):
                    sections.append({'id': sid, 'topic': topic, 'title': heading, 'start_page': page, 'end_page': page, 'text': f'[PÁGINA {page}]\n## {heading}\n{chunk}'})
                    sid += 1
        else:
            topic = classify_text_topic(text[:4000])
            chunks = [text[i:i+max_chars] for i in range(0, len(text), max_chars)] or [text]
            for chunk in chunks:
                sections.append({'id': sid, 'topic': topic, 'title': f'Página {page}', 'start_page': page, 'end_page': page, 'text': f'[PÁGINA {page}]\n{chunk}'})
                sid += 1

    # Tables become first-class sections; not tied to one example PDF.
    for t in tables:
        rows = t.get('rows') or []
        if not rows: continue
        text = '[TABELA p.%s]\n' % t.get('page') + '\n'.join(' | '.join(r) for r in rows[:160])
        low = text.lower()
        if any(x in low for x in ['cargo', 'vagas', 'vencimento', 'salário', 'remuneração', 'requisito']):
            topic = 'cargos_vagas'
        elif any(x in low for x in ['conteúdo', 'programático', 'questões', 'disciplina']):
            topic = 'conteudo_programatico'
        elif any(x in low for x in ['cronograma', 'data', 'período', 'resultado']):
            topic = 'cronograma'
        else:
            topic = classify_text_topic(text)
        sections.append({'id': sid, 'topic': topic, 'title': f'Tabela {t.get("table")} p.{t.get("page")}', 'start_page': t.get('page'), 'end_page': t.get('page'), 'text': text[:max_chars], 'table': True})
        sid += 1
    return sections
