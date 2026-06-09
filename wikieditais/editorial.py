from __future__ import annotations

import json
import re
from typing import Any

from .config import config
from .llm import complete
from .utils import clean_text, date_fmt, money_fmt

# =============================================================================
# WikiEditais v11 — Editorial Engine
# =============================================================================
# Objetivo: transformar edital em uma base de conhecimento escrita como guia,
# não em cópia do PDF. Esta camada ensina o modelo o papel de cada página,
# separa fatos validados de material bruto e faz uma revisão crítica simples.
# =============================================================================

NO_COPY_RULES = """
IDENTIDADE DO AGENTE
Você é um editor especializado em editais de concursos públicos. Seu trabalho é transformar PDF bruto em uma LLM Wiki útil para candidatos. Você não é um copiador de edital e não é apenas um extrator de campos.

PRINCÍPIO CENTRAL
- O PDF é evidência, não texto final.
- A wiki deve parecer um guia escrito manualmente para candidato.
- Cada página tem uma função: explicar um tema, separar o que está confirmado, avisar o que precisa de revisão e apontar fontes.
- Informação incerta deve ser escrita como “não identificado com segurança”, nunca inventada.

ONTOLOGIA BÁSICA DE EDITAIS
- Instituição/órgão: entidade responsável pela seleção, como Prefeitura, Universidade, Conselho, Secretaria.
- Banca/organizadora: entidade que organiza ou aplica o certame, como IPRO, IBADE, CEBRASPE, FGV, FEPESE, COMPEC.
- Cargo/função: oportunidade para qual o candidato concorre. Ex.: Enfermeiro, Guarda Civil Municipal, Assistente Administrativo, Professor de Matemática.
- Vaga: quantidade oferecida para um cargo, incluindo ampla concorrência, PcD, cadastro reserva ou lotação.
- Requisito: escolaridade, curso, registro em conselho, CNH ou experiência exigida para o cargo.
- Salário/vencimento/remuneração: valor pago pelo cargo. Auxílio, taxa, adicional, nota e pontuação não são salário base.
- Cronograma: datas operacionais do certame, como inscrição, pagamento, prova, gabarito, recurso e resultado.
- Status do edital: situação do certame inteiro, não situação de uma inscrição individual.

REGRAS DURAS
- Não copie blocos crus do edital como corpo principal.
- Não transforme regra solta em cargo.
- Não transforme “inscrição cancelada” em “concurso cancelado”.
- Não transforme data de lei/decreto/portaria/CNPJ/CEP em cronograma.
- Não transforme auxílio, taxa, adicional, nota ou pontuação em salário.
- Não transforme “Nível Médio”, “Remuneração:” ou “PcD” sozinho em cargo.
- Não coloque frase quebrada em tabela.
- Se a tabela estiver ruim, escreva resumo e marque revisão.

COMO ESCREVER
- Comece com visão geral clara.
- Explique para que serve a página.
- Use listas e tabelas apenas quando ajudarem.
- Separe dados confirmados de pendências.
- Inclua “Pontos de atenção” quando houver retificação, suspensão, prorrogação, tabela extensa ou informação incompleta.
- Termine com fontes usadas.
""".strip()

