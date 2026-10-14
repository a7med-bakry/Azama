import hashlib
import json
import threading
from types import SimpleNamespace

import pytest
import requests
from cryptography.fernet import Fernet
from instagrapi import exceptions as errors

from backend.instagram import make_client
from test_api import FakeClient, HEADERS, add_account, running, wait_login


def saved_id(user_id='ordinary'):
    return hashlib.sha256(('instagram:' + user_id).encode()).hexdigest()[:32]


def test_saved_session_is_verified_without_credential_login(tmp_path):
    calls = []
    class Client(FakeClient):
        def login(self, *args, **kwargs):
            calls.append(('login', kwargs.get('relogin')))
            return super().login(*args, **kwargs)
        def account_info(self):
            calls.append(('verify', self.user_id))
            return super().account_info()
    with running(tmp_path, factory=Client) as (client, app, settings):
        account_id = add_account(client)
        assert calls == [('login', False)]
        attempt = client.post('/api/logins', headers=HEADERS, json={'username':'ordinary'}).json()
        result = wait_login(client, attempt['id'], ['ready'])
        assert result['account_id'] == account_id
        assert calls == [('login', False), ('verify', 'ordinary')]
        assert len(client.get('/api/accounts', headers=HEADERS).json()) == 1


@pytest.mark.parametrize('password', ['', 'new-password'])
def test_expired_saved_session_requires_password_for_one_fresh_login(tmp_path, password):
    calls = []
    class Expired(FakeClient):
        def account_info(self):
            raise errors.LoginRequired('private-provider-response')
        def login(self, *args, **kwargs):
            calls.append(kwargs.get('relogin'))
            return super().login(*args, **kwargs)
    with running(tmp_path, factory=Expired) as (client, app, settings):
        add_account(client)
        attempt = client.post('/api/logins', headers=HEADERS, json={'username':'ordinary','password':password}).json()
        result = wait_login(client, attempt['id'], ['ready','failed'])
        if password:
            assert result['status'] == 'ready'
            assert calls == [False, True]
        else:
            assert result['failure_code'] == 'session_expired'
            assert calls == [False]


@pytest.mark.parametrize('failure, code', [
    (errors.PleaseWaitFewMinutes, 'rate_limited'),
    (errors.ClientConnectionError, 'connection'),
    (errors.ClientRequestTimeout, 'connection'),
])
def test_session_network_failures_do_not_trigger_password_login(tmp_path, failure, code):
    calls = []
    class Unavailable(FakeClient):
        def login(self, *args, **kwargs):
            calls.append(True)
            return super().login(*args, **kwargs)
        def account_info(self):
            raise failure('private-provider-response')
    with running(tmp_path, factory=Unavailable) as (client, app, settings):
        account_id = add_account(client)
        before = app.state.store.get('account', account_id)['session']
        attempt = client.post('/api/logins', headers=HEADERS, json={'username':'ordinary','password':'secret-password'}).json()
        result = wait_login(client, attempt['id'], ['failed'])
        assert result['failure_code'] == code
        assert calls == [True]
        assert app.state.store.get('account', account_id)['session'] == before


def test_wrong_saved_identity_does_not_replace_account(tmp_path):
    class Wrong(FakeClient):
        def account_info(self):
            return SimpleNamespace(pk='someone-else', username='someone-else')
    with running(tmp_path, factory=Wrong) as (client, app, settings):
        account_id = add_account(client)
        before = app.state.store.get('account', account_id)
        attempt = client.post('/api/logins', headers=HEADERS, json={'username':'ordinary','password':'secret-password'}).json()
        assert wait_login(client, attempt['id'], ['failed'])['failure_code'] == 'session_identity'
        assert app.state.store.get('account', account_id) == before


def test_session_import_uses_real_authenticated_identity_and_encrypts(tmp_path, monkeypatch, caplog):
    instagram = make_client()
    instagram.request_timeout = 0
    sent = []
    def get(url, **kwargs):
        sent.append(url)
        assert url.endswith('/accounts/current_user/?edit=true')
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response.request = requests.Request('GET', url).prepare()
        response._content = json.dumps({'status':'ok', 'user':{
            'pk':'123456789', 'username':'verified_account', 'full_name':'Synthetic account',
            'is_private':False, 'is_verified':False, 'is_business':False,
            'profile_pic_url':'https://synthetic.test/avatar.jpg'}}).encode()
        return response
    monkeypatch.setattr(instagram.private, 'get', get)
    monkeypatch.setattr(instagram.private, 'post', lambda *a, **k: pytest.fail('Import must not send credentials'))
    payload = {'settings':{
        'cookies':{'sessionid':'synthetic-private-session','ds_user_id':'123456789'},
        'uuids':{'phone_id':'synthetic-phone'}, 'password':'secret-password',
        'session_retry_total':99, 'request_timeout':999}}
    with running(tmp_path, factory=lambda: instagram) as (client, app, settings):
        assert client.post('/api/sessions', json=payload).status_code == 401
        attempt = client.post('/api/sessions', headers=HEADERS, json=payload).json()
        result = wait_login(client, attempt['id'], ['ready'])
        assert len(sent) == 1
        assert result['account_id'] == saved_id('123456789')
        accounts = client.get('/api/accounts', headers=HEADERS).json()
        assert accounts[0]['username'] == 'verified_account'
        assert 'session' not in accounts[0]
        stored = app.state.store.get('account', result['account_id'])
        decoded = json.loads(Fernet(settings.encryption_key.encode()).decrypt(stored['session'].encode()))
        assert decoded['cookies']['sessionid'] == 'synthetic-private-session'
        assert decoded['uuids']['phone_id'] == 'synthetic-phone'
        assert decoded['request_timeout'] == 0
        assert instagram.session_retry_total == 0
        combined = json.dumps(accounts) + json.dumps(result) + caplog.text + (tmp_path/'store.sqlite').read_bytes().decode(errors='ignore')
        assert 'synthetic-private-session' not in combined
        assert 'secret-password' not in combined


