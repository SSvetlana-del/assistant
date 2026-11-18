"""Deterministic chat booking. Models can advise, but cannot confirm a write."""
import re
from datetime import date
from advisor.catalog import start_date_text, price_text, MONTHS

CONFIRM = {'подтверждаю','подтверждаю запись','подтвердить запись','да','да подтверждаю','всё верно','все верно'}
CANCEL = {'отмена','отменить','отменить запись','не хочу записываться','передумал','передумала'}


def normalize(text):
    return re.sub(r'[^\w\s-]', '', text.casefold()).strip()


def dates(course):
    return course.get('start_dates', [course['start_date']])


def receipt_fields(record):
    return {'Имя':record['name'], 'Курс':record['course'],
            'Начало обучения':start_date_text(record['start_date']) if record.get('start_date') else 'не указано в прежней записи',
            'Длительность':record['duration'],
            'Стоимость курса':price_text(record['price_rub']) if record.get('price_rub') is not None else 'не указана в прежней записи',
            'Формат':record['format']}


def receipt_text(record):
    return '\n'.join([f"Запись № {record['registration_id']}"] + [f'{k}: {v}' for k,v in receipt_fields(record).items()] + ['IT Навигатор · Тестовый проект. Оплата не взимается.'])


class ChatService:
    def __init__(self, advisor, store):
        self.advisor, self.store = advisor, store
        self.courses = advisor.courses

    def course_from_text(self, text, state):
        value = normalize(text)
        choices = list(self.courses)
        if value.isdigit() and state.get('stage')=='course' and 1 <= int(value) <= len(choices):
            return choices[int(value)-1]
        full = [c['id'] for c in self.courses.values() if normalize(c['title']) in value or value==c['id']]
        if full:
            chosen=max(full,key=lambda cid:len(self.courses[cid]['title']))
            if ('продвин' in value or 'мидл' in value) and self.courses[chosen]['level']!='Продвинутый':
                return {'system':'system-middle','project':'project-middle','product':'product-pro'}.get(chosen)
            return chosen
        aliases={'sql':'sql','бизнес-аналит':'business','бизнес аналит':'business',
                 'продуктовый аналит':'product-analytics','продуктовая аналит':'product-analytics',
                 'системный аналит':'system','системная аналит':'system',
                 'аналитик данных':'data','аналитика данных':'data','дизайнер интерфейс':'design','юнит':'unit',
                 'управление проект':'project','менеджер проект':'project','проджект':'project',
                 'управление продукт':'product','продакт':'product',
                 'ux':'ux','bi':'bi','продакт-менеджер с нуля':'product'}
        for key,cid in aliases.items():
            if key in value:
                if ('мидл' in value or 'продвин' in value) and cid in ('system','project'):return cid+'-middle'
                if ('опыт' in value or 'продвин' in value) and cid=='product':return 'product-pro'
                return cid
        if 'тестирован' in value or value=='qa':
            return 'qa-plus' if 'продвин' in value else 'qa'
        return None

    def choose_date(self, text, course):
        value=normalize(text)
        available=dates(course)
        if value in {'ближайшая','ближайшую','первая','первую','ближайший старт'}:
            return available[0]
        if value.isdigit() and 1 <= int(value) <= len(available):
            return available[int(value)-1]
        matches=[]
        for iso in available:
            d=date.fromisoformat(iso)
            patterns=[iso, d.strftime('%d.%m.%Y'), d.strftime('%d.%m'),
                      f'{d.day} {MONTHS[d.month-1]}',f'{d.day:02d} {MONTHS[d.month-1]}']
            # Explicit years must match; "1 декабря 2027" cannot silently select 2026.
            years=re.findall(r'\b20\d{2}\b',text)
            years += [str(2000+int(y)) for y in re.findall(r'\b\d{1,2}\.\d{1,2}\.(\d{2})\b',text)]
            if years and str(d.year) not in years:continue
            if any(re.search(r'(?<!\d)'+re.escape(p)+r'(?!\d)',text.casefold()) for p in patterns):
                matches.append(iso)
        return matches[0] if len(matches)==1 else None

    @staticmethod
    def name_from_text(text):
        value=re.sub(r'^(меня зовут|моё имя|мое имя|имя|я)\s*[:—-]?\s*','',text.strip(),flags=re.I).strip()
        if not 2<=len(value)<=80 or not re.fullmatch(r"[^\W\d_]+(?:[ '\-][^\W\d_]+){0,4}",value,re.UNICODE):
            return None
        if normalize(value) in CONFIRM or normalize(value) in CANCEL:return None
        words=normalize(value).split()
        blocked={'да','нет','подтверждаю','запиши','записаться','отмена','привет','хочу','хорошо','ок','изменить','курс','когда','сколько','как','почему','пожалуйста','что','где','можно','спасибо','подойдет','подойдёт','сейчас','завтра'}
        return None if any(w in blocked for w in words) else value

    def cancel_draft(self, sid):
        self.store.cancel_draft(sid)

    def prompt(self, state):
        stage=state['stage']
        if stage=='course':
            choices='\n'.join(f"{i}. {c['title']}" for i,c in enumerate(self.courses.values(),1))
            return 'Давайте подберём программу для записи. На какой курс хотите записаться? Напишите название или номер:\n\n'+choices
        c=self.courses[state['course_id']]
        if stage=='date':
            options='\n'.join(f'{i}. {start_date_text(day)}' for i,day in enumerate(dates(c),1))
            return f"Курс «{c['title']}» — {price_text(c['price_rub'])}.\n\nВыберите дату начала обучения — напишите дату или номер:\n\n{options}"
        if stage=='name':
            return f"Выбрали старт {start_date_text(state['start_date'])}. Как вас зовут? Можно указать только имя."
        if stage=='edit':
            return 'Что поменяем: курс, дату старта или имя?'
        return (f"**Проверим вашу запись**\n\n"
                f"Курс: **{c['title']}**\n\n"
                f"Начало: **{start_date_text(state['start_date'])}**\n\n"
                f"Имя: **{state['name']}**\n\n"
                f"Стоимость: **{price_text(c['price_rub'])}** · Длительность: {c['duration']}\n\n"
                'Всё верно? Напишите **«Подтверждаю»** или нажмите кнопку под чатом. '
                'До подтверждения запись не сохраняется. Если нужно, можно изменить данные или отменить запись.')

    def advance(self, sid, state):
        if not state.get('course_id'):state['stage']='course'
        elif not state.get('start_date'):state['stage']='date'
        elif not state.get('name'):state['stage']='name'
        else:
            c=self.courses[state['course_id']]
            payload=dict(course_id=c['id'],course=c['title'],name=state['name'],start_date=state['start_date'],
                         duration=c['duration'],price_rub=c['price_rub'],format=c['format'])
            state['token']=self.store.draft(sid,payload)
            state['stage']='confirm'
        return self.prompt(state)

    def resolve_course(self, text, saved):
        cid=self.course_from_text(text,saved.get('booking') or {})
        if cid:
            if ('продвин' in normalize(text) or 'мидл' in normalize(text)) and self.courses[cid]['level']!='Продвинутый':return None
            return cid
        value=normalize(text)
        generic={'хочу записаться','записаться','запиши меня','оформить запись','хочу оформить запись','помоги записаться'}
        ids=saved.get('course_ids',[])
        if value in generic and len(ids)==1:return ids[0]
        classify=getattr(self.advisor,'classify',None)
        if classify:
            result=classify({'history':saved.get('history',[])+[{'role':'user','content':text}],'course_ids':[]})
            ids=result.get('course_ids',[])
            if not result.get('error') and len(ids)==1:
                if ('продвин' in value or 'мидл' in value) and self.courses[ids[0]]['level']!='Продвинутый':return None
                return ids[0]
        return None

    def seed(self, text, ids):
        state={'course_id':ids[0]} if len(ids)==1 else {}
        if state:
            chosen=self.choose_date(text,self.courses[state['course_id']])
            if chosen:state['start_date']=chosen
            match=re.search(r'(?:меня зовут|моё имя|мое имя)\s+([^,.!?\n]+)',text,re.I)
            if match:
                name=self.name_from_text(match.group(1))
                if name:state['name']=name
        return state

    def turn(self, sid, text):
        saved=self.store.load(sid)
        value=normalize(text)
        state=dict(saved.get('booking') or {})
        history=saved.get('history',[])
        record=None
        question_like = '?' in text or bool(re.match(r'^(сколько|как|какая|какой|когда|где|можно|расскажи|подскажи|что)\b', value))
        if value in CANCEL or re.fullmatch(r'(?:я )?(?:хочу )?(?:отменить|отмена|передумал|передумала)(?: запись)?', value):
            self.cancel_draft(sid);state={}
            answer=('Незавершённой заявки сейчас нет. Уже подтверждённая запись сохранена. Есть вопросы по обучению?' if saved.get('last_receipt') and not saved.get('booking') else 'Хорошо, эту заявку не оформляем. Могу помочь подобрать другую программу — какое направление вам интересно?')
        elif state:
            if value in CONFIRM and state['stage']=='confirm' and not question_like:
                try:
                    record,created=self.store.confirm(sid,state['token'])
                except ValueError:
                    state.pop('token',None)
                    answer='Срок подтверждения истёк. '+self.advance(sid,state)
                else:
                    saved['last_receipt']=record
                    saved['confirmation_echo_pending']=True
                    state={}
                    answer=(f"{'Готово, вы записаны' if created else 'Вы уже записаны'} на курс **«{record['course']}»**! "
                            f"Начало — {start_date_text(record['start_date']) if record.get('start_date') else 'по прежним условиям'}.\n\n"
                            f"Имя: {record['name']} · Номер записи: **{record['registration_id']}**.\n\n"
                            'Подтверждение можно скачать под чатом. Есть ещё вопросы по обучению?')
            elif value.startswith(('измен','помен','другой курс','другая дата')) or state['stage']=='edit':
                self.cancel_draft(sid);state.pop('token',None)
                if 'курс' in value:
                    state.pop('course_id',None);state.pop('start_date',None)
                elif 'дат' in value or 'старт' in value:state.pop('start_date',None)
                elif 'имя' in value:state.pop('name',None)
                else:
                    state['stage']='edit'
                    answer=self.prompt(state)
                if any(w in value for w in ('курс','дат','старт','имя')):answer=self.advance(sid,state)
            elif state['stage']=='course':
                cid=self.resolve_course(text,saved)
                if cid:state['course_id']=cid;answer=self.advance(sid,state)
                else:answer='Не удалось однозначно выбрать программу. '+self.prompt(state)
            elif state['stage']=='date':
                chosen=self.choose_date(text,self.courses[state['course_id']])
                if chosen:state['start_date']=chosen;answer=self.advance(sid,state)
                else:answer='Уточните одну дату из доступных вариантов. '+self.prompt(state)
            elif state['stage']=='name':
                name=None if question_like else self.name_from_text(text)
                if name:state['name']=name;answer=self.advance(sid,state)
                else:answer='Укажите, пожалуйста, имя, например «Анна» или «Меня зовут Анна». '+self.prompt(state)
            else:
                answer='Для сохранения нужно явное подтверждение. '+self.prompt(state)
            # Questions during booking should not be mistaken for a name or confirmation.
            if state and question_like and record is None and value not in CONFIRM:
                context=dict(saved,course_ids=[state['course_id']] if state.get('course_id') else [])
                reply=self.advisor.reply(text,context)
                answer=reply['history'][-1]['content']+'\n\n'+self.prompt(state)
        elif value in (CONFIRM-{'да','всё верно','все верно'}) and saved.get('confirmation_echo_pending') and saved.get('last_receipt'):
            answer='Эта запись уже сохранена — повторно оформлять её не нужно. Хотите выбрать другой курс?'
        else:
            saved['confirmation_echo_pending']=False
            explicit=bool(re.search(r'запис|оформить',value)) and not bool(re.search(r'как.*запис',value))
            if explicit:
                resolved=self.resolve_course(text,saved)
                ids=[resolved] if resolved else []
                state=self.seed(text,ids)
                answer=self.advance(sid,state)
            else:
                reply=self.advisor.reply(text,saved)
                saved['course_ids']=reply.get('course_ids',[])
                if reply.get('route')=='enroll':
                    ids=reply.get('course_ids',[])
                    state=self.seed(text,ids)
                    answer=self.advance(sid,state)
                else:answer=reply['history'][-1]['content']
        saved['booking']=state
        if state.get('course_id'):saved['course_ids']=[state['course_id']]
        saved['history']=history+[{'role':'user','content':text},{'role':'assistant','content':answer}]
        self.store.save(sid,saved)
        return saved
