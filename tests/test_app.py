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
        assert args[3] == 100
        return ['https://example.org/good', 'https://example.org/copy', 'https://example.org/low', 'https://example.org/broken']
    async def fetch(_, url):
        if url.endswith('broken'):
            raise TimeoutError()
        return jpeg_fixture('blue' if url.endswith('low') else 'red')
    scores = iter([9, 3])
    class FakeAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)
        async def create(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"score": %d, "reason": "Test judgment"}' % next(scores)))])
        async def close(self):
            pass
    monkeypatch.setattr(m, 'search_urls', search)
    monkeypatch.setattr(m, 'fetch_image', fetch)
    monkeypatch.setattr(m, 'AsyncOpenAI', FakeAI)
    job_id = 'testjob'
    m.jobs[job_id] = {'status':'running', 'logs':[], 'images':[], 'processed':0, 'total':0, 'errors':0, 'zip_url':None}
    asyncio.run(m.workflow(job_id, m.SearchInput(query='history'), {'openai_key':'test', 'provider':'duckduckgo'}))
    job = m.jobs[job_id]
    assert job['status'] == 'completed'
    assert job['processed'] == 4 and job['errors'] == 1
    assert len(job['images']) == 1
    assert job['duplicates'] == 1
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


def jpeg_fixture(color):
    raw = io.BytesIO()
    Image.new('RGB', (80, 60), color).save(raw, 'JPEG')
    return raw.getvalue()


def test_exact_and_resized_visual_duplicates():
    from PIL import ImageDraw
    image = Image.new('RGB', (320, 240), '#213a56')
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 40, 180, 180), fill='#ddddaa')
    draw.ellipse((120, 50, 280, 220), fill='#32aa88')
    def encode(im, quality):
        raw = io.BytesIO()
        im.save(raw, 'JPEG', quality=quality)
        return raw.getvalue()
    original = encode(image, 95)
    detector = m.ImageDeduplicator()
    assert not detector.is_duplicate(original)
    assert detector.is_duplicate(original)
    assert detector.is_duplicate(encode(image.resize((160, 120)), 75))
    assert not detector.is_duplicate(jpeg_fixture('red'))
    assert not detector.is_duplicate(jpeg_fixture('blue'))


def test_default_count_and_gallery_form(client):
    assert m.SearchInput(query='park').maximum == 100
    page = client.get('/').text
    assert 'id="count-value">100' in page
    assert 'max="200" value="100"' in page


def test_storyboard_sections_dedup_partial_failure_and_zip(client, monkeypatch):
    searches = []
    async def search(http, settings, query, maximum):
        searches.append(query)
        assert maximum == 10
        if query.endswith('reports'):
            raise TimeoutError()
        if query.endswith('onset'):
            return ['https://example.org/red']
        return ['https://example.org/red', 'https://example.org/red-copy',
                'https://example.org/blue', 'https://example.org/green']
    async def fetch(_, url):
        return jpeg_fixture('red' if 'red' in url else url.rsplit('/', 1)[1])
    decisions = iter([True, False, True])
    prompts = []
    class FakeAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)
        async def create(self, **kwargs):
            prompts.append(kwargs['messages'])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=
                m.json.dumps({'score':10, 'reason':'scene judgment', 'matches_scene':next(decisions)})))])
        async def close(self):
            pass
    monkeypatch.setattr(m, 'search_urls', search)
    monkeypatch.setattr(m, 'fetch_image', fetch)
    monkeypatch.setattr(m, 'AsyncOpenAI', FakeAI)
    job_id = 'storyboard'
    m.jobs[job_id] = {'status':'running','logs':[],'images':[], 'processed':0,
                      'total':0,'errors':0,'zip_url':None}
    body = m.SearchInput(query='hurricane', location='Florida', event_date='2024',
                         scenes=['onset','aftermath','reports'], maximum=10)
    asyncio.run(m.workflow(job_id, body, {'openai_key':'test','provider':'duckduckgo'}))
    job = m.jobs[job_id]
    assert searches == ['hurricane Florida 2024 onset', 'hurricane Florida 2024 aftermath',
                        'hurricane Florida 2024 reports']
    assert job['status'] == 'completed' and job['errors'] == 1
    assert job['duplicates'] == 2
    assert len(prompts) == 3  # URL/content duplicates make no AI call.
    assert len(job['images']) == 2  # A score of 10 cannot override a scene mismatch.
    assert [i['section'] for i in job['images']] == ['onset','aftermath']
    assert job['sections'][2]['status'] == 'failed'
    assert 'matches_scene' in prompts[0][0]['content']
    with zipfile.ZipFile(io.BytesIO(client.get(job['zip_url']).content)) as archive:
        assert '01_onset/image_001.jpg' in archive.namelist()
        assert '02_aftermath/image_004.jpg' in archive.namelist()
        assert 'sections.json' in archive.namelist()
    assert client.get(job['images'][0]['url']).status_code == 200


def test_scene_input_limits_and_form(client):
    assert m.SearchInput(query='storm', scenes=[' onset ', '', 'onset']).scenes == ['onset']
    with pytest.raises(ValueError):
        m.SearchInput(query='storm', scenes=['x' * 501])
    with pytest.raises(ValueError):
        m.SearchInput(query='storm', scenes=[str(i) for i in range(11)], maximum=100)
    page = client.get('/').text
    for field in ['scenes', 'location', 'event-date', 'candidate-budget']:
        assert f'id="{field}"' in page
