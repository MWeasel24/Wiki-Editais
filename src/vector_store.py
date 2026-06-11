from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.:-]+", "-", value or "item").strip("-")[:180]


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def table_to_text(table: dict[str, Any]) -> str:
    headers = table.get("headers") or []
    lines: list[str] = []
    if table.get("title_guess"):
        lines.append(str(table.get("title_guess")))
    lines.append(f"Tipo da tabela: {table.get('kind') or 'tabela'}")
    if table.get("page"):
        lines.append(f"Página: {table.get('page')}")
    for row in (table.get("rows") or [])[:60]:
        vals: list[str] = []
        if headers:
            for h in headers:
                v = str(row.get(h, "")).strip()
                if v:
                    vals.append(f"{h}: {v}")
        else:
            for k, v in row.items():
                if str(v).strip():
                    vals.append(f"{k}: {v}")
        if vals:
            lines.append("; ".join(vals))
    return _norm_text("\n".join(lines))


def summary_to_documents(summary: dict[str, Any]) -> list[dict[str, Any]]:
    edital_id = summary.get("edital_id") or "edital"
    docs: list[dict[str, Any]] = []
    dados = []
    for label, key in [
        ("Título", "titulo"), ("Órgão", "orgao"), ("Banca", "banca"), ("Ano", "ano"),
        ("Inscrição", "inscricao"), ("Taxa", "taxa"), ("Prova", "prova"),
    ]:
        if summary.get(key):
            dados.append(f"{label}: {summary.get(key)}")
    if dados:
        docs.append({
            "id": _safe_id(f"{edital_id}:dados-gerais"),
            "text": _norm_text("\n".join(dados)),
            "metadata": {"edital_id": edital_id, "source_type": "json", "section": "dados gerais", "page_start": ""},
        })
    cargos_lines = []
    for c in summary.get("cargos") or []:
        if c.get("suspeito"):
            continue
        cargos_lines.append("; ".join([f"{k}: {v}" for k, v in c.items() if v and k not in {"fonte", "fonte_tipo", "suspeito", "motivo_suspeita"}]))
    if cargos_lines:
        docs.append({
            "id": _safe_id(f"{edital_id}:cargos"),
            "text": _norm_text("\n".join(cargos_lines[:200])),
            "metadata": {"edital_id": edital_id, "source_type": "json", "section": "cargos", "page_start": ""},
        })
    cron_lines = []
    for e in summary.get("cronograma") or []:
        cron_lines.append(f"{e.get('evento')}: {e.get('data_ou_periodo')}")
    if cron_lines:
        docs.append({
            "id": _safe_id(f"{edital_id}:cronograma"),
            "text": _norm_text("\n".join(cron_lines[:250])),
            "metadata": {"edital_id": edital_id, "source_type": "json", "section": "cronograma", "page_start": ""},
        })
    content = summary.get("conteudo_programatico") or {}
    sections = content.get("sections") if isinstance(content, dict) else []
    if sections:
        lines = []
        for sec in sections:
            lines.append(str(sec.get("titulo") or "Conteúdo programático"))
            for top in sec.get("topicos") or []:
                lines.append(f"- {top}")
        docs.append({
            "id": _safe_id(f"{edital_id}:conteudo"),
            "text": _norm_text("\n".join(lines[:350])),
            "metadata": {"edital_id": edital_id, "source_type": "json", "section": "conteúdo programático", "page_start": ""},
        })
    return docs


def build_documents(edital_id: str, summary: dict[str, Any], chunks: list[dict[str, Any]], tables: list[dict[str, Any]], wiki_dir: Path | None = None) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    docs.extend(summary_to_documents(summary))
    for i, c in enumerate(chunks):
        text = _norm_text(c.get("text") or "")
        if len(text) < 80:
            continue
        docs.append({
            "id": _safe_id(f"{edital_id}:chunk:{c.get('id') or i}"),
            "text": text[:5000],
            "metadata": {
                "edital_id": edital_id,
                "source_type": "chunk",
                "section": str(c.get("section") or c.get("kind") or "chunk"),
                "page_start": str(c.get("page_start") or ""),
                "source_id": str(c.get("id") or f"chunk-{i}"),
            },
        })
    for i, t in enumerate(tables):
        if t.get("ignored") and t.get("kind") not in {"formulario", "tabela_desconhecida"}:
            continue
        text = table_to_text(t)
        if len(text) < 80:
            continue
        docs.append({
            "id": _safe_id(f"{edital_id}:table:{t.get('id') or i}"),
            "text": text[:5000],
            "metadata": {
                "edital_id": edital_id,
                "source_type": "tabela",
                "section": str(t.get("kind") or "tabela"),
                "page_start": str(t.get("page") or ""),
                "source_id": str(t.get("id") or f"tabela-{i}"),
            },
        })
    if wiki_dir:
        for md in wiki_dir.rglob("*.md"):
            try:
                text = _norm_text(md.read_text(encoding="utf-8"))
            except Exception:
                continue
            if edital_id not in str(md) and edital_id not in text[:300]:
                # Avoid mixing pages from other processed edital ids.
                continue
            if len(text) >= 80:
                docs.append({
                    "id": _safe_id(f"{edital_id}:wiki:{md.relative_to(wiki_dir)}"),
                    "text": text[:5000],
                    "metadata": {"edital_id": edital_id, "source_type": "wiki", "section": md.stem, "page_start": "", "source_id": str(md)},
                })
    return docs


