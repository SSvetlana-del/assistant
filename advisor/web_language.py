"""Declare the site's language in the server-rendered HTML before browser detection."""
import re


class RussianHTMLMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('path') not in ('', '/') or scope.get('method') == 'HEAD':
            return await self.app(scope, receive, send)
        start = None
        chunks = []
        rewrite = False

        async def language_send(message):
            nonlocal start, rewrite
            if message['type'] == 'http.response.start':
                headers = message.get('headers', [])
                content_type = next((v for k,v in headers if k.lower() == b'content-type'), b'')
                rewrite = content_type.lower().startswith(b'text/html')
                if rewrite:
                    start = dict(message)
                    return
            elif message['type'] == 'http.response.body' and rewrite:
                chunks.append(message.get('body', b''))
                if message.get('more_body', False):
                    return
                body = b''.join(chunks)
                def russian_tag(match):
                    tag = re.sub(rb'\s+lang\s*=\s*([\"\']).*?\1', b'', match.group(0), flags=re.I)
                    return tag[:-1] + b' lang="ru">'
                body = re.sub(rb'<html\b[^>]*>', russian_tag, body, count=1, flags=re.I)
                start['headers'] = [(k,v) for k,v in start['headers']
                                    if k.lower() not in (b'content-length', b'content-language')]
                start['headers'] += [(b'content-language', b'ru'), (b'content-length', str(len(body)).encode())]
                await send(start)
                await send({'type':'http.response.body', 'body':body})
                return
            await send(message)

        await self.app(scope, receive, language_send)
