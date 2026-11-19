"""Grounded retrieval and intent guards shared by the graph and booking service."""
import re
from advisor.catalog import price_text, start_date_text


def norm(text):
    return re.sub(r'[^\w\s-]', '', text.casefold()).strip()


def is_payment(text):
    return bool(re.search(r'оплат|плат[её]ж|платить|рассроч|возврат|скидк', text.casefold()))


def is_comparison(text):
    return bool(re.search(r'сравн|разниц|отлича|чем\s+отлич|что\s+лучше.*\sили\s',text,re.I))


def is_selection(text):
    return bool(re.search(r'подоб|подбер|подбор|порекоменд|посовет|выбрать|(?:какой|какая|какое|какие|что).*(?:подойд|подход(?:ит|ят|ящ)|выбрат|лучше)',text,re.I))


def comparison_scope_reply(text, history):
    last=next((m['content'] for m in reversed(history) if m['role']=='assistant'),'')
    return ('В каком направлении сравнить программы' in last and bool(directions(text))
            and not is_selection(text)
            and not re.search(r'\?|стоит|цен[ауы]|стоимост|запис|оплат|что входит',text,re.I))


def is_program(text):
    return bool(re.search(r'что.*(?:входит|изуч|науч)|программ[ауы]|содержан|темы|чему.*науч|расскажи.*курс', text.casefold()))


def explicit_enrollment(text):
    value=norm(text)
    if re.search(r'не\s+(?:хочу\s+)?(?:запис|оформ)|(?:как|можно ли|что нужно|где).*запис',value):return False
    return bool(re.search(r'\b(?:запиши(?:те)?(?:сь)?|записаться|записывай(?:те)?|оформ(?:и|ите|ить) запись)\b',value))


def enrollment_consent(text, history):
    if '?' in text or norm(text) not in {'да','хочу','давайте','да хочу','да запишите','да пожалуйста','хорошо'}:return False
    last=next((m['content'] for m in reversed(history) if m['role']=='assistant'),'')
    return bool(re.search(r'(?:хотите записаться|записать вас|помочь с записью|оформим запись)',last,re.I))


DIRECTIONS=[
 ('Тестирование ПО',r'тестирован|тестиров|\bqa\b|автотест|автоматизаци.*тест'),
 ('Системная аналитика',r'системн\w* аналит'),
 ('Бизнес-аналитика',r'бизнес[ -]аналит'),
 ('Продуктовая аналитика',r'продуктов\w* аналит|юнит[ -]эконом'),
 ('Аналитика данных',r'аналити[кч]\w* данн|\bsql\b|\bbi\b|визуализац'),
 ('Управление проектами',r'управлен\w* проект|менеджер\w* проект|проджект'),
 ('Управление продуктом',r'управлен\w* продукт|продакт|продуктов\w* менедж'),
 ('Дизайн',r'дизайн|\bux\b|\bui\b'),
]


def directions(text):
    return [d for d,p in DIRECTIONS if re.search(p,text,re.I)]