class OllamaEmbeddingFunction:
    def __init__(self, model: str = "nomic-embed-text", base_url: str = "http://localhost:11434", timeout: int = 60):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def __call__(self, input: list[str]) -> list[list[float]]:  # Chroma protocol
        embeddings: list[list[float]] = []
        for text in input:
            r = requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
            emb = data.get("embedding")
            if not emb:
                raise RuntimeError("Ollama não retornou embedding. Verifique se o modelo de embedding está instalado.")
            embeddings.append(emb)
        return embeddings


def _client(persist_dir: Path):
    import chromadb
    return chromadb.PersistentClient(path=str(persist_dir))


def rebuild_vector_index(edital_id: str, summary: dict[str, Any], chunks: list[dict[str, Any]], tables: list[dict[str, Any]], root: Path, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    rag_cfg = config.get("rag") or {}
    if not rag_cfg.get("enabled", True):
        return {"enabled": False, "indexed": 0, "error": None}
    persist_dir = root / (rag_cfg.get("persist_dir") or "data/vectorstore")
    model = rag_cfg.get("embedding_model") or "bge-m3"
    base_url = rag_cfg.get("ollama_base_url") or (config.get("llm") or {}).get("base_url") or "http://localhost:11434"
    docs = build_documents(edital_id, summary, chunks, tables, root / "wiki")
    name = "wikieditais"
    if not docs:
        return {"enabled": True, "indexed": 0, "error": "sem documentos para indexar"}
    try:
        client = _client(persist_dir)
        collection = client.get_or_create_collection(name=name, embedding_function=OllamaEmbeddingFunction(model=model, base_url=base_url))
        # Atualiza apenas o edital atual; não apaga vetores de outros editais.
        try:
            collection.delete(where={"edital_id": edital_id})
        except Exception:
            pass
        # Chroma has practical batch limits; keep batches small because Ollama embeds one by one.
        for start in range(0, len(docs), 32):
            batch = docs[start:start+32]
            collection.add(
                ids=[d["id"] for d in batch],
                documents=[d["text"] for d in batch],
                metadatas=[d["metadata"] for d in batch],
            )
        return {"enabled": True, "indexed": len(docs), "model": model, "store": "ChromaDB", "error": None}
    except Exception as exc:
        fallback_model = rag_cfg.get("fallback_embedding_model")
        if fallback_model and fallback_model != model:
            try:
                client = _client(persist_dir)
                collection = client.get_or_create_collection(name=name, embedding_function=OllamaEmbeddingFunction(model=fallback_model, base_url=base_url))
                try:
                    collection.delete(where={"edital_id": edital_id})
                except Exception:
                    pass
                for start in range(0, len(docs), 32):
                    batch = docs[start:start+32]
                    collection.add(ids=[d["id"] for d in batch], documents=[d["text"] for d in batch], metadatas=[d["metadata"] for d in batch])
                return {"enabled": True, "indexed": len(docs), "model": fallback_model, "store": "ChromaDB", "error": f"modelo principal falhou ({model}): {exc}"}
            except Exception as exc2:
                return {"enabled": True, "indexed": 0, "model": model, "store": "ChromaDB", "error": f"{exc}; fallback {fallback_model}: {exc2}"}
        return {"enabled": True, "indexed": 0, "model": model, "store": "ChromaDB", "error": str(exc)}


def search_vector(question: str, edital_id: str, root: Path, config: dict[str, Any] | None = None, top_k: int = 6) -> list[dict[str, Any]]:
    config = config or {}
    rag_cfg = config.get("rag") or {}
    if not rag_cfg.get("enabled", True):
        return []
    persist_dir = root / (rag_cfg.get("persist_dir") or "data/vectorstore")
    if not persist_dir.exists():
        return []
    primary = rag_cfg.get("embedding_model") or "bge-m3"
    fallback = rag_cfg.get("fallback_embedding_model")
    models = [primary] + ([fallback] if fallback and fallback != primary else [])
    base_url = rag_cfg.get("ollama_base_url") or (config.get("llm") or {}).get("base_url") or "http://localhost:11434"
    for model in models:
        try:
            client = _client(persist_dir)
            collection = client.get_or_create_collection(name="wikieditais", embedding_function=OllamaEmbeddingFunction(model=model, base_url=base_url))
            res = collection.query(query_texts=[question], n_results=top_k, where={"edital_id": edital_id})
            docs = res.get("documents", [[]])[0]
            metas = res.get("metadatas", [[]])[0]
            ids = res.get("ids", [[]])[0]
            dists = res.get("distances", [[]])[0] if res.get("distances") else [None] * len(docs)
            out = []
            for doc, meta, idv, dist in zip(docs, metas, ids, dists):
                out.append({
                    "id": meta.get("source_id") or idv,
                    "section": meta.get("section") or "vetor",
                    "text": doc,
                    "score": round(1 / (1 + float(dist)), 4) if dist is not None else 1,
                    "source_type": meta.get("source_type") or "vetor",
                    "page_start": meta.get("page_start") or None,
                })
            return out
        except Exception:
            continue
    return []
