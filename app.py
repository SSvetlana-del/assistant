"""IT Navigator: a branded Gradio chat with confirmed conversational booking."""
import html
import json
import os
import re
import secrets
import tempfile
from functools import lru_cache
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv
from starlette.middleware import Middleware
from advisor.web_language import RussianHTMLMiddleware
from advisor.engine import Advisor
from advisor.storage import create_store
from advisor.catalog import start_date_text, price_text
from advisor.booking import ChatService, dates, receipt_fields, receipt_text

ROOT=Path(__file__).resolve().parent
load_dotenv(ROOT/'.env')
CATALOG=json.loads((ROOT/'data/courses.json').read_text(encoding='utf-8'))
COURSES={c['id']:c for c in CATALOG['courses']}
store=create_store(os.getenv('APP_DB',str(ROOT/'data/advisor.sqlite3')))
advisor=Advisor(CATALOG)
service=ChatService(advisor,store)
if os.getenv('RENDER') and not os.getenv('BROWSER_SECRET'):
    raise RuntimeError('Set BROWSER_SECRET in Render environment.')
SECRET_FILE=Path(store.path).parent/'browser.secret' if store.path else ROOT/'data/browser.secret'
if not SECRET_FILE.exists():
    SECRET_FILE.write_text(secrets.token_hex(32));SECRET_FILE.chmod(0o600)

WELCOME={'role':'assistant','content':'Здравствуйте! Я Навигатор, AI-консультант платформы. Помогу выбрать курс, расскажу об обучении и оформлю запись прямо здесь.\n\nКакую задачу хотите решить: освоить новую профессию или развить навыки?'}


def session_id(value):
    return value if isinstance(value,str) and re.fullmatch(r'[a-f0-9]{64}',value) else secrets.token_hex(32)


@lru_cache(maxsize=1024)
def receipt_file(serialized):
    with tempfile.NamedTemporaryFile(mode='w',suffix='.txt',prefix='it-navigator-',encoding='utf-8',delete=False) as out:
        out.write(receipt_text(json.loads(serialized)))
        return out.name


def progress_html(state):
    stage=state.get('stage')
    steps={'course':0,'date':1,'name':2,'confirm':3}
    if not stage:return ''
    current=steps.get(stage,3)
    label={'course':'Выбираем курс','date':'Выбираем дату','name':'Знакомимся','confirm':'Проверяем данные','edit':'Изменяем данные'}[stage]
    dots=''.join(f'<span class="progress-dot {"done" if i<current else "active" if i==current else ""}"></span>' for i in range(4))
    return f'<div class="booking-progress">{dots}<b>{label}</b></div>'


def view(saved):
    record=saved.get('last_receipt')
    file=receipt_file(json.dumps(record,ensure_ascii=False,sort_keys=True)) if record else None
    return ([WELCOME]+saved.get('history',[]),gr.update(value=file,visible=bool(file)),
            gr.update(visible=saved.get('booking',{}).get('stage')=='confirm'),
            progress_html(saved.get('booking') or {}))


def restore(value):
    sid=session_id(value)
    return (sid,sid,*view(store.load(sid)),*[gr.update(interactive=True) for _ in range(5)])


def send(text,sid):
    if not sid:raise gr.Error('Чат загружается, подождите секунду.')
    text=(text or '').strip()
    if len(text)>4000:raise gr.Error('Сократите сообщение до 4000 символов.')
    saved=service.turn(sid,text) if text else store.load(sid)
    return ('',*view(saved))


def reset():
    sid=secrets.token_hex(32)
    return (sid,sid,*view({'history':[]}), '')


def catalog_cards(direction='Все направления',level='Любой уровень',availability='Любое время'):
    budget={'До 5 ч/нед':5,'До 8 ч/нед':8}.get(availability)
    selected=[]
    for c in COURSES.values():
        if direction!='Все направления' and c['direction']!=direction:continue
        if level!='Любой уровень' and c['level']!=level:continue
        if budget and max(map(int,re.findall(r'\d+',c['weekly_load'])))>budget:continue
        selected.append(c)
    cards=[]
    for c in selected:
        e=html.escape
        pro=' pro' if c['level']=='Продвинутый' else ''
        starts=start_date_text(dates(c)[0]).replace(' года','')
        cards.append(f'<article class="course-card"><div class="course-tags"><span class="course-tag{pro}">{e(c["level"])}</span></div>'
                     f'<h3>{e(c["title"])}</h3><div class="course-meta">{e(c["duration"])} · {e(c["weekly_load"])}<br>Ближайший старт: {e(starts)} · ещё 2 даты</div>'
                     f'<div class="course-footer"><span class="course-price">{price_text(c["price_rub"])}</span>'
                     f'<span class="course-start">за весь курс</span></div></article>')
    empty='<p class="catalog-count">Не нашли подходящую программу? Расскажите о ваших планах в чате.</p>'
    return f'<div class="catalog-count">Найдено программ: {len(selected)}</div><div class="course-list">'+(''.join(cards) or empty)+'</div><div class="catalog-tip">Понравилась программа? Напишите её название в чате — помогу с выбором и записью.</div>'


# Compatibility helpers for existing saved confirmations and documentation.
def readable(record):
    return receipt_fields(record)


def catalog_markdown():
    return '\n\n'.join(f"{c['title']} — {price_text(c['price_rub'])}. Начало: {start_date_text(c['start_date'])}. Примерная нагрузка: {c['weekly_load']}." for c in COURSES.values())


