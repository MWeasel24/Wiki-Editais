from __future__ import annotations
import re, json
from datetime import date
from .config import config
from .storage import load_schema, get_markdown_pages
from .llm import complete, LLMError
from .utils import date_fmt, money_fmt, parse_date

PAGE_HINTS={
    'inscricoes.md':['inscrição','inscrições','taxa','isenção','pagamento','cadastro'],
    'cargos-e-vagas.md':['cargo','cargos','vaga','vagas','salário','remuneração','vencimento','benefício','bolsa'],
    'cronograma.md':['cronograma','prazo','data','resultado','homologação','recurso','inscrição','prova'],
    'provas-e-etapas.md':['prova','objetiva','discursiva','local','cartão','levar','proibido','permitido','caneta','documento','dia da prova','etapa','avaliação'],
    'conteudo-programatico.md':['conteúdo','programático','matéria','questões','disciplina','estudar','estudos','rotina'],
    'requisitos.md':['requisito','escolaridade','documento','posse','condição'],
    'recursos.md':['recurso','gabarito','resultado','impugnação'],
    'retificacoes.md':['retificação','errata','prorrogação','suspensão','comunicado','alteração'],
    'dados-principais.md':['instituição','banca','organizadora','taxa','salário','vagas'],
    'MASTER.md':['resumo','geral','edital']
}

def choose_pages(question:str, pages:dict[str,str])->dict[str,str]:
    q=question.lower()
    scored=[]
    for fn,content in pages.items():
        score=0
        for kw in PAGE_HINTS.get(fn,[]):
            if kw in q: score+=5
        for token in re.findall(r'\w{4,}', q):
            if token in content.lower(): score+=1
        scored.append((score,fn,content))
    scored.sort(reverse=True)
    selected={}
    for score,fn,content in scored:
        if score>0 or fn in ['MASTER.md','dados-principais.md']:
            selected[fn]=content
        if len(selected)>=5: break
    if not selected and pages.get('MASTER.md'): selected={'MASTER.md':pages['MASTER.md']}
    return selected

def direct_answer(schema:dict, question:str):
    q=question.lower()
    # Only direct factual questions; avoid hijacking prova rules.
    if any(x in q for x in ['quando é a inscrição','período de inscrição','data de inscrição','até quando posso me inscrever','quando acaba a inscrição']):
        a,b=schema.get('registration_start'),schema.get('registration_end')
        if a or b: return f"As inscrições vão de {date_fmt(a)} a {date_fmt(b)}."
    if any(x in q for x in ['qual a taxa','valor da taxa','taxa de inscrição']):
        fee_text=(schema.get('display') or {}).get('fee') or schema.get('fee_text')
        if fee_text and fee_text != 'Não identificada com segurança': return f"A taxa de inscrição identificada é {fee_text}."
        if schema.get('fee') is not None: return f"A taxa de inscrição é {money_fmt(schema.get('fee'))}."
    if any(x in q for x in ['qual o salário','remuneração','salário máximo']):
        if schema.get('salary_max') is not None: return f"A remuneração máxima identificada é {money_fmt(schema.get('salary_max'))}."
    if any(x in q for x in ['quantas vagas','número de vagas','total de vagas']):
        if schema.get('total_vacancies') is not None: return f"O total de vagas identificado é {schema.get('total_vacancies')}."
    if any(x in q for x in ['quando é a prova','data da prova','dia da prova objetiva']):
        # only when asking date explicitly, not rules
        if not any(y in q for y in ['levar','pode','não pode','proibido','permitido']):
            if schema.get('exam_date'): return f"A prova está prevista para {date_fmt(schema.get('exam_date'))}."
    return None

