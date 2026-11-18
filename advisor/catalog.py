"""Display formatting for the IT Navigator demo catalog."""
from datetime import date

MONTHS=('января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря')


def start_date_text(value):
    day=date.fromisoformat(value)
    return f'{day.day:02d} {MONTHS[day.month-1]} {day.year} года'


def price_text(value):
    return f'{value} ₽'
