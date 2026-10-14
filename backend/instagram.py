import logging
from instagrapi import Client
from instagrapi.exceptions import TwoFactorRequired, ClientJSONDecodeError


class VerificationRequired(RuntimeError):
    """Verification that must be completed in the official Instagram app."""


class InstagramClient(Client):
    """Keep error responses available to the client, including after session restore."""

    def _build_private_session_retry_strategy(self):
        return super()._build_private_session_retry_strategy().new(total=0, raise_on_status=False)

    def _build_public_session_retry_strategy(self):
        return super()._build_public_session_retry_strategy().new(total=0, raise_on_status=False)

    def password_publickeys(self):
        # The upstream helper reads headers without checking for an HTTP error first.
        response = self.public.get('https://i.instagram.com/api/v1/qe/sync/', timeout=20)
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
