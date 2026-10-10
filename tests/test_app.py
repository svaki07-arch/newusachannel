import asyncio
import io
import zipfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app import main as m


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'DATA', tmp_path)
    monkeypatch.setattr(m, 'SETTINGS', tmp_path / 'settings.json')
    m.jobs.clear()
    with TestClient(m.app) as c:
        yield c


def test_settings_and_missing_key(client):
    assert client.post('/api/jobs', json={'query': 'documents'}).status_code == 400
    response = client.post('/api/settings', json={'openai_key': 'secret-test', 'provider': 'duckduckgo'})
    assert response.json()['has_openai_key']
    assert 'secret-test' not in client.get('/api/settings').text
    client.post('/api/settings', json={'provider': 'duckduckgo'})
    assert client.get('/api/settings').json()['has_openai_key']
    assert client.post('/api/settings', json={}, headers={'origin':'https://evil.example'}).status_code == 403
    assert client.delete('/api/settings').status_code == 200
    assert not client.get('/api/settings').json()['has_openai_key']


def test_private_urls_rejected():
    for url in ['http://127.0.0.1/a.jpg', 'http://169.254.169.254/latest', 'file:///etc/passwd']:
        with pytest.raises(ValueError):
            asyncio.run(m.public_url(url))


def test_image_validation():
    raw = io.BytesIO()
    Image.new('RGB', (20, 20)).save(raw, 'PNG')
    result = m.normalize_image(raw.getvalue())
    assert Image.open(io.BytesIO(result)).format == 'JPEG'
    with pytest.raises(Exception):
        m.normalize_image(b'<html>not an image</html>')


def test_workflow_filter_errors_and_zip(client, monkeypatch):
    async def search(*args):
        assert args[2] == 'park winter'
        return ['https://example.org/good', 'https://example.org/low', 'https://example.org/mismatch', 'https://example.org/broken']
    async def fetch(_, url):
        if url.endswith('broken'):
            raise TimeoutError()
        return b'pixels'
    decisions = iter([(9, True), (3, True), (10, False)])
    class FakeAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)
        async def create(self, **kwargs):
            prompt = kwargs['messages'][0]['content']
            assert 'no people' in prompt and 'winter' in prompt
            assert '"reject_visible_watermarks": true' in prompt
            score, matches = next(decisions)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=m.json.dumps({'score': score, 'reason': 'Test judgment', 'meets_criteria': matches})))])
        async def close(self):
            pass
    monkeypatch.setattr(m, 'search_urls', search)
    monkeypatch.setattr(m, 'fetch_image', fetch)
    monkeypatch.setattr(m, 'AsyncOpenAI', FakeAI)
    job_id = 'testjob'
    m.jobs[job_id] = {'status':'running', 'logs':[], 'images':[], 'processed':0, 'total':0, 'errors':0, 'zip_url':None}
    asyncio.run(m.workflow(job_id, m.SearchInput(query='park', refinement='winter', criteria='no people'), {'openai_key':'test', 'provider':'duckduckgo'}))
    job = m.jobs[job_id]
    assert job['status'] == 'completed'
    assert job['processed'] == 4 and job['errors'] == 1
    assert len(job['images']) == 1
    response = client.get(job['zip_url'])
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {'image_001.jpg', 'manifest.json'}
    assert client.get('/api/jobs/testjob/images/unknown.jpg').status_code == 404


def test_search_pagination(client):
    requests = []
    def handler(request):
        requests.append(request)
        start = int(request.url.params['start'])
        return m.httpx.Response(200, json={'items':[{'link':f'https://example.org/{i}'} for i in range(start, start+10)]})
    async def run():
        async with m.httpx.AsyncClient(transport=m.httpx.MockTransport(handler)) as http:
            return await m.search_urls(http, {'provider':'google','search_key':'test','google_cx':'cx'}, 'history', 20)
    assert len(asyncio.run(run())) == 20
    assert len(requests) == 2


def test_duckduckgo_retries_with_longer_timeout(monkeypatch):
    import ddgs
    from ddgs.exceptions import DDGSException
    attempts = []
    class FakeDDGS:
        def __init__(self, timeout):
            assert timeout == 30
        def images(self, query, max_results):
            attempts.append(query)
            if len(attempts) < 3:
                raise DDGSException('Temporary search failure')
            return [{'image': 'https://example.org/photo.jpg'}]
    async def no_wait(_):
        pass
    monkeypatch.setattr(ddgs, 'DDGS', FakeDDGS)
    monkeypatch.setattr(m.asyncio, 'sleep', no_wait)
    result = asyncio.run(m.search_urls(None, {'provider':'duckduckgo'}, 'history', 10))
    assert len(attempts) == 3
    assert result == ['https://example.org/photo.jpg']
