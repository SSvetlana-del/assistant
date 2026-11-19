"""IT Navigator: a branded Gradio chat with confirmed conversational booking."""
import html
import json
import os
import re
import secrets
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv
from starlette.middleware import Middleware
from advisor.web_language import RussianHTMLMiddleware
from advisor.engine import Advisor
from advisor.storage import create_store
from advisor.catalog import start_date_text, price_text
from advisor.booking import ChatService, dates
from advisor.replies import clean_support_reply

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

WELCOME={'role':'assistant','content':'Здравствуйте! Я Навигатор. Помогу выбрать курс, сравнить программы и оформить заявку.\n\nВы хотите освоить новую профессию или развить навыки?'}


def session_id(value):
    return value if isinstance(value,str) and re.fullmatch(r'[a-f0-9]{64}',value) else secrets.token_hex(32)


def progress_html(state):
    stage=state.get('stage')
    steps={'course':0,'date':1,'name':2,'contact':3,'confirm':4}
    if not stage:return ''
    current=steps.get(stage,4)
    label={'course':'Выбираем курс','date':'Выбираем дату','name':'Знакомимся','contact':'Контакт для связи','confirm':'Проверяем данные','edit':'Изменяем данные'}[stage]
    dots=''.join(f'<span class="progress-dot {"done" if i<current else "active" if i==current else ""}"></span>' for i in range(5))
    return f'<div class="booking-progress">{dots}<b>{label}</b></div>'


def view(saved):
    history=[dict(m,content=clean_support_reply(m['content'])) if m['role']=='assistant' else dict(m)
             for m in saved.get('history',[])]
    return ([WELCOME]+history,
            gr.update(visible=saved.get('booking',{}).get('stage')=='confirm'),
            progress_html(saved.get('booking') or {}))


def restore(value):
    sid=session_id(value)
    return (sid,sid,*view(service.restore(sid)),*[gr.update(interactive=True) for _ in range(5)])


def answer(text,sid):
    if not sid:raise gr.Error('Чат загружается, подождите секунду.')
    text=(text or '').strip()
    if len(text)>4000:raise gr.Error('Сократите сообщение до 4000 символов.')
    saved=service.turn(sid,text) if text else store.load(sid)
    return view(saved)


def capture(text,history):
    visible=list(history or []) + ([{'role':'user','content':text}] if (text or '').strip() else [])
    return (text,visible,gr.update(value='',interactive=False),*[gr.update(interactive=False) for _ in range(8)])


def enable_controls():
    return [gr.update(interactive=True) for _ in range(9)]


BUSY_JS = """(...args) => {
 const input=document.querySelector('#message-input textarea');
 if(input)input.disabled=true;
 const status=document.querySelector('#assistant-status');
 if(status){status.textContent='Готовлю ответ…';status.classList.add('is-busy');}
 document.querySelector('#conversation')?.setAttribute('aria-busy','true');
 document.querySelectorAll('#send-button, #suggestions button, #confirm-actions button, #reset-button').forEach(b=>b.disabled=true);
 return args;
}"""


READY_JS = """(...args) => {
 const status=document.querySelector('#assistant-status');
 if(status){status.textContent='На связи';status.classList.remove('is-busy');}
 document.querySelector('#conversation')?.removeAttribute('aria-busy');
 return args;
}"""


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
                     f'<details class="course-details"><summary>Программа и результат</summary><p>{e(c["description"])}</p><p>{e(c["audience"])}</p>'
                     + '<ul>'+''.join('<li>'+e(t)+'</li>' for t in c['syllabus'])+'</ul>'
                     + f'<p><strong>Практика:</strong> {e(c["final_project"])}</p><p><strong>Результат:</strong> {e("; ".join(c["outcomes"]))}</p>'
                     f'<p><strong>Входные знания:</strong> {e(c["prerequisites"])}</p><p>{e(c["limitations"])}</p></details>'
                     f'<div class="course-footer"><span class="course-price">{price_text(c["price_rub"])}</span>'
                     f'<span class="course-start">за весь курс</span></div></article>')
    empty='<p class="catalog-count">Не нашли подходящую программу? Расскажите о ваших планах в чате.</p>'
    return f'<div class="catalog-count">Найдено программ: {len(selected)}</div><div class="course-list">'+(''.join(cards) or empty)+'</div><div class="catalog-tip">Понравилась программа? Напишите её название в чате — помогу с выбором и записью.</div>'


