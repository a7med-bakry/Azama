import logging
from instagrapi import Client
from instagrapi.exceptions import TwoFactorRequired, ClientJSONDecodeError, PleaseWaitFewMinutes, ClientThrottledError
from instagrapi.utils import dumps, generate_signature


class VerificationRequired(RuntimeError):
    """Verification that must be completed in the official Instagram app."""


class PreLoginRateLimit(RuntimeError):
    """Stop login when setup is throttled; upstream otherwise ignores this signal."""

    def __init__(self, response=None):
        super().__init__('Instagram throttled device setup')
        self.response = response


class InstagramClient(Client):
    """Keep error responses available to the client, including after session restore."""

    login_request = 'not_started'

    def private_request(self, endpoint, *args, **kwargs):
        self.login_request = {
            'launcher/sync/': 'device_setup',
            'qe/sync/': 'device_setup',
            'accounts/login/': 'account_login',
            'accounts/two_factor_login/': 'two_factor',
            'feed/reels_tray/': 'post_login_feed',
            'feed/timeline/': 'post_login_feed',
        }.get(endpoint, 'other')
        return super().private_request(endpoint, *args, **kwargs)

    def pre_login_flow(self):
        try:
            return super().pre_login_flow()
        except (PleaseWaitFewMinutes, ClientThrottledError) as error:
            raise PreLoginRateLimit(response=getattr(error, 'response', None)) from None

    def _build_private_session_retry_strategy(self):
        return super()._build_private_session_retry_strategy().new(total=0, raise_on_status=False)

    def _build_public_session_retry_strategy(self):
        return super()._build_public_session_retry_strategy().new(total=0, raise_on_status=False)

    def password_publickeys(self):
        self.login_request = 'password_key'
        # Match sync_device_features: qe/sync expects a signed private POST, not GET.
        headers = dict(self.base_headers)
        headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
        data = {'id': self.uuid, 'server_config_retrieval': '1'}
        response = self.private.post('https://i.instagram.com/api/v1/qe/sync/',
                                     data=generate_signature(dumps(data)), headers=headers, timeout=20)
        response.raise_for_status()
        try:
            key_id = int(response.headers['ig-set-password-encryption-key-id'])
            public_key = response.headers['ig-set-password-encryption-pub-key']
            if not 0 <= key_id <= 255 or not public_key:
                raise ValueError()
            return key_id, public_key
        except (KeyError, ValueError):
            raise ClientJSONDecodeError('Password encryption headers unavailable', response=response) from None


def make_client():
    logger = logging.getLogger('instaflow.instagram')
    logger.disabled = True
    client = InstagramClient(logger=logger, request_timeout=20, session_retry_total=0)
    client.private.verify = True
    client.public.verify = True
    # Provider logging may contain challenge responses. Keep it out of application logs.
    client.private_request_logger = logger
    client.public_request_logger = logger
    def unsupported_verification(*args):
        raise VerificationRequired('Complete verification in the Instagram app')
    client.change_password_handler = unsupported_verification
    return client


def action(client, kind, url, comment):
    """Count success only when the Instagram operation acknowledges it."""
    media_pk = client.media_pk_from_url(url)
    if kind == 'like':
        if not client.media_like(media_pk):
            raise RuntimeError('Instagram did not acknowledge the action')
    elif kind == 'comment':
        if not client.media_comment(media_pk, comment):
            raise RuntimeError('Instagram did not acknowledge the action')
    else:
        raise ValueError('Unsupported action')
