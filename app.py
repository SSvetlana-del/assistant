"""Run: python app.py. Credentials stay server-side in .env."""
import json
import os
import re
import secrets
import tempfile
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv
from advisor.engine import Advisor
from advisor.storage import create_store
from advisor.catalog import start_date_text, price_text

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
CATALOG = json.loads((ROOT / 'data/courses.json').read_text(encoding='utf-8'))
COURSES = {c['id']: c for c in CATALOG['courses']}
store = create_store(os.getenv('APP_DB', str(ROOT / 'data/advisor.sqlite3')))
advisor = Advisor(CATALOG)
if os.getenv('RENDER') and not os.getenv('BROWSER_SECRET'):
    raise RuntimeError('Set BROWSER_SECRET in Render environment.')
SECRET_FILE = Path(store.path).parent / 'browser.secret' if store.path else ROOT / 'data/browser.secret'
if not SECRET_FILE.exists():
    SECRET_FILE.write_text(secrets.token_hex(32))
    SECRET_FILE.chmod(0o600)


def session_id(value):
    return value if isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) else secrets.token_hex(32)


def restore(value):
    sid = session_id(value)
    return sid, sid, store.load(sid)['history'], gr.update(interactive=True), gr.update(interactive=True)


def send(text, sid):
    if not sid:
        raise gr.Error('Подождите загрузки страницы.')
    text = (text or '').strip()
    if not text:
        return '', store.load(sid)['history']
    if len(text) > 4000:
        raise gr.Error('Сократите сообщение до 4000 символов.')
    saved = advisor.reply(text, store.load(sid))
    store.save(sid, saved)
    return '', saved['history']


def make_draft(course_id, name, load, consent, sid):
    if not sid:
        raise gr.Error('Подождите загрузки страницы.')
    if course_id not in COURSES:
        raise gr.Error('Выберите курс.')
    name = (name or '').strip()
    if not 2 <= len(name) <= 80 or any(ord(c) < 32 for c in name):
        raise gr.Error('Укажите имя от 2 до 80 символов.')
    if load not in ('2–3 часа в неделю', '4–5 часов в неделю', '6–10 часов в неделю'):
        raise gr.Error('Выберите нагрузку.')
    if not consent:
        raise gr.Error('Подтвердите сохранение параметров записи.')
    c = COURSES[course_id]
    payload = dict(course_id=course_id, course=c['title'], name=name, preferred_load=load,
                   format=c['format'], duration=c['duration'], price_rub=c['price_rub'],
                   weekly_load=c['weekly_load'], start_date=c['start_date'],
                   scope='Запись на IT Навигаторе. Тестовый проект, оплата не взимается.')
    token = store.draft(sid, payload)
    # Textbox avoids rendering user-supplied names as HTML or Markdown.
    preview = '\n'.join(f'{k}: {v}' for k,v in readable(payload).items())
    return preview, token, gr.update(interactive=True), None


def readable(record):
    return {'Имя': record['name'], 'Курс': record['course'], 'Формат': record['format'],
            'Начало обучения': start_date_text(record['start_date']) if record.get('start_date') else 'не указано в прежней записи',
            'Длительность': record['duration'],
            'Примерная нагрузка': record.get('weekly_load', 'не указана в прежней записи'),
            'Желаемая нагрузка': record['preferred_load'],
            'Стоимость курса': price_text(record['price_rub']) if record.get('price_rub') is not None else 'не указана в прежней записи',
            'Условия': record['scope']}


def confirm(token, sid):
    if not sid or not token:
        raise gr.Error('Сначала проверьте параметры записи.')
    try:
        record, created = store.confirm(sid, token)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    lines = [f"{'Запись сохранена' if created else 'Вы уже записаны на этот курс'}. Номер: {record['registration_id']}"]
    lines.extend(f'{k}: {v}' for k,v in readable(record).items())
    lines.append('Дата (UTC): '+record['created_at'])
    lines.append('Есть вопросы по обучению? Напишите — помогу разобраться.')
    notification = '\n'.join(lines)
    # Unique file per receipt, never expose the database or an entire receipts folder.
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', prefix='course-confirmation-', encoding='utf-8', delete=False) as out:
        out.write(notification)
        path = out.name
    saved = store.load(sid)
    saved['history'].append({'role': 'assistant', 'content': notification})
    saved['course_ids'] = [record['course_id']]
    store.save(sid, saved)
    return saved['history'], path, '', gr.update(interactive=False), notification


def invalidate():
    return '', gr.update(interactive=False), 'Параметры изменены. Нажмите «Проверить параметры».', None


def reset():
    sid = secrets.token_hex(32)
    return sid, sid, [], '', gr.update(interactive=False), None, ''