def catalog_markdown():
    return '\n\n'.join(f"{c['title']} — {price_text(c['price_rub'])}. Начало: {start_date_text(c['start_date'])}. Примерная нагрузка: {c['weekly_load']}." for c in COURSES.values())


def build_app():
    with gr.Blocks(title='IT Навигатор · Ваш следующий шаг в IT',analytics_enabled=False) as demo:
        browser=gr.BrowserState(None,storage_key='it-advisor-session-v1',secret=os.getenv('BROWSER_SECRET') or SECRET_FILE.read_text())
        sid=gr.State('')
        pending=gr.State('')
        gr.HTML('<header class="brand-nav"><div class="brand"><span class="brand-mark"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="18" fill="#5757ef"/><path d="M17 29 48 16 35 48l-5-14Z" fill="#fff"/><path d="m30 34 18-18-13 32Z" fill="#d7d3ff"/></svg></span>IT Навигатор</div><nav class="nav-links" aria-label="Навигация"><a href="#workspace">Помощь с выбором</a><a href="#catalog-panel">Каталог курсов</a><span class="nav-label">ОНЛАЙН-ПЛАТФОРМА</span></nav></header>')
        gr.HTML('<section class="hero"><div><div class="eyebrow">ОБРАЗОВАНИЕ ДЛЯ ВАШЕГО СЛЕДУЮЩЕГО ШАГА</div><h1>Найдите свой <span>курс в IT.</span></h1><p>Сравните программы и обсудите обучение с AI-консультантом.</p></div><div class="hero-note"><strong>17 программ</strong>8 направлений · 2 уровня</div></section>')
        with gr.Row(elem_id='workspace'):
            with gr.Column(scale=7,min_width=480,elem_id='chat-shell'):
                gr.HTML('<div class="chat-header"><div class="agent"><span class="agent-symbol"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="18" fill="#5757ef"/><path d="M17 29 48 16 35 48l-5-14Z" fill="#fff"/><path d="m30 34 18-18-13 32Z" fill="#d7d3ff"/></svg></span><div><div class="agent-name">Навигатор</div><div class="agent-sub">AI-консультант<span class="desktop-only"> по обучению</span></div></div></div><div class="online" id="assistant-status" role="status" aria-live="polite">На связи</div></div>')
                chat=gr.Chatbot(value=[WELCOME],height=350,show_label=False,buttons=['copy'],elem_id='conversation',
                                avatar_images=(None,str(ROOT/'assets/navigator.svg')),group_consecutive_messages=False)
                progress=gr.HTML('',elem_id='progress')
                with gr.Row(visible=False,elem_id='confirm-actions') as confirm_row:
                    confirm_btn=gr.Button('Подтвердить запись',variant='primary')
                    change_btn=gr.Button('Изменить данные')
                    cancel_btn=gr.Button('Отменить запись')
                with gr.Row(elem_id='composer'):
                    message=gr.Textbox(label='Ваше сообщение',show_label=False,placeholder='Ваш вопрос о курсах…',lines=1,max_lines=4,interactive=False,scale=8,elem_id='message-input')
                    submit=gr.Button('Отправить ↑',variant='primary',interactive=False,scale=1,elem_id='send-button')
                with gr.Row(elem_id='suggestions'):
                    pick=gr.Button('Подобрать курс',interactive=False)
                    compare=gr.Button('Сравнить программы',interactive=False)
                    book=gr.Button('Хочу записаться',interactive=False)
                gr.HTML('<div class="chat-bottom"><span>Отвечаем на вопросы и записываем прямо в чате</span><span>IT Навигатор</span></div>')
                with gr.Row(elem_id='reset-actions'):
                    clear=gr.Button('Новый диалог',elem_id='reset-button',scale=0,min_width=0)
            with gr.Column(scale=3,min_width=340,elem_id='sidebar'):
                gr.HTML('<section class="side-intro"><span class="side-tag">ПОМОЖЕМ ОПРЕДЕЛИТЬСЯ</span><h2>Курс, который подходит вам.</h2><p>Расскажите о цели и опыте — Навигатор поможет сравнить программы и выбрать удобный старт.</p><div class="side-steps"><span>Подбор</span><span>Сравнение</span><span>Запись</span></div></section>')
                with gr.Column(elem_id='catalog-panel'):
                    gr.HTML('<div class="catalog-heading">Выберите курс <span>17 программ</span></div>')
                    direction=gr.Dropdown(['Все направления']+list(dict.fromkeys(c['direction'] for c in COURSES.values())),value='Все направления',label='Направление',interactive=True)
                    level=gr.Dropdown(['Любой уровень','Начальный','Продвинутый'],value='Любой уровень',label='Ваш уровень',interactive=True)
                    availability=gr.Dropdown(['Любое время','До 5 ч/нед','До 8 ч/нед'],value='Любое время',label='Время на учёбу',interactive=True)
                    cards=gr.HTML(catalog_cards())
        gr.HTML('<footer class="page-footer"><span>© 2026 IT Навигатор · Вместе к новым возможностям</span><span>'+html.escape(CATALOG['notice'])+'</span></footer>')
        queue=dict(concurrency_id='advisor',concurrency_limit=1,api_name=False,show_progress='hidden')
        demo.load(restore,[browser],[browser,sid,chat,confirm_row,progress,message,submit,pick,compare,book],api_name=False,show_progress='hidden')
        controls=[message,submit,pick,compare,book,confirm_btn,change_btn,cancel_btn,clear]
        def wire(component,text=None,enter=False):
            fn=capture if text is None else lambda history,text=text:capture(text,history)
            event=(component.submit if enter else component.click)(fn,[message,chat] if text is None else [chat],
                      [pending,chat]+controls,queue=False,api_name=False,show_progress='hidden',js=BUSY_JS)
            result=event.success(answer,[pending,sid],[chat,confirm_row,progress],**queue)
            result.success(enable_controls,[],controls,queue=False,api_name=False,show_progress='hidden',js=READY_JS)
            result.failure(enable_controls,[],controls,queue=False,api_name=False,show_progress='hidden',js=READY_JS)
        wire(submit)
        wire(message,enter=True)
        for button,text in [(pick,'Помогите подобрать курс'),(compare,'Хочу сравнить программы'),(book,'Хочу записаться'),
                            (confirm_btn,'Подтверждаю запись'),(change_btn,'Изменить данные'),(cancel_btn,'Отмена')]:
            wire(button,text)
        clear.click(reset,[],[browser,sid,chat,confirm_row,progress,message],**queue)
        for field in (direction,level,availability):
            field.input(catalog_cards,[direction,level,availability],[cards],api_name=False,show_progress='hidden')
    return demo.queue(max_size=32)


if __name__=='__main__':
    build_app().launch(server_name=os.getenv('APP_HOST','0.0.0.0' if os.getenv('RENDER') else '127.0.0.1'),
                       server_port=int(os.getenv('PORT') or os.getenv('APP_PORT','7860')),
                       share=False,show_error=False,footer_links=[],
                       app_kwargs={'middleware':[Middleware(RussianHTMLMiddleware)]},
                       css=(ROOT/'assets/theme.css').read_text(),theme=gr.themes.Soft(primary_hue='indigo'))
