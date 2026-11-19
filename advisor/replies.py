"""Presentation cleanup for provider replies, including historical assistant text."""
import re

LABEL=re.compile(r'\*{0,2}(?:(?:дополнительный|уточняющий)\s+вопрос|вопрос\s+пользователю)\s*\*{0,2}\s*[:—-]\s*\*{0,2}\s*',re.I)
TRAILING_QUESTIONS=re.compile(r'(?P<first>(?:^|(?<=[.!?]))\s*[^.!?\n]*\?)(?:\s+[^.!?\n]*\?)+\s*$',re.S)


def clean_support_reply(text):
    result=LABEL.sub('',text).strip()
    # Keep one adjacent follow-up at the end; preserve factual sentences and lists.
    match=TRAILING_QUESTIONS.search(result)
    if match:
        result=result[:match.start()]+match.group('first').rstrip()
    if re.search(r'вопросов (?:больше )?нет',result,re.I):
        result=re.sub(r'\s*(?:Что ещ[её] хотите (?:узнать|уточнить) об обучении|Есть ещ[её] вопросы(?: об обучении)?)\?\s*$','',result,flags=re.I)
    return result.strip()
