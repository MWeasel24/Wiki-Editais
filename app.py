from __future__ import annotations
import json
import re
import threading
import time
import shutil
import uuid
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from werkzeug.utils import secure_filename
try:
    from slugify import slugify
except Exception:
    import unicodedata
    def slugify(value: str) -> str:
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
        return re.sub(r"[^a-z0-9]+", "-", value).strip("-")

from src.pdf_extract import extract_pdf_text, save_extracted_markdown
from src.table_extractor import extract_tables_from_pdf, save_tables
from src.clean_text import clean_text
from src.chunker import chunk_markdown
from src.extractors import extract_summary
from src.schemas import ConcursoResumo
from src.wiki_builder import build_concurso_markdown
from src.retriever import answer_hybrid
from src.vector_store import rebuild_vector_index
from src.semantic_wiki import build_semantic_wiki, load_semantic_manifest, read_semantic_page
from src.content_extractor import extract_content_programatico
from src.evaluator import load_evaluation, load_all_evaluations, EXAMPLE as EVALUATION_EXAMPLE

ROOT = Path(__file__).parent
DATA = ROOT / "data"
RAW_DIR = DATA / "raw" / "editais"
EXTRACTED_DIR = DATA / "extracted"
CHUNKS_DIR = DATA / "chunks"
JSON_DIR = DATA / "json"
TABLES_DIR = DATA / "tables"
EVAL_DIR = DATA / "avaliacoes"
CONTENT_LLM_DIR = DATA / "conteudo_llm"
WIKI_DIR = ROOT / "wiki"

app = Flask(__name__)
app.secret_key = "wikieditais-dev"

