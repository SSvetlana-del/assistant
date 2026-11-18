import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from advisor.booking import ChatService, receipt_fields
from advisor.storage import Store

CATALOG=json.loads((Path(__file__).parents[1]/'data/courses.json').read_text())


class AdvisorStub:
    def __init__(self):
        self.courses={c['id']:c for c in CATALOG['courses']}
    def reply(self,text,saved):
        return dict(history=saved.get('history',[])+[{'role':'user','content':text},{'role':'assistant','content':'Стоимость курса — 4000 ₽. Есть вопросы?'}],course_ids=saved.get('course_ids',[]),route='price')


@pytest.fixture
def service(tmp_path):
    return ChatService(AdvisorStub(),Store(tmp_path/'booking.sqlite3'))


def count(service):
    with service.store.connect() as db:
        return db.execute('SELECT count(*) FROM enrollments').fetchone()[0]


def prepare(service,sid='one'):
    service.turn(sid,'Хочу записаться на SQL')
    service.turn(sid,'1 декабря 2026')
    return service.turn(sid,'Меня зовут Анна')


def test_complete_chat_booking_requires_confirmation(service):
    first=service.turn('one','Хочу записаться на SQL')
    assert first['booking']['stage']=='date' and count(service)==0
    second=service.turn('one','1 декабря 2026')
    assert second['booking']['stage']=='name' and count(service)==0
    preview=service.turn('one','Меня зовут Анна')
    assert preview['booking']['stage']=='confirm' and count(service)==0
    assert '4000 ₽' in preview['history'][-1]['content']
    saved=service.turn('one','Подтверждаю')
    assert count(service)==1 and not saved['booking']
    record=saved['last_receipt']
    assert record['name']=='Анна' and record['start_date']=='2026-12-01'
    assert 'preferred_load' not in record and 'weekly_load' not in record
    assert 'форма' not in saved['history'][-1]['content'].casefold()


def test_confirm_outside_confirmation_cannot_write(service):
    service.turn('one','Хочу записаться на SQL')
    service.turn('one','Подтверждаю')
    assert count(service)==0


def test_duplicate_confirm_does_not_duplicate_record(service):
    prepare(service)
    first=service.turn('one','Подтверждаю')
    second=service.turn('one','Подтверждаю запись')
    assert count(service)==1
    assert second['last_receipt']['registration_id']==first['last_receipt']['registration_id']


def test_edit_date_invalidates_previous_confirmation(service):
    preview=prepare(service)
    old=preview['booking']['token']
    state=service.turn('one','Изменить дату')
    assert state['booking']['stage']=='date'
    with pytest.raises(ValueError):service.store.confirm('one',old)
    state=service.turn('one','15 декабря 2026')
    assert state['booking']['stage']=='confirm' and state['booking']['name']=='Анна'
    saved=service.turn('one','Подтверждаю')
    assert saved['last_receipt']['start_date']=='2026-12-15'


def test_edit_name_and_cancellation(service):
    prepare(service)
    state=service.turn('one','Изменить данные')
    assert state['booking']['stage']=='edit'
    state=service.turn('one','имя')
    assert state['booking']['stage']=='name'
    state=service.turn('one','Светлана')
    assert state['booking']['name']=='Светлана'
    state=service.turn('one','Отмена')
    assert not state['booking'] and count(service)==0
    service.turn('one','Подтверждаю')
    assert count(service)==0


def test_unknown_start_cannot_be_booked(service):
    service.turn('one','Хочу записаться на SQL')
    for text in ['1 декабря 2027','25 декабря 2026','2026-12-22']:
        state=service.turn('one',text)
        assert state['booking']['stage']=='date' and count(service)==0


def test_stored_booking_survives_service_restart(service):
    service.turn('one','Хочу записаться на SQL')
    restarted=ChatService(AdvisorStub(),Store(service.store.path))
    state=restarted.turn('one','1')
    assert state['booking']['stage']=='name'
    state=restarted.turn('one','Анна')
    assert state['booking']['stage']=='confirm' and count(service)==0