PAGE_PLANS: dict[str, dict[str, Any]] = {
    'dados_gerais': {
        'title': 'Dados gerais',
        'intent': 'Identificar o edital, o órgão, a banca e o escopo, separando informações confirmadas de incertezas.',
        'definition': 'Dados gerais são a identidade documental do edital: título, número, órgão responsável, banca/organizadora, cidade/UF quando aplicável, tipo de seleção e situação do certame.',
        'must_include': ['título do edital', 'instituição/órgão responsável', 'banca ou organizadora se houver', 'cidade/UF quando aplicável', 'situação do edital', 'observações de confiabilidade'],
        'avoid': ['frases de comparecimento', 'documentos pessoais', 'endereço como se fosse instituição', 'comissão genérica como banca quando houver organizadora explícita'],
        'sections': ['Visão geral', 'Identificação do edital', 'Órgão e organização', 'Situação do edital', 'O que ainda precisa de revisão'],
        'good': 'O edital trata de concurso público do Conselho Regional de Enfermagem do Amazonas, organizado pelo IBADE. As informações principais foram separadas para consulta rápida.',
        'bad': 'Dados gerais: o candidato deverá comparecer munido de documento...',
    },
    'inscricoes': {
        'title': 'Inscrições',
        'intent': 'Explicar como o candidato se inscreve, prazo, taxa, pagamento, isenção e cuidados.',
        'definition': 'Inscrição é o processo pelo qual o candidato solicita participação no certame. Inclui período, canal, formulário, boleto, pagamento, taxa, isenção, homologação de inscrição e problemas de inscrição.',
        'must_include': ['período de inscrição', 'site/canal', 'taxa e pagamento', 'isenção', 'prorrogação se houver', 'cuidados para não ter inscrição indeferida'],
        'avoid': ['tratar inscrição cancelada como concurso cancelado', 'copiar regras longas de formulário', 'confundir homologação de inscrições com resultado final'],
        'sections': ['Visão geral', 'Como se inscrever', 'Período de inscrição', 'Taxa e pagamento', 'Isenção', 'Pontos de atenção'],
        'good': 'As inscrições devem seguir o período e o canal definidos pelo edital. Quando a data exata não foi consolidada, a página indica que o candidato deve consultar o cronograma oficial.',
        'bad': 'Inscrições: 3.1 Será cancelada a inscrição do candidato...',
    },
    'cargos_vagas': {
        'title': 'Cargos, vagas e salários',
        'intent': 'Apresentar cargos/oportunidades, vagas, requisitos, carga horária, remuneração e benefícios sem misturar regras aleatórias.',
        'definition': 'Cargo é a função ou oportunidade para a qual o candidato concorre. Uma linha boa de cargo normalmente tem nome da função, requisito, carga horária, vagas e remuneração.',
        'must_include': ['resumo por nível de escolaridade', 'total de vagas se identificado', 'cargos ou exemplos de cargos', 'requisitos', 'carga horária', 'salário/remuneração', 'PcD/cadastro reserva se houver', 'erratas que alteram vagas'],
        'avoid': ['lei/decreto como cargo', 'frase de PcD como cargo', 'comparecimento como cargo', 'conteúdo programático como cargo', 'benefício como salário', 'Nível Médio sozinho como cargo'],
        'sections': ['Visão geral', 'Resumo das oportunidades', 'Cargos identificados', 'Remuneração e benefícios', 'Requisitos', 'Pontos de atenção'],
        'good': 'O quadro de oportunidades indica cargo, quantidade de vagas e remuneração. Benefícios aparecem separados do salário base.',
        'bad': 'Cargo: destinada à pessoa com deficiência será a 5ª vaga; Cargo: o candidato deverá comparecer...',
    },
    'etapas_provas': {
        'title': 'Etapas e provas',
        'intent': 'Explicar as etapas de avaliação, tipos de prova, critérios, comparecimento e classificação.',
        'definition': 'Etapas e provas descrevem como o candidato será avaliado: prova objetiva, prática, títulos, critérios de pontuação, classificação, eliminação e regras de comparecimento.',
        'must_include': ['tipo de prova', 'data da prova se clara', 'turno/horário se claro', 'disciplinas', 'pontuação', 'critérios de aprovação', 'títulos ou prova prática se houver'],
        'avoid': ['usar data de recurso como data de prova', 'usar lei como prova', 'misturar conteúdo programático inteiro no corpo'],
        'sections': ['Visão geral', 'Etapas da seleção', 'Prova objetiva ou avaliação', 'Critérios de classificação', 'Comparecimento e documentos', 'Pontos de atenção'],
        'good': 'A seleção pode incluir prova objetiva, avaliação de títulos ou outras etapas. A página separa regra de aplicação, critérios e cuidados para o candidato.',
        'bad': 'Prova: Lei nº 14.133/2021 de 1º de abril de 2021...',
    },
    'cronograma': {
        'title': 'Cronograma',
        'intent': 'Listar datas operacionais do certame e explicar o que o candidato deve acompanhar.',
        'definition': 'Cronograma é conjunto de datas operacionais do concurso: inscrições, pagamento, isenção, prova, gabarito, recurso, resultado, homologação e convocação.',
        'must_include': ['eventos com data confirmada', 'intervalos de inscrição/pagamento', 'prova/gabarito/recurso/resultado se houver', 'datas não identificadas com segurança'],
        'avoid': ['datas de leis', 'decretos', 'portarias', 'CNPJ', 'CEP', 'datas antigas de legislação', 'data solta sem evento'],
        'sections': ['Visão geral', 'Eventos confirmados', 'Datas não identificadas com segurança', 'Como acompanhar atualizações'],
        'good': 'O cronograma deve reunir inscrição, pagamento, prova, gabarito, recursos e resultados quando essas datas estiverem claras.',
        'bad': 'Cronograma: Lei nº 8.112 de 11/12/1990; Decreto nº...',
    },
    'recursos': {
        'title': 'Recursos',
        'intent': 'Explicar quando e como apresentar recurso, contra quais fases e quais cuidados seguir.',
        'definition': 'Recursos são mecanismos de contestação contra atos do certame, como indeferimento de inscrição, gabarito, nota, classificação ou resultado preliminar.',
        'must_include': ['prazo de recurso se claro', 'canal de envio', 'atos recorríveis', 'exigência de fundamentação', 'cuidados formais'],
        'avoid': ['copiar toda norma jurídica', 'confundir recurso administrativo com recurso financeiro/material'],
        'sections': ['Visão geral', 'Quando cabe recurso', 'Como interpor recurso', 'Prazos', 'Pontos de atenção'],
        'good': 'A página explica o procedimento de recurso e orienta o candidato a acompanhar o prazo indicado para cada etapa.',
        'bad': 'Recursos: não haverá recursos será de responsabilidade...',
    },
    'requisitos_documentos': {
        'title': 'Requisitos e documentos',
        'intent': 'Organizar requisitos de participação, posse/contratação, documentos e impedimentos.',
        'definition': 'Requisitos são condições para inscrição, participação, posse ou contratação. Podem incluir escolaridade, idade, nacionalidade, documentos, registro profissional, CNH e aptidão física/mental.',
        'must_include': ['requisitos gerais', 'documentos exigidos', 'requisitos por cargo quando possível', 'posse/contratação', 'registros profissionais'],
        'avoid': ['transformar documento em cargo', 'copiar lista gigantesca sem explicação', 'misturar requisito com conteúdo programático'],
        'sections': ['Visão geral', 'Requisitos de participação', 'Documentos exigidos', 'Posse, matrícula ou contratação', 'Pontos de atenção'],
        'good': 'Os requisitos devem ser conferidos antes da inscrição e novamente na etapa de posse ou contratação.',
        'bad': 'Requisitos: dado o decreto o cargo deve comparecer...',
    },
    'conteudo_programatico': {
        'title': 'Conteúdo programático',
        'intent': 'Transformar o programa de estudos em uma página navegável por disciplinas e tópicos.',
        'definition': 'Conteúdo programático é o conjunto de disciplinas e tópicos cobrados na prova. Deve virar guia de estudos, não bloco copiado.',
        'must_include': ['disciplinas gerais', 'conhecimentos específicos', 'organização por cargo ou nível quando houver', 'orientação de estudo'],
        'avoid': ['regras de inscrição', 'regras de posse', 'prazos de recurso', 'documentos pessoais como conteúdo'],
        'sections': ['Visão geral', 'Disciplinas identificadas', 'Conteúdos por área', 'Como usar esta página para estudar'],
        'good': 'A página agrupa disciplinas e tópicos cobrados, sem misturar conteúdo programático com regras administrativas.',
        'bad': 'Conteúdo: perderá o direito à vaga, recurso indeferido...',
    },
    'retificacoes': {
        'title': 'Retificações e comunicados',
        'intent': 'Registrar alterações, prorrogações, suspensões, erratas e comunicados, sem confundir menções soltas com status.',
        'definition': 'Retificações são alterações oficiais do edital: erratas, comunicados, suspensão, prorrogação ou mudança de tabela. A página deve explicar o impacto prático para o candidato.',
        'must_include': ['tipo de alteração', 'data do comunicado se houver', 'o que mudou', 'impacto para inscrição/prova/cargos', 'pontos que precisam de conferência'],
        'avoid': ['copiar todos os Onde se lê/Leia-se sem síntese', 'confundir cancelamento individual com cancelamento do certame'],
        'sections': ['Visão geral', 'Alterações identificadas', 'Impacto para o candidato', 'Pontos que exigem conferência'],
        'good': 'Se houver retificação, a página explica o que mudou e quais partes do edital original foram afetadas.',
        'bad': 'Retificação: a inscrição poderá ser cancelada...',
    },
}


