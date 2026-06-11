from __future__ import annotations
from pathlib import Path
import json
from collections import defaultdict
from typing import Any


def _safe_load_json(path: Path) -> Any | None:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _items_from_data(data: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if data is None:
        return [], {}
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)], {}
    if isinstance(data, dict):
        items = data.get("items") or data.get("perguntas") or data.get("avaliacoes") or []
        if not isinstance(items, list):
            items = []
        meta = {k: v for k, v in data.items() if k not in {"items", "perguntas", "avaliacoes"}}
        return [x for x in items if isinstance(x, dict)], meta
    return [], {}


def load_evaluation(path: Path) -> dict[str, Any]:
    data = _safe_load_json(path)
    items, meta = _items_from_data(data)
    if data is None:
        return {"items": [], "metrics": calculate_metrics([]), "meta": {}, "exists": False, "name": path.stem}
    return {"items": items, "metrics": calculate_metrics(items), "meta": meta, "exists": True, "name": path.stem}


def _score(item: dict[str, Any]) -> float:
    # Preferred: nota in 0..1. Also accepts score, correto bool, or result labels.
    value = item.get("nota", item.get("score", item.get("pontuacao", None)))
    if value is None and "correto" in item:
        value = 1 if item.get("correto") else 0
    if value is None:
        label = str(item.get("resultado") or item.get("status") or "").lower()
        if label in {"correto", "certo", "ok", "acerto", "sim"}:
            value = 1
        elif label in {"parcial", "meio", "incompleto"}:
            value = 0.5
        elif label in {"errado", "erro", "não", "nao"}:
            value = 0
    try:
        score = float(value)
    except Exception:
        score = 0.0
    return max(0.0, min(1.0, score))


def _kind(item: dict[str, Any]) -> str:
    raw = str(item.get("tipo") or item.get("escopo") or item.get("modulo") or item.get("categoria") or "").lower()
    # A análise final foca só em Wiki e Chat. Itens operacionais/sistema não viram métrica própria.
    if any(x in raw for x in ["chat", "pergunta", "resposta", "rag"]):
        return "chat"
    if any(x in raw for x in ["wiki", "pagina", "página", "conteudo", "conteúdo", "cargo", "cronograma", "extração", "extracao"]):
        return "wiki"
    # Se tem pergunta aberta, normalmente avalia o chat/RAG.
    if item.get("pergunta") and not item.get("campo"):
        return "chat"
    # Critérios de página/campo entram como Wiki por padrão.
    return "wiki"


def calculate_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    valid_items = [i for i in items if isinstance(i, dict)]
    total = len(valid_items)
    if total == 0:
        return {
            "total": 0,
            "media_geral": None,
            "percentual_geral": None,
            "acertos_cheios": 0,
            "parciais": 0,
            "erros": 0,
            "com_fonte": 0,
            "taxa_com_fonte": None,
            "por_categoria": {},
            "por_dificuldade": {},
            "por_tipo": {},
            "wiki_percentual": None,
            "chat_percentual": None,
        }
    scores = [_score(i) for i in valid_items]
    full = sum(1 for s in scores if s >= 0.999)
    partial = sum(1 for s in scores if 0 < s < 0.999)
    errors = sum(1 for s in scores if s <= 0)
    with_source = sum(1 for i in valid_items if bool(i.get("fonte_ok", i.get("com_fonte", False))))

    def grouped(key: str, values: list[str] | None = None):
        buckets: dict[str, list[float]] = defaultdict(list)
        for item, sc in zip(valid_items, scores):
            k = values.pop(0) if values is not None else str(item.get(key) or "não informado")
            buckets[k].append(sc)
        return {
            k: {
                "total": len(v),
                "media": round(sum(v) / len(v), 3),
                "percentual": round(100 * sum(v) / len(v), 1),
            }
            for k, v in sorted(buckets.items())
        }

    tipos = [_kind(i) for i in valid_items]
    por_tipo = grouped("tipo", values=tipos.copy())
    avg = sum(scores) / total

    return {
        "total": total,
        "media_geral": round(avg, 3),
        "percentual_geral": round(avg * 100, 1),
        "acertos_cheios": full,
        "parciais": partial,
        "erros": errors,
        "com_fonte": with_source,
        "taxa_com_fonte": round(100 * with_source / total, 1),
        "por_categoria": grouped("categoria"),
        "por_dificuldade": grouped("dificuldade"),
        "por_tipo": por_tipo,
        "wiki_percentual": por_tipo.get("wiki", {}).get("percentual"),
        "chat_percentual": por_tipo.get("chat", {}).get("percentual"),
    }


def aggregate_metrics(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    all_items: list[dict[str, Any]] = []
    for ev in evaluations:
        all_items.extend(ev.get("items") or [])
    return calculate_metrics(all_items)


def load_all_evaluations(folder: Path) -> dict[str, Any]:
    folder.mkdir(parents=True, exist_ok=True)
    evaluations = []
    for path in sorted(folder.glob("*.json")):
        ev = load_evaluation(path)
        # Prevent empty/invalid JSON from breaking or polluting the metrics.
        if not ev.get("exists") or not ev.get("items"):
            continue
        ev["file"] = path.name
        ev["edital_id"] = path.stem
        evaluations.append(ev)
    return {
        "evaluations": evaluations,
        "metrics": aggregate_metrics(evaluations),
        "total_arquivos": len(evaluations),
        "exists": bool(evaluations),
    }


EXAMPLE = {
    "items": [
        {
            "pergunta": "Qual é o prazo de inscrição?",
            "tipo": "chat",
            "categoria": "inscrição",
            "dificuldade": "fácil",
            "resposta_esperada": "09/03/2016 a 18/04/2016",
            "resposta_sistema": "09/03/2016 a 18/04/2016",
            "nota": 1,
            "fonte_ok": True,
            "observacao": "Resposta correta e com fonte."
        },
        {
            "pergunta": "A página de cargos lista vagas e remuneração?",
            "tipo": "wiki",
            "categoria": "cargos",
            "dificuldade": "média",
            "resposta_esperada": "Página com cargos, vagas, remuneração e fontes.",
            "resposta_sistema": "",
            "nota": 0.75,
            "fonte_ok": True,
            "observacao": "Faltou uma remuneração."
        },
        {
            "pergunta": "A wiki apresenta as informações principais do edital?",
            "tipo": "wiki",
            "categoria": "mapa do edital",
            "dificuldade": "fácil",
            "resposta_esperada": "Resumo, cargos, cronograma, conteúdo e fontes aparecem organizados.",
            "resposta_sistema": "",
            "nota": 1,
            "fonte_ok": True,
            "observacao": "acertou"
        }
    ]
}
