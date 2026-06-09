from __future__ import annotations
import json, os
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from .config import config, ROOT
from .storage import list_editais, load_schema, get_markdown_pages, edital_dir, save_schema, delete_edital, schema_path, update_catalog_entry
from .wiki_engine import index_upload, index_file, download_url, render_lint_md
from .query import ask_edital, compare_schemas, verdict
from .evaluator import summarize
from .utils import date_fmt, money_fmt, truncate, parse_date, write_json, read_json
from .site_schema import build_site_schema
from .linting import lint_schema



def create_app():
    app=Flask(__name__)
    app.secret_key='wikieditais-dev'
    app.jinja_env.filters['datefmt']=date_fmt
    app.jinja_env.filters['money']=money_fmt
    app.jinja_env.filters['truncate2']=truncate
    app.add_url_rule('/', 'home', home)
    app.add_url_rule('/edital/<edital_id>', 'edital_detail', edital_detail)
    app.add_url_rule('/edital/<edital_id>/ask','ask',ask,methods=['POST'])
    app.add_url_rule('/edital/<edital_id>/pdf','view_pdf',view_pdf)
    app.add_url_rule('/comparar','compare',compare,methods=['GET','POST'])
    app.add_url_rule('/analise','analysis',analysis)
    app.add_url_rule('/debug','debug',debug,methods=['GET','POST'])
    app.add_url_rule('/debug/test-model','test_model_route',test_model_route,methods=['POST'])
    app.add_url_rule('/debug/edital/<edital_id>/edit','edit_edital',edit_edital,methods=['GET','POST'])
    app.add_url_rule('/debug/edital/<edital_id>/delete','delete_route',delete_route,methods=['POST'])
    app.add_url_rule('/debug/edital/<edital_id>/rebuild-public-schema','rebuild_public_schema_route',rebuild_public_schema_route,methods=['POST'])
    return app

def home():
    items=list_editais()
    q=request.args.get('q','').lower().strip(); status=request.args.get('status',''); state=request.args.get('state',''); keyword=request.args.get('keyword','').lower().strip()
    filtered=[]
    for e in items:
        blob=' '.join(str(e.get(k,'') or '') for k in ['title','institution','summary','organizer','city','state']).lower()
        ok=True
        if q and q not in blob: ok=False
        if keyword and keyword not in blob: ok=False
        if status and e.get('status')!=status: ok=False
        if state and (e.get('state') or '').upper()!=state.upper(): ok=False
        if ok: filtered.append(e)
    return render_template('home.html', editais=filtered, all_editais=items, q=q, status=status, state=state, keyword=keyword, title='WikiEditais')

def edital_detail(edital_id):
    schema=load_schema(edital_id)
    if not schema: return render_template('error.html', message='Edital não encontrado'),404
    pages=get_markdown_pages(edital_id)
    current_step=compute_current_step(schema)
    return render_template('edital.html', e=schema, pages=pages, current_step=current_step, title=schema.get('title'))

def compute_current_step(schema):
    from datetime import date
    today=date.today()
    timeline=schema.get('timeline') or []
    current=None; future=[]
    for ev in timeline:
        st=parse_date(ev.get('start')); en=parse_date(ev.get('end')) or st
        if st and en and st<=today<=en: current=ev; break
        if st and st>today: future.append((st,ev))
    if current: return {'label':current.get('label'),'status':'etapa atual','tips':tips_for(current)}
    if future:
        ev=sorted(future,key=lambda x:x[0])[0][1]
        return {'label':ev.get('label'),'status':'próxima etapa','tips':tips_for(ev)}
    return {'label':'Encerrado ou sem cronograma identificado','status':'encerrado/indefinido','tips':['Consulte resultados, recursos ou homologação se existirem na wiki.']}

def tips_for(ev):
    t=(ev.get('type') or '').lower(); label=(ev.get('label') or '').lower()
    if 'inscr' in t or 'inscr' in label: return ['Verifique os requisitos do cargo.','Faça a inscrição dentro do prazo.','Guarde comprovante e observe taxa/isenção.']
    if 'prova' in t or 'prova' in label: return ['Confira local e horário da prova.','Separe documento oficial e materiais permitidos.','Revise o conteúdo programático.']
    if 'recurso' in t or 'recurso' in label: return ['Leia as regras de recurso.','Observe prazo e formato exigido.','Anexe documentos quando necessário.']
    return ['Acompanhe a publicação oficial.','Verifique se há documentos ou prazos associados.']

def ask(edital_id):
    question=(request.form.get('question') or '').strip()
    model=request.form.get('model') or config.data['models'].get('default_chat_model')
    if not question: return jsonify({'answer':'Digite uma pergunta.'})
    return jsonify({'answer':ask_edital(edital_id,question,model)})

def view_pdf(edital_id):
    schema=load_schema(edital_id); raw=schema.get('raw_file') or ''
    filename=Path(raw).name
    p=config.p('raw')/filename
    if not p.exists(): return render_template('error.html',message='Arquivo do edital não encontrado na pasta raw.'),404
    return send_file(p, as_attachment=False)

def compare():
    editais=list_editais(); a_id=request.values.get('a'); b_id=request.values.get('b')
    a=load_schema(a_id) if a_id else None; b=load_schema(b_id) if b_id else None
    rows=[]; ver=None
    if a and b:
        rows=compare_schemas(a,b)
        ver=verdict(a,b,rows,config.data['models'].get('default_compare_model'))
    return render_template('compare.html', editais=editais, a=a, b=b, rows=rows, verdict=ver, title='Comparar')

def analysis(): return render_template('analysis.html', data=summarize(), title='Análise')