def test_different_sessions_cannot_share_pending_booking(service):
    prepare(service)
    other=service.turn('two','Подтверждаю')
    assert not other['booking'] and count(service)==0


def test_price_question_during_booking_is_not_a_name(service):
    service.turn('one','Хочу записаться на SQL')
    service.turn('one','1')
    state=service.turn('one','А сколько стоит?')
    assert state['booking']['stage']=='name' and not state['booking'].get('name')
    assert '4000 ₽' in state['history'][-1]['content']


def test_negated_or_qualified_confirmation_cannot_write(service):
    prepare(service)
    for text in ['не подтверждаю','подтверждаю, но измени дату','запиши без подтверждения']:
        service.turn('one',text)
        assert count(service)==0


def test_all_offered_dates_belong_to_course(service):
    for c in service.courses.values():
        assert len(c['start_dates'])==3 and c['start_dates'][0]==c['start_date']


def test_workload_filters_catalog_only():
    from app import catalog_cards
    light=catalog_cards(availability='До 5 ч/нед')
    assert 'Интерактивный тренажер по SQL' in light
    assert 'Мидл системный аналитик' not in light


def test_all_details_in_one_message_still_require_confirmation(service):
    state=service.turn('one','Хочу записаться на SQL 1 декабря 2026, меня зовут Анна')
    assert state['booking']['stage']=='confirm' and count(service)==0
    assert state['booking']['name']=='Анна'


def test_question_without_question_mark_is_not_captured_as_name(service):
    service.turn('one','Хочу записаться на SQL');service.turn('one','1')
    state=service.turn('one','расскажи о программе')
    assert state['booking']['stage']=='name' and not state['booking'].get('name')


def test_unknown_course_does_not_reuse_previous_course(service):
    service.store.save('one',{'history':[],'course_ids':['sql']})
    state=service.turn('one','Хочу записаться на кибербезопасность')
    assert state['booking']['stage']=='course' and not state['booking'].get('course_id')


def test_question_is_not_explicit_confirmation(service):
    prepare(service)
    state=service.turn('one','Подтверждаю?')
    assert state['booking']['stage']=='confirm' and count(service)==0


def test_confirmation_phrase_is_not_a_name(service):
    service.turn('one','Хочу записаться на SQL');service.turn('one','1')
    state=service.turn('one','всё верно')
    assert state['booking']['stage']=='name' and not state['booking'].get('name')


def test_ambiguous_date_and_wrong_two_digit_year_require_clarification(service):
    service.turn('one','Хочу записаться на SQL')
    for text in ['1 декабря 2026 или 15 декабря 2026','01.12.27']:
        state=service.turn('one',text)
        assert state['booking']['stage']=='date' and count(service)==0


def test_new_booking_after_previous_confirmation_can_start(service):
    prepare(service);service.turn('one','Подтверждаю')
    service.turn('one','Сколько стоит другой курс?')
    class EnrollAfterYes(AdvisorStub):
        def reply(self,text,saved):
            result=super().reply(text,saved)
            result['route']='enroll';result['course_ids']=['qa']
            return result
    service.advisor=EnrollAfterYes()
    state=service.turn('one','Да')
    assert state['booking']['stage']=='date' and state['booking']['course_id']=='qa'
    assert count(service)==1


def test_cancel_after_confirm_does_not_claim_enrollment_removed(service):
    prepare(service);service.turn('one','Подтверждаю')
    state=service.turn('one','Отмена')
    assert 'подтверждённая запись сохранена' in state['history'][-1]['content']
    assert count(service)==1


def test_booking_respects_requested_advanced_level(service):
    state=service.turn('one','Хочу записаться на продвинутый курс системный аналитик')
    assert state['booking']['course_id']=='system-middle'


def test_missing_advanced_course_is_not_replaced_by_beginner(service):
    state=service.turn('one','Хочу записаться на продвинутый бизнес-аналитик')
    assert state['booking']['stage']=='course' and not state['booking'].get('course_id')
