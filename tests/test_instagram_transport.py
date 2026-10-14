"""Exercise real HTTP adapters locally, without credentials or Instagram requests."""
import json
import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests
from Cryptodome.PublicKey import RSA

from backend.instagram import make_client


@pytest.fixture(scope='module')
def error_server():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def respond(self):
            calls.append((self.command, self.path))
            status = int(self.path.split('/')[1])
            body = json.dumps({'status': 'fail', 'message': 'synthetic-provider-error'}).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Retry-After', '1')
            self.end_headers()
            self.wfile.write(body)

        do_GET = respond
        do_POST = respond

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port), calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize('status', [429, 500, 502, 503, 504])
@pytest.mark.parametrize('session_name', ['private', 'public'])
@pytest.mark.parametrize('method', ['GET', 'POST'])
@pytest.mark.parametrize('restore_settings', [False, True])
def test_http_error_reaches_client_without_retry(error_server, status, session_name, method, restore_settings):
    client = make_client()
    if restore_settings:
        settings = client.get_settings()
        # Saved sessions must not re-enable transport retries or hide HTTP responses.
        settings['session_retry_total'] = 3
        client.set_settings(settings)
    session = getattr(client, session_name)
    session.trust_env = False
    base_url, calls = error_server
    path = f'/{status}/{session_name}/{method}/{restore_settings}'
    before = len(calls)
    response = session.request(method, base_url + path, timeout=2)
    assert response.status_code == status
    assert response.json()['message'] == 'synthetic-provider-error'
    assert calls[before:] == [(method, path)]
    client.private.close()
    client.public.close()


def test_valid_password_keys_work_with_upstream_encryption(monkeypatch):
    client = make_client()
    response = requests.Response()
    response.status_code = 200
    response.headers['ig-set-password-encryption-key-id'] = '1'
    response.headers['ig-set-password-encryption-pub-key'] = base64.b64encode(RSA.generate(2048).public_key().export_key()).decode()
    monkeypatch.setattr(client.public, 'get', lambda *args, **kwargs: response)
    encrypted = client.password_encrypt('synthetic-test-password')
    assert encrypted.startswith('#PWD_INSTAGRAM:4:')
    assert len(base64.b64decode(encrypted.split(':', 3)[3])) > 256
    assert 'synthetic-test-password' not in encrypted
