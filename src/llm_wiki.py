from __future__ import annotations
from pathlib import Path
from typing import Any


def _read_llm_config() -> dict[str, Any]:
    """Tiny YAML-ish reader for config.yaml without adding PyYAML."""
    cfg_path = Path(__file__).resolve().parents[1] / "config.yaml"
    cfg = {"enabled": False, "model": "qwen2.5:14b-instruct", "base_url": "http://localhost:11434"}
    if not cfg_path.exists():
        return cfg
    in_llm = False
    for raw in cfg_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.startswith("llm:"):
            in_llm = True
            continue
        if in_llm and not line.startswith(" "):
            break
        if in_llm and ":" in line:
            key, value = line.strip().split(":", 1)
            value = value.strip().strip('"\'')
            if value.lower() in {"true", "false"}:
                cfg[key] = value.lower() == "true"
            else:
                cfg[key] = value
    return cfg


def _cargo_sample(summary: Any, limit: int = 8) -> str:
    cargos = getattr(summary, "cargos", []) or []
    parts = []
    for c in cargos[:limit]:
        detail = c.nome
        if c.vagas:
            detail += f" ({c.vagas} vagas)"
        if c.remuneracao:
            detail += f", {c.remuneracao}"
        parts.append(detail)
    return "; ".join(parts) or "não encontrado"


def _fallback_narrative(summary: Any, section: str = "resumo") -> str:
    cargos = getattr(summary, "cargos", []) or []
    cron = getattr(summary, "cronograma", []) or []
    if section == "cargos":
        if not cargos:
            return "Nenhum cargo foi consolidado automaticamente para esta página."
        return f"Foram consolidados {len(cargos)} cargo(s). As informações de vagas, remuneração, carga horária e requisitos aparecem abaixo quando identificadas nas fontes."
    if section == "cronograma":
        if not cron:
            return "Nenhum cronograma foi consolidado automaticamente para esta página."
        return f"Foram consolidados {len(cron)} evento(s) de cronograma, incluindo inscrições, provas, recursos e resultados quando encontrados."
    if section == "conteudo":
        return "O conteúdo programático é exibido quando foi estruturado a partir de tabelas ou seções específicas do edital."

    partes = []
    orgao = getattr(summary, 'orgao', None)
    banca = getattr(summary, 'banca', None)
    if orgao:
        frase = f"O edital é vinculado a **{orgao}**"
        if banca:
            frase += f" e tem **{banca}** como banca identificada"
        partes.append(frase + ".")
    elif banca:
        partes.append(f"A banca identificada foi **{banca}**.")
    if getattr(summary, "inscricao", None):
        partes.append(f"O período de inscrição identificado foi **{summary.inscricao}**.")
    if getattr(summary, "taxa", None):
        partes.append(f"A taxa identificada foi **{summary.taxa}**.")
    if getattr(summary, "prova", None):
        partes.append(f"A informação de prova consolidada foi: **{summary.prova}**.")
    partes.append(f"A extração consolidou **{len(cargos)} cargo(s)** e **{len(cron)} evento(s)** de cronograma.")
    return " ".join(partes)


def generate_wiki_narrative(summary: Any, section: str = "resumo") -> tuple[str, str]:
    """Return (text, mode). mode is 'llm' or 'template'.

    LLM is optional. When enabled with Ollama, it writes short wiki-style text from
    structured facts. It must not explain the system or use promotional wording.
    """
    cfg = _read_llm_config()
    if not cfg.get("enabled"):
        return _fallback_narrative(summary, section), "template"
    try:
        from .llm_client import ollama_generate
        cargos = getattr(summary, "cargos", []) or []
        cron = getattr(summary, "cronograma", []) or []
        cron_sample = "; ".join(f"{e.evento}: {e.data_ou_periodo}" for e in cron[:8]) or "não encontrado"
        prompt = f"""Escreva uma seção curta de wiki sobre um edital de concurso público.
Use somente os dados abaixo. Não invente datas, cargos, valores ou requisitos.
Não explique que a página foi gerada, processada, transformada, organizada ou indexada.
Não use tom promocional. Use tom seco, informativo e natural.
Se uma informação estiver ausente, diga apenas que não foi encontrada.

Seção solicitada: {section}
Título: {summary.titulo}
Órgão: {summary.orgao or 'não encontrado'}
Banca: {summary.banca or 'não encontrada'}
Ano: {summary.ano or 'não encontrado'}
Inscrição: {summary.inscricao or 'não encontrada'}
Taxa: {summary.taxa or 'não encontrada'}
Prova: {summary.prova or 'não encontrada'}
Quantidade de cargos: {len(cargos)}
Cargos principais: {_cargo_sample(summary)}
Eventos de cronograma: {len(cron)}
Exemplos de eventos: {cron_sample}

Texto:"""
        text = ollama_generate(prompt, model=str(cfg.get("model")), base_url=str(cfg.get("base_url")), timeout=90)
        return (text.strip() or _fallback_narrative(summary, section)), "llm"
    except Exception:
        return _fallback_narrative(summary, section), "template"
