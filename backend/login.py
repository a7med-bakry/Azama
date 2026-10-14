import queue
import threading
import time
import uuid
from datetime import datetime, timezone
import json
import hashlib
import logging
import requests
from cryptography.fernet import InvalidToken
from instagrapi import exceptions as instagram_errors
from .instagram import TwoFactorRequired, VerificationRequired, PreLoginRateLimit
from .storage import StorageError


logger = logging.getLogger(__name__)


def response_status(error):
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    return status if type(status) is int and 100 <= status <= 599 else None


def client_diagnostics(client):
    request = getattr(client, 'login_request', None)
    if request not in ('not_started', 'device_setup', 'password_key', 'account_login', 'two_factor', 'post_login_feed', 'other'):
        request = 'unknown'
    try:
        authenticated = bool(client and client.user_id and client.authorization)
    except Exception:
        authenticated = False
    return request, authenticated


def login_failure(error, stage):
    """Use fixed messages: provider exceptions may contain credentials and challenges."""
    failures = (
        ((StorageError,), 'storage', 'تعذر قراءة أو حفظ السيشن في قاعدة البيانات؛ راجع اتصال Supabase وصلاحيات الجدول.'),
        ((InvalidToken,), 'session_key', 'تعذر فك تشفير السيشن المحفوظة؛ راجع أن مفتاح التشفير الأصلي لم يتغير.'),
        ((instagram_errors.BadPassword, instagram_errors.BadCredentials), 'credentials', 'إنستجرام رفض بيانات الدخول. تأكد من اسم المستخدم وكلمة المرور في تطبيق إنستجرام.'),
        ((instagram_errors.SentryBlock, instagram_errors.ProxyAddressIsBlocked, instagram_errors.ClientForbiddenError), 'access_denied', 'إنستجرام رفض طلب الدخول من السيرفر. نجاح الدخول من الموبايل لا يثبت قبول اتصال السيرفر.'),
        ((PreLoginRateLimit, instagram_errors.PleaseWaitFewMinutes, instagram_errors.RateLimitError, instagram_errors.ClientThrottledError, instagram_errors.FeedbackRequired), 'rate_limited', 'إنستجرام قيّد المحاولة مؤقتًا. أوقف تكرار المحاولات وراجع الحساب في التطبيق.'),
        ((VerificationRequired, instagram_errors.ChallengeError, instagram_errors.CaptchaChallengeRequired, instagram_errors.TwoFactorRequired, instagram_errors.ResetPasswordError), 'verification', 'إنستجرام طلب تحققًا لا يمكن إكماله هنا. افتح تطبيق إنستجرام وأكمل التحقق الظاهر فيه.'),
        ((instagram_errors.ClientConnectionError, instagram_errors.ClientRequestTimeout, instagram_errors.ClientIncompleteReadError, requests.ConnectionError, requests.Timeout, requests.exceptions.RetryError), 'connection', 'تعذر إكمال طلب الاتصال بإنستجرام من السيرفر. راجع السجل وحاول لاحقًا.'),
    )
    for types, code, message in failures:
        if isinstance(error, types):
            return code, message
    if isinstance(error, (instagram_errors.ClientError, requests.HTTPError)):
        status = response_status(error)
        if status == 429:
            return 'rate_limited', 'إنستجرام قيّد المحاولة مؤقتًا. أوقف تكرار المحاولات وراجع الحساب في التطبيق.'
        if status == 403:
            return 'access_denied', 'إنستجرام رفض طلب الاتصال من السيرفر.'
        if status == 405:
            return 'instagram_response', 'إنستجرام رفض طريقة الطلب؛ يلزم مراجعة توافق كود تسجيل الدخول.'
        if status is not None and status >= 500:
            return 'provider_unavailable', 'طلب السيرفر رجع بخطأ من خدمة إنستجرام. حاول لاحقًا؛ الرسالة لا تعني أن كلمة المرور غير صحيحة.'
    if stage in ('instagram_login', 'two_factor') and isinstance(error, (KeyError, instagram_errors.ClientJSONDecodeError)):
        return 'instagram_response', 'السيرفر لم يتمكن من قراءة رد إنستجرام؛ قد تكون المشكلة في توافق مكتبة تسجيل الدخول. راجع سجل السيرفر.'
    return 'unexpected', 'حدث خطأ تقني أثناء تسجيل الدخول؛ راجع سجل السيرفر لتحديد السبب.'


def now():
    return datetime.now(timezone.utc).isoformat()


