import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from advisor.engine import Advisor, Route
from advisor.storage import Store

CATALOG = json.loads((Path(__file__).parents[1] / 'data/courses.json').read_text())


class FakeModel:
    def __init__(self, intent='general', ids=None, answer='Ответ по каталогу'):
        self.route = Route(intent=intent, course_ids=ids or [])
        self.answer = answer
        self.calls = []

    def with_structured_output(self, schema):
        parent = self
        class Classifier:
            def invoke(self, messages):
                parent.calls.append(messages)
                return parent.route
        return Classifier()

    def invoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=self.answer)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'db.sqlite3')


def payload(course='qa'):
    return {'course_id': course, 'name': 'Тест', 'course': 'Курс', 'price_rub': 0,
            'duration':'8 недель','format':'Онлайн','preferred_load':'4–5 часов в неделю',
            'weekly_load':'4–6 часов в неделю','start_date':'2026-12-07','scope':'Учебная запись'}


def test_history_persists_and_is_isolated(store):
    store.save('one', {'history': [{'role':'user','content':'Хочу дизайн'}], 'course_ids':['design']})
    reopened = Store(store.path)
    assert reopened.load('one')['course_ids'] == ['design']
    assert reopened.load('two')['history'] == []


def test_confirmation_is_durable_single_use_and_idempotent(store):
    token = store.draft('one', payload())
    record, created = store.confirm('one', token)
    assert created and record['registration_id']
    with pytest.raises(ValueError):
        store.confirm('one', token)
    second, created = store.confirm('one', store.draft('one', payload()))
    assert not created and second == record
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM enrollments').fetchone()[0] == 1


def test_draft_cannot_be_confirmed_from_another_session(store):
    token = store.draft('one', payload())
    with pytest.raises(ValueError):
        store.confirm('two', token)


def test_new_draft_invalidates_previous(store):
    token = store.draft('one', payload())
    store.draft('one', payload('design'))
    with pytest.raises(ValueError):
        store.confirm('one', token)


def test_expired_draft_rejected(store):
    token = store.draft('one', payload())
    with store.connect() as db:
        db.execute("UPDATE drafts SET created_at='2000-01-01T00:00:00+00:00'")
    with pytest.raises(ValueError):
        store.confirm('one', token)


def test_price_is_not_generated_by_llm():
    model = FakeModel('price', ['qa-plus'])
    result = Advisor(CATALOG, model).reply('Сколько стоит?', {})
    answer = result['history'][-1]['content']
    course = next(c for c in CATALOG['courses'] if c['id']=='qa-plus')
    assert f"{course['price_rub']} ₽" in answer
    assert '2026 года' in answer and 'Хотите записаться?' in answer
    assert 'http' not in answer and 'Источник' not in answer
    assert len(model.calls) == 1


def test_price_without_course_asks_instead_of_listing_catalog():
    result = Advisor(CATALOG, FakeModel('price')).reply('Сколько стоит?', {})
    answer = result['history'][-1]['content']
    assert 'Какой курс' in answer and '?' in answer
    assert '₽' not in answer


def test_sql_price_matches_support_example():
    result = Advisor(CATALOG, FakeModel('price', ['sql'])).reply('Сколько стоит?', {})
    answer = result['history'][-1]['content']
    assert answer.replace('\n\n',' ') == ('Интерактивный тренажер по SQL — 4000 ₽. '
            'Обучение начнется 01 декабря 2026 года. Хотите записаться?')


@pytest.mark.parametrize('intent', ['selection','general'])
def test_generation_receives_history_and_catalog(intent):
    model = FakeModel(intent, ['design'])
    previous = {'history':[{'role':'user','content':'Я дизайнер, опыт 3 года'},
                           {'role':'assistant','content':'Какая цель?'}], 'course_ids':['design']}
    result = Advisor(CATALOG, model).reply('Хочу развиваться', previous)
    assert len(result['history']) == 4
    assert any('опыт 3 года' in m.content for m in model.calls[-1])
    if intent=='general':
        assert 'Дизайнер интерфейсов' in model.calls[-1][0].content
        assert 'Юнит-экономика' not in model.calls[-1][0].content
    else:
        assert result['course_ids']==['design-pro','ux']


