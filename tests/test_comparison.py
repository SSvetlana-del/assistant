"""Comparison is a distinct graph route; exploration is not a recommendation."""
import json
from pathlib import Path
import pytest
from advisor.engine import Advisor
from advisor.guidance import mentioned_courses
from advisor.booking import ChatService
from advisor.storage import Store
from test_advisor import FakeModel

CATALOG=json.loads((Path(__file__).parents[1]/'data/courses.json').read_text())


def make():return Advisor(CATALOG,FakeModel('general'))


def content(state):return state['history'][-1]['content']


def test_exact_reported_conversation(tmp_path):
    advisor=make();service=ChatService(advisor,Store(tmp_path/'compare.sqlite3'))
    first=service.turn('one','Хочу сравнить программы')
    assert 'В каком направлении сравнить программы' in content(first)
    second=service.turn('one','по дизайну')
    assert second['course_ids']==['design','design-pro','ux']
    assert '| Критерий |' in content(second)
    assert 'Уточните, программу какого курса' not in content(second)
    assert 'Практический проект' in content(second) and 'Входные знания' in content(second)
    assert 'Это не базовое обучение созданию интерфейсов' in content(second)
    last=service.turn('one','хочу сравнить программы, чтобы понять какая подходит лучше')
    assert '| Критерий |' in content(last) and not last['booking']
    assert not advisor.model.calls


@pytest.mark.parametrize('text',['Хочу сравнить программы по дизайну',
 'Чем отличаются курсы по дизайну?', 'В чём разница между программами по дизайну?',
 'Сравни стоимость и содержание курсов по дизайну'])
def test_comparison_precedes_program_keywords(text):
    state=make().reply(text,{})
    assert state['route']=='comparison'
    assert state['course_ids']==['design','design-pro','ux']
    assert 'Стоимость курса' in content(state) and 'Длительность и нагрузка' in content(state)


def test_explicit_pair_in_same_direction_is_not_collapsed():
    advisor=make()
    state=advisor.reply('Сравни Дизайнер интерфейсов и UX-исследования',{})
    assert state['course_ids']==['design','ux']
    assert 'Продуктовый подход для дизайнеров' not in content(state)
    ids=mentioned_courses('Сравни Системный аналитик и Мидл системный аналитик',advisor.courses)
    assert ids==['system','system-middle']


def test_title_plus_alias_both_survive():
    state=make().reply('Сравни Дизайнер интерфейсов и UX',{})
    assert state['course_ids']==['design','ux']


def test_base_title_inside_advanced_title_does_not_create_a_second_course():
    advisor=make()
    assert mentioned_courses('Что входит в курс Мидл системный аналитик?',advisor.courses)==['system-middle']


def test_single_course_program_still_works():
    state=make().reply('Что входит в курс UX-исследования?',{})
    assert state['route']=='general' and 'Что изучите' in content(state)
    assert '| Критерий |' not in content(state)


def test_comparison_lists_levels_even_for_beginner_without_recommending_ux():
    previous={'history':[{'role':'user','content':'Я начинающий дизайнер'}],'course_ids':['design']}
    state=make().reply('Сравни программы по дизайну',previous)
    assert 'Продвинутый' in content(state) and state['course_ids']==['design','design-pro','ux']
    assert 'Что хотите развить' in content(state)
    assert 'подойдут следующие программы' not in content(state)


def test_advanced_design_needs_goal_before_recommending_specializations():
    state=make().reply('Подберите курс по дизайну, опыт 3 года',{})
    assert 'Что хотите развить' in content(state)
    assert 'подойдут следующие программы' not in content(state)


def test_beginner_ui_goal_recommends_interface_course_only():
    state=make().reply('Я начинающий дизайнер, хочу создавать интерфейсы',{})
    assert state['course_ids']==['design']
    assert 'UX-исследования' not in content(state)


def test_beginner_research_goal_is_not_forced_into_interface_course():
    state=make().reply('Я начинающий дизайнер, хочу проводить исследования пользователей',{})
    assert state['course_ids']==[]
    assert 'отдельного курса в каталоге пока нет' in content(state)
    assert 'подойдут следующие программы' not in content(state)


def test_research_goal_and_practical_experience_recommend_ux_only():
    state=make().reply('Я дизайнер с опытом, хочу проводить интервью и исследования пользователей',{})
    assert state['course_ids']==['ux']


def test_goal_followup_after_comparison_uses_known_experience():
    advisor=make()
    state=advisor.reply('Сравни программы по дизайну',{})
    state=advisor.reply('Есть практический опыт',state)
    assert 'Что хотите развить' in content(state)
    state=advisor.reply('Хочу изучать пользователей',state)
    assert state['course_ids']==['ux']
    assert 'подойдут следующие программы' in content(state)


def test_product_design_goal_does_not_recommend_ux():
    state=make().reply('Я опытный дизайнер, хочу освоить продуктовый подход и метрики',{})
    assert state['course_ids']==['design-pro']
    assert 'UX-исследования' not in content(state)


def test_negated_research_interest_does_not_recommend_ux():
    state=make().reply('Я опытный дизайнер, не хочу исследования, интересуют макеты в Figma',{})
    assert state['course_ids']==[]  # No advanced Figma-only course in the catalog.


def test_comparing_beginner_and_advanced_titles_is_not_a_level_declaration():
    advisor=make()
    state=advisor.reply('Сравни Системный аналитик и Мидл системный аналитик',{})
    assert state['course_ids']==['system','system-middle']
    assert 'Вы только начинаете' in content(state)



def test_best_fit_question_is_selection_not_program_description():
    previous={'history':[{'role':'user','content':'по дизайну'}],'course_ids':['design','design-pro','ux']}
    state=make().reply('Какая из этих программ лучше подойдёт мне?',previous)
    assert state['route']=='selection' and 'Какой у вас уровень' in content(state)
    assert 'Уточните, программу какого курса' not in content(state)


def test_reported_legacy_history_can_continue_without_reset():
    previous={'history':[{'role':'user','content':'Хочу сравнить программы'},
                         {'role':'assistant','content':'Уточните, программу какого курса показать?'},
                         {'role':'user','content':'по дизайну'},
                         {'role':'assistant','content':'Какой у вас уровень?'}],
              'course_ids':['design','design-pro','ux']}
    state=make().reply('хочу сравнить программы, чтобы понять какая подходит лучше',previous)
    assert state['route']=='comparison' and '| Критерий |' in content(state)
