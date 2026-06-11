from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .schemas import Cargo, CampoStatus, ConcursoResumo, EventoCronograma, QualidadeIngestao

DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}\s+de\s+[a-zç]+\s+de\s+20\d{2}", re.I)
MONEY_RE = re.compile(r"R\$\s*\d{1,3}(?:\.\d{3})*,\d{2}|\d+(?:,\d+)?\s*sal[aá]rios?\s+m[ií]nimos?(?:\s+nacionais?)?", re.I)
ROLE_RE = re.compile(r"\b(assistente|agente|auxiliar|analista|professor|t[eé]cnico|tecnica|motorista|operador|enfermeiro|m[eé]dico|contador|administrador|advogado|gari|fiscal|pedagogo|psic[oó]logo|farmac[eê]utico|odont[oó]logo|vigia|merendeira|cozinheiro|procurador|engenheiro|arquiteto|bibliotec[aá]rio)\b", re.I)
REQ_RE = re.compile(r"ensino|superior|fundamental|m[eé]dio|alfabetizado|habilita|registro|conselho|curso|gradua|licenciatura|bacharel|cnh|experi[eê]ncia|escolaridade", re.I)
TITLE_RE = re.compile(r"t[ií]tulo de|doutorado|mestrado|especializa|p[oó]s[-\s]?gradua|diploma|certificado|avalia[cç][aã]o de t[ií]tulos|prova de t[ií]tulos|pontua[cç][aã]o|pontos", re.I)
FORM_RE = re.compile(r"cpf|rg|telefone|e-?mail|endere[cç]o|assinatura|foto 3x4|data de nascimento|nome do candidato|declaro|requerimento|laudo m[eé]dico|cargo para o qual concorre", re.I)


ORG_BAD_RE = re.compile(r"munic[ií]pio\s+de\s+atua[cç][aã]o|vagas|reservas\s+legais|\bPcD\b|\bPPP\b|\bPIND\b|\bPQUI\b|carga\s+hor[aá]ria|remunera[cç][aã]o|requisito|conte[uú]do\s+program[aá]tico", re.I)
ORG_GOOD_RE = re.compile(r"\b(universidade|prefeitura|munic[ií]pio|c[âa]mara|conselho|instituto|secretaria|tribunal|defensoria|minist[eé]rio)\b", re.I)


def _is_bad_orgao(value: str | None) -> bool:
    if not value:
        return True
    v = re.sub(r"\s+", " ", value).strip()
    if len(v) < 6 or len(v) > 190:
        return True
    if ORG_BAD_RE.search(v):
        return True
    if re.search(r"publica[cç][aã]o|inscri[cç][aã]o|candidato|edital de abertura|contar da|dever[aá]|poder[aá]", v, re.I):
        return True
    return False


def _first_match(patterns: list[str], text: str) -> str | None:
    for pat in patterns:
        m = re.search(pat, text, re.I | re.S | re.M)
        if m:
            value = m.group(1) if m.groups() else m.group(0)
            return re.sub(r"\s+", " ", value).strip(" :-–—")
    return None


def _find_title(text: str) -> str:
    m = re.search(r"(?im)^\s*(EDITAL\s+(?:N[º°O.]\s*)?[^\n]{1,140})", text)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    first = next((l.strip() for l in text.splitlines() if len(l.strip()) > 20), "Edital processado")
    return first[:140]