class LoginAttempt:
    def __init__(self, account_id, timeout):
        self.id = uuid.uuid4().hex
        self.account_id = account_id
        self.status = 'logging_in'
        self.message = 'جاري تسجيل الدخول'
        self.challenge = None
        self.challenge_id = None
        self.failure_code = None
        self.codes = queue.Queue(maxsize=1)
        self.expires = time.monotonic() + timeout
        self.guard = threading.Lock()
        self.cancelled = threading.Event()
        self.future = None

    def public(self):
        with self.guard:
            return {'id': self.id, 'account_id': self.account_id, 'status': self.status, 'message': self.message,
                    'challenge': self.challenge, 'challenge_id': self.challenge_id, 'failure_code': self.failure_code}

    def set_state(self, status, message, challenge=None, failure_code=None):
        with self.guard:
            self.status, self.message, self.challenge = status, message, challenge
            self.challenge_id = uuid.uuid4().hex if status == 'awaiting_code' else None
            self.failure_code = failure_code

    def wait_code(self, kind):
        if self.cancelled.is_set():
            raise TimeoutError()
        self.set_state('awaiting_code', 'أدخل كود التحقق لإكمال تسجيل الدخول', kind)
        timeout = max(0, self.expires - time.monotonic())
        try:
            code = self.codes.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError() from None
        if code is None or self.cancelled.is_set():
            raise TimeoutError()
        self.set_state('logging_in', 'جاري التحقق من الكود')
        return code

    def submit(self, challenge_id, code):
        with self.guard:
            if self.status != 'awaiting_code' or self.challenge_id != challenge_id or time.monotonic() >= self.expires:
                return False
            try:
                self.codes.put_nowait(code)
            except queue.Full:
                return False
            self.status = 'logging_in'
            self.challenge_id = None
            return True

    def cancel(self):
        self.cancelled.set()
        try:
            self.codes.put_nowait(None)
        except queue.Full:
            pass


def run_login(attempt, username, password, store, cipher, factory, lock, lock_provider):
    if not lock.acquire(blocking=False):
        attempt.set_state('failed', 'الحساب مشغول؛ حاول بعد انتهاء العملية الحالية')
        return
    client = None
    canonical_lock = None
    stage = 'client_setup'
    try:
        client = factory()
        stage = 'session_read'
        existing = store.get('account', attempt.account_id)
        if existing and existing.get('session'):
            stage = 'session_restore'
            client.set_settings(json.loads(cipher.decrypt(existing['session'].encode())))
        client.challenge_code_handler = lambda _username, choice: attempt.wait_code('sms' if getattr(choice, 'value', choice) == 0 else 'email')
        stage = 'instagram_login'
        try:
            logged_in = client.login(username, password, relogin=True)
        except TwoFactorRequired:
            stage = 'two_factor'
            logged_in = client.login(username, password, verification_code=attempt.wait_code('two_factor'))
        if not logged_in:
            raise RuntimeError('Login not confirmed')
        if attempt.cancelled.is_set() or time.monotonic() >= attempt.expires:
            raise TimeoutError()
        # Use Instagram's authenticated user id so email and username share one session/lock.
        stage = 'account_identity'
        user_id = client.user_id
        if not user_id:
            raise RuntimeError('Instagram did not return an authenticated user id')
        canonical_id = hashlib.sha256(('instagram:' + str(user_id)).encode()).hexdigest()[:32]
        if canonical_id != attempt.account_id:
            canonical_lock = lock_provider(canonical_id)
            if not canonical_lock.acquire(blocking=False):
                canonical_lock = None
                raise RuntimeError('Account busy')
        with attempt.guard:
            attempt.account_id = canonical_id
        stage = 'session_read'
        saved = store.get('account', canonical_id)
        display_name = saved['username'] if saved else username
        if '@' in display_name:
            try:
                display_name = client.account_info().username
            except Exception:
                pass  # Authentication succeeded even if optional profile lookup is unavailable.
        identifiers = list(set((saved or {}).get('identifier_hashes', []) + [hashlib.sha256(username.encode()).hexdigest()[:32]]))
        stage = 'session_save'
        session = cipher.encrypt(json.dumps(client.get_settings()).encode()).decode()
        if attempt.cancelled.is_set() or time.monotonic() >= attempt.expires:
            raise TimeoutError()
        store.put('account', {'id': canonical_id, 'username': display_name, 'status': 'ready',
                              'identifier_hashes': identifiers, 'session': session, 'updated_at': now()})
        attempt.set_state('ready', 'تم تسجيل الدخول وحفظ السيشن')
    except TimeoutError:
        attempt.set_state('expired', 'انتهت مهلة تسجيل الدخول؛ ابدأ محاولة جديدة')
    except Exception as error:
        code, message = login_failure(error, stage)
        request, authenticated = client_diagnostics(client)
        # Log only the exception class and fixed diagnostic fields, never its body/traceback.
        logger.warning('Instagram login failed: code=%s stage=%s exception=%s http_status=%s request=%s authenticated=%s attempt=%s',
                       code, stage, type(error).__name__, response_status(error), request, authenticated, attempt.id)
        attempt.set_state('failed', message, failure_code=code)
    finally:
        password = None
        if client is not None:
            client.password = None
        if canonical_lock is not None:
            canonical_lock.release()
        lock.release()