def write_editorial_topic_page(topic: str, label: str, material: str, structured: dict, section_pages: list[int] | None, model_id: str | None) -> str:
    plan = PAGE_PLANS.get(topic, {'title': label, 'intent': 'Escrever uma página de wiki útil.', 'sections': ['Visão geral', 'Informações principais', 'Pontos de atenção'], 'good': '', 'bad': ''})
    source_note = 'Páginas usadas: ' + (', '.join(f'p. {p}' for p in (section_pages or [])[:40]) if section_pages else 'não identificadas com segurança') + '.'

    if config.data.get('indexing', {}).get('use_llm_for_wiki_writing', True) and model_id and (material or structured):
        prompt = editorial_prompt(topic, plan, structured, material, source_note)
        try:
            out = complete(
                prompt,
                model_id=model_id,
                system='Você é um editor de LLM Wiki de concursos públicos. Escreva como guia, não como cópia.',
                temperature=0.05,
                timeout=int(config.data.get('indexing', {}).get('request_timeout_seconds', 360)),
            )
            out = sanitize_editorial_markdown(out, plan['title'], source_note)
            score, reasons = score_wiki_page(out, topic)
            # Se o texto ainda parecer dump, uma única revisão pede reescrita.
            if score < 72 and config.data.get('indexing', {}).get('use_llm_editorial_critic', True):
                revised = revise_page(out, topic, plan, structured, material, source_note, reasons, model_id)
                if revised:
                    rscore, _ = score_wiki_page(revised, topic)
                    if rscore >= score:
                        out = revised
                        score = rscore
            if score >= 58:
                return out
        except Exception:
            pass
    return deterministic_editorial_page(topic, plan, structured, material, source_note)