def test_expired_import_does_not_fall_back_to_password(tmp_path):
    class Expired(FakeClient):
        def account_info(self):
            raise errors.LoginRequired()
        def login(self, *a, **k):
            pytest.fail('No automatic credential login on import')
    with running(tmp_path, factory=Expired) as (client, app, settings):
        attempt = client.post('/api/sessions', headers=HEADERS, json={'settings':{'cookies':{'sessionid':'synthetic'}}}).json()
        assert wait_login(client, attempt['id'], ['failed'])['failure_code'] == 'session_expired'
        assert client.get('/api/accounts', headers=HEADERS).json() == []


@pytest.mark.parametrize('payload, expected', [
    ({}, 'تعذر قراءة بيانات السيشن'),
    ({'settings':[]}, 'تعذر قراءة بيانات السيشن'),
    ({'settings':{}}, 'لا يحتوي على بيانات جلسة'),
    ({'settings':{'cookies':[]}}, 'صيغة بيانات السيشن غير مدعومة'),
    ({'settings':{'cookies':{'sessionid':123}}}, 'لا يحتوي على بيانات جلسة'),
    ({'settings':{'cookies':{'sessionid':'synthetic'}, 'mid':'x'*13000}}, 'أكبر من الحد المسموح'),
])
def test_invalid_import_is_redacted_and_never_reaches_provider(tmp_path, payload, expected):
    def unused():
        pytest.fail('Invalid session must not create client')
    with running(tmp_path, factory=unused) as (client, app, settings):
        response = client.post('/api/sessions', headers=HEADERS, json=payload)
        assert response.status_code == 422
        assert expected in response.json()['detail']
        assert 'الرابط' not in response.text
        assert 'الإيميل' not in response.text
        assert 'synthetic' not in response.text


def test_malformed_session_json_has_own_message_without_private_content(tmp_path):
    with running(tmp_path) as (client, app, settings):
        response = client.post('/api/sessions', headers={**HEADERS, 'Content-Type':'application/json'}, content='{"private-session-secret":')
        assert response.status_code == 422
        assert 'تعذر قراءة بيانات السيشن' in response.json()['detail']
        assert 'private-session-secret' not in response.text
        assert 'الرابط' not in response.text


def test_header_only_session_is_accepted_without_username_or_password(tmp_path):
    class HeaderOnly(FakeClient):
        def set_settings(self, settings):
            self.settings = settings
            self.user_id = settings['authorization_data']['ds_user_id']
        def login(self, *args, **kwargs):
            pytest.fail('Session import must never require credential login')
    with running(tmp_path, factory=HeaderOnly) as (client, app, settings):
        payload = {'settings':{'authorization_data':{'ds_user_id':'ordinary','sessionid':'synthetic-private-session'}}}
        attempt = client.post('/api/sessions', headers=HEADERS, json=payload)
        assert attempt.status_code == 202
        result = wait_login(client, attempt.json()['id'], ['ready'])
        assert result['account_id'] == saved_id()
        assert 'synthetic-private-session' not in attempt.text + json.dumps(result)


def test_cancelled_and_duplicate_import_cannot_save(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Paused(FakeClient):
        def account_info(self):
            entered.set()
            assert release.wait(3)
            return super().account_info()
    payload = {'settings':{'cookies':{'sessionid':'synthetic','ds_user_id':'ordinary'}}}
    with running(tmp_path, factory=Paused) as (client, app, settings):
        try:
            attempt = client.post('/api/sessions', headers=HEADERS, json=payload).json()
            assert entered.wait(2)
            assert client.post('/api/sessions', headers=HEADERS, json=payload).status_code == 409
            assert client.delete('/api/logins/' + attempt['id'], headers=HEADERS).status_code == 200
        finally:
            release.set()
        assert wait_login(client, attempt['id'], ['expired'])['status'] == 'expired'
        assert client.get('/api/accounts', headers=HEADERS).json() == []


def test_missing_password_for_new_account_is_rejected(tmp_path):
    with running(tmp_path) as (client, app, settings):
        assert client.post('/api/logins', headers=HEADERS, json={'username':'new_account'}).status_code == 422
