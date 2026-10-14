import json
import time
import threading
from types import SimpleNamespace
from contextlib import contextmanager
import pytest
import requests
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from backend.config import Settings
from backend.main import create_app
from backend.instagram import TwoFactorRequired, make_client
from backend.instagram import VerificationRequired
from instagrapi import exceptions as instagram_errors
from instagrapi.mixins.challenge import ChallengeChoice
from backend.storage import SQLiteStore, SupabaseStore, StorageError

TOKEN = 'synthetic-test-administrator-token-123456789'
HEADERS = {'Authorization': 'Bearer ' + TOKEN}


class FakeClient:
    def __init__(self):
        self.settings = {'cookies': {'sessionid': 'synthetic-session'}}
        self.password = None
        self.user_id = None

    def login(self, username, password, relogin=False, verification_code=''):
        self.password = password
        assert relogin or verification_code
        if username == 'bad':
            raise ValueError('secret-password synthetic-private-provider-response')
        if username == 'twofactor' and not verification_code:
            raise TwoFactorRequired()
        if username == 'twofactor':
            assert verification_code == '123456'
        if username == 'email':
            assert self.challenge_code_handler(username, ChallengeChoice.EMAIL) == '123456'
        if username == 'retry_code':
            self.challenge_code_handler(username, ChallengeChoice.EMAIL)
            assert self.challenge_code_handler(username, ChallengeChoice.EMAIL) == '123456'
        self.user_id = username.split('@')[0]
        return True

    def account_info(self):
        return SimpleNamespace(username=self.user_id)

    def get_settings(self):
        return self.settings

    def set_settings(self, settings):
        self.settings = settings

    def media_pk_from_url(self, url):
        return url

    def media_like(self, media_pk):
        return not media_pk.endswith('/FAIL/')

    def media_comment(self, media_pk, text):
        assert text
        return {'id': 'comment-id'}


@contextmanager
def running(tmp_path, factory=FakeClient, worker=False, timeout=5):
    settings = Settings(TOKEN, Fernet.generate_key().decode(), database_path=str(tmp_path/'store.sqlite'), action_delay=0, login_timeout=timeout)
    app = create_app(settings, client_factory=factory, start_worker=worker)
    with TestClient(app) as client:
        yield client, app, settings


def wait_login(client, attempt_id, expected):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        result = client.get('/api/logins/' + attempt_id, headers=HEADERS).json()
        if result['status'] in expected:
            return result
        time.sleep(.01)
    pytest.fail('Login did not reach ' + str(expected))


def add_account(client, username='ordinary'):
    response = client.post('/api/logins', headers=HEADERS, json={'username': username, 'password': 'secret-password'})
    assert response.status_code == 202
    attempt = wait_login(client, response.json()['id'], ['ready'])
    return attempt['account_id']


def job_payload(account_id, **fields):
    return dict(action='like', url='https://www.instagram.com/reel/ABC/', quantity=1, account_ids=[account_id], **fields)