def build_app():
    with gr.Blocks(title='IT Навигатор · Ваш следующий шаг в IT',analytics_enabled=False) as demo:
        browser=gr.BrowserState(None,storage_key='it-advisor-session-v1',secret=os.getenv('BROWSER_SECRET') or SECRET_FILE.read_text())
        sid=gr.State('')
        gr.HTML('<header class="brand-nav"><div class="brand"><span class="brand-mark">✦</span>IT Навигатор</div><div class="nav-links"><span>Обучение, которое подходит вам</span><span class="nav-label">ОНЛАЙН-ПЛАТФОРМА</span></div></header>')
        gr.HTML('<section class="hero"><div><div class="eyebrow">ЗНАНИЯ ДЛЯ НОВОГО ЭТАПА</div><h1>Ваш следующий шаг в IT.<br><span>Давайте найдём его вместе.</span></h1><p>Расскажите о своих планах. Навигатор поможет выбрать программу,<br>разобраться в условиях и записаться на удобный старт.</p></div><div class="hero-note"><strong>17 программ</strong>от первого знакомства до уверенного роста</div></section>')
        with gr.Row(elem_id='workspace'):
            with gr.Column(scale=7,min_width=370,elem_id='chat-shell'):
                gr.HTML('<div class="chat-header"><div class="agent"><span class="agent-symbol">✦</span><div><div class="agent-name">Навигатор</div><div class="agent-sub">Ваш AI-консультант по обучению</div></div></div><div class="online">На связи</div></div>')
                chat=gr.Chatbot(value=[WELCOME],height=520,show_label=False,buttons=['copy'],elem_id='conversation',
                                avatar_images=(None,str(ROOT/'assets/navigator.svg')),group_consecutive_messages=False)
                progress=gr.HTML('',elem_id='progress')
                with gr.Row(visible=False,elem_id='confirm-actions') as confirm_row:
                    confirm_btn=gr.Button('Подтвердить запись',variant='primary')
                    change_btn=gr.Button('Изменить данные')
                    cancel_btn=gr.Button('Отменить запись')
                receipt=gr.File(label='Ваше подтверждение',visible=False,interactive=False,elem_id='confirmation-download')
                with gr.Row(elem_id='composer'):
                    message=gr.Textbox(label='Ваше сообщение',show_label=False,placeholder='Напишите вопрос или «Хочу записаться»…',lines=1,max_lines=4,interactive=False,scale=8,elem_id='message-input')
                    submit=gr.Button('Отправить ↑',variant='primary',interactive=False,scale=1,elem_id='send-button')
                with gr.Row(elem_id='suggestions'):
                    pick=gr.Button('Подобрать курс',interactive=False)
                    compare=gr.Button('Сравнить программы',interactive=False)
                    book=gr.Button('Хочу записаться',interactive=False)
                gr.HTML('<div class="chat-bottom"><span>Отвечаем на вопросы и записываем прямо в чате</span><span>✧ IT Навигатор</span></div>')
                clear=gr.Button('Новый диалог',elem_id='reset-button')
            with gr.Column(scale=3,min_width=285,elem_id='sidebar'):
                gr.HTML('<section class="side-intro"><span class="side-tag">БЕЗ ЛИШНИХ ШАГОВ</span><h2>От «что выбрать?»<br>до «я записан».</h2><p>Всё в одном диалоге. Выбираем курс и старт, знакомимся — и проверяем данные перед записью.</p><div class="side-steps"><span>1</span> Курс <span>2</span> Дата <span>3</span> Имя <span>4</span> Готово</div></section>')
                with gr.Column(elem_id='catalog-panel'):
                    gr.HTML('<div class="catalog-heading">Найдите свою программу <span>17 КУРСОВ</span></div>')
                    direction=gr.Dropdown(['Все направления']+list(dict.fromkeys(c['direction'] for c in COURSES.values())),value='Все направления',label='Направление',interactive=True)
                    level=gr.Dropdown(['Любой уровень','Начальный','Продвинутый'],value='Любой уровень',label='Ваш уровень',interactive=True)
                    availability=gr.Dropdown(['Любое время','До 5 ч/нед','До 8 ч/нед'],value='Любое время',label='Время на учёбу',interactive=True)
                    cards=gr.HTML(catalog_cards())
        gr.HTML('<footer class="page-footer"><span>© 2026 IT Навигатор · Вместе к новым возможностям</span><span>'+html.escape(CATALOG['notice'])+'</span></footer>')
        queue=dict(concurrency_id='advisor',concurrency_limit=1,api_name=False)
        demo.load(restore,[browser],[browser,sid,chat,receipt,confirm_row,progress,message,submit,pick,compare,book],api_name=False)
        outputs=[message,chat,receipt,confirm_row,progress]
        submit.click(send,[message,sid],outputs,**queue)
        message.submit(send,[message,sid],outputs,**queue)
        for button,text in [(pick,'Помогите подобрать курс'),(compare,'Хочу сравнить программы'),(book,'Хочу записаться'),
                            (confirm_btn,'Подтверждаю запись'),(change_btn,'Изменить данные'),(cancel_btn,'Отмена')]:
            button.click(lambda session,text=text:send(text,session),[sid],outputs,**queue)
        clear.click(reset,[],[browser,sid,chat,receipt,confirm_row,progress,message],**queue)
        for field in (direction,level,availability):
            field.input(catalog_cards,[direction,level,availability],[cards],api_name=False)
    return demo.queue(max_size=32)


if __name__=='__main__':
    build_app().launch(server_name=os.getenv('APP_HOST','0.0.0.0' if os.getenv('RENDER') else '127.0.0.1'),
                       server_port=int(os.getenv('PORT') or os.getenv('APP_PORT','7860')),
                       share=False,show_error=False,footer_links=[],
                       app_kwargs={'middleware':[Middleware(RussianHTMLMiddleware)]},
                       css=(ROOT/'assets/theme.css').read_text(),theme=gr.themes.Soft(primary_hue='indigo'))