def editorial_prompt(topic: str, plan: dict, structured: dict, material: str, source_note: str) -> str:
    return f"""
{NO_COPY_RULES}

TAREFA
Você vai escrever a página `{plan['title']}` de uma LLM Wiki de concursos públicos.
Objetivo da página: {plan['intent']}

CONCEITO DA PÁGINA
Definição do tema: {plan.get('definition', 'Tema da wiki de edital.')}
Informações que esta página deve procurar: {', '.join(plan.get('must_include', [])) or 'informações principais do tópico'}
Coisas que NÃO pertencem a esta página: {', '.join(plan.get('avoid', [])) or 'ruídos fora do tópico'}

FORMATO OBRIGATÓRIO
- Comece exatamente com: # {plan['title']}
- Use estas seções, nesta ordem quando fizer sentido: {', '.join(plan['sections'])}
- A primeira seção deve explicar o tema em linguagem natural, não despejar dado.
- Escreva como guia para candidato: explique o que significa e o que ele deve conferir.
- Use tabelas apenas para cargos, datas ou valores quando houver fatos claros.
- Se uma tabela estiver longa, resuma por grupos e mostre exemplos confiáveis.
- Se um campo importante não estiver claro, escreva “não identificado com segurança”.
- Tenha uma seção de “Pontos de atenção” quando houver errata, suspensão, tabela quebrada ou incerteza.
- Termine com uma seção `## Fontes usadas` contendo apenas: {source_note}

EXEMPLO RUIM, NÃO FAÇA:
{plan.get('bad','')}

EXEMPLO BOM, SIGA O ESTILO:
{plan.get('good','')}

FATOS VALIDADOS / DADOS ESTRUTURADOS
{json.dumps(structured or {}, ensure_ascii=False, indent=2)[:7000]}

MATERIAL BRUTO DE APOIO
Use apenas como evidência. Não copie como texto final.
{(material or '')[:9000]}

Agora escreva somente Markdown final.
""".strip()


