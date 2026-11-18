from fastapi import FastAPI
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.testclient import TestClient
from advisor.web_language import RussianHTMLMiddleware


def client(response):
    app=FastAPI()
    @app.get('/')
    def root():
        return response
    app.add_middleware(RussianHTMLMiddleware)
    return TestClient(app)


def test_html_language_is_russian_before_javascript_runs():
    response=client(HTMLResponse('<html\n lang="en"><body>Привет</body></html>')).get('/')
    assert 'lang="ru"' in response.text and 'lang="en"' not in response.text
    assert response.headers['content-language']=='ru'
    assert int(response.headers['content-length'])==len(response.content)


def test_json_is_not_rewritten():
    response=client(JSONResponse({'lang':'en'})).get('/')
    assert response.json()=={'lang':'en'}
    assert 'content-language' not in response.headers


def test_streaming_chat_events_are_not_rewritten():
    response=client(StreamingResponse(iter(['data: hello\n\n','data: done\n\n']),media_type='text/event-stream')).get('/')
    assert response.text=='data: hello\n\ndata: done\n\n'
    assert 'content-language' not in response.headers
