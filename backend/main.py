import asyncio
import hashlib
import json
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from cryptography.fernet import Fernet
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .config import Settings
from .storage import SQLiteStore, SupabaseStore, StorageError
from .login import LoginAttempt, run_login, now
from .models import LoginInput, SessionInput, CodeInput, JobInput, job_validation_message, session_validation_message
from .instagram import make_client
from .jobs import Worker

WEB = Path(__file__).resolve().parent.parent / 'web'


def create_app(settings=None, store=None, client_factory=make_client, start_worker=True):
    settings = settings or Settings.from_env()
    store = store or (SupabaseStore(settings.supabase_url, settings.supabase_key) if settings.supabase_url else SQLiteStore(settings.database_path))
    cipher = Fernet(settings.encryption_key.encode())
    attempts = {}
    locks = {}
    state_lock = threading.RLock()
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='instagram-login')

    def account_lock(account_id):
        with state_lock:
            return locks.setdefault(account_id, threading.Lock())

    worker = Worker(store, cipher, client_factory, account_lock, state_lock, settings.action_delay)

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(store.ping)
        if start_worker:
            await worker.start()
        yield
        for attempt in list(attempts.values()):
            attempt.cancel()
        await worker.stop()
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)

    app = FastAPI(title='Insta Bot Manager', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.worker, app.state.attempts = store, worker, attempts
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.origins), allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['Authorization', 'Content-Type'])

    @app.middleware('http')
    async def headers(request, call_next):
        # Bound request bodies before Pydantic parses passwords or large account lists.
        if request.method in ('POST', 'PUT', 'PATCH'):
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 16384:
                    return JSONResponse({'detail': 'Request too large'}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src https: http://localhost:8000 http://127.0.0.1:8000; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        return response

    def authorized(authorization: str = Header(default='')):
        if not secrets.compare_digest(authorization.encode(), ('Bearer ' + settings.admin_token).encode()):
            raise HTTPException(401, 'مفتاح الإدارة غير صحيح')

    auth = [Depends(authorized)]

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        if request.url.path == '/api/sessions':
            return JSONResponse({'detail': session_validation_message(exc.errors())}, status_code=422)
        if request.url.path == '/api/jobs':
            return JSONResponse({'detail': job_validation_message(exc.errors())}, status_code=422)
        return JSONResponse({'detail': 'راجع الحقول المطلوبة، الرابط، والعدد. استخدم اسم المستخدم أو الإيميل الصحيح.'}, status_code=422)

    @app.exception_handler(StorageError)
    async def storage_error(request, exc):
        return JSONResponse({'detail': 'قاعدة البيانات غير متاحة حاليًا'}, status_code=503)

    @app.get('/health')
    def health():
        store.ping()
        return {'status': 'ok'}

    @app.get('/api/accounts', dependencies=auth)
    def accounts():
        return [{k: v for k, v in account.items() if k not in ('session', 'identifier_hashes')} for account in store.list('account')]

    def start_attempt(account_id, username='', password='', imported_settings=None):
        with state_lock:
            # Finished attempts expire; live network calls are not removed until their thread ends.
            for key, attempt in list(attempts.items()):
                if time.monotonic() >= attempt.expires:
                    attempt.cancel()
                    if attempt.future and attempt.future.done():
                        del attempts[key]
            if any(a.account_id == account_id and a.future and not a.future.done() for a in attempts.values()):
                raise HTTPException(409, 'هناك محاولة دخول جارية لهذا الحساب')
            if sum(bool(a.future and not a.future.done()) for a in attempts.values()) >= 4:
                raise HTTPException(429, 'انتظر انتهاء إحدى محاولات تسجيل الدخول')
            if len(attempts) >= 100:
                raise HTTPException(429, 'انتظر قليلًا قبل بدء محاولة جديدة')
            attempt = LoginAttempt(account_id, settings.login_timeout)
            attempts[attempt.id] = attempt
            attempt.future = executor.submit(run_login, attempt, username, password, store, cipher, client_factory, account_lock(account_id), account_lock, imported_settings)
            return attempt.public()

    @app.post('/api/logins', dependencies=auth, status_code=202)
    def login(data: LoginInput):
        identifier_hash = hashlib.sha256(data.username.encode()).hexdigest()[:32]
        with state_lock:
            existing = next((a for a in store.list('account') if identifier_hash in a.get('identifier_hashes', []) or a['username'] == data.username), None)
            if not data.password and not (existing and existing.get('session')):
                raise HTTPException(422, 'أدخل كلمة المرور لأول تسجيل دخول، أو استخدم استيراد السيشن')
            return start_attempt(existing['id'] if existing else identifier_hash, data.username, data.password)

    @app.post('/api/sessions', dependencies=auth, status_code=202)
    def import_session(data: SessionInput):
        # Deduplicate concurrent uploads without exposing the session credentials.
        account_id = hashlib.sha256(('session:' + json.dumps(data.settings, sort_keys=True)).encode()).hexdigest()[:32]
        return start_attempt(account_id, imported_settings=data.settings)

    def find_attempt(attempt_id):
        with state_lock:
            attempt = attempts.get(attempt_id)
            if not attempt:
                raise HTTPException(404, 'محاولة الدخول غير موجودة؛ ابدأ من جديد')
            if time.monotonic() >= attempt.expires:
                attempt.cancel()
                if attempt.public()['status'] not in ('ready', 'failed', 'expired'):
                    attempt.set_state('expired', 'انتهت مهلة تسجيل الدخول')
            return attempt

    @app.get('/api/logins/{attempt_id}', dependencies=auth)
    def login_status(attempt_id: str):
        return find_attempt(attempt_id).public()

    @app.post('/api/logins/{attempt_id}/code', dependencies=auth, status_code=202)
    def code(attempt_id: str, data: CodeInput):
        attempt = find_attempt(attempt_id)
        if not attempt.submit(data.challenge_id, data.code):
            raise HTTPException(409, 'الكود لا يخص خطوة التحقق الحالية أو انتهت المهلة')
        return attempt.public()

    @app.delete('/api/logins/{attempt_id}', dependencies=auth)
    def cancel_login(attempt_id: str):
        attempt = find_attempt(attempt_id)
        attempt.cancel()
        return {'status': 'cancel_requested'}

    @app.delete('/api/accounts/{account_id}', dependencies=auth)
    def delete_account(account_id: str):
        with state_lock:
            if not store.get('account', account_id):
                raise HTTPException(404, 'الحساب غير موجود')
            if any(a.account_id == account_id and a.future and not a.future.done() for a in attempts.values()):
                raise HTTPException(409, 'انتظر انتهاء تسجيل الدخول')
            if any(j['status'] in ('queued', 'running') and account_id in j['account_ids'] for j in store.list('job')):
                raise HTTPException(409, 'ألغِ طلبات الحساب أولًا')
            store.delete('account', account_id)
        return {'status': 'deleted'}

    @app.get('/api/jobs', dependencies=auth)
    def jobs():
        return store.list('job')

    @app.post('/api/jobs', dependencies=auth, status_code=202)
    def enqueue(data: JobInput):
        with state_lock:
            for account_id in data.account_ids:
                account = store.get('account', account_id)
                if not account or account['status'] != 'ready':
                    raise HTTPException(422, 'اختر حسابات مسجلة وجاهزة للتشغيل')
            if sum(j['status'] in ('queued', 'running') for j in store.list('job')) >= 100:
                raise HTTPException(429, 'طابور المهام ممتلئ')
            job = dict(data.model_dump(), id=uuid.uuid4().hex, status='queued', completed=0, failed=0,
                       results=[], cancel_requested=False, created_at=now(), updated_at=now(), message='في انتظار التشغيل')
            store.put('job', job)
            return job

    @app.post('/api/jobs/{job_id}/cancel', dependencies=auth)
    def cancel_job(job_id: str):
        with state_lock:
            job = store.get('job', job_id)
            if not job:
                raise HTTPException(404, 'الطلب غير موجود')
            if job['status'] in ('queued', 'running'):
                job.update(cancel_requested=True)
                if job['status'] == 'queued':
                    job.update(status='cancelled', message='تم إلغاء الطلب')
                job['updated_at'] = now()
                store.put('job', job)
        return job

    @app.get('/')
    def index():
        return FileResponse(WEB / 'index.html')

    app.mount('/assets', StaticFiles(directory=WEB / 'assets'), name='assets')
    return app