def wait_job(client, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = next(j for j in client.get('/api/jobs', headers=HEADERS).json() if j['id'] == job_id)
        if result['status'] not in ('queued', 'running'):
            return result
        time.sleep(.02)
    pytest.fail('Job did not finish')


def test_auth_validation_and_assets(tmp_path):
    with running(tmp_path) as (client, app, settings):
        assert client.get('/health').status_code == 200
        for path in ['/api/accounts', '/api/jobs']:
            assert client.get(path).status_code == 401
        assert client.post('/api/logins', json={'username':'a','password':'p'}).status_code == 401
        result = client.post('/api/logins', headers=HEADERS, json={'username': 'bad@@example.com', 'password': 'secret-password'})
        assert result.status_code == 422
        assert 'secret-password' not in result.text
        assert client.post('/api/logins', headers=HEADERS, content='x'*17000).status_code == 413
        assert client.get('/').status_code == 200
        assert client.get('/assets/app.js').status_code == 200
        assert client.get('/assets/styles.css').status_code == 200
        assert client.get('/api/accounts', headers=HEADERS).headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('username', ['ordinary', 'twofactor', 'email'])
def test_login_challenge_encryption_and_relogin(tmp_path, username):
    with running(tmp_path) as (client, app, settings):
        response = client.post('/api/logins', headers=HEADERS, json={'username': username, 'password':'secret-password'})
        attempt_id = response.json()['id']
        result = wait_login(client, attempt_id, ['ready','awaiting_code'])
        if result['status'] == 'awaiting_code':
            assert client.post('/api/logins/' + attempt_id + '/code', headers=HEADERS, json={'challenge_id': 'stale', 'code':'123456'}).status_code == 409
            assert client.post('/api/logins/' + attempt_id + '/code', headers=HEADERS, json={'challenge_id': result['challenge_id'], 'code':'123456'}).status_code == 202
            result = wait_login(client, attempt_id, ['ready'])
        accounts = client.get('/api/accounts', headers=HEADERS).json()
        assert len(accounts) == 1 and 'session' not in accounts[0]
        stored = app.state.store.get('account', result['account_id'])
        assert 'synthetic-session' not in json.dumps(stored)
        decoded = json.loads(Fernet(settings.encryption_key.encode()).decrypt(stored['session'].encode()))
        assert decoded['cookies']['sessionid'] == 'synthetic-session'
        assert 'secret-password' not in (tmp_path/'store.sqlite').read_bytes().decode(errors='ignore')
        # For a saved session, login must force an actual authentication attempt.
        if username == 'ordinary':
            add_account(client, username)
            assert len(client.get('/api/accounts', headers=HEADERS).json()) == 1


def test_repeated_challenge_rejects_stale_code(tmp_path):
    with running(tmp_path) as (client, app, settings):
        attempt = client.post('/api/logins', headers=HEADERS, json={'username':'retry_code','password':'p'}).json()
        first = wait_login(client, attempt['id'], ['awaiting_code'])
        assert client.post('/api/logins/' + attempt['id'] + '/code', headers=HEADERS, json={'code':'111111','challenge_id':first['challenge_id']}).status_code == 202
        second = wait_login(client, attempt['id'], ['awaiting_code'])
        assert second['challenge_id'] != first['challenge_id']
        assert client.post('/api/logins/' + attempt['id'] + '/code', headers=HEADERS, json={'code':'123456','challenge_id':first['challenge_id']}).status_code == 409
        assert client.post('/api/logins/' + attempt['id'] + '/code', headers=HEADERS, json={'code':'123456','challenge_id':second['challenge_id']}).status_code == 202
        wait_login(client, attempt['id'], ['ready'])


def test_login_failure_timeout_and_duplicate(tmp_path):
    with running(tmp_path) as (client, app, settings):
        bad = client.post('/api/logins', headers=HEADERS, json={'username':'bad','password':'secret-password'}).json()
        failed = wait_login(client, bad['id'], ['failed'])
        assert 'secret-password' not in json.dumps(failed)
        attempt = client.post('/api/logins', headers=HEADERS, json={'username':'email','password':'p'}).json()
        challenge = wait_login(client, attempt['id'], ['awaiting_code'])
        assert client.post('/api/logins', headers=HEADERS, json={'username':'email','password':'p'}).status_code == 409
        app.state.attempts[attempt['id']].expires = time.monotonic() - 1
        assert client.post('/api/logins/' + attempt['id'] + '/code', headers=HEADERS, json={'code':'123456','challenge_id':challenge['challenge_id']}).status_code == 409
        assert client.get('/api/accounts', headers=HEADERS).json() == []


@pytest.mark.parametrize('error_type, code', [
    (instagram_errors.BadPassword, 'credentials'),
    (instagram_errors.BadCredentials, 'credentials'),
    (instagram_errors.SentryBlock, 'access_denied'),
    (instagram_errors.ClientForbiddenError, 'access_denied'),
    (instagram_errors.PleaseWaitFewMinutes, 'rate_limited'),
    (instagram_errors.FeedbackRequired, 'rate_limited'),
    (instagram_errors.ChallengeSelfieCaptcha, 'verification'),
    (VerificationRequired, 'verification'),
    (instagram_errors.ClientConnectionError, 'connection'),
    (requests.exceptions.RetryError, 'connection'),
    (instagram_errors.ClientJSONDecodeError, 'instagram_response'),
    (KeyError, 'instagram_response'),
    (RuntimeError, 'unexpected'),
])
def test_login_failure_diagnostics_do_not_leak_provider_details(tmp_path, caplog, error_type, code):
    private_detail = 'secret-password synthetic-private-provider-response 123456'
    class FailingClient(FakeClient):
        def login(self, *args, **kwargs):
            raise error_type(private_detail)
    with running(tmp_path, factory=FailingClient) as (client, app, settings):
        attempt = client.post('/api/logins', headers=HEADERS, json={'username':'ordinary','password':'secret-password'}).json()
        failed = wait_login(client, attempt['id'], ['failed'])
        assert failed['failure_code'] == code
        assert 'code=' + code in caplog.text
        assert 'stage=instagram_login' in caplog.text
        assert 'exception=' + error_type.__name__ in caplog.text
        assert 'attempt=' + attempt['id'] in caplog.text
        for secret in ('secret-password', 'synthetic-private-provider-response', '123456'):
            assert secret not in json.dumps(failed) + caplog.text
        assert client.get('/api/accounts', headers=HEADERS).json() == []
        # Failed attempts release their locks; a new attempt is accepted.
        assert client.post('/api/logins', headers=HEADERS, json={'username':'ordinary','password':'p'}).status_code == 202


def test_session_save_failure_is_not_reported_as_bad_credentials(tmp_path, monkeypatch, caplog):
    with running(tmp_path) as (client, app, settings):
        def unavailable(*args):
            raise StorageError('synthetic-service-key secret-password')
        monkeypatch.setattr(app.state.store, 'put', unavailable)
        attempt = client.post('/api/logins', headers=HEADERS, json={'username':'ordinary','password':'secret-password'}).json()
        failed = wait_login(client, attempt['id'], ['failed'])
        assert failed['failure_code'] == 'storage'
        assert 'Supabase' in failed['message']
        assert 'stage=session_save' in caplog.text
        assert 'synthetic-service-key' not in caplog.text + json.dumps(failed)
        assert 'secret-password' not in caplog.text + json.dumps(failed)


@pytest.mark.parametrize('status, code', [(429, 'rate_limited'), (403, 'access_denied'), (405, 'instagram_response'), (503, 'provider_unavailable'), (200, 'instagram_response')])
def test_real_client_password_key_failure_has_safe_http_diagnostic(tmp_path, monkeypatch, caplog, status, code):
    instagram = make_client()
    response = requests.Response()
    response.status_code = status
    response._content = b'synthetic-private-provider-response secret-password 123456'
    response.url = 'https://synthetic-provider.test/private-url'
    monkeypatch.setattr(instagram, 'pre_login_flow', lambda: True)
    def key_request(url, **kwargs):
        assert url == 'https://i.instagram.com/api/v1/qe/sync/'
        assert 'secret-password' not in kwargs['data']
        return response
    monkeypatch.setattr(instagram.private, 'post', key_request)
    monkeypatch.setattr(instagram.public, 'get', lambda *args, **kwargs: pytest.fail('Obsolete GET key request'))
    with running(tmp_path, factory=lambda: instagram) as (client, app, settings):
        attempt = client.post('/api/logins', headers=HEADERS, json={'username':'ordinary','password':'secret-password'}).json()
        failed = wait_login(client, attempt['id'], ['failed'])
        assert failed['failure_code'] == code
        assert 'http_status=' + str(status) in caplog.text
        for private in ('secret-password', '123456', 'synthetic-private-provider-response', 'private-url'):
            assert private not in json.dumps(failed) + caplog.text


def test_unreadable_saved_session_identifies_encryption_key_failure(tmp_path, caplog):
    with running(tmp_path) as (client, app, settings):
        account_id = add_account(client)
        stored = app.state.store.get('account', account_id)
        stored['session'] = Fernet(Fernet.generate_key()).encrypt(b'{}').decode()
        app.state.store.put('account', stored)
        attempt = client.post('/api/logins', headers=HEADERS, json={'username':'ordinary','password':'secret-password'}).json()
        failed = wait_login(client, attempt['id'], ['failed'])
        assert failed['failure_code'] == 'session_key'
        assert 'stage=session_restore' in caplog.text
        assert 'secret-password' not in caplog.text + json.dumps(failed)


@pytest.mark.parametrize('url', ['http://www.instagram.com/p/ABC/', 'https://evil.test/p/ABC/', 'https://www.instagram.com.evil.test/p/ABC/', 'https://www.instagram.com:443/p/ABC/', 'https://www.instagram.com/stories/name/123/', 'https://www.instagram.com/p/../ABC/'])
def test_job_url_validation(tmp_path, url):
    with running(tmp_path) as (client, app, settings):
        payload = job_payload('nonexistent'); payload['url'] = url
        assert client.post('/api/jobs', headers=HEADERS, json=payload).status_code == 422


def test_jobs_validation_cancel_and_delete(tmp_path):
    with running(tmp_path) as (client, app, settings):
        account_id = add_account(client)
        for change in [{'quantity':2}, {'account_ids':[account_id,account_id]}, {'action':'view'}, {'action':'comment','comment':''}, {'account_ids':['absent']}]:
            payload = job_payload(account_id); payload.update(change)
            assert client.post('/api/jobs', headers=HEADERS, json=payload).status_code == 422
        payload = job_payload(account_id); payload['url'] += '?igsh=tracking'
        job = client.post('/api/jobs', headers=HEADERS, json=payload).json()
        assert '?' not in job['url']
        assert client.delete('/api/accounts/' + account_id, headers=HEADERS).status_code == 409
        assert client.post('/api/jobs/' + job['id'] + '/cancel', headers=HEADERS).json()['status'] == 'cancelled'
        assert client.delete('/api/accounts/' + account_id, headers=HEADERS).status_code == 200


@pytest.mark.parametrize('action_kind, url, status, completed', [('like','https://www.instagram.com/p/ABC/','completed',1), ('comment','https://www.instagram.com/p/ABC/','completed',1), ('like','https://www.instagram.com/p/FAIL/','finished_with_errors',0)])
def test_worker_counts_acknowledged_actions(tmp_path, action_kind, url, status, completed):
    with running(tmp_path, worker=True) as (client, app, settings):
        account_id = add_account(client)
        payload = job_payload(account_id); payload.update(action=action_kind, url=url, comment='synthetic comment')
        job = client.post('/api/jobs', headers=HEADERS, json=payload).json()
        result = wait_job(client, job['id'])
        assert result['status'] == status and result['completed'] == completed
        assert result['failed'] == 1 - completed


def test_cancellation_during_action_preserves_acknowledged_result(tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = []
    class Slow(FakeClient):
        def media_like(self, media_pk):
            entered.set(); assert release.wait(3); calls.append(media_pk); return True
    with running(tmp_path, factory=Slow, worker=True) as (client, app, settings):
        ids = [add_account(client, 'one'), add_account(client, 'two')]
        payload = job_payload(ids[0]); payload.update(account_ids=ids, quantity=2)
        job = client.post('/api/jobs', headers=HEADERS, json=payload).json()
        assert entered.wait(3)
        client.post('/api/jobs/' + job['id'] + '/cancel', headers=HEADERS)
        release.set()
        result = wait_job(client, job['id'])
        assert result['status'] == 'cancelled' and result['completed'] == 1 and len(calls) == 1


def test_restart_does_not_retry_ambiguous_jobs(tmp_path):
    with running(tmp_path) as (client, app, settings):
        account_id = add_account(client)
        job = client.post('/api/jobs', headers=HEADERS, json=job_payload(account_id)).json()
        job['status'] = 'running'; app.state.store.put('job', job)
    with running(tmp_path, worker=True) as (client, app, settings):
        result = wait_job(client, job['id'])
        assert result['status'] == 'interrupted' and result['completed'] == 0
        assert len(client.get('/api/accounts', headers=HEADERS).json()) == 1


def test_storage_claim_is_atomic(tmp_path):
    store = SQLiteStore(str(tmp_path/'claims.sqlite'))
    job = {'id':'test', 'status':'queued'}; store.put('job', job)
    job['status'] = 'running'
    assert store.claim(job)
    assert not store.claim(job)


def test_supabase_transport_hides_secrets_and_filters_claim(monkeypatch):
    calls = []
    class Response:
        content = b'[]'
        def raise_for_status(self): pass
        def json(self): return [{'payload': {'id':'test'}}]
    def request(method, url, **kwargs):
        calls.append((method,url,kwargs)); return Response()
    monkeypatch.setattr('backend.storage.requests.request', request)
    store = SupabaseStore('https://synthetic.supabase.co', 'synthetic-service-key')
    assert store.get('account','abc') == {'id':'test'}
    assert store.claim({'id':'test','status':'running'})
    assert calls[-1][2]['params']['status'] == 'eq.queued'
    assert calls[-1][2]['headers']['Prefer'] == 'return=representation'
    import requests
    def broken(*args, **kwargs): raise requests.RequestException('synthetic-service-key')
    monkeypatch.setattr('backend.storage.requests.request', broken)
    with pytest.raises(StorageError) as exc:
        store.ping()
    assert 'synthetic-service-key' not in str(exc.value)


def test_real_client_tls_retries_and_no_interactive_password_prompt():
    client = make_client()
    assert client.private.verify and client.public.verify
    assert client.session_retry_total == 0
    assert client.private.adapters['https://'].max_retries.total == 0
    with pytest.raises(RuntimeError): client.change_password_handler('synthetic')


def test_email_and_username_share_one_account(tmp_path):
    with running(tmp_path) as (client, app, settings):
        first = add_account(client, 'ordinary@example.com')
        second = add_account(client, 'ordinary')
        assert first == second
        accounts = client.get('/api/accounts', headers=HEADERS).json()
        assert len(accounts) == 1 and accounts[0]['username'] == 'ordinary'
        assert 'identifier_hashes' not in accounts[0]