def _clean_candidate(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip(" .,:;:-–—")
    bad = ["público que realizará", "verá certificar", "deverá ler", "poderá ser", "contar da publicação", "edital de abertura", "candidato", "nascimento"]
    if any(b in value.lower() for b in bad):
        return None
    return value[:220]


def _extract_orgao(full_text: str) -> str | None:
    head = "\n".join(full_text.splitlines()[:120])
    direct_patterns = [
        r"(PREFEITURA\s+MUNICIPAL\s+DE\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ\s\-]{2,90})",
        r"(MUNIC[IÍ]PIO\s+DE\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ\s\-]{2,90})(?:\n|\s+ESTADO)",
        r"(C[ÂA]MARA\s+MUNICIPAL\s+DE\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ\s\-]{2,90})",
        r"(UNIVERSIDADE\s+FEDERAL\s+DO\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ\s\-]{2,90})",
        r"(INSTITUTO\s+FEDERAL\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ\s\-]{5,90})",
        r"(CONSELHO\s+REGIONAL\s+DE\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ\s\-]{5,110})",
    ]
    for pat in direct_patterns:
        value = _clean_candidate(_first_match([pat], head))
        if value:
            value = re.sub(r"\s+CONCURSO\s+P[ÚU]BLICO.*$", "", value, flags=re.I).strip()
            value = re.sub(r"\s+ESTADO\s+DO?\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ\s-]+$", "", value).strip()
            if not _is_bad_orgao(value):
                return value[:170]
    fallback = _clean_candidate(_first_match([
        r"A\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ\s\-]{8,90})\s*,?\s+por meio",
        r"([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ\s\-]{8,90})\s+torna público",
    ], head))
    return fallback if fallback and not _is_bad_orgao(fallback) else None


def _extract_banca(full_text: str) -> str | None:
    return _clean_candidate(_first_match([
        r"banca(?: organizadora)?\s*[:\-–]\s*([^\n;.]{2,80})",
        r"Comissão Permanente de Concursos\s*\(([^)]+)\)",
        r"\b(COMPEC|CEBRASPE|CESPE|FGV|IBFC|FCC|VUNESP|IDECAN|AOCP|QUADRIX|IBADE|INSTITUTO\s+AOCP)\b",
    ], full_text))


def _has_date(text: str) -> bool:
    return bool(DATE_RE.search(text or ""))


def _all_values(row: dict[str, Any]) -> list[str]:
    return [str(v).strip() for v in row.values() if str(v).strip()]


def _row_value(row: dict[str, Any], names: list[str]) -> str | None:
    for key, value in row.items():
        low = str(key).lower()
        if any(name in low for name in names) and str(value).strip():
            return str(value).strip()
    return None


def _looks_like_code(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{1,5}\d{1,4}", value.strip()))


def _looks_like_city(value: str) -> bool:
    return bool(re.fullmatch(r"[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-Za-zÁÀÂÃÉÊÍÓÔÕÚÇáàâãéêíóôõúç\s\-]{2,45}", value.strip())) and not re.search(r"CR|\d|cargo|vaga|ensino|professor", value, re.I)


def _is_header_like_row(row: dict[str, Any]) -> bool:
    b = " ".join(_all_values(row)).lower()
    keys = " ".join(str(k).lower() for k in row.keys())
    return bool(re.fullmatch(r".*(cargo|vagas|remunera|requisito|carga horaria|escolaridade).*", b)) and not ROLE_RE.search(b) and not MONEY_RE.search(b)


def _money_from_row(row: dict[str, Any]) -> str | None:
    for key, value in row.items():
        low = str(key).lower()
        val = str(value)
        if any(x in low for x in ["remuneracao", "remuneração", "salario", "salário", "vencimento", "subsidio"]):
            m = MONEY_RE.search(val)
            if m:
                return m.group(0)
            if val.strip() and re.search(r"sal[aá]rios?\s+m[ií]nimos?", val, re.I):
                return val.strip()
    for val in _all_values(row):
        m = MONEY_RE.search(val)
        if m:
            return m.group(0)
    return None


def _carga_from_row(row: dict[str, Any]) -> str | None:
    explicit = _row_value(row, ["carga_horaria", "carga", "jornada", "horaria", "ch"])
    if explicit and re.search(r"\d+\s*h|horas|semanais", explicit, re.I):
        return explicit[:80]
    for val in _all_values(row):
        if re.fullmatch(r"\d{1,3}\s*h(?:/s|oras)?|\d{1,3}\s*horas(?:\s+semanais)?", val.strip(), re.I):
            return val.strip()
    return None


def _requisito_from_row(row: dict[str, Any]) -> str | None:
    for key, value in row.items():
        low = str(key).lower()
        if "fallback" in low:
            continue
        if any(name in low for name in ["requisito", "escolaridade", "formacao", "formação", "habilitacao", "exigencia"]):
            val = str(value).strip()
            if val and len(val) > 2:
                return val[:320]
    candidates = []
    for val in _all_values(row):
        if REQ_RE.search(val):
            candidates.append(val)
    if candidates:
        return " ".join(candidates)[:320]
    for val in _all_values(row):
        if len(val) > 30 and not MONEY_RE.search(val) and not DATE_RE.search(val) and not re.fullmatch(r"CR|\d+|\d+\s*\+\s*CR", val, re.I):
            if not FORM_RE.search(val) and not TITLE_RE.search(val):
                return val[:320]
    return None


def _vagas_from_row(row: dict[str, Any]) -> str | None:
    for key, value in row.items():
        low = str(key).lower()
        val = str(value).strip()
        if not val:
            continue
        if any(x in low for x in ["vagas", "ampla_concorrencia", "total"]):
            if re.fullmatch(r"CR|\d{1,4}\*?|\d{1,4}\s*\+\s*CR|\d{1,4}\s*\+\s*Cadastro Reserva", val, re.I):
                return val
    for val in _all_values(row):
        if _looks_like_code(val) or _looks_like_city(val) or MONEY_RE.search(val) or DATE_RE.search(val):
            continue
        if re.fullmatch(r"CR|\d{1,4}\*?|\d{1,4}\s*\+\s*CR", val, re.I):
            return val
    return None


def _cargo_from_row(row: dict[str, Any]) -> str | None:
    cargo = _row_value(row, ["cargo", "emprego", "função", "funcao"])
    if cargo and not FORM_RE.search(cargo) and not TITLE_RE.search(cargo):
        return cargo[:160]
    values = [v for v in _all_values(row) if not _looks_like_code(v) and not MONEY_RE.search(v) and not DATE_RE.search(v)]
    values = [v for v in values if 4 <= len(v) <= 150 and not re.fullmatch(r"CR|\d+|\d+\s*\+\s*CR", v, re.I)]
    role_vals = [v for v in values if ROLE_RE.search(v) and not FORM_RE.search(v) and not TITLE_RE.search(v)]
    if role_vals:
        return max(role_vals, key=len)[:160]
    return None


def _merge_cargo_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for row in rows:
        if not any(str(v).strip() for v in row.values()) or _is_header_like_row(row):
            continue
        cargo = _cargo_from_row(row)
        if cargo:
            merged.append(dict(row))
            continue
        if not merged:
            continue
        vals = [v for v in _all_values(row) if not re.fullmatch(r"\d+|CR", v, re.I)]
        if not vals:
            continue
        text = " ".join(vals)
        prev = merged[-1]
        money = MONEY_RE.search(text)
        if money and not _money_from_row(prev):
            prev["remuneracao_fallback"] = money.group(0)
        if REQ_RE.search(text):
            prev["requisito_fallback"] = (str(prev.get("requisito_fallback", "")).strip() + " " + text).strip()
        elif len(text) > 20 and not FORM_RE.search(text):
            prev["observacao_fallback"] = (str(prev.get("observacao_fallback", "")).strip() + " " + text).strip()
    return merged


def _cargo_suspicion(cargo: str, row: dict[str, Any], vagas: str | None, remun: str | None, req: str | None) -> tuple[bool, str | None, str]:
    blob = " ".join(_all_values(row))
    reasons = []
    if TITLE_RE.search(cargo) or TITLE_RE.search(blob):
        reasons.append("parece tabela de avaliação de títulos, não cargo")
    if FORM_RE.search(blob) and not (vagas or remun or req):
        reasons.append("linha parece formulário/anexo")
    if vagas and _looks_like_city(vagas):
        reasons.append("campo de vagas parece município/localidade")
    if not (vagas or remun or req):
        reasons.append("sem evidência de vaga, remuneração ou requisito")
    if re.fullmatch(r"cargo|emprego|função|função pública|escolaridade|requisito", cargo.strip(), re.I):
        reasons.append("nome parece cabeçalho")
    conf = "alta" if not reasons and (vagas and (remun or req)) else "media" if not reasons else "baixa"
    return bool(reasons), "; ".join(reasons) if reasons else None, conf


def _extract_cargos_from_tables(tables: list[dict[str, Any]]) -> list[Cargo]:
    cargos: list[Cargo] = []
    seen = set()
    for t in tables:
        if t.get("ignored") or t.get("kind") != "quadro_de_vagas":
            continue
        # Prevent form/title tables from producing cargo rows even if misclassified.
        table_blob = " ".join(t.get("headers", [])) + " " + " ".join(" ".join(row.values()) for row in t.get("rows", [])[:8])
        if TITLE_RE.search(table_blob):
            continue
        if FORM_RE.search(table_blob) and not re.search(r"vagas|remunera|sal[aá]rio|vencimento|carga hor[aá]ria|requisito|escolaridade", table_blob, re.I):
            continue
        for row in _merge_cargo_rows(t.get("rows", [])[:220]):
            cargo = _cargo_from_row(row)
            if not cargo or len(cargo) < 4:
                continue
            if re.search(r"total|reservas legais|munic[ií]pio|hor[aá]ria", cargo, re.I) and len(cargo) < 50:
                continue
            vagas = _vagas_from_row(row)
            remuneracao = _money_from_row(row) or row.get("remuneracao_fallback")
            carga = _carga_from_row(row)
            requisito_base = _requisito_from_row(row)
            requisito_extra = str(row.get("requisito_fallback") or row.get("observacao_fallback") or "").strip()
            requisito = requisito_base or requisito_extra or None
            if requisito_base and requisito_extra and requisito_extra not in requisito_base:
                requisito = f"{requisito_base} {requisito_extra}"[:340]
            if requisito and requisito.strip().lower() == cargo.strip().lower():
                requisito = None
            suspeito, motivo, confianca = _cargo_suspicion(cargo, row, vagas, remuneracao, requisito)
            if suspeito and motivo and ("avaliação de títulos" in motivo or "formulário" in motivo):
                # Do not put obvious non-cargos in the main wiki list.
                continue
            key = re.sub(r"\s+", " ", cargo.lower()).strip()
            if key in seen:
                continue
            seen.add(key)
            cargos.append(Cargo(
                nome=cargo[:150], vagas=vagas, remuneracao=remuneracao, carga_horaria=carga,
                requisito=requisito, fonte=t.get("id"), fonte_tipo="tabela", pagina=t.get("page"),
                confianca=confianca, suspeito=suspeito, motivo_suspeita=motivo,
            ))
            if len(cargos) >= 120:
                return cargos
    return cargos


def _extract_cargos(chunks: list[dict[str, Any]], tables: list[dict[str, Any]]) -> list[Cargo]:
    from_tables = _extract_cargos_from_tables(tables)
    if from_tables:
        return _enrich_cargos(from_tables, chunks, tables)
    cargos: list[Cargo] = []
    seen = set()
    for c in [c for c in chunks if c.get("kind") == "cargos_vagas"][:30]:
        for line in c.get("text", "").splitlines():
            clean = re.sub(r"\s+", " ", line).strip(" |\t")
            if len(clean) < 8 or len(clean) > 180 or not ROLE_RE.search(clean):
                continue
            if re.search(r"conteúdo|programático|deverá|inscrição|concurso público|título de", clean, re.I):
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            m = re.search(r"\b(CR|\d{1,4}\s*\+\s*CR|\d{1,4})\b", clean, re.I)
            cargos.append(Cargo(nome=clean[:140], vagas=m.group(1) if m else None, fonte=c.get("id"), fonte_tipo="chunk", pagina=c.get("page_start"), confianca="baixa"))
    return cargos


def _enrich_cargos(cargos: list[Cargo], chunks: list[dict[str, Any]], tables: list[dict[str, Any]]) -> list[Cargo]:
    # Lightweight generic enrichment: if salary/requirement is missing, search for the exact cargo in other table rows/chunks.
    for cargo in cargos:
        if cargo.remuneracao and cargo.requisito and cargo.carga_horaria:
            continue
        pattern = re.escape(cargo.nome[:70])
        for t in tables:
            if t.get("ignored"):
                continue
            for row in t.get("rows", [])[:260]:
                text = " ".join(_all_values(row))
                if not re.search(pattern, text, re.I):
                    continue
                if not cargo.remuneracao:
                    cargo.remuneracao = _money_from_row(row)
                if not cargo.carga_horaria:
                    cargo.carga_horaria = _carga_from_row(row)
                if not cargo.requisito:
                    cargo.requisito = _requisito_from_row(row)
        if not cargo.remuneracao or not cargo.requisito:
            for c in chunks[:200]:
                text = c.get("text", "")
                if not re.search(pattern, text, re.I):
                    continue
                window = text[:2000]
                if not cargo.remuneracao:
                    m = MONEY_RE.search(window)
                    if m:
                        cargo.remuneracao = m.group(0)
                if not cargo.requisito:
                    lines = [l.strip() for l in window.splitlines() if REQ_RE.search(l)]
                    if lines:
                        cargo.requisito = lines[0][:320]
    return cargos


def _extract_taxa(all_text: str, tables: list[dict[str, Any]]) -> str | None:
    for t in tables:
        if t.get("ignored") or t.get("kind") != "taxas":
            continue
        for row in t.get("rows", [])[:60]:
            row_blob = " ".join(str(v) for v in row.values())
            if re.search(r"taxa|inscri|boleto|pagamento", row_blob, re.I):
                m = MONEY_RE.search(row_blob)
                if m:
                    return m.group(0)
    for m in re.finditer(r".{0,90}(?:taxa de inscrição|taxa de inscricao|valor da inscrição|valor da taxa|boleto|pagamento da inscrição).{0,170}", all_text, re.I | re.S):
        window = re.sub(r"\s+", " ", m.group(0))
        if re.search(r"remuneração|remuneracao|vencimento|salário|salario|provento", window, re.I):
            continue
        value = MONEY_RE.search(window)
        if value:
            return value.group(0)
    return None


def _first_date_cell(row: dict[str, Any]) -> str | None:
    ini = _row_value(row, ["inicio", "início"])
    fim = _row_value(row, ["fim", "termino", "término"])
    parts = []
    if ini and DATE_RE.search(ini):
        parts.append(f"Início: {ini}")
    if fim and DATE_RE.search(fim):
        parts.append(f"Fim: {fim}")
    if parts:
        return " | ".join(parts)
    for value in row.values():
        value = str(value).strip()
        if value and DATE_RE.search(value):
            return value
    return None


def _best_event_cell(row: dict[str, Any]) -> str | None:
    values = [v for v in _all_values(row) if not re.fullmatch(r"\d{1,3}", v.strip())]
    values = [v for v in values if not DATE_RE.search(v)]
    if not values:
        return None
    eventish = [v for v in values if re.search(r"publica|inscri|prova|resultado|recurso|gabarito|homologa|impugna|convoca|pagamento|isen", v, re.I)]
    return max(eventish or values, key=len)


def _extract_cronograma_from_tables(tables: list[dict[str, Any]]) -> list[EventoCronograma]:
    events: list[EventoCronograma] = []
    seen = set()
    for t in tables:
        if t.get("ignored") or t.get("kind") != "cronograma":
            continue
        for row in t.get("rows", [])[:180]:
            event = _row_value(row, ["evento", "atividade", "etapa", "descrição", "descricao"]) or _best_event_cell(row)
            data = _row_value(row, ["data_ou_periodo", "data", "período", "periodo", "prazo"]) or _first_date_cell(row)
            if not event or not data or not DATE_RE.search(data):
                continue
            if len(event) < 4 or re.fullmatch(r"hor[aá]rio|data|fim|in[ií]cio", event, re.I):
                continue
            key = f"{event}|{data}".lower()
            if key in seen:
                continue
            seen.add(key)
            events.append(EventoCronograma(evento=event[:180], data_ou_periodo=data[:240], fonte=t.get("id"), fonte_tipo="tabela", pagina=t.get("page"), confianca=t.get("confidence", "media")))
            if len(events) >= 120:
                return events
    return events


def _extract_cronograma(chunks: list[dict[str, Any]], tables: list[dict[str, Any]]) -> list[EventoCronograma]:
    from_tables = _extract_cronograma_from_tables(tables)
    if from_tables:
        return from_tables
    events: list[EventoCronograma] = []
    seen = set()
    for c in chunks:
        if c.get("kind") not in {"cronograma", "inscricao", "etapas", "recursos"}:
            continue
        for line in c.get("text", "").splitlines():
            clean = re.sub(r"\s+", " ", line).strip()
            if len(clean) < 15 or len(clean) > 240 or not DATE_RE.search(clean):
                continue
            if not re.search(r"inscri|prova|resultado|recurso|isenção|isencao|pagamento|gabarito|cronograma|divulgação|publicação", clean, re.I):
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            events.append(EventoCronograma(evento=clean[:160], data_ou_periodo=clean[:220], fonte=c.get("id"), fonte_tipo="chunk", pagina=c.get("page_start"), confianca="baixa"))
            if len(events) >= 40:
                return events
    return events


def _extract_inscricao_from_cronograma(cronograma: list[EventoCronograma]) -> str | None:
    preferred = []
    fallback = []
    for ev in cronograma:
        e = ev.evento.lower()
        if "inscri" not in e:
            continue
        if any(x in e for x in ["isenção", "isencao", "resultado", "recurso", "homologa", "pagamento", "cartão", "cartao"]):
            fallback.append(ev)
        else:
            preferred.append(ev)
    return (preferred or fallback)[0].data_ou_periodo if (preferred or fallback) else None


def _extract_prova_from_cronograma(cronograma: list[EventoCronograma]) -> str | None:
    """Return only the application date/event for the summary field.

    Other proof-related events (gabarito, recurso, resultado, locais) stay in the Cronograma tab.
    """
    strong_patterns = [
        r"^\s*(aplica[cç][aã]o|realiza[cç][aã]o)\s+da\s+prova",
        r"^\s*prova\s+(objetiva|pr[aá]tica|discursiva)",
        r"data\s+da\s+prova",
        r"provas\s+objetivas",
    ]
    reject = re.compile(r"local|cart[aã]o|gabarito|resultado|recurso|homologa|convoca|divulga[cç][aã]o|vista|corre[cç][aã]o", re.I)
    for ev in cronograma:
        evento = ev.evento or ""
        data = ev.data_ou_periodo or ""
        if reject.search(evento):
            continue
        if any(re.search(p, evento, re.I) for p in strong_patterns):
            return f"{evento}: {data}"
    # fallback: any prova event with an explicit date, still avoiding administrative proof events.
    for ev in cronograma:
        evento = ev.evento or ""
        data = ev.data_ou_periodo or ""
        if "prova" in evento.lower() and not reject.search(evento) and _has_date(data):
            return f"{evento}: {data}"
    return None



def _status_for_field(name: str, value: str | None) -> CampoStatus:
    if not value:
        return CampoStatus(valor=None, status="nao_encontrado", motivo="campo não encontrado na extração inicial")
    v = value.strip()
    if name == "orgao":
        if _is_bad_orgao(v) or not ORG_GOOD_RE.search(v):
            return CampoStatus(valor=v, status="suspeito", motivo="valor parece cabeçalho, frase genérica ou não contém padrão claro de órgão")
        return CampoStatus(valor=v, status="confirmado", motivo="padrão forte de órgão encontrado no início do edital")
    if name == "taxa":
        if not MONEY_RE.search(v):
            return CampoStatus(valor=v, status="suspeito", motivo="não parece valor monetário")
        return CampoStatus(valor=v, status="provavel", motivo="valor monetário encontrado com contexto de inscrição/taxa")
    if name == "prova":
        if re.fullmatch(r"[a-zçãõéíóúêâô )(.]{1,25}", v, re.I):
            return CampoStatus(valor=v, status="suspeito", motivo="parece fragmento textual")
        return CampoStatus(valor=v, status="provavel", motivo="extraído de cronograma ou trecho com contexto de prova")
    if name == "inscricao":
        return CampoStatus(valor=v, status="provavel", motivo="extraído de cronograma ou trecho com contexto de inscrição")
    if name == "banca":
        return CampoStatus(valor=v, status="provavel", motivo="extraído por padrão textual de banca/comissão")
    return CampoStatus(valor=v, status="provavel")


def _build_status_maps(orgao: str | None, banca: str | None, inscricao: str | None, taxa: str | None, prova: str | None) -> tuple[dict[str, CampoStatus], dict[str, str], dict[str, str], dict[str, str]]:
    fields = {"orgao": orgao, "banca": banca, "inscricao": inscricao, "taxa": taxa, "prova": prova}
    status = {k: _status_for_field(k, v) for k, v in fields.items()}
    confirmados = {k: s.valor for k, s in status.items() if s.status == "confirmado" and s.valor}
    provaveis = {k: s.valor for k, s in status.items() if s.status == "provavel" and s.valor}
    suspeitos = {k: s.valor for k, s in status.items() if s.status == "suspeito" and s.valor}
    return status, confirmados, provaveis, suspeitos

def _build_quality(chunks: list[dict[str, Any]], tables: list[dict[str, Any]], cargos: list[Cargo], cronograma: list[EventoCronograma], orgao: str | None, taxa: str | None, prova: str | None) -> QualidadeIngestao:
    chunk_types = Counter(c.get("kind", "geral") for c in chunks)
    table_types = Counter(t.get("kind", "tabela_desconhecida") for t in tables)
    sizes = [int(c.get("char_count", len(c.get("text", "")))) for c in chunks]
    avisos: list[str] = []
    campos_suspeitos: list[str] = []

    tabelas_ignoradas = sum(1 for t in tables if t.get("ignored"))
    tabelas_uteis = sum(1 for t in tables if not t.get("ignored"))
    tabelas_continuacao = sum(1 for t in tables if t.get("inherited_from"))
    tabelas_suspeitas = 0
    for t in tables:
        if t.get("kind") == "quadro_de_vagas" and (t.get("scores", {}).get("formulario", 0) >= 8 or t.get("scores", {}).get("avaliacao_titulos", 0) >= 6):
            tabelas_suspeitas += 1
            campos_suspeitos.append(f"Tabela {t.get('id')} foi classificada como quadro de vagas, mas tem sinais de formulário/títulos.")
        if t.get("kind") == "tabela_desconhecida" and not t.get("ignored"):
            tabelas_suspeitas += 1
    cargos_suspeitos = sum(1 for c in cargos if c.suspeito)
    for c in cargos:
        if c.suspeito:
            campos_suspeitos.append(f"Cargo '{c.nome}' marcado com baixa confiança: {c.motivo_suspeita}")
    if orgao and _is_bad_orgao(orgao):
        campos_suspeitos.append("Órgão extraído parece cabeçalho de tabela ou frase genérica; revisar.")
    if taxa and not MONEY_RE.search(taxa):
        campos_suspeitos.append("Taxa extraída não parece valor monetário; revisar.")
    if prova and re.fullmatch(r"[a-zçãõéíóúêâô )(.]{1,20}", prova.strip(), re.I):
        campos_suspeitos.append("Data da prova parece fragmento textual; revisar.")

    if not tables:
        avisos.append("Nenhuma tabela foi detectada automaticamente; cargos e cronogramas podem depender de texto linearizado.")
    if table_types.get("avaliacao_titulos"):
        avisos.append(f"{table_types.get('avaliacao_titulos')} tabela(s) de avaliação de títulos foram separadas para não virar cargo.")
    if tabelas_ignoradas:
        avisos.append(f"{tabelas_ignoradas} tabela(s) foram classificadas como formulário/anexo/irrelevante e ignoradas na extração principal.")
    if tabelas_suspeitas:
        avisos.append(f"{tabelas_suspeitas} tabela(s) continuam suspeitas e devem ser revisadas.")
    if cargos_suspeitos:
        avisos.append(f"{cargos_suspeitos} cargo(s) foram extraídos com baixa confiança.")

    fontes_tabela = sum(1 for c in cargos if c.fonte_tipo == "tabela") + sum(1 for e in cronograma if e.fonte_tipo == "tabela")
    fontes_texto = sum(1 for c in cargos if c.fonte_tipo == "chunk") + sum(1 for e in cronograma if e.fonte_tipo == "chunk")
    return QualidadeIngestao(
        total_chunks=len(chunks), total_tabelas=len(tables), tipos_chunks=dict(chunk_types), tipos_tabelas=dict(table_types),
        maior_chunk_chars=max(sizes) if sizes else 0, media_chunk_chars=round(sum(sizes) / len(sizes)) if sizes else 0,
        chunks_muito_pequenos=sum(1 for s in sizes if s < 300), fontes_texto=fontes_texto, fontes_tabela=fontes_tabela,
        tabelas_uteis=tabelas_uteis, tabelas_ignoradas=tabelas_ignoradas, tabelas_continuacao=tabelas_continuacao,
        tabelas_suspeitas=tabelas_suspeitas, cargos_suspeitos=cargos_suspeitos,
        campos_suspeitos=campos_suspeitos[:30], avisos=avisos,
    )


def extract_summary(edital_id: str, chunks: list[dict[str, Any]], tables: list[dict[str, Any]] | None = None) -> ConcursoResumo:
    tables = tables or []
    full_text = "\n".join(c.get("text", "") for c in chunks[:14])
    all_text = "\n".join(c.get("text", "") for c in chunks)
    titulo = _find_title(full_text)
    orgao = _extract_orgao(full_text)
    banca = _extract_banca(full_text)
    ano = _first_match([r"\b(20\d{2})\b"], titulo + "\n" + full_text[:1200])
    cargos = _extract_cargos(chunks, tables)
    cronograma = _extract_cronograma(chunks, tables)
    inscricao = _extract_inscricao_from_cronograma(cronograma)
    if not inscricao:
        inscricao = _clean_candidate(_first_match([
            r"inscriç(?:ão|ões).*?(?:de|no período de|período)\s*([^\n.]{5,180})",
            r"período de inscrição\s*[:\-–]\s*([^\n.]{5,180})",
        ], all_text))
        if inscricao and not (_has_date(inscricao) or re.search(r"\bàs\b|\baté\b|início|término|inicio|fim", inscricao, re.I)):
            inscricao = None
    taxa = _extract_taxa(all_text, tables)
    prova = _extract_prova_from_cronograma(cronograma)
    if not prova:
        prova = _clean_candidate(_first_match([
            r"prova objetiva.*?(?:dia|data|realizada em)\s*([^\n.;]{5,100})",
            r"data da prova\s*[:\-–]\s*([^\n.;]{5,100})",
        ], all_text))
        if prova and not _has_date(prova):
            prova = None
    campos_status, dados_confirmados, dados_provaveis, dados_suspeitos = _build_status_maps(orgao, banca, inscricao, taxa, prova)
    qualidade = _build_quality(chunks, tables, cargos, cronograma, orgao, taxa, prova)
    for nome, st in campos_status.items():
        if st.status == "suspeito" and st.valor:
            qualidade.campos_suspeitos.append(f"{nome}: {st.valor} — {st.motivo}")
    missing = []
    for label, value in [("órgão", orgao), ("banca", banca), ("inscrição", inscricao), ("taxa", taxa), ("prova", prova)]:
        if not value:
            missing.append(label)
    return ConcursoResumo(
        edital_id=edital_id, titulo=titulo, orgao=orgao, banca=banca, ano=ano, inscricao=inscricao,
        taxa=taxa, prova=prova, cargos=cargos, cronograma=cronograma, campos_nao_encontrados=missing,
        campos_status=campos_status, dados_confirmados=dados_confirmados, dados_provaveis=dados_provaveis, dados_suspeitos=dados_suspeitos,
        qualidade=qualidade,
    )
