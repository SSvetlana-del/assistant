import pytest
from advisor.engine import Advisor
from advisor.booking import ChatService
from advisor.storage import Store
from advisor.replies import clean_support_reply
from test_advisor import CATALOG, FakeModel


@pytest.mark.parametrize('text',['нет','Нет.','нет, спасибо','вопросов больше нет','нет вопросов','спасибо, пока','всё понятно'])
def test_no_more_questions_after_manager_confirmation(text):
    model=FakeModel('general',answer='Это не должно генерироваться')
    saved={'history':[{'role':'assistant','content':'Заявка сохранена. Пока ждёте, есть ещё вопросы об обучении?'}],
           'course_ids':['qa'],'last_receipt':{'status':'pending_manager'}}
    state=Advisor(CATALOG,model).reply(text,saved)
    answer=state['history'][-1]['content']
    assert state['route']=='closing' and '?' not in answer
    assert 'Ждём связи от нашего менеджера!' in answer
    assert 'обращайтесь' in answer and not model.calls


def test_closing_without_application_does_not_claim_a_manager_will_contact():
    state=Advisor(CATALOG,FakeModel()).reply('Вопросов больше нет',{})
    answer=state['history'][-1]['content']
    assert '?' not in answer and 'менеджер' not in answer


@pytest.mark.parametrize('text',['а что в программе?','Расскажите о программе','Что изучим на курсе?', 'Что входит в программу?'])
def test_program_followup_retains_chosen_course_without_profile_questions(text):
    # Even a model inclined to restart selection cannot override a program query.
    advisor=Advisor(CATALOG,FakeModel('selection',['qa','qa-plus']))
    saved={'history':[{'role':'user','content':'За 14 000'},
                      {'role':'assistant','content':'Базовый курс — 14000 ₽. Хотите записаться?'}],
           'course_ids':['qa']}
    state=advisor.reply(text,saved)
    answer=state['history'][-1]['content']
    assert state['course_ids']==['qa'] and state['route']=='general'
    assert 'Ручное тестирование API' in answer
    assert answer.endswith('Хотите записаться или рассмотреть другие курсы?')
    assert 'Какой у вас уровень' not in answer and 'Сколько времени' not in answer
    assert not advisor.model.calls


def test_selected_course_to_program_to_booking_has_no_repeat_selection(tmp_path):
    advisor=Advisor(CATALOG,FakeModel('price',['qa']))
    service=ChatService(advisor,Store(tmp_path/'conversation.sqlite3'))
    service.turn('one','За 14 000')
    program=service.turn('one','а что в программе?')
    assert 'Что изучите' in program['history'][-1]['content']
    state=service.turn('one','Да')
    assert state['booking']['stage']=='date' and state['booking']['course_id']=='qa'
    assert 'уровень' not in state['history'][-1]['content']


def test_closing_does_not_delete_application_and_allows_later_questions(tmp_path):
    service=ChatService(Advisor(CATALOG,FakeModel()),Store(tmp_path/'closed.sqlite3'))
    service.turn('one','Хочу записаться на SQL');service.turn('one','1')
    service.turn('one','Анна');service.turn('one','anna@example.com')
    record=service.turn('one','Подтверждаю')['last_receipt']
    state=service.turn('one','нет')
    assert '?' not in state['history'][-1]['content']
    assert state['last_receipt']==record and not state['booking']
    with service.store.connect() as db:
        assert db.execute('SELECT count(*) FROM enrollments').fetchone()[0]==1
    state=service.turn('one','Что входит в программу SQL?')
    assert 'Что изучите' in state['history'][-1]['content']


def test_plain_no_is_not_unconditionally_a_farewell():
    saved={'history':[{'role':'assistant','content':'Есть ли у вас опыт в дизайне?'}]}
    # "No experience" answers a profile question, not "any more questions?".
    state=Advisor(CATALOG,FakeModel('general',answer='Можно начать с базового курса.')).reply('нет',saved)
    assert state['route']!='closing'


def test_old_closing_message_has_no_forced_question_in_display():
    text='Понял, вопросов больше нет. Ждём связи от нашего менеджера!\n\nЕсли понадобится помощь, обращайтесь. Хорошего вам обучения!\n\nЧто ещё хотите узнать об обучении?'
    result=clean_support_reply(text)
    assert '?' not in result and result.endswith('Хорошего вам обучения!')



def test_ready_to_enroll_after_no_questions_is_an_action_not_a_farewell():
    state=Advisor(CATALOG,FakeModel()).reply('Вопросов нет, хочу записаться на SQL',{})
    assert state['route']=='enroll' and state['course_ids']==['sql']