def revise_page(page: str, topic: str, plan: dict, structured: dict, material: str, source_note: str, reasons: list[str], model_id: str) -> str | None:
    prompt = f"""
Você é o revisor editorial de uma LLM Wiki de concursos públicos.
A página abaixo foi gerada, mas tem problemas: {', '.join(reasons) or 'qualidade irregular'}.
Reescreva a página inteira para parecer um guia feito à mão para candidato.

REGRAS:
{NO_COPY_RULES}

Página esperada: {plan['title']}
Objetivo: {plan['intent']}
Definição do tema: {plan.get('definition', 'Tema da wiki de edital.')}
Deve procurar: {', '.join(plan.get('must_include', [])) or 'informações principais'}
Não deve incluir: {', '.join(plan.get('avoid', [])) or 'ruídos fora do tópico'}
Seções esperadas: {', '.join(plan['sections'])}

Fatos validados:
{json.dumps(structured or {}, ensure_ascii=False, indent=2)[:6000]}

Página ruim:
{page[:9000]}

Material bruto, apenas se precisar conferir:
{(material or '')[:5000]}

Finalize com `## Fontes usadas` e `{source_note}`.
Responda somente Markdown.
""".strip()
    try:
        out = complete(prompt, model_id=model_id, system='Você revisa e reescreve páginas de wiki de edital.', temperature=0.03, timeout=int(config.data.get('indexing', {}).get('request_timeout_seconds', 360)))
        return sanitize_editorial_markdown(out, plan['title'], source_note)
    except Exception:
        return None


def deterministic_editorial_page(topic: str, plan: dict, structured: dict, material: str, source_note: str) -> str:
    title = plan['title']
    out = [f'# {title}', '', '## Visão geral', '', default_intro(topic), '']
    if topic == 'dados_gerais':
        rows = [
            ('Título', structured.get('title')),
            ('Tipo', structured.get('document_type')),
            ('Instituição', structured.get('institution')),
            ('Banca/organização', structured.get('organizer')),
            ('Localidade', localidade(structured)),
            ('Situação', structured.get('status')),
        ]
        out += ['## Identificação do edital', '']
        out += [f'- **{k}:** {v or "não identificado com segurança"}' for k, v in rows]
    elif topic == 'inscricoes':
        out += ['## Informações principais', '', f'- **Período:** {periodo(structured.get("registration_start"), structured.get("registration_end"))}', f'- **Taxa:** {fee_text(structured)}', '', '## Pontos de atenção', '', '- Confira sempre o canal oficial de inscrição e o prazo de pagamento indicados no edital.', '- Se houver regra de isenção, ela deve ser solicitada dentro do prazo próprio.']
    elif topic == 'cargos_vagas':
        out += cargos_block(structured)
    elif topic == 'etapas_provas':
        out += ['## Etapas identificadas', '', f'- **Data de prova/avaliação:** {date_fmt(structured.get("exam_date")) or "não identificada com segurança"}', f'- **Local de prova:** {structured.get("exam_location") or "não identificado com segurança"}', '', '## Como ler esta página', '', 'Esta página concentra regras de prova, avaliação, classificação e comparecimento. Regras administrativas que não descrevem etapa de seleção foram tratadas como contexto, não como evento.']
    elif topic == 'cronograma':
        out += cronograma_block(structured)
    elif topic == 'recursos':
        out += ['## Quando cabe recurso', '', 'O edital pode prever recurso contra inscrições, gabarito, resultado preliminar ou outras etapas. Quando o prazo exato não estiver consolidado, consulte o cronograma oficial.', '', '## Pontos de atenção', '', '- Recursos normalmente precisam ser enviados no prazo e pelo canal definido pela banca.', '- Evite considerar datas de leis ou decretos como prazo de recurso.']
    elif topic == 'requisitos_documentos':
        out += ['## Requisitos de participação', '', 'Esta página reúne condições de participação, requisitos para posse, matrícula ou contratação e documentos exigidos. Quando o edital trouxer exigências específicas por cargo, elas devem ser conferidas junto da página de cargos e vagas.']
    elif topic == 'conteudo_programatico':
        out += ['## Disciplinas e tópicos', '', 'O conteúdo programático deve ser usado como guia de estudos. Quando o edital trouxer conteúdos diferentes por cargo, confira se o tópico pertence ao cargo desejado antes de estudar.']
    elif topic == 'retificacoes':
        out += ['## Alterações e comunicados', '', 'Esta página registra retificações, prorrogações, suspensões ou comunicados quando forem identificados de forma explícita. Menções genéricas a cancelamento de inscrição ou regras individuais não alteram o status do concurso.']

    useful = summarize_material(material, topic)
    if useful:
        out += ['', '## Síntese editorial', ''] + useful
    out += ['', '## Fontes usadas', '', source_note]
    return '\n'.join(out).strip() + '\n'


