from __future__ import annotations
import re

BAD_ENTITY_WORDS=['deverá','poderá','candidato','inscrição','documento','cadastro único','direito','pagamento','exime']
BAD_POSITION_WORDS=['deverá','poderá','candidato','inscrição','documento','lei','decreto','destinada','cadastro único','regional','municipal']

def lint_schema(schema:dict, master_md:str='', evidence=None)->dict:
    evidence=evidence or {}
    issues=[]; warnings=[]; score=100
    def issue(msg, pts=10):
        nonlocal score
        issues.append({'message':msg}); score-=pts
    def warn(msg, pts=5):
        nonlocal score
        warnings.append({'message':msg}); score-=pts

    if not schema.get('title'): issue('Título não identificado.', 8)
    inst=(schema.get('institution') or '')
    if not inst: issue('Instituição não identificada com segurança.', 14)
    elif len(inst)>140 or any(w in inst.lower() for w in BAD_ENTITY_WORDS): issue('Instituição parece frase quebrada ou ruído.', 20)

    org=(schema.get('organizer') or '')
    if org and (len(org)>130 or any(w in org.lower() for w in BAD_ENTITY_WORDS)): issue('Banca/organizador parece frase quebrada.', 15)

    status=schema.get('status') or 'indefinido'
    if status in ['cancelado','suspenso','retificado','prorrogado']:
        title=(schema.get('title') or '').lower()
        # Accept special statuses only when title/source context is explicit enough.
        if status=='cancelado' and not re.search(r'(concurso|certame|edital).{0,30}cancelad|cancelamento do concurso', title): warn('Status especial precisa ser conferido manualmente.', 8)

    positions=schema.get('positions') or []
    cap=None
    if positions:
        bad=0
        for p in positions:
            name=(p.get('name') or '').lower()
            if len(name)<4 or len(name)>100 or any(w in name for w in BAD_POSITION_WORDS): bad+=1
        if bad:
            issue(f'{bad} cargo(s) parecem quebrados ou inválidos.', min(30, 8+bad*3))
        complete=sum(1 for p in positions if p.get('vacancies') is not None or p.get('salary') is not None)
        if complete/max(1,len(positions)) < 0.5: warn('Muitos cargos estão sem vagas ou salário; tabela precisa de revisão.', 12)
    else:
        report=evidence.get('ingest_report') or {}
        if report.get('candidate_pages',{}).get('cargos-e-vagas.md') or (evidence.get('sections',{}).get('cargos-e-vagas') or {}).get('pages'):
            warn('Há indícios de cargos/vagas, mas o sistema não estruturou cargos com segurança.', 10)
            cap = 72 if cap is None else min(cap,72)

    timeline=schema.get('timeline') or []
    for ev in timeline:
        src=(ev.get('source') or '').lower()
        if any(w in src for w in ['lei','decreto','portaria','cnpj','cep','constituição']):
            issue('Cronograma contém data com contexto jurídico/administrativo suspeito.', 15); break
    if not timeline:
        report=evidence.get('ingest_report') or {}
        if report.get('candidate_pages',{}).get('cronograma.md') or (evidence.get('sections',{}).get('cronograma') or {}).get('pages'):
            warn('Há indícios de cronograma, mas nenhum evento foi estruturado com segurança.', 8)
            cap = 78 if cap is None else min(cap,78)

    if schema.get('salary_min') and schema.get('salary_min') < 500:
        issue('Salário mínimo estruturado é suspeito; pode ser auxílio, taxa ou pontuação.', 18)
    if schema.get('exam_date'):
        ok=False
        for ev in timeline:
            if ev.get('type')=='prova' and ev.get('start')==schema.get('exam_date'): ok=True
        if not ok: issue('Data de prova não está vinculada a evento forte de prova.', 18)

    if len(master_md or '')<800: warn('MASTER.md curto demais para uma wiki útil.', 8)
    if 'Evidências relacionadas' in (master_md or ''): issue('A wiki ainda parece dump de evidências.', 12)

    report=evidence.get('ingest_report') or {}
    for msg in report.get('issues',[])[:4]: warn(msg, 4)

    if cap is not None:
        score=min(score, cap)
    score=max(0, min(100, int(score)))
    ok=score>=75 and not issues
    return {'score':score, 'ok':ok, 'issues':issues, 'warnings':warnings}