def ask_edital(edital_id:str, question:str, model_id:str|None=None)->str:
    schema=load_schema(edital_id); pages=get_markdown_pages(edital_id)
    direct=direct_answer(schema,question)
    if direct: return direct
    selected=choose_pages(question,pages)
    context='\n\n'.join(f"# Arquivo: {fn}\n{content}" for fn,content in selected.items())
    max_chars=config.data.get('chat',{}).get('max_context_chars',24000)
    context=context[:max_chars]
    today=date.today().isoformat()
    prompt=f'''
Você é o chat público da WikiEditais. Responda em português natural e sem termos técnicos.
Use somente o schema e as páginas Markdown abaixo.
Se a informação não estiver na wiki, diga que a wiki deste edital não possui essa informação.
Se o usuário pedir rotina de estudos, use o conteúdo programático, a data atual ({today}) e a data da prova, se existir.
Não cite rotas, ferramentas, JSON, debug ou nomes de funções.

SCHEMA:
{json.dumps(schema, ensure_ascii=False, indent=2)[:9000]}

PÁGINAS DA WIKI SELECIONADAS:
{context}

Pergunta do usuário: {question}

Resposta objetiva, útil e suave:
'''
    try:
        ans=complete(prompt,model_id or config.data['models'].get('default_chat_model'),system='Você responde perguntas usando uma LLM Wiki de editais.',temperature=config.data.get('chat',{}).get('temperature',0.2))
        return ans.strip()
    except Exception:
        return lexical_answer(question, selected, schema)

def lexical_answer(question:str, pages:dict[str,str], schema:dict)->str:
    qlow=question.lower()
    if any(x in qlow for x in ['não pode','nao pode','levar','proibido','permitido']):
        provas = pages.get('provas-e-etapas.md','') or pages.get('provas.md','')
        bullets = [line.strip('- ').strip() for line in provas.splitlines() if line.strip().startswith('-')]
        if bullets:
            return 'Segundo a página de provas da wiki, foram identificadas estas regras/restrições: ' + '; '.join(bullets[:6])
    qtokens=set(re.findall(r'\w{4,}', question.lower()))
    best=[]
    for fn,content in pages.items():
        for para in re.split(r'\n\s*\n', content):
            score=sum(1 for t in qtokens if t in para.lower())
            if score: best.append((score,fn,para.strip()))
    best.sort(reverse=True)
    if best:
        txt=best[0][2]
        return txt[:900] + ('' if len(txt)<=900 else '…')
    return 'A wiki deste edital não possui informação suficiente para responder essa pergunta.'

def compare_schemas(a:dict,b:dict)->list[dict]:
    fields=[('Instituição','institution'),('Banca','organizer'),('Local','city'),('Estado','state'),('Status','status'),('Vagas','total_vacancies'),('Salário máximo','salary_max'),('Taxa','fee'),('Inscrições','registration'),('Prova','exam_date'),('Local de prova','exam_location')]
    rows=[]
    for label,key in fields:
        if key=='registration':
            va=f"{date_fmt(a.get('registration_start'))} a {date_fmt(a.get('registration_end'))}"; vb=f"{date_fmt(b.get('registration_start'))} a {date_fmt(b.get('registration_end'))}"
        elif key in ['salary_max','fee']:
            va=money_fmt(a.get(key)); vb=money_fmt(b.get(key))
        elif key=='exam_date':
            va=date_fmt(a.get(key)); vb=date_fmt(b.get(key))
        else:
            va=a.get(key) or '—'; vb=b.get(key) or '—'
        rows.append({'field':label,'a':va,'b':vb})
    return rows

def verdict(a:dict,b:dict,rows:list[dict],model_id:str|None=None)->str:
    prompt=f'''
Escreva um veredito curto, natural e útil comparando dois editais.
Use somente esta tabela. Não invente dados.
Evite frases robóticas como "com base nos dados fornecidos".

Edital A: {a.get('title')}
Edital B: {b.get('title')}
Tabela: {json.dumps(rows, ensure_ascii=False)}

Veredito em 1 a 3 parágrafos:
'''
    try: return complete(prompt, model_id or config.data['models'].get('default_compare_model'), system='Você compara editais de forma clara para candidatos.', temperature=0.25)
    except Exception:
        return 'A comparação acima mostra os principais campos extraídos dos dois editais. A escolha mais adequada depende principalmente de prazo, remuneração, vagas disponíveis e compatibilidade dos cargos com o perfil do candidato.'