def default_intro(topic: str) -> str:
    return {
        'dados_gerais': 'Esta página apresenta a identificação do edital e os dados principais para consulta rápida.',
        'inscricoes': 'Esta página explica como funcionam as inscrições e quais cuidados o candidato deve observar.',
        'cargos_vagas': 'Esta página organiza oportunidades, vagas, requisitos, salários e benefícios sem misturar regras administrativas com nomes de cargos.',
        'etapas_provas': 'Esta página resume etapas de seleção, provas, avaliação e critérios de classificação.',
        'cronograma': 'Esta página reúne datas operacionais do certame. Referências legais e datas de normas são ignoradas.',
        'recursos': 'Esta página reúne orientações sobre recursos e contestação de etapas.',
        'requisitos_documentos': 'Esta página organiza requisitos e documentos exigidos para participação ou contratação.',
        'conteudo_programatico': 'Esta página transforma o programa do edital em uma visão de estudos.',
        'retificacoes': 'Esta página registra alterações oficiais e comunicados relevantes do edital.',
    }.get(topic, 'Esta página organiza informações do edital em linguagem de wiki.')


def cargos_block(structured: dict) -> list[str]:
    out = ['## Resumo das oportunidades', '']
    out.append(f'- **Total de vagas:** {structured.get("total_vacancies") or "não consolidado com segurança"}')
    smin, smax = structured.get('salary_min'), structured.get('salary_max')
    out.append(f'- **Faixa salarial:** {money_fmt(smin) if smin else "não identificada"}' + (f' a {money_fmt(smax)}' if smax and smax != smin else ''))
    positions = structured.get('positions_preview') or []
    out.append(f'- **Cargos consolidados:** {len(positions) if positions else "não identificados com segurança"}')
    if positions:
        out += ['', '## Cargos identificados', '', '| Cargo | Vagas | Remuneração | Requisitos |', '|---|---:|---:|---|']
        for p in positions[:40]:
            out.append(f"| {safe_cell(p.get('name'))} | {p.get('vacancies') if p.get('vacancies') is not None else '—'} | {money_fmt(p.get('salary')) if p.get('salary') else '—'} | {safe_cell(p.get('requirements') or '—')} |")
    else:
        out += ['', '## Cargos identificados', '', 'A tabela de cargos não foi consolidada com segurança. Use esta página como guia e confira o quadro oficial do edital ou anexo correspondente.']
    out += ['', '## Como interpretar cargos, vagas e salário', '', 'Cargos são nomes de funções ou oportunidades. Regras de PcD, comparecimento, documentos e decretos não devem ser tratadas como cargo. Benefícios, auxílios e taxas também não são salário base.']
    return out


def cronograma_block(structured: dict) -> list[str]:
    events = structured.get('timeline') or []
    out = ['## Eventos confirmados', '']
    if events:
        out += ['| Evento | Início | Fim |', '|---|---:|---:|']
        for ev in events[:40]:
            out.append(f"| {safe_cell(ev.get('label') or ev.get('type') or 'Evento')} | {date_fmt(ev.get('start')) or '—'} | {date_fmt(ev.get('end')) or '—'} |")
    else:
        out.append('Nenhuma data operacional foi consolidada com segurança. Isso é preferível a confundir datas de leis, decretos ou referências normativas com cronograma do concurso.')
    out += ['', '## Como acompanhar atualizações', '', 'O candidato deve acompanhar o site oficial da banca ou instituição, especialmente para retificações, locais de prova, gabaritos e resultados.']
    return out


def localidade(s: dict) -> str | None:
    city, state = s.get('city'), s.get('state')
    if city and state:
        return f'{city}/{state}'
    return state or city


