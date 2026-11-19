import pytest
from advisor.replies import clean_support_reply
from advisor.engine import Advisor
from test_advisor import CATALOG, FakeModel


@pytest.mark.parametrize('raw,expected',[
 ('Есть два курса. Какой вам интересен? Дополнительный вопрос: хотели бы узнать подробности одного из них?',
  'Есть два курса. Какой вам интересен?'),
 ('Обучение онлайн.\n\n**Дополнительный вопрос:** Хотите записаться?',
  'Обучение онлайн.\n\nХотите записаться?'),
 ('Обучение онлайн. Уточняющий вопрос: Какой курс интересует?',
  'Обучение онлайн. Какой курс интересует?'),
 ('Сначала теория, затем практика.\n\nВопрос пользователю: Есть ли у вас опыт?',
  'Сначала теория, затем практика.\n\nЕсть ли у вас опыт?'),
 ('Есть два курса. Какой вам интересен?\n\nХотите узнать подробности?',
  'Есть два курса. Какой вам интересен?'),
 ('Курс стоит 4000 ₽.\n\nХотите записаться или рассмотреть другие курсы?',
  'Курс стоит 4000 ₽.\n\nХотите записаться или рассмотреть другие курсы?'),
 ('Есть ли опыт? Стоимость — 4000 ₽.\n\nКакой курс интересует?',
  'Есть ли опыт? Стоимость — 4000 ₽.\n\nКакой курс интересует?'),
])
def test_reply_cleanup_preserves_facts_and_one_natural_followup(raw,expected):
    assert clean_support_reply(raw)==expected


def test_generation_cleans_observed_provider_text():
    model=FakeModel('general',['qa','qa-plus'],answer='Есть два курса. Какой вам интересен? Дополнительный вопрос: хотели бы узнать подробности одного из них?')
    reply=Advisor(CATALOG,model).reply('Есть курсы по тестированию?',{})
    answer=reply['history'][-1]['content']
    assert answer=='Есть два курса. Какой вам интересен?'
    assert answer.count('?')==1


def test_old_messages_are_cleaned_for_display_without_rewriting_history():
    from app import view
    original={'role':'assistant','content':'Есть два курса. Какой интересен? Дополнительный вопрос: хотите подробности?'}
    user={'role':'user','content':'Что значит «Дополнительный вопрос»?'}
    saved={'history':[user,original]}
    messages,_,_=view(saved)
    assert messages[-1]['content']=='Есть два курса. Какой интересен?'
    assert messages[-2]==user and saved['history'][-1]==original


def test_app_disables_gradio_progress_overlays_on_all_events():
    from app import build_app
    config=build_app().get_config_file()
    assert config['dependencies']
    assert all(d['show_progress']=='hidden' for d in config['dependencies'])