for folder in [RAW_DIR, EXTRACTED_DIR, CHUNKS_DIR, JSON_DIR, TABLES_DIR, EVAL_DIR, CONTENT_LLM_DIR, WIKI_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

JOBS: dict[str, dict] = {}

def render_markdown(md_text: str) -> str:
    """Render Markdown safely enough for local academic demo.

    If markdown2 is unavailable, the caller can still show plain Markdown.
    """
    try:
        import markdown2
        return markdown2.markdown(md_text or '', extras=['tables', 'fenced-code-blocks', 'strike', 'cuddled-lists'])
    except Exception:
        import html
        return '<pre class="markdown-view">' + html.escape(md_text or '') + '</pre>'

def _progress(job_id: str | None, pct: int, etapa: str, detalhe: str = '') -> None:
    if not job_id:
        return
    job = JOBS.setdefault(job_id, {})
    job.update({
        'pct': max(0, min(100, int(pct))),
        'etapa': etapa,
        'detalhe': detalhe,
        'updated_at': time.time(),
    })

def _stage_progress(job_id: str | None, start: int, end: int, etapa: str):
    def cb(current: int, total: int):
        total = max(total, 1)
        pct = start + ((end - start) * current / total)
        _progress(job_id, int(pct), etapa, f'{current}/{total} páginas')
    return cb


def read_config() -> dict:
    """Tiny YAML-ish reader for config.yaml without requiring PyYAML."""
    path = ROOT / "config.yaml"
    cfg: dict = {}
    current: str | None = None
    if not path.exists():
        return cfg
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if not raw.startswith(" ") and raw.rstrip().endswith(":"):
            current = raw.strip()[:-1]
            cfg[current] = {}
            continue
        if current and raw.startswith(" ") and ":" in raw:
            k, v = raw.strip().split(":", 1)
            v = v.strip().strip('"\'')
            if v.lower() in {"true", "false"}:
                value = v.lower() == "true"
            else:
                value = v
            cfg[current][k] = value
        elif ":" in raw:
            k, v = raw.split(":", 1)
            cfg[k.strip()] = v.strip().strip('"\'')
    return cfg


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: dict | list):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_concursos():
    items = []
    for path in sorted(JSON_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        items.append(_load_json(path))
    return items


def _summary_path(edital_id: str) -> Path:
    return JSON_DIR / f"{edital_id}.json"


def _chunks_path(edital_id: str) -> Path:
    return CHUNKS_DIR / f"{edital_id}.json"


def _tables_path(edital_id: str) -> Path:
    return TABLES_DIR / f"{edital_id}.tables.json"




BAD_CARGO_NAME_PATTERNS = [
    r"^ensino\s+(fundamental|m[eé]dio|superior)\b",
    r"^curso\s+(t[eé]cnico|superior|de)\b",
    r"^registro\s+no\s+conselho\b",
    r"^gradua[cç][aã]o\b",
    r"^experi[eê]ncia\b",
    r"^habilita[cç][aã]o\b",
]

def _looks_like_requirement_name(name: str | None) -> bool:
    text = (name or '').strip().lower()
    if not text:
        return True
    if len(text) > 115 and any(x in text for x in ['ensino', 'curso', 'registro', 'conselho', 'habilitação', 'cnh']):
        return True
    return any(re.search(p, text, re.I) for p in BAD_CARGO_NAME_PATTERNS)


def _apply_runtime_quality(summary: dict) -> dict:
    """Conservative final guard used by the UI/chat.

    It does not delete extracted data; it marks obvious false cargo names as
    suspicious so they leave public counts/results and remain visible in Debug.
    """
    cargos = summary.get('cargos') or []
    changed = False
    for c in cargos:
        if _looks_like_requirement_name(c.get('nome')):
            c['suspeito'] = True
            c['confianca'] = 'baixa'
            c['motivo_suspeita'] = c.get('motivo_suspeita') or 'nome parece requisito/escolaridade, não cargo'
            changed = True
    if changed:
        q = summary.setdefault('qualidade', {})
        try:
            q['cargos_suspeitos'] = max(int(q.get('cargos_suspeitos') or 0), sum(1 for c in cargos if c.get('suspeito')))
        except Exception:
            q['cargos_suspeitos'] = sum(1 for c in cargos if c.get('suspeito'))
    return summary

def _load_bundle(edital_id: str):
    summary_path = _summary_path(edital_id)
    if not summary_path.exists():
        return None, [], []
    summary = _apply_runtime_quality(_load_json(summary_path))
    chunks = _load_json(_chunks_path(edital_id)) if _chunks_path(edital_id).exists() else []
    tables = _load_json(_tables_path(edital_id)) if _tables_path(edital_id).exists() else []
    return summary, chunks, tables


def _find_raw_pdf(edital_id: str) -> Path | None:
    for pdf in RAW_DIR.glob("*.pdf"):
        if slugify(pdf.stem)[:80] == edital_id:
            return pdf
    return None


def _remove_vector_entries(edital_id: str) -> str:
    """Remove entradas vetoriais do edital quando ChromaDB estiver disponível.

    A exclusão do edital não deve quebrar se o banco vetorial não estiver instalado
    ou se o Ollama/Chroma não estiverem ativos.
    """
    try:
        cfg = read_config()
        rag_cfg = cfg.get('rag') or {}
        persist_dir = ROOT / (rag_cfg.get('persist_dir') or 'data/vectorstore')
        if not persist_dir.exists():
            return 'sem vectorstore'
        import chromadb
        client = chromadb.PersistentClient(path=str(persist_dir))
        collection = client.get_or_create_collection(name='wikieditais')
        collection.delete(where={'edital_id': edital_id})
        return 'vetores removidos'
    except Exception as exc:
        return f'vetores não removidos: {exc}'


def nuclear_delete_edital(edital_id: str) -> dict:
    """Remove o edital da base local: PDF, extrações, JSONs, wiki, memória e vetores."""
    removed: list[str] = []

    def rm_file(path: Path):
        if path.exists() and path.is_file():
            path.unlink()
            removed.append(str(path.relative_to(ROOT)))

    def rm_dir(path: Path):
        if path.exists() and path.is_dir():
            shutil.rmtree(path)
            removed.append(str(path.relative_to(ROOT)) + '/')

    # PDF original
    raw_pdf = _find_raw_pdf(edital_id)
    if raw_pdf:
        rm_file(raw_pdf)

    # Artefatos diretos
    for path in [
        EXTRACTED_DIR / f'{edital_id}.md',
        CHUNKS_DIR / f'{edital_id}.json',
        JSON_DIR / f'{edital_id}.json',
        TABLES_DIR / f'{edital_id}.tables.json',
        TABLES_DIR / f'{edital_id}.tables.md',
        DATA / 'wiki_memory' / f'{edital_id}.json',
        DATA / 'conteudo_llm' / f'{edital_id}.md',
        DATA / 'conteudo_llm' / f'{edital_id}.sources.json',
    ]:
        rm_file(path)

    # Backups do JSON
    backup_dir = JSON_DIR / 'backups'
    if backup_dir.exists():
        for p in backup_dir.glob(f'{edital_id}*'):
            rm_file(p)

    # Avaliações associadas por nome ou por conteúdo
    for p in EVAL_DIR.glob('*.json'):
        remove = edital_id in p.stem
        if not remove:
            try:
                remove = edital_id in p.read_text(encoding='utf-8')[:3000]
            except Exception:
                remove = False
        if remove:
            rm_file(p)

    # Wiki Markdown clássica e temática
    for path in [
        WIKI_DIR / 'concursos' / f'{edital_id}.md',
        WIKI_DIR / 'cronogramas' / f'{edital_id}.md',
        WIKI_DIR / 'conteudos' / f'{edital_id}.md',
        WIKI_DIR / 'fontes' / f'{edital_id}.md',
        WIKI_DIR / 'tabelas' / f'{edital_id}.md',
        WIKI_DIR / 'cargos' / edital_id,
        WIKI_DIR / 'temas' / edital_id,
    ]:
        if path.is_dir():
            rm_dir(path)
        else:
            rm_file(path)

    vector_msg = _remove_vector_entries(edital_id)
    return {'removed': removed, 'vector_msg': vector_msg}


def _money_to_float(value: str | None):
    if not value:
        return None
    m = re.search(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", str(value))
    if not m:
        return None
    return float(m.group(1).replace('.', '').replace(',', '.'))


def _fmt_money(value: float | None) -> str | None:
    if value is None:
        return None
    s = f"{value:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"R$ {s}"


def _numeric_vagas(value: str | None):
    if not value:
        return None
    text = str(value).strip()
    if re.fullmatch(r"CR|cadastro\s+reserva", text, re.I):
        return None
    m = re.search(r"\d+", text)
    if not m:
        return None
    return int(m.group(0))


def build_public_metrics(summary: dict) -> dict:
    cargos = summary.get('cargos') or []
    vagas_min = 0
    has_vagas = False
    tem_cr = False
    salaries = []
    for c in cargos:
        if c.get('suspeito'):
            continue
        v = c.get('vagas')
        n = _numeric_vagas(v)
        if n is not None:
            vagas_min += n
            has_vagas = True
        if v and re.search(r"\bCR\b|cadastro\s+reserva|\*", str(v), re.I):
            tem_cr = True
        money = _money_to_float(c.get('remuneracao'))
        if money:
            salaries.append(money)
    salary_range = None
    if salaries:
        lo, hi = min(salaries), max(salaries)
        salary_range = _fmt_money(lo) if lo == hi else f"{_fmt_money(lo)} a {_fmt_money(hi)}"
    return {
        'total_vagas_min': vagas_min if has_vagas else None,
        'vagas_obs': 'soma mínima; CR/asteriscos não entram no total' if tem_cr else None,
        'qtd_cargos': len([c for c in cargos if not c.get('suspeito')]),
        'faixa_salarial': salary_range,
    }


def _clean_topic_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip(" -•\t")
    line = re.sub(r"^\d+(?:\.\d+)*\s*[-.)]?\s*", "", line)
    return line.strip()


def _extract_content_topics(chunks: list[dict]) -> list[dict]:
    """Small public-safe content extractor. It never exposes chunk ids/text blocks.

    It converts content-program chunks into readable sections/topics. Raw chunks stay in Debug.
    """
    sections: list[dict] = []
    seen = set()
    candidates = []
    for c in chunks:
        text_probe = (c.get('section', '') + ' ' + c.get('text', '')[:800]).lower()
        if c.get('kind') == 'conteudo' or any(x in text_probe for x in [
            'conteúdo programático', 'conteudos programaticos', 'conhecimentos básicos',
            'conhecimentos especificos', 'conhecimentos específicos', 'programa de prova'
        ]):
            candidates.append(c)
    for c in candidates[:10]:
        heading = c.get('section') or 'Conteúdo programático'
        if len(heading) > 110:
            heading = 'Conteúdo programático'
        topics = []
        text = c.get('text', '')
        # Split lines and sentence-like chunks. Keep only lines that look like syllabus topics.
        raw_parts = []
        for line in text.splitlines():
            line = _clean_topic_line(line)
            if len(line) < 8:
                continue
            if any(x in line.lower() for x in ['conteúdo programático', 'conhecimentos básicos', 'conhecimentos específicos', 'língua portuguesa', 'matemática', 'informática', 'legislação']):
                raw_parts.append(line)
            elif (';' in line or ',' in line) and len(line) < 240:
                raw_parts.extend([_clean_topic_line(p) for p in re.split(r";", line)])
            elif re.search(r"\b(texto|ortografia|concordância|regência|porcentagem|raciocínio|informática|constituição|administração|ética|direito|matemática|português)\b", line, re.I):
                raw_parts.append(line)
        for part in raw_parts:
            if 8 <= len(part) <= 180 and part.lower() not in seen:
                seen.add(part.lower())
                topics.append(part)
            if len(topics) >= 18:
                break
        if topics:
            sections.append({'titulo': heading, 'topicos': topics, 'pagina': c.get('page_start')})
    return sections[:6]


def get_content_programatico(chunks: list[dict], tables: list[dict], summary: dict | None = None) -> dict:
    if summary and isinstance(summary.get('conteudo_programatico'), dict):
        stored = summary.get('conteudo_programatico') or {}
        if stored.get('sections'):
            return stored
    return extract_content_programatico(chunks, tables)


def get_conteudo_llm_rag(summary: dict, chunks: list[dict], tables: list[dict], force: bool = False) -> dict:
    """Síntese da aba Conteúdo gerada pelo mesmo fluxo LLM/RAG do chat.

    A extração estruturada de conteúdo programático varia muito entre editais.
    Para a aba pública final, usamos uma pergunta fixa contra a LLM Wiki/RAG e
    guardamos o resultado em cache local para não chamar o Ollama a cada reload.
    """
    edital_id = summary.get('edital_id') or slugify(summary.get('titulo') or 'edital')[:80]
    cache_path = CONTENT_LLM_DIR / f'{edital_id}.md'
    sources_path = CONTENT_LLM_DIR / f'{edital_id}.sources.json'
    if cache_path.exists() and not force:
        answer = cache_path.read_text(encoding='utf-8')
        try:
            sources = json.loads(sources_path.read_text(encoding='utf-8')) if sources_path.exists() else []
        except Exception:
            sources = []
        return {'answer': answer, 'html': render_markdown(answer), 'sources': sources, 'cached': True}

    question = (
        'Com base no edital, organize o conteúdo programático da prova objetiva. '
        'Liste conhecimentos básicos, conhecimentos específicos, disciplinas, tópicos e, se existir, quantidade de questões/pontuação. '
        'Use somente informações encontradas no edital. Se algo não estiver claro, diga que não foi detalhado.'
    )
    try:
        answer, sources = answer_hybrid(question, summary, chunks, tables, root=ROOT, config=read_config())
    except Exception as exc:
        answer, sources = (
            'Não foi possível gerar a síntese do conteúdo programático pela LLM/RAG neste momento. '
            f'Erro: {exc}',
            []
        )
    if not answer or len(str(answer).strip()) < 20:
        answer = 'Não encontrei conteúdo programático suficiente para gerar uma síntese confiável a partir deste edital.'
    cache_path.write_text(str(answer).strip() + '\n', encoding='utf-8')
    try:
        sources_path.write_text(json.dumps(sources[:10], ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass
    return {'answer': str(answer).strip(), 'html': render_markdown(str(answer)), 'sources': sources[:10], 'cached': False}


def get_table_stats(tables: list[dict]) -> dict:
    stats = {}
    for t in tables:
        k = t.get('kind', 'tabela_desconhecida')
        stats[k] = stats.get(k, 0) + 1
    return stats


def _wiki_markdown_path(summary: dict) -> Path:
    slug = slugify(summary.get("edital_id") or summary.get("titulo"))[:90]
    return WIKI_DIR / "concursos" / f"{slug}.md"


def _rebuild_wiki_from_summary(summary_dict: dict, chunks: list[dict], tables: list[dict]) -> None:
    summary_obj = ConcursoResumo.model_validate(summary_dict)
    build_concurso_markdown(summary_obj, chunks, WIKI_DIR, tables)
    build_semantic_wiki(summary_dict, chunks, tables, ROOT, read_config())


def process_pdf(pdf_path: Path, edital_id: str, job_id: str | None = None):
    _progress(job_id, 1, 'Preparando arquivo', pdf_path.name)

    _progress(job_id, 5, 'Extraindo texto do PDF', 'iniciando leitura página a página')
    pages = extract_pdf_text(pdf_path, progress=_stage_progress(job_id, 5, 24, 'Extraindo texto do PDF'))

    _progress(job_id, 25, 'Extraindo tabelas', 'varrendo páginas e estruturas tabulares')
    tables = extract_tables_from_pdf(pdf_path, edital_id, progress=_stage_progress(job_id, 25, 42, 'Extraindo tabelas'))
    _progress(job_id, 43, 'Salvando tabelas', f'{len(tables)} tabelas úteis detectadas')
    save_tables(tables, TABLES_DIR / f"{edital_id}.tables.json", TABLES_DIR / f"{edital_id}.tables.md")

    _progress(job_id, 47, 'Limpando texto', 'normalizando quebras e ruídos')
    raw_md_path = EXTRACTED_DIR / f"{edital_id}.md"
    save_extracted_markdown(pages, raw_md_path)
    cleaned = clean_text(raw_md_path.read_text(encoding="utf-8"))
    raw_md_path.write_text(cleaned, encoding="utf-8")

    _progress(job_id, 55, 'Gerando chunks', 'segmentando o edital com sobreposição controlada')
    chunks = chunk_markdown(cleaned, edital_id=edital_id, max_chars=5000, overlap_chars=400)
    chunks_dict = [c.__dict__ for c in chunks]
    _save_json(_chunks_path(edital_id), chunks_dict)

    _progress(job_id, 63, 'Extraindo dados estruturados', 'cargos, cronograma, taxa, inscrição e campos principais')
    tables_dict = [t.__dict__ for t in tables]
    summary = extract_summary(edital_id, chunks_dict, tables_dict)
    summary_dict = summary.model_dump(mode="json")

    _progress(job_id, 70, 'Estruturando conteúdo programático', 'disciplinas, tópicos e fontes')
    summary_dict['conteudo_programatico'] = extract_content_programatico(chunks_dict, tables_dict)
    for _p in [CONTENT_LLM_DIR / f'{edital_id}.md', CONTENT_LLM_DIR / f'{edital_id}.sources.json']:
        if _p.exists():
            _p.unlink()
    _save_json(_summary_path(edital_id), summary_dict)

    _progress(job_id, 76, 'Gerando wiki principal', 'páginas estruturadas e Markdown')
    build_concurso_markdown(ConcursoResumo.model_validate(summary_dict), chunks_dict, WIKI_DIR, tables_dict)

    _progress(job_id, 82, 'Atualizando LLM Wiki', 'assimilando o edital em páginas temáticas')
    build_semantic_wiki(summary_dict, chunks_dict, tables_dict, ROOT, read_config())

    _progress(job_id, 91, 'Atualizando índice RAG', 'ChromaDB + embeddings, com fallback textual')
    vector_status = rebuild_vector_index(edital_id, summary_dict, chunks_dict, tables_dict, ROOT, read_config())
    summary_dict.setdefault('qualidade', {})['rag_vetorial'] = vector_status
    _save_json(_summary_path(edital_id), summary_dict)

    _progress(job_id, 100, 'Concluído', f'{len(chunks)} chunks e {len(tables)} tabelas detectadas')
    return ConcursoResumo.model_validate(summary_dict), chunks_dict, tables_dict

@app.route("/")
def index():
    return render_template("index.html", concursos=list_concursos())


@app.route("/debug")
def debug():
    return render_template("debug.html", concursos=list_concursos())



@app.route("/analise")
def analise():
    evaluation = load_all_evaluations(EVAL_DIR)
    return render_template("analise.html", evaluation=evaluation, concursos=list_concursos())

@app.route("/upload/start", methods=["POST"])
def upload_start():
    file = request.files.get("edital")
    if not file or not file.filename:
        return jsonify({'ok': False, 'error': 'Envie um arquivo PDF.'}), 400
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'ok': False, 'error': 'A versão atual aceita apenas PDF.'}), 400
    filename = secure_filename(file.filename)
    edital_id = slugify(Path(filename).stem)[:80]
    pdf_path = RAW_DIR / filename
    file.save(pdf_path)
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {
        'ok': True,
        'done': False,
        'error': None,
        'edital_id': edital_id,
        'pct': 0,
        'etapa': 'Na fila',
        'detalhe': 'arquivo recebido',
        'started_at': time.time(),
        'updated_at': time.time(),
        'redirect': None,
    }

    def run_job():
        # O processamento roda em uma thread separada. Algumas partes do pipeline
        # podem tocar em config/helpers do Flask; por isso abrimos explicitamente
        # o contexto da aplicação para evitar "Working outside of application context".
        with app.app_context():
            try:
                summary, chunks, tables = process_pdf(pdf_path, edital_id, job_id=job_id)
                JOBS[job_id].update({
                    'done': True,
                    'pct': 100,
                    'etapa': 'Concluído',
                    'detalhe': f'{len(chunks)} chunks e {len(tables)} tabelas detectadas',
                    # Evita chamar url_for fora do request context. Caminho relativo basta para o JS redirecionar.
                    'redirect': f'/debug/edital/{edital_id}',
                    'updated_at': time.time(),
                })
            except Exception as exc:
                JOBS[job_id].update({
                    'done': True,
                    'ok': False,
                    'error': str(exc),
                    'etapa': 'Erro',
                    'detalhe': str(exc),
                    'updated_at': time.time(),
                })

    threading.Thread(target=run_job, daemon=True).start()
    return jsonify({'ok': True, 'job_id': job_id, 'edital_id': edital_id})


@app.route("/progresso/<job_id>")
def progresso(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({'ok': False, 'done': True, 'error': 'Processo não encontrado.'}), 404
    elapsed = int(time.time() - float(job.get('started_at') or time.time()))
    payload = dict(job)
    payload['elapsed'] = elapsed
    return jsonify(payload)


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("edital")
    if not file or not file.filename:
        flash("Envie um arquivo PDF.")
        return redirect(url_for("debug"))
    if not file.filename.lower().endswith(".pdf"):
        flash("A versão atual aceita apenas PDF.")
        return redirect(url_for("debug"))

    filename = secure_filename(file.filename)
    edital_id = slugify(Path(filename).stem)[:80]
    pdf_path = RAW_DIR / filename
    file.save(pdf_path)

    try:
        summary, chunks, tables = process_pdf(pdf_path, edital_id)
        flash(f"Edital processado: {len(chunks)} chunks e {len(tables)} tabelas detectadas.")
        return redirect(url_for("debug_edital", edital_id=edital_id))
    except Exception as exc:
        flash(f"Erro ao processar PDF: {exc}")
        return redirect(url_for("debug"))


@app.route("/debug/edital/<edital_id>/refazer", methods=["POST"])
def refazer_ingestao(edital_id: str):
    pdf_path = _find_raw_pdf(edital_id)
    if not pdf_path:
        flash("PDF original não encontrado em data/raw/editais.")
        return redirect(url_for("debug_edital", edital_id=edital_id))
    try:
        old_summary = _summary_path(edital_id)
        if old_summary.exists():
            backup_dir = JSON_DIR / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"{edital_id}.before-refazer.json"
            backup_path.write_text(old_summary.read_text(encoding="utf-8"), encoding="utf-8")
        summary, chunks, tables = process_pdf(pdf_path, edital_id)
        flash(f"Edital reprocessado: {len(chunks)} chunks e {len(tables)} tabelas detectadas. Backup anterior salvo em data/json/backups.")
    except Exception as exc:
        flash(f"Erro ao reprocessar edital: {exc}")
    return redirect(url_for("debug_edital", edital_id=edital_id))


@app.route("/debug/edital/<edital_id>/atualizar-wiki", methods=["POST"])
def atualizar_wiki(edital_id: str):
    summary, chunks, tables = _load_bundle(edital_id)
    if not summary:
        flash("Concurso não encontrado.")
        return redirect(url_for("debug"))
    try:
        build_semantic_wiki(summary, chunks, tables, ROOT, read_config())
        vector_status = rebuild_vector_index(edital_id, summary, chunks, tables, ROOT, read_config())
        summary.setdefault('qualidade', {})['rag_vetorial'] = vector_status
        _save_json(_summary_path(edital_id), summary)
        flash("Wiki temática e índice RAG atualizados.")
    except Exception as exc:
        flash(f"Erro ao atualizar wiki: {exc}")
    return redirect(url_for("debug_edital", edital_id=edital_id, tab='diagnostico'))


@app.route("/debug/edital/<edital_id>/excluir", methods=["POST"])
def excluir_edital(edital_id: str):
    if not _summary_path(edital_id).exists() and not _find_raw_pdf(edital_id):
        flash("Edital não encontrado na base.")
        return redirect(url_for("debug"))
    try:
        result = nuclear_delete_edital(edital_id)
        total = len(result.get('removed') or [])
        flash(f"Edital removido da base: {total} artefatos excluídos. {result.get('vector_msg')}")
    except Exception as exc:
        flash(f"Erro ao excluir edital: {exc}")
        return redirect(url_for("debug_edital", edital_id=edital_id))
    return redirect(url_for("debug"))


@app.route("/concurso/<edital_id>")
def concurso(edital_id: str):
    summary, chunks, tables = _load_bundle(edital_id)
    if not summary:
        flash("Concurso não encontrado.")
        return redirect(url_for("index"))
    tab = request.args.get('tab', 'resumo')
    allowed = {'resumo', 'wiki', 'cargos', 'cronograma', 'conteudo', 'chat'}
    if tab not in allowed:
        tab = 'resumo'
    metrics = build_public_metrics(summary)
    content = get_content_programatico(chunks, tables, summary)
    content_llm = get_conteudo_llm_rag(summary, chunks, tables) if tab == 'conteudo' else None
    semantic_wiki = load_semantic_manifest(ROOT, edital_id)
    selected_wiki_page = request.args.get('wiki_page') or 'visao-geral'
    semantic_page_text = read_semantic_page(ROOT, edital_id, selected_wiki_page) if tab == 'wiki' else ''
    semantic_page_html = render_markdown(semantic_page_text) if semantic_page_text else ''
    pdf_available = _find_raw_pdf(edital_id) is not None
    return render_template("concurso.html", summary=summary, tab=tab, metrics=metrics, content=content, pdf_available=pdf_available, semantic_wiki=semantic_wiki, selected_wiki_page=selected_wiki_page, semantic_page_text=semantic_page_text, semantic_page_html=semantic_page_html, content_llm=content_llm)


@app.route("/cargos/<edital_id>")
def cargos_page(edital_id: str):
    return redirect(url_for('concurso', edital_id=edital_id, tab='cargos'))


@app.route("/cronograma/<edital_id>")
def cronograma_page(edital_id: str):
    return redirect(url_for('concurso', edital_id=edital_id, tab='cronograma'))


@app.route("/perguntar/<edital_id>", methods=["GET", "POST"])
def perguntar(edital_id: str):
    if request.method == 'GET':
        return redirect(url_for('concurso', edital_id=edital_id, tab='chat'))
    summary, chunks, tables = _load_bundle(edital_id)
    if not summary:
        flash("Concurso não encontrado.")
        return redirect(url_for("index"))
    question = request.form.get("question", "").strip()
    answer, sources = answer_hybrid(question, summary, chunks, tables, root=ROOT, config=read_config())
    metrics = build_public_metrics(summary)
    content = get_content_programatico(chunks, tables, summary)
    pdf_available = _find_raw_pdf(edital_id) is not None
    return render_template("concurso.html", summary=summary, tab='chat', metrics=metrics, content=content, question=question, answer=answer, sources=sources, pdf_available=pdf_available, semantic_wiki=load_semantic_manifest(ROOT, edital_id), selected_wiki_page='visao-geral', semantic_page_text='', semantic_page_html='', content_llm=None)


@app.route("/debug/edital/<edital_id>")
def debug_edital(edital_id: str):
    summary, chunks, tables = _load_bundle(edital_id)
    if not summary:
        flash("Concurso não encontrado.")
        return redirect(url_for("debug"))
    tab = request.args.get('tab', 'diagnostico')
    allowed = {'diagnostico', 'tabelas', 'chunks', 'markdown', 'revisar'}
    if tab not in allowed:
        tab = 'diagnostico'
    table_stats = get_table_stats(tables)
    chunk_stats = {}
    for c in chunks:
        k = c.get('kind', 'geral')
        chunk_stats[k] = chunk_stats.get(k, 0) + 1
    md_path = _wiki_markdown_path(summary)
    markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else "Wiki ainda não gerada."
    content = get_content_programatico(chunks, tables, summary)
    return render_template("debug_edital.html", summary=summary, chunks=chunks, tables=tables, tab=tab, table_stats=table_stats, chunk_stats=chunk_stats, markdown=markdown, content=content)


@app.route("/debug/edital/<edital_id>/revisar", methods=["POST"])
def salvar_revisao(edital_id: str):
    summary, chunks, tables = _load_bundle(edital_id)
    if not summary:
        flash("Concurso não encontrado.")
        return redirect(url_for("debug"))
    action = request.form.get("action", "main")
    if action == "main":
        for field in ["titulo", "orgao", "banca", "ano", "inscricao", "taxa", "prova"]:
            value = request.form.get(field, "").strip()
            summary[field] = value or None
            if 'campos_status' in summary and field in summary['campos_status']:
                summary['campos_status'][field]['valor'] = summary[field]
                summary['campos_status'][field]['status'] = 'confirmado' if value else 'nao_encontrado'
                summary['campos_status'][field]['motivo'] = 'revisado manualmente' if value else 'removido na revisão manual'
    elif action == "cargos":
        cargos = []
        names = request.form.getlist("cargo_nome")
        vagas = request.form.getlist("cargo_vagas")
        rems = request.form.getlist("cargo_remuneracao")
        cargas = request.form.getlist("cargo_carga_horaria")
        reqs = request.form.getlist("cargo_requisito")
        for i, nome in enumerate(names):
            nome = nome.strip()
            if not nome:
                continue
            old = (summary.get('cargos') or [{}])[i] if i < len(summary.get('cargos') or []) else {}
            cargos.append({
                **old,
                'nome': nome,
                'vagas': vagas[i].strip() or None if i < len(vagas) else None,
                'remuneracao': rems[i].strip() or None if i < len(rems) else None,
                'carga_horaria': cargas[i].strip() or None if i < len(cargas) else None,
                'requisito': reqs[i].strip() or None if i < len(reqs) else None,
                'confianca': 'alta',
                'suspeito': False,
                'motivo_suspeita': None,
            })
        summary['cargos'] = cargos
    elif action == "cronograma":
        eventos = []
        evs = request.form.getlist("evento")
        datas = request.form.getlist("data_ou_periodo")
        for i, ev in enumerate(evs):
            ev = ev.strip()
            data = datas[i].strip() if i < len(datas) else ""
            if not ev and not data:
                continue
            old = (summary.get('cronograma') or [{}])[i] if i < len(summary.get('cronograma') or []) else {}
            eventos.append({**old, 'evento': ev or 'Evento', 'data_ou_periodo': data or 'Não encontrado', 'confianca': 'alta'})
        summary['cronograma'] = eventos
    elif action == "conteudo":
        titles = request.form.getlist("conteudo_titulo")
        topics_blocks = request.form.getlist("conteudo_topicos")
        pages = request.form.getlist("conteudo_pagina")
        sections = []
        for i, title in enumerate(titles):
            title = title.strip()
            raw_topics = topics_blocks[i] if i < len(topics_blocks) else ""
            topics = [x.strip(" -•\t") for x in raw_topics.splitlines() if x.strip(" -•\t")]
            if not title and not topics:
                continue
            page = None
            if i < len(pages):
                try:
                    page = int(pages[i]) if pages[i].strip() else None
                except Exception:
                    page = None
            sections.append({'titulo': title or 'Conteúdo programático', 'topicos': topics, 'pagina': page, 'fonte': 'revisao_manual'})
        summary['conteudo_programatico'] = {'sections': sections, 'tables_count': 0, 'revisado': True}
    elif action == "markdown":
        md_path = _wiki_markdown_path(summary)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(request.form.get("markdown", ""), encoding="utf-8")
        _save_json(_summary_path(edital_id), summary)
        flash("Markdown salvo.")
        return redirect(url_for("debug_edital", edital_id=edital_id, tab='markdown'))

    _save_json(_summary_path(edital_id), summary)
    try:
        _rebuild_wiki_from_summary(summary, chunks, tables)
        vector_status = rebuild_vector_index(edital_id, summary, chunks, tables, ROOT, read_config())
        summary.setdefault('qualidade', {})['rag_vetorial'] = vector_status
        _save_json(_summary_path(edital_id), summary)
    except Exception as exc:
        flash(f"Revisão salva, mas a wiki não pôde ser regenerada: {exc}")
        return redirect(url_for("debug_edital", edital_id=edital_id, tab='revisar'))
    flash("Revisão salva e wiki regenerada.")
    return redirect(url_for("debug_edital", edital_id=edital_id, tab='revisar'))


@app.route("/revisao/<edital_id>")
def revisao_page(edital_id: str):
    return redirect(url_for('debug_edital', edital_id=edital_id, tab='revisar'))


@app.route("/tabelas/<edital_id>")
def tabelas(edital_id: str):
    return redirect(url_for('debug_edital', edital_id=edital_id, tab='tabelas'))


@app.route("/wiki/<edital_id>")
def wiki_page(edital_id: str):
    return redirect(url_for('debug_edital', edital_id=edital_id, tab='markdown'))


@app.route("/edital/<edital_id>/pdf")
def abrir_pdf(edital_id: str):
    pdf_path = _find_raw_pdf(edital_id)
    if not pdf_path or not pdf_path.exists():
        flash("PDF original não encontrado.")
        return redirect(url_for("concurso", edital_id=edital_id))
    return send_file(pdf_path, mimetype="application/pdf", as_attachment=False, download_name=pdf_path.name)



if __name__ == "__main__":
    app.run(debug=True)
