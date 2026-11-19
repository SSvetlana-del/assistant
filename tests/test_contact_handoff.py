"""Contact collection, explicit handoff, persistence and legacy records."""
import json
import pytest
from advisor.contact import parse_contact
from advisor.booking import ChatService
from advisor.storage import Store
from test_booking import AdvisorStub, count
from test_advisor import payload


@pytest.fixture
def service(tmp_path):
    return ChatService(AdvisorStub(),Store(tmp_path/'handoff.sqlite3'))


def start(service):
    service.turn('one','Хочу записаться на SQL')
    service.turn('one','1')
    return service.turn('one','Анна')


@pytest.mark.parametrize('text,kind,value',[
 ('email@example.com','email','email@example.com'),
 ('emailman@example.com','email','emailman@example.com'),
 ('+84 912 345 678','phone','+84912345678'),
 ('anna+course@Example.com','email','anna+course@example.com'),
 ('Мой email: anna@example.com','email','anna@example.com'),
 ('+7 (999) 123-45-67','phone','+79991234567'),
 ('Телефон: 8 999 123 45 67','phone','+79991234567'),
 ('9991234567','phone','+79991234567'),
 ('+49 151 12345678','phone','+4915112345678'),
])
def test_valid_contact(text,kind,value):
    assert parse_contact(text)==dict(contact_type=kind,contact_value=value)


@pytest.mark.parametrize('text',['Анна','да','Подтверждаю','a@','a@domain','a..b@example.com',
                                 '@example.com','name@example..com','123','+00000000000',
                                 'anna@example.com, bob@example.com','<script>alert(1)</script>'])
def test_invalid_contact(text):assert parse_contact(text) is None


def test_contact_required_then_confirmed_before_handoff(service):
    state=start(service)
    assert state['booking']['stage']=='contact'
    for text in ['Подтверждаю','ошибка','123']:
        state=service.turn('one',text)
        assert state['booking']['stage']=='contact' and count(service)==0
    state=service.turn('one','anna@example.com')
    assert state['booking']['stage']=='confirm' and count(service)==0
    assert 'anna@example.com' in state['history'][-1]['content']
    state=service.turn('one','Подтверждаю')
    record=state['last_receipt']
    assert count(service)==1 and record['contact_type']=='email'
    assert record['contact_value']=='anna@example.com'
    assert record['status']=='pending_manager' and record['notification_status']=='not_configured'
    content=state['history'][-1]['content']
    assert 'передана менеджеру' in content and 'в течение рабочего дня' in content and 'оплате' in content
    assert 'скач' not in content.casefold()
    service.turn('one','Подтверждаю')
    assert count(service)==1


def test_edit_contact_invalidates_token_and_keeps_other_fields(service):
    start(service);state=service.turn('one','anna@example.com')
    old=state['booking']['token']
    state=service.turn('one','Изменить контакт')
    assert state['booking']['stage']=='contact'
    with pytest.raises(ValueError):service.store.confirm('one',old)
    state=service.turn('one','+7 999 123-45-67')
    assert state['booking']['stage']=='confirm' and state['booking']['name']=='Анна'
    assert state['booking']['start_date']=='2026-12-01'
    state=service.turn('one','Подтверждаю')
    assert state['last_receipt']['contact_value']=='+79991234567'


def test_contact_stage_survives_restart_and_questions(service):
    start(service)
    reopened=ChatService(AdvisorStub(),Store(service.store.path))
    state=reopened.turn('one','А сколько стоит?')
    assert state['booking']['stage']=='contact' and count(service)==0
    state=reopened.turn('one','anna@example.com')
    assert state['booking']['stage']=='confirm'


def test_cancellation_never_saves_a_manager_request(service):
    start(service);service.turn('one','anna@example.com');service.turn('one','Отмена')
    service.turn('one','Подтверждаю')
    assert count(service)==0
    with service.store.connect() as db:assert db.execute('SELECT count(*) FROM drafts').fetchone()[0]==0


def test_legacy_pending_preview_must_collect_contact_on_reload(service):
    token=service.store.draft('one',payload('sql'))
    service.store.save('one',{'history':[],'booking':{'course_id':'sql','start_date':'2026-12-01','name':'Анна','stage':'confirm','token':token}})
    state=service.restore('one')
    assert state['booking']['stage']=='contact' and 'token' not in state['booking']
    assert len(service.restore('one')['history'])==1  # Reload is idempotent.
    with pytest.raises(ValueError):service.store.confirm('one',token)
    state=service.turn('one','Подтверждаю')
    assert state['booking']['stage']=='contact' and count(service)==0


def test_legacy_confirm_without_reload_cannot_bypass_contact(service):
    token=service.store.draft('one',payload('sql'))
    service.store.save('one',{'history':[],'booking':{'course_id':'sql','start_date':'2026-12-01','name':'Анна','stage':'confirm','token':token}})
    state=service.turn('one','Подтверждаю')
    assert state['booking']['stage']=='contact' and count(service)==0


def test_existing_legacy_enrollment_can_acquire_contact_after_new_confirmation(service):
    old,_=service.store.confirm('one',service.store.draft('one',payload('sql')))
    service.store.save('one',{'history':[],'last_receipt':old})
    start(service);state=service.turn('one','anna@example.com')
    assert count(service)==1 and state['booking']['stage']=='confirm'
    with service.store.connect() as db:
        previous=json.loads(db.execute('SELECT payload FROM enrollments').fetchone()[0])
        assert 'contact_value' not in previous
    state=service.turn('one','Подтверждаю')
    assert count(service)==1
    assert state['last_receipt']['registration_id']==old['registration_id']
    assert state['last_receipt']['contact_value']=='anna@example.com'