def catalog_markdown():
    lines = []
    for c in CATALOG['courses']:
        lines.append(f"**{c['title']}** · {c['level']}\n\n"
                     f"{c['direction']}\n\n"
                     f"Стоимость: **{price_text(c['price_rub'])}**  \n"
                     f"Начало обучения: **{start_date_text(c['start_date'])}**  \n"
                     f"Длительность: {c['duration']}  \n"
                     f"Примерная нагрузка: {c['weekly_load']}\n\n---")
    return '\n\n'.join(lines)


def build_app():
    with gr.Blocks(title='IT Навигатор · AI-консультант', analytics_enabled=False) as demo:
        browser = gr.BrowserState(None, storage_key='it-advisor-session-v1', secret=os.getenv('BROWSER_SECRET') or SECRET_FILE.read_text())
        sid = gr.State('')
        token = gr.State('')
        gr.Markdown('# IT Навигатор\n### Найдите свой следующий шаг в IT\nАналитика · тестирование · менеджмент · дизайн')
        gr.Markdown(CATALOG['notice'])
        if store.path and os.getenv('DEMO_EPHEMERAL') == 'true':
            gr.Markdown('Демо: история и записи могут сбрасываться после перезапуска сервера. Скачайте подтверждение записи.')
        with gr.Row():
            with gr.Column(scale=3):
                chat = gr.Chatbot(height=500, label='Поддержка IT Навигатора', buttons=['copy'],
                                  placeholder='Расскажите, чему хотите научиться и какой у вас опыт.')
                message = gr.Textbox(label='Ваш вопрос', placeholder='Хочу перейти из маркетинга в продуктовую аналитику. С чего начать?', max_lines=5, interactive=False)
                with gr.Row():
                    submit = gr.Button('Отправить', variant='primary', interactive=False)
                    clear = gr.Button('Новый диалог')
                gr.Examples(examples=[['Подбери курс по бизнес-аналитике для новичка'],
                                      ['Есть ли продвинутые курсы для дизайнеров?'],
                                      ['Сколько стоит курс по тестированию?'],
                                      ['Хочу записаться на курс по управлению продуктом']], inputs=message)
                gr.Markdown('Диалог привязан к этому браузеру. Для продолжения беседы возвращайтесь в этот браузер. «Новый диалог» начинает отдельную историю.')
            with gr.Column(scale=2):
                gr.Markdown('## Запись на курс\nВыберите параметры, проверьте их и подтвердите. Оплата не требуется.')
                course = gr.Dropdown(choices=[(c['title'], c['id']) for c in COURSES.values()], label='Курс')
                name = gr.Textbox(label='Как вас зовут?', max_lines=1)
                load = gr.Radio(['2–3 часа в неделю', '4–5 часов в неделю', '6–10 часов в неделю'], label='Желаемая нагрузка', value='4–5 часов в неделю')
                consent = gr.Checkbox(label='Согласен сохранить имя и параметры записи в учебном приложении')
                preview_btn = gr.Button('Проверить параметры')
                preview = gr.Textbox(label='Параметры записи', interactive=False, lines=8)
                confirm_btn = gr.Button('Подтвердить запись', variant='primary', interactive=False)
                receipt = gr.File(label='Скачать подтверждение', interactive=False)
        with gr.Accordion('Курсы IT Навигатора', open=False):
            gr.Markdown(catalog_markdown())
        if not os.getenv('GIGACHAT_CREDENTIALS'):
            gr.Markdown('⚙️ GigaChat ещё не подключён: добавьте ключ в `.env` на сервере. Каталог и запись уже работают.')
        demo.load(restore, [browser], [browser, sid, chat, message, submit], api_name=False)
        # One shared queue prevents races between chat and enrollment callbacks.
        queue = dict(concurrency_id='advisor', concurrency_limit=1, api_name=False)
        submit.click(send, [message, sid], [message, chat], **queue)
        message.submit(send, [message, sid], [message, chat], **queue)
        preview_btn.click(make_draft, [course, name, load, consent, sid], [preview, token, confirm_btn, receipt], **queue)
        confirm_btn.click(confirm, [token, sid], [chat, receipt, token, confirm_btn, preview], **queue)
        for field in (course, name, load, consent):
            field.input(invalidate, [], [token, confirm_btn, preview, receipt], **queue)
        clear.click(reset, [], [browser, sid, chat, token, confirm_btn, receipt, preview], **queue)
    return demo.queue(max_size=32)


if __name__ == '__main__':
    build_app().launch(server_name=os.getenv('APP_HOST', '0.0.0.0' if os.getenv('RENDER') else '127.0.0.1'),
                       server_port=int(os.getenv('PORT') or os.getenv('APP_PORT', '7860')),
                       share=False, show_error=False, theme=gr.themes.Soft(primary_hue='indigo'),
                       blocked_paths=[p for p in [str(ROOT / '.env'), store.path, str(SECRET_FILE)] if p])