def test_follow_up_price_retains_course():
    result = Advisor(CATALOG, FakeModel('price')).reply('А цена?', {'history':[], 'course_ids':['qa-plus']})
    assert result['course_ids'] == ['qa-plus']
    assert str(next(c for c in CATALOG['courses'] if c['id']=='qa-plus')['price_rub']) in result['history'][-1]['content']


def test_enrollment_intent_cannot_write_database():
    model = FakeModel('enroll',['design'])
    result = Advisor(CATALOG, model).reply('Запиши меня', {})
    assert 'подтвердите' in result['history'][-1]['content']
    assert not model.calls  # Explicit write intent is recognized without a model.


def test_provider_failure_is_safe():
    class Broken(FakeModel):
        def with_structured_output(self, schema):
            raise RuntimeError('SECRET_TOKEN_should_not_leak')
    result = Advisor(CATALOG, Broken()).reply('Привет', {})
    assert 'не получается ответить' in result['history'][-1]['content']
    assert 'SECRET_TOKEN' not in result['history'][-1]['content']


def test_unknown_course_id_is_filtered():
    result = Advisor(CATALOG, FakeModel('price',['invented'])).reply('Цена?', {})
    assert result['course_ids'] == []


def test_catalog_covers_user_directions_and_levels():
    directions = {c['direction'] for c in CATALOG['courses']}
    assert directions >= {'Тестирование ПО','Аналитика данных','Системная аналитика',
                          'Продуктовая аналитика','Бизнес-аналитика','Управление проектами',
                          'Управление продуктом','Дизайн'}
    assert any(c['level']=='Продвинутый' for c in CATALOG['courses'])
    assert all('source' not in c for c in CATALOG['courses'])


def test_real_provider_accepts_route_schema_without_network():
    from langchain_gigachat import GigaChat
    model = GigaChat(credentials='dummy-test-key', base_url='https://api.giga.chat/v1')
    assert model.with_structured_output(Route) is not None


def test_gigachat_trust_context_preserves_verification(monkeypatch):
    import ssl
    monkeypatch.setenv('GIGACHAT_CREDENTIALS','dummy-test-key')
    monkeypatch.delenv('GIGACHAT_CA_BUNDLE',raising=False)
    model = Advisor(CATALOG).llm()
    assert model.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert model.ssl_context.check_hostname is True


def test_error_categories_do_not_leak_secrets():
    from advisor.engine import failure_reason
    assert failure_reason(RuntimeError('SECRET_VALUE')) == 'RuntimeError'


def test_new_endpoint_404_retries_legacy_once(monkeypatch):
    from gigachat.exceptions import ResponseError
    advisor = Advisor(CATALOG)
    class Broken:
        def with_structured_output(self, schema):
            raise ResponseError('https://api.giga.chat/v1/chat/completions',404,b'',{})
    calls=[]
    def model():
        calls.append(1)
        return Broken() if len(calls)==1 else FakeModel('price',['qa-plus'])
    monkeypatch.setattr(advisor,'llm',model)
    result=advisor.reply('Цена?',{})
    assert str(next(c for c in CATALOG['courses'] if c['id']=='qa-plus')['price_rub']) in result['history'][-1]['content']
    assert advisor._compat_base_url=='https://gigachat.devices.sberbank.ru/api/v1'
    assert len(calls)==2



def test_demo_catalog_has_full_schedule_and_bounded_prices():
    from datetime import date
    for c in CATALOG['courses']:
        lower,upper=(12000,45000) if c['level']=='Продвинутый' else (4000,15000)
        assert lower <= c['price_rub'] <= upper
        assert date.fromisoformat(c['start_date']) >= date(2026,12,1)
        assert c['duration'] and c['weekly_load']
        assert 'не подтвержден' not in c['duration'].lower()


def test_generated_reply_does_not_get_an_automatic_question():
    model=FakeModel('general',answer='Обучение проходит онлайн.')
    reply=Advisor(CATALOG,model).reply('Как проходит обучение?',{})['history'][-1]['content']
    assert reply=='Обучение проходит онлайн.'


def test_catalog_display_and_no_download_component():
    from app import build_app, catalog_markdown
    cards=catalog_markdown()
    assert 'http' not in cards and '4000 ₽' in cards
    assert '01 декабря 2026 года' in cards
    assert 'Тестовый проект. Запись сохраняется только в этом приложении.'==CATALOG['notice']
    config=build_app().get_config_file()
    assert all(c['type']!='file' for c in config['components'])