def stats():
    editais=list_editais(); wiki_root=config.p('wiki')
    md=sum(1 for _ in wiki_root.glob('**/*.md')) if wiki_root.exists() else 0
    schemas=sum(1 for _ in wiki_root.glob('**/schema.json')) if wiki_root.exists() else 0
    raw=sum(1 for _ in config.p('raw').glob('*')) if config.p('raw').exists() else 0
    evals=sum(1 for _ in config.p('evaluations').glob('*.json')) if config.p('evaluations').exists() else 0
    return {'editais':len(editais),'raw':raw,'md':md,'schemas':schemas,'evaluations':evals}

def debug():
    if request.method=='POST':
        action=request.form.get('action')
        if action=='save_config':
            config.data['models']['default_index_model']=request.form.get('default_index_model') or config.data['models']['default_index_model']
            config.data['models']['default_chat_model']=request.form.get('default_chat_model') or config.data['models']['default_chat_model']
            config.data['models']['default_compare_model']=request.form.get('default_compare_model') or config.data['models']['default_compare_model']
            config.save(); flash('Configurações salvas.'); return redirect(url_for('debug'))
        if action=='index_upload':
            f=request.files.get('file'); title_hint=request.form.get('title_hint','').strip(); model=config.data['models']['default_index_model']
            if not f or not f.filename: flash('Selecione um PDF/TXT/MD.'); return redirect(url_for('debug'))
            try:
                schema=index_upload(f,title_hint,model)
                flash(f'Edital indexado: {schema.get("title") or schema.get("id")}')
                return redirect(url_for('edital_detail', edital_id=schema.get('id')))
            except Exception as e:
                flash(f'Falha na indexação: {e}')
                return redirect(url_for('debug'))
        if action=='index_url':
            url=request.form.get('url','').strip(); title_hint=request.form.get('title_hint','').strip(); model=config.data['models']['default_index_model']
            if not url: flash('Informe uma URL.'); return redirect(url_for('debug'))
            try:
                path=download_url(url,title_hint); schema=index_file(path,title_hint or path.stem,model,source_url=url)
                flash(f'URL baixada e indexada: {schema.get("title") or schema.get("id")}')
                return redirect(url_for('edital_detail', edital_id=schema.get('id')))
            except Exception as e:
                flash(f'Falha ao baixar/indexar: {e}')
    return render_template('debug.html', stats=stats(), editais=list_editais(), models_all=config.models(), models_index=config.models('index'), models_chat=config.models('chat'), models_compare=config.models('compare'), cfg=config.data, title='Debug')

def test_model_route():
    from .llm import test_model
    model=request.form.get('model') or config.data['models'].get('default_index_model')
    ok,msg=test_model(model)
    flash(('OK: ' if ok else 'Falhou: ') + msg)
    return redirect(url_for('debug'))

def edit_edital(edital_id):
    schema=load_schema(edital_id)
    if not schema: return render_template('error.html',message='Edital não encontrado'),404
    if request.method=='POST':
        schema=json.loads(request.form.get('schema_json') or '{}')
        schema['id']=edital_id
        save_schema(edital_id,schema)
        for key,val in request.form.items():
            if key.startswith('md__'):
                fn=key[4:]
                (edital_dir(edital_id)/fn).write_text(val,encoding='utf-8')
        flash('Edital atualizado.')
        return redirect(url_for('edit_edital',edital_id=edital_id))
    return render_template('edit_edital.html', e=schema, pages=get_markdown_pages(edital_id), schema_json=json.dumps(schema,ensure_ascii=False,indent=2), title='Editar edital')


def rebuild_public_schema_route(edital_id):
    schema=load_schema(edital_id)
    if not schema:
        return render_template('error.html',message='Edital não encontrado'),404
    pages=get_markdown_pages(edital_id)
    d=edital_dir(edital_id)
    sections=read_json(d/'sections.json', {}) or {}
    facts=read_json(d/'validated_facts.json', {}) or schema.get('validated_facts') or {}
    positions=read_json(d/'positions.json', []) or schema.get('raw_positions') or schema.get('positions') or []
    timeline=read_json(d/'timeline.json', []) or schema.get('raw_timeline') or schema.get('timeline') or []
    model=request.form.get('model') or config.data['models'].get('default_index_model')
    public_schema, artifact = build_site_schema(schema, pages, sections, facts, positions, timeline, model)
    lint_payload={'sections':sections,'wiki_pages':pages,'positions':positions,'timeline':timeline,'validated_facts':facts}
    lint=lint_schema(public_schema, pages.get('MASTER.md',''), evidence=lint_payload)
    public_schema['lint_score']=lint['score']
    public_schema['quality']='boa' if lint['score']>=85 else ('revisar' if lint['score']>=65 else 'crítica')
    public_schema['raw_positions']=positions[:250]
    public_schema['raw_timeline']=timeline[:80]
    public_schema['validated_facts']=facts
    public_schema['wiki_strategy']='v10_public_schema_from_markdown_rebuilt'
    write_json(d/'public_schema_draft.json', artifact)
    write_json(d/'public_schema.json', public_schema)
    write_json(d/'schema.json', public_schema)
    write_json(d/'lint.json', lint)
    (d/'lint.md').write_text(render_lint_md(lint),encoding='utf-8')
    save_schema(edital_id, public_schema)
    update_catalog_entry(public_schema)
    flash('Schema público reconstruído a partir dos Markdown da wiki e validado para o site.')
    return redirect(url_for('edital_detail', edital_id=edital_id))

def delete_route(edital_id):
    delete_edital(edital_id); flash('Edital excluído.'); return redirect(url_for('debug'))
