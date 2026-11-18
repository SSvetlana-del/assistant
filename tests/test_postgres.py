"""Integration tests run against a real disposable PostgreSQL, not the user's DB.

TEST_POSTGRES_URL=... python -m pytest -q
Never point TEST_POSTGRES_URL at Supabase or production.
"""
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
import pytest
from advisor.storage import PostgresStore, create_store
from test_advisor import payload


@pytest.fixture
def pg():
    url = os.getenv('TEST_POSTGRES_URL')
    if not url:
        pytest.skip('Set TEST_POSTGRES_URL to a disposable PostgreSQL instance')
    return PostgresStore(url)


def test_durable_history_and_isolation(pg):
    sid = secrets.token_hex(16)
    pg.save(sid, {'history':[{'role':'user','content':'Хочу UX'}], 'course_ids':['ux']})
    assert pg.load(sid)['course_ids'] == ['ux']
    assert pg.load(secrets.token_hex(16))['history'] == []
    second = PostgresStore(os.environ['TEST_POSTGRES_URL'])
    assert second.load(sid)['history'][0]['content'] == 'Хочу UX'


def test_concurrent_confirmation_and_deduplication(pg):
    sid = secrets.token_hex(16)
    token = pg.draft(sid, payload())
    def submit():
        try:
            return pg.confirm(sid, token)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:submit(), range(2)))
    successful = [r for r in results if r is not None]
    assert len(successful) == 1 and successful[0][1]
    record, created = pg.confirm(sid, pg.draft(sid, payload()))
    assert not created and record == successful[0][0]


def test_wrong_session_and_replaced_draft(pg):
    sid = secrets.token_hex(16)
    old = pg.draft(sid, payload())
    with pytest.raises(ValueError):
        pg.confirm('other', old)
    new = pg.draft(sid, payload('design'))
    with pytest.raises(ValueError):
        pg.confirm(sid, old)
    assert pg.confirm(sid, new)[0]['course_id'] == 'design'


def test_empty_database_url_on_render_fails_instead_of_losing_data(monkeypatch,tmp_path):
    monkeypatch.setenv('RENDER','true')
    monkeypatch.delenv('DATABASE_URL',raising=False)
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        create_store(tmp_path / 'should-not-exist.sqlite3')
    assert not (tmp_path / 'should-not-exist.sqlite3').exists()


def test_rls_enabled_and_schema_not_public(pg):
    with pg.connect() as db:
        rows=db.execute("SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='it_advisor' AND c.relkind='r'").fetchall()
    assert len(rows)==3 and all(r['relrowsecurity'] for r in rows)


def test_conversational_booking_is_persistent_and_confirmed(pg):
    from advisor.booking import ChatService
    from test_booking import AdvisorStub
    sid=secrets.token_hex(16)
    service=ChatService(AdvisorStub(),pg)
    service.turn(sid,'Хочу записаться на SQL')
    service.turn(sid,'1')
    preview=service.turn(sid,'Анна')
    assert preview['booking']['stage']=='confirm'
    with pg.connect() as db:
        assert db.execute('SELECT count(*) AS n FROM enrollments WHERE session_id=%s',(sid,)).fetchone()['n']==0
    reopened=ChatService(AdvisorStub(),PostgresStore(os.environ['TEST_POSTGRES_URL']))
    result=reopened.turn(sid,'Подтверждаю')
    assert result['last_receipt']['name']=='Анна'
    assert result['last_receipt']['start_date']=='2026-12-01'
    assert 'preferred_load' not in result['last_receipt']
    other=secrets.token_hex(16)
    service.turn(other,'Хочу записаться на SQL');service.turn(other,'1');service.turn(other,'Анна')
    service.turn(other,'Отмена')
    with pg.connect() as db:
        assert db.execute('SELECT count(*) AS n FROM drafts WHERE session_id=%s',(other,)).fetchone()['n']==0