def periodo(a: Any, b: Any) -> str:
    if a and b:
        return f'{date_fmt(a)} a {date_fmt(b)}'
    if b:
        return f'até {date_fmt(b)}'
    if a:
        return f'a partir de {date_fmt(a)}'
    return 'não identificado com segurança'


def fee_text(s: dict) -> str:
    if s.get('fee_min') and s.get('fee_max') and s.get('fee_min') != s.get('fee_max'):
        return f"{money_fmt(s.get('fee_min'))} a {money_fmt(s.get('fee_max'))}"
    return money_fmt(s.get('fee') or s.get('fee_min') or s.get('fee_max')) or 'não identificada com segurança'


def summarize_material(material: str, topic: str) -> list[str]:
    if not material:
        return []
    # Seleciona poucas frases úteis, removendo aparência de norma/cópia.
    bad = r'lei n[ºo]|decreto|portaria|cnpj|cep|cadastro único|constituição'
    good_by_topic = {
        'inscricoes': r'inscri|taxa|pagamento|isen',
        'cargos_vagas': r'cargo|vaga|remunera|vencimento|sal[aá]rio|requisito|jornada',
        'etapas_provas': r'prova|etapa|avalia|classifica|gabarito|t[íi]tulo',
        'cronograma': r'cronograma|prazo|per[ií]odo|data|resultado|recurso|prova|inscri',
        'recursos': r'recurso|impugna|contest',
    }.get(topic, r'edital|concurso|processo|seleção|selecao')
    out = []
    for sent in re.split(r'(?<=[.!?])\s+|\n+', material):
        s = clean_text(sent)
        low = s.lower()
        if len(s) < 60 or len(s) > 360:
            continue
        if re.search(bad, low):
            continue
        if not re.search(good_by_topic, low):
            continue
        out.append('- ' + editorialize_sentence(s))
        if len(out) >= 4:
            break
    return out


def editorialize_sentence(s: str) -> str:
    s = re.sub(r'^\[p\.\s*\d+\]\s*', '', s, flags=re.I)
    s = clean_text(s)
    if len(s) > 260:
        s = s[:257].rstrip() + '...'
    return s


def score_wiki_page(md: str, topic: str) -> tuple[int, list[str]]:
    reasons = []
    score = 100
    if not md or len(md) < 700:
        score -= 25; reasons.append('texto curto')
    lines = [l for l in md.splitlines() if l.strip()]
    if lines:
        bullet = sum(1 for l in lines if l.strip().startswith(('-', '*')))
        if bullet / max(1, len(lines)) > 0.68:
            score -= 18; reasons.append('parece lista/dump')
    if re.search(r'\[p\.\s*\d+\].{120,}', md, re.I):
        score -= 15; reasons.append('contém evidência crua longa')
    if re.search(r'lei n[ºo]|decreto|portaria|cnpj|cep', md[:2500].lower()) and topic in {'cronograma','cargos_vagas','dados_gerais'}:
        score -= 10; reasons.append('ruído legal no corpo principal')
    if topic == 'cargos_vagas' and re.search(r'cargo[^\n]{0,80}(deverá|devera|comparecer|documento|defici[eê]ncia)', md.lower()):
        score -= 20; reasons.append('confundiu cargo com regra')
    if '## Fontes usadas' not in md:
        score -= 8; reasons.append('fontes ausentes')
    return max(0, score), reasons


def sanitize_editorial_markdown(out: str, title: str, source_note: str) -> str:
    out = (out or '').strip()
    out = re.sub(r'^```(?:markdown)?\s*|\s*```$', '', out, flags=re.I | re.S).strip()
    if not out.lower().startswith('#'):
        out = f'# {title}\n\n' + out
    if '## Fontes usadas' not in out:
        out = out.rstrip() + f'\n\n## Fontes usadas\n\n{source_note}'
    return out.strip() + '\n'


def safe_cell(v: Any) -> str:
    s = clean_text(str(v or '—'))
    return s.replace('|', '/').replace('\n', ' ')[:180]


