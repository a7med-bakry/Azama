import queue
import threading
import time
import uuid
from datetime import datetime, timezone
import json
import hashlib
from .instagram import TwoFactorRequired


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
        self.codes = queue.Queue(maxsize=1)
        self.expires = time.monotonic() + timeout
        self.guard = threading.Lock()
        self.cancelled = threading.Event()
        self.future = None

    def public(self):
        with self.guard:
            return {'id': self.id, 'account_id': self.account_id, 'status': self.status, 'message': self.message,
                    'challenge': self.challenge, 'challenge_id': self.challenge_id}

    def set_state(self, status, message, challenge=None):
        with self.guard:
            self.status, self.message, self.challenge = status, message, challenge
            self.challenge_id = uuid.uuid4().hex if status == 'awaiting_code' else None

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
    try:
        client = factory()
        existing = store.get('account', attempt.account_id)
        if existing and existing.get('session'):
            client.set_settings(json.loads(cipher.decrypt(existing['session'].encode())))
        client.challenge_code_handler = lambda _username, choice: attempt.wait_code('sms' if getattr(choice, 'value', choice) == 0 else 'email')
        try:
            logged_in = client.login(username, password, relogin=True)
        except TwoFactorRequired:
            logged_in = client.login(username, password, verification_code=attempt.wait_code('two_factor'))
        if not logged_in:
            raise RuntimeError('Login not confirmed')
        if attempt.cancelled.is_set() or time.monotonic() >= attempt.expires:
            raise TimeoutError()
        # Use Instagram's authenticated user id so email and username share one session/lock.
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
        saved = store.get('account', canonical_id)
        display_name = saved['username'] if saved else username
        if '@' in display_name:
            try:
                display_name = client.account_info().username
            except Exception:
                pass  # Authentication succeeded even if optional profile lookup is unavailable.
        identifiers = list(set((saved or {}).get('identifier_hashes', []) + [hashlib.sha256(username.encode()).hexdigest()[:32]]))
        session = cipher.encrypt(json.dumps(client.get_settings()).encode()).decode()
        if attempt.cancelled.is_set() or time.monotonic() >= attempt.expires:
            raise TimeoutError()
        store.put('account', {'id': canonical_id, 'username': display_name, 'status': 'ready',
                              'identifier_hashes': identifiers, 'session': session, 'updated_at': now()})
        attempt.set_state('ready', 'تم تسجيل الدخول وحفظ السيشن')
    except TimeoutError:
        attempt.set_state('expired', 'انتهت مهلة تسجيل الدخول؛ ابدأ محاولة جديدة')
    except Exception:
        # instagrapi exceptions can include private challenge details. Do not return them.
        attempt.set_state('failed', 'تعذر تسجيل الدخول. راجع البيانات؛ قد يحتاج الحساب تحققًا من تطبيق إنستجرام')
    finally:
        password = None
        if client is not None:
            client.password = None
        if canonical_lock is not None:
            canonical_lock.release()
        lock.release()