def mentioned_courses(text, courses):
    value=norm(text)
    # Match non-overlapping title spans so two explicitly named courses survive.
    # A base title nested inside an advanced title is not a separate mention.
    spans=[]
    found=[]
    for cid,c in sorted(courses.items(),key=lambda pair:len(pair[1]['title']),reverse=True):
        for match in re.finditer(re.escape(norm(c['title'])),value):
            a,b=match.span()
            if not any(a<end and b>start for start,end in spans):
                found.append((a,cid));spans.append((a,b))
    aliases=[('sql','sql'),('аналитика данных','data'),('аналитик данных','data'),
             ('бизнес-аналит','business'),('бизнес аналит','business'),('системн','system'),
             ('продуктовая аналит','product-analytics'),('продуктовый аналит','product-analytics'),
             ('юнит','unit'),('ux','ux'),('bi','bi'),('дизайнер интерфейс','design'),
             ('продакт','product'),('управление продукт','product'),
             ('управление проект','project'),('менеджер проект','project')]
    for alias,cid in aliases:
        if cid=='system' and 'аналит' not in value:continue
        pattern=r'\b'+re.escape(alias)+(r'\b' if alias.isascii() else '')
        for match in re.finditer(pattern,value):
            a,b=match.span()
            if not any(a<end and b>start for start,end in spans):
                found.append((a,cid));spans.append((a,b))
    ids=list(dict.fromkeys(cid for _,cid in sorted(found)))
    if value in courses:ids=[value]
    if is_comparison(text):
        ds=directions(text)
        return ids or [cid for cid,c in courses.items() if c['direction'] in ds]
    advanced=bool(re.search(r'продвин|мидл|middle',value))
    beginner=bool(re.search(r'начинающ|с нуля|базовый|нович',value))
    if advanced:
        mapping={'system':'system-middle','project':'project-middle','product':'product-pro','design':'design-pro'}
        ids=[mapping.get(cid,cid) for cid in ids]
    ds=directions(text)
    if not ids and ds:
        ids=[cid for cid,c in courses.items() if c['direction'] in ds]
    if beginner and not advanced:ids=[cid for cid in ids if courses[cid]['level']=='Начальный']
    if advanced:ids=[cid for cid in ids if courses[cid]['level']=='Продвинутый']
    return ids


def preferences(history):
    result={}
    for m in history:
        if m['role']!='user':continue
        text=m['content'].casefold()
        ds=directions(text)
        if ds and ds!=result.get('directions'):
            result={'directions':ds}  # A new field of study starts a new selection context.
        if is_comparison(text) or is_program(text):continue
        if re.search(r'начинающ|(?<!не )нович|без опыта|нет (?:практического )?опыта|с нуля',text):result['level']='Начальный'
        elif re.search(r'продвин|мидл|опытн|с опытом|есть (?:практический |базовый )?опыт|работаю дизайнер|не нович|опыт.{0,10}[1-9]\s*(?:год|лет)',text):result['level']='Продвинутый'
        hours=re.search(r'(?:до\s*)?(\d+)(?:\s*[-–]\s*(\d+))?\s*(?:час|ч\b)',text)
        if hours:result['hours']=int(hours.group(2) or hours.group(1))
        elif 'несколько часов' in text:result['hours']=6
        budget=re.search(r'(?:бюджет|до)\s*(\d[\d ]*)\s*(тыс|₽|руб)',text)
        if budget:result['budget']=int(budget.group(1).replace(' ',''))*(1000 if budget.group(2)=='тыс' else 1)
        if re.search(r'автоматическ|автоматизац|автотест',text):result['automation']=True
        if result.get('directions')==['Дизайн']:
            positive=' '.join(part for part in re.split(r'[,;]|\bно\b',text)
                              if not re.search(r'не\s+(?:хочу|интерес|нуж|планир)',part))
            goals=[]
            for goal,pattern in [('research',r'исследован|интервью|юзабилити|изучать пользовател|потребност.*пользовател'),
                                 ('interfaces',r'интерфейс|макет|figma|фигм|прототип|\bui\b'),
                                 ('product_design',r'метрик|конверси|продуктов.*подход|бизнес.*результат|влияни.*продукт')]:
                if re.search(pattern,positive):goals.append(goal)
            if len(goals)==1:result['design_goal']=goals[0]
            elif len(goals)>1:result.pop('design_goal',None)
    return result


def course_summary(c):
    return (f"**«{c['title']}»** — {price_text(c['price_rub'])}\n"
            f"Старт: {start_date_text(c['start_date'])} · {c['duration']} · {c['weekly_load']}\n"
            f"{c['description']}")


def program_answer(c):
    modules='\n'.join(f'{i}. {s}' for i,s in enumerate(c['syllabus'],1))
    outcomes='\n'.join('• '+s for s in c['outcomes'])
    return (course_summary(c)+f"\n\nДля кого: {c['audience']}\nВходные знания: {c['prerequisites']}"
            f"\n\n**Что изучите:**\n{modules}\n\n**Практика:** {c['final_project']}"
            f"\n\n**Результат:**\n{outcomes}\n\nИнструменты: {', '.join(c['tools'])}."
            f"\n\n{c['limitations']}\n\nХотите записаться или уточнить содержание программы?")