def write_editorial_master_page(schema: dict, pages: dict[str, str], model_id: str | None) -> str:
    title = schema.get('title') or 'Edital'
    page_summaries = []
    for fn in ['dados-principais.md','inscricoes.md','cargos-e-vagas.md','provas-e-etapas.md','cronograma.md','recursos.md','requisitos.md','conteudo-programatico.md','retificacoes.md']:
        txt = pages.get(fn) or ''
        if txt:
            page_summaries.append(f'## {fn}\n{compact_page(txt, 1000)}')
    material = '\n\n'.join(page_summaries)[:14000]
    if config.data.get('indexing', {}).get('use_llm_for_master', True) and model_id:
        prompt = f"""
{NO_COPY_RULES}

Escreva o MASTER.md, a página principal de uma LLM Wiki para um site de concursos públicos.
A página deve parecer um guia inicial feito à mão para candidatos.

FORMATO:
# {title}
## Visão geral
## O que este edital oferece
## Informações principais
## Como usar esta wiki
## Pontos de atenção
## Páginas da wiki

DADOS DO SITE:
{json.dumps(schema, ensure_ascii=False, indent=2)[:7000]}

RESUMOS DAS PÁGINAS:
{material}

Não copie texto cru. Não invente. Se algo não estiver claro, marque como não identificado com segurança.
Responda apenas Markdown.
""".strip()
        try:
            out = complete(prompt, model_id=model_id, system='Você escreve o artigo principal de uma LLM Wiki de concursos.', temperature=0.05, timeout=int(config.data.get('indexing', {}).get('request_timeout_seconds', 360)))
            out = sanitize_editorial_markdown(out, title, 'Fontes detalhadas estão em `fontes.md`, `source.md` e nas páginas temáticas.')
            score, _ = score_wiki_page(out, 'master')
            if score >= 60:
                return out
        except Exception:
            pass
    return deterministic_master(schema, pages)


def compact_page(txt: str, limit: int) -> str:
    txt = re.sub(r'#.+', '', txt)
    txt = re.sub(r'## Fontes usadas.*', '', txt, flags=re.S)
    return clean_text(txt)[:limit]


def deterministic_master(schema: dict, pages: dict[str, str]) -> str:
    title = schema.get('title') or 'Edital'
    display = schema.get('display') or {}
    out = [f'# {title}', '', '## Visão geral', '', schema.get('summary') or 'Esta wiki organiza as informações do edital em linguagem simples para consulta por candidatos.', '', '## Informações principais', '']
    fields = [
        ('Instituição', schema.get('institution')),
        ('Banca/organização', schema.get('organizer')),
        ('Localidade', localidade(schema)),
        ('Status', schema.get('status') or 'indefinido'),
        ('Inscrições', display.get('registration') or periodo(schema.get('registration_start'), schema.get('registration_end'))),
        ('Data da prova', display.get('exam_date') or date_fmt(schema.get('exam_date')) or 'não identificada com segurança'),
        ('Vagas', schema.get('total_vacancies') or 'não consolidado com segurança'),
    ]
    out += [f'- **{k}:** {v or "não identificado com segurança"}' for k, v in fields]
    out += ['', '## Como usar esta wiki', '', 'Use as páginas temáticas para consultar inscrições, cargos, provas, cronograma, recursos, requisitos e conteúdo programático. O cartão público do site exibe apenas campos tratados como seguros; quando houver incerteza, a wiki mostra a pendência em vez de inventar dados.', '', '## Pontos de atenção', '']
    if schema.get('needs_review'):
        for item in schema.get('needs_review', [])[:8]:
            out.append(f'- {item.get("message") if isinstance(item, dict) else item}')
    else:
        out.append('- Nenhum ponto crítico automático foi identificado, mas o edital oficial continua sendo a fonte final.')
    out += ['', '## Páginas da wiki', '', '- [Dados gerais](dados-principais.md)', '- [Inscrições](inscricoes.md)', '- [Cargos, vagas e salários](cargos-e-vagas.md)', '- [Etapas e provas](provas-e-etapas.md)', '- [Cronograma](cronograma.md)', '- [Recursos](recursos.md)', '- [Requisitos](requisitos.md)', '- [Conteúdo programático](conteudo-programatico.md)', '- [Fontes](fontes.md)', '', '## Fontes usadas', '', 'Fontes detalhadas estão em `fontes.md`, `source.md` e nas páginas temáticas.']
    return '\n'.join(out).strip() + '\n'
