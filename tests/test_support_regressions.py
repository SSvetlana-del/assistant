"""Regressions for the actual support conversation, including adversarial routing."""
import json
from pathlib import Path
import pytest
from advisor.engine import Advisor
from advisor.booking import ChatService
from advisor.storage import Store
from test_advisor import FakeModel

CATALOG=json.loads((Path(__file__).parents[1]/'data/courses.json').read_text())


def make(tmp_path,intent='enroll',ids=None):
    # Intentionally wrong statistical routes must not start bookings.
    return ChatService(Advisor(CATALOG,FakeModel(intent,ids or ['qa'])),Store(tmp_path/'support.sqlite3'))


def answer(saved):return saved['history'][-1]['content']


def test_actual_user_flow_and_payment_after_confirmation(tmp_path):
    s=make(tmp_path,'price',['qa','qa-plus'])
    state=s.turn('one','Сколько стоит курс по тестированию?')
    assert '14000 ₽' in answer(state)
    s.turn('one','Помогите подобрать курс')
    state=s.turn('one','начинающий, несколько часов в неделю, автоматическое тестирование')
    assert state['course_ids']==['qa']
    assert 'Юнит-экономика' not in answer(state) and 'ручному' in answer(state)
    assert 'Selenium/Playwright' in answer(state)  # Honest scope, not an automation promise.
    state=s.turn('one','запишите, а когда нужно оплатить?')
    assert state['booking']['course_id']=='qa' and 'оплата не взимается' in answer(state)
    s.turn('one','1');s.turn('one','Анна')
    state=s.turn('one','Подтверждаю запись')
    assert not state['booking']
    rid=state['last_receipt']['registration_id']
    state=s.turn('one','а когда нужно оплатить?')
    assert not state['booking'] and 'Выберите дату' not in answer(state)
    assert 'оплата не взимается' in answer(state)
    assert state['last_receipt']['registration_id']==rid
    state=s.turn('one','что входит в курс Аналитика данных?')
    assert not state['booking'] and state['course_ids']==['data']
    assert 'SQL' in answer(state) and 'DataLens' in answer(state) and 'Что изучите' in answer(state)
    assert 'Выберите дату' not in answer(state) and 'Базовый курс тестировщика' not in answer(state)
    with s.store.connect() as db:assert db.execute('SELECT count(*) FROM enrollments').fetchone()[0]==1


@pytest.mark.parametrize('text',['а когда нужно оплатить?','Когда оплата','Какие способы оплаты?','Можно оплатить позже?','Что нужно для записи?','Я уже записана?'])
def test_model_enroll_route_is_not_user_authorization(tmp_path,text):
    s=make(tmp_path)
    state=s.turn('one',text)
    assert not state['booking']


def test_yes_requires_a_booking_offer(tmp_path):
    s=make(tmp_path)
    s.store.save('one',{'history':[{'role':'assistant','content':'Есть вопросы по обучению?'}],'course_ids':['qa']})
    assert not s.turn('one','Да')['booking']
    saved=s.store.load('one')
    saved['history'].append({'role':'assistant','content':'Хотите записаться?'})
    s.store.save('one',saved)
    state=s.turn('one','Да')
    assert state['booking']['stage']=='date'


def test_switch_course_during_unfinished_booking_clears_old_draft(tmp_path):
    s=make(tmp_path)
    s.turn('one','Хочу записаться на SQL');s.turn('one','1');s.turn('one','Анна')
    old=s.store.load('one')['booking']['token']
    state=s.turn('one','Что входит в курс Аналитика данных?')
    assert not state['booking'] and state['course_ids']==['data']
    assert 'DataLens' in answer(state) and 'Проверим вашу запись' not in answer(state)
    with pytest.raises(ValueError):s.store.confirm('one',old)


def test_legacy_phantom_booking_is_repaired_without_deleting_enrollment(tmp_path):
    s=make(tmp_path)
    s.turn('one','Хочу записаться на SQL');s.turn('one','1');s.turn('one','Анна');s.turn('one','Подтверждаю')
    saved=s.store.load('one');rid=saved['last_receipt']['registration_id']
    saved['booking']={'stage':'date','course_id':'sql'}
    s.store.save('one',saved)
    state=s.turn('one','А когда нужно оплатить?')
    assert not state['booking'] and state['last_receipt']['registration_id']==rid


def test_payment_question_during_unconfirmed_booking_preserves_fields(tmp_path):
    s=make(tmp_path)
    s.turn('one','Хочу записаться на SQL');s.turn('one','1')
    state=s.turn('one','А когда оплатить?')
    assert state['booking']['stage']=='name' and 'оплата не взимается' in answer(state)
    assert 'Выберите дату' not in answer(state)
    state=s.turn('one','Анна')
    assert state['booking']['stage']=='confirm'


@pytest.mark.parametrize('cid',[c['id'] for c in CATALOG['courses']])
def test_each_program_is_answered_exactly_from_catalog(cid):
    model=FakeModel('enroll',['unit'])
    advisor=Advisor(CATALOG,model)
    course=advisor.courses[cid]
    state=advisor.reply('Что входит в курс '+course['title']+'?',{})
    content=answer(state)
    assert state['course_ids']==[cid]
    assert all(module in content for module in course['syllabus'])
    assert course['final_project'] in content and course['prerequisites'] in content
    assert not model.calls  # Programs cannot gain invented topics through generation.


def test_selection_filters_level_time_and_budget():
    advisor=Advisor(CATALOG,FakeModel('selection',['unit']))
    state=advisor.reply('Я начинающий, ищу аналитику данных, до 5 часов в неделю, бюджет 5000 рублей',{})
    assert state['course_ids']==['sql']
    assert '4000 ₽' in answer(state) and 'Юнит-экономика' not in answer(state)


def test_unsupported_advanced_direction_does_not_leak_another_course():
    state=Advisor(CATALOG,FakeModel()).reply('Подберите продвинутый курс бизнес-аналитики',{})
    assert state['course_ids']==[] and 'нет программы' in answer(state)
