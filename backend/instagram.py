import logging
from instagrapi import Client
from instagrapi.exceptions import TwoFactorRequired


def make_client():
    logger = logging.getLogger('instaflow.instagram')
    logger.disabled = True
    client = Client(logger=logger, request_timeout=20, session_retry_total=0)
    client.private.verify = True
    client.public.verify = True
    # Provider logging may contain challenge responses. Keep it out of application logs.
    client.private_request_logger = logger
    client.public_request_logger = logger
    def unsupported_verification(*args):
        raise RuntimeError('Complete verification in the Instagram app')
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
