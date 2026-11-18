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
            'duration':'50 часов','format':'Онлайн','preferred_load':'4–5 часов в неделю',
            'scope':'Учебная запись','source':'https://stepik.org'}


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
    assert '5 900 ₽' in answer and '245575' in answer
    assert len(model.calls) == 1


def test_unknown_price_is_not_zero():
    result = Advisor(CATALOG, FakeModel('price', ['design'])).reply('Цена?', {})
    assert 'цена не подтверждена' in result['history'][-1]['content']
    assert 'бесплатно' not in result['history'][-1]['content']


@pytest.mark.parametrize('intent', ['selection','general'])
def test_generation_receives_history_and_catalog(intent):
    model = FakeModel(intent, ['design'])
    previous = {'history':[{'role':'user','content':'Я дизайнер, опыт 3 года'},
                           {'role':'assistant','content':'Какая цель?'}], 'course_ids':['design']}
    result = Advisor(CATALOG, model).reply('Хочу развиваться', previous)
    assert len(result['history']) == 4
    assert any('опыт 3 года' in m.content for m in model.calls[-1])
    assert 'UX-исследования' in model.calls[-1][0].content


def test_follow_up_price_retains_course():
    result = Advisor(CATALOG, FakeModel('price')).reply('А цена?', {'history':[], 'course_ids':['qa-plus']})
    assert result['course_ids'] == ['qa-plus']
    assert '5 900' in result['history'][-1]['content']


def test_enrollment_intent_cannot_write_database():
    model = FakeModel('enroll',['design'])
    result = Advisor(CATALOG, model).reply('Запиши меня', {})
    assert 'подтвердите' in result['history'][-1]['content']
    assert len(model.calls) == 1


def test_provider_failure_is_safe():
    class Broken(FakeModel):
        def with_structured_output(self, schema):
            raise RuntimeError('SECRET_TOKEN_should_not_leak')
    result = Advisor(CATALOG, Broken()).reply('Привет', {})
    assert 'недоступен' in result['history'][-1]['content']
    assert 'SECRET_TOKEN' not in result['history'][-1]['content']


def test_unknown_course_id_is_filtered():
    result = Advisor(CATALOG, FakeModel('price',['invented'])).reply('Цена?', {})
    assert result['course_ids'] == []


def test_catalog_covers_user_directions_and_levels():
    directions = {c['direction'] for c in CATALOG['courses']}
    assert directions >= {'Тестирование ПО','Аналитика данных','Системная аналитика',
                          'Продуктовая аналитика','Бизнес-аналитика','Управление проектами',
                          'Управление продуктом','Дизайн'}
    assert any(c['level']=='С опытом' for c in CATALOG['courses'])
    assert all(c['source'].startswith('https://') for c in CATALOG['courses'])


def test_real_provider_accepts_route_schema_without_network():
    from langchain_gigachat import GigaChat
    model = GigaChat(credentials='dummy-test-key', base_url='https://api.giga.chat/v1')
    assert model.with_structured_output(Route) is not None
