"""Validate a single learner contact without external verification or messaging."""
import re


def parse_contact(text):
    value=re.sub(r'^(?:мой|моя)?\s*(?:контакт|телефон|тел\.?|почта|email|e-mail)?\s*[:—-]?\s*','',text.strip(),flags=re.I).strip()
    if len(value)>254:return None
    if '@' in value:
        match=re.fullmatch(r"([A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+)@([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+)",value)
        if not match:return None
        local,domain=match.groups()
        if len(local)>64 or local.startswith('.') or local.endswith('.') or '..' in local:return None
        if any(len(label)>63 for label in domain.split('.')):return None
        return {'contact_type':'email','contact_value':local+'@'+domain.lower()}
    if not re.fullmatch(r'\+?[\d\s()\-]+',value):return None
    digits=re.sub(r'\D','',value)
    if len(digits)==11 and digits[0] in '78':digits='7'+digits[1:]
    elif len(digits)==10 and not value.startswith('+'):digits='7'+digits
    elif not value.startswith('+'):return None
    if not 8<=len(digits)<=15 or digits.startswith('0') or len(set(digits))<3:return None
    return {'contact_type':'phone','contact_value':'+'+digits}


def contact_label(record):
    return 'Email' if record.get('contact_type')=='email' else 'Телефон'
