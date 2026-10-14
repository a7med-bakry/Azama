import asyncio
import json
from .instagram import action
from .login import now


class Worker:
    def __init__(self, store, cipher, factory, account_lock, state_lock, delay):
        self.store, self.cipher, self.factory = store, cipher, factory
        self.account_lock, self.state_lock, self.delay = account_lock, state_lock, delay
        self.stopping = None
        self.task = None

    def update(self, job_id, **fields):
        with self.state_lock:
            job = self.store.get('job', job_id)
            job.update(fields, updated_at=now())
            self.store.put('job', job)
            return job

    def execute_one(self, account_id, job):
        # Serializes Instagram clients for the same session, including login attempts.
        with self.account_lock(account_id):
            latest = self.store.get('job', job['id'])
            if latest.get('cancel_requested'):
                return None
            account = self.store.get('account', account_id)
            if not account or account['status'] != 'ready':
                return False
            client = self.factory()
            # Never pause the worker awaiting a code; re-authentication uses the login flow.
            def challenge_required(*args):
                raise RuntimeError('Re-authentication required')
            client.challenge_code_handler = challenge_required
            try:
                client.set_settings(json.loads(self.cipher.decrypt(account['session'].encode())))
                action(client, job['action'], job['url'], job['comment'])
            except Exception:
                return False
            try:
                account['session'] = self.cipher.encrypt(json.dumps(client.get_settings()).encode()).decode()
                account['updated_at'] = now()
                self.store.put('account', account)
            except Exception:
                # The action was acknowledged; failure to save session must not trigger a retry.
                pass
            return True

    async def run_job(self, job):
        for account_id in job['account_ids'][:job['quantity']]:
            current = await asyncio.to_thread(self.store.get, 'job', job['id'])
            if self.stopping.is_set():
                await asyncio.to_thread(self.update, job['id'], status='interrupted', message='توقف السيرفر؛ راجع النتائج قبل إنشاء طلب جديد')
                return
            if current.get('cancel_requested'):
                await asyncio.to_thread(self.update, job['id'], status='cancelled', message='تم إلغاء العمليات المتبقية')
                return
            success = await asyncio.to_thread(self.execute_one, account_id, job)
            if success is None:
                await asyncio.to_thread(self.update, job['id'], status='cancelled', message='تم إلغاء العمليات المتبقية')
                return
            results = current['results'] + [{'account_id': account_id, 'success': success,
                                           'message': 'تمت العملية' if success else 'لم تتأكد العملية؛ راجع الحساب قبل إعادة المحاولة'}]
            job = await asyncio.to_thread(self.update, job['id'], results=results,
                                          completed=sum(r['success'] for r in results),
                                          failed=sum(not r['success'] for r in results))
            if len(results) < job['quantity']:
                try:
                    await asyncio.wait_for(self.stopping.wait(), timeout=self.delay)
                except asyncio.TimeoutError:
                    pass
        current = await asyncio.to_thread(self.store.get, 'job', job['id'])
        status = 'cancelled' if current.get('cancel_requested') else ('completed' if not current['failed'] else 'finished_with_errors')
        await asyncio.to_thread(self.update, job['id'], status=status, message='انتهى الطلب')

    async def run(self):
        while not self.stopping.is_set():
            claimed = None
            try:
                jobs = await asyncio.to_thread(self.store.list, 'job')
                for job in sorted(jobs, key=lambda j: j['created_at']):
                    if job['status'] != 'queued':
                        continue
                    job['status'] = 'running'
                    job['message'] = 'جاري التنفيذ'
                    if await asyncio.to_thread(self.store.claim, job):
                        claimed = job
                        await self.run_job(job)
                        break
            except Exception:
                # Unknown results never get retried automatically.
                if claimed:
                    try:
                        await asyncio.to_thread(self.update, claimed['id'], status='interrupted', message='توقفت المهمة؛ راجع النتائج قبل إعادة المحاولة')
                    except Exception:
                        pass
            try:
                await asyncio.wait_for(self.stopping.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass

    async def start(self):
        self.stopping = asyncio.Event()
        # Deployment runs one process/one instance. A previous running job is ambiguous after a restart.
        for job in await asyncio.to_thread(self.store.list, 'job'):
            if job['status'] == 'running':
                await asyncio.to_thread(self.update, job['id'], status='interrupted', message='انقطع التنفيذ السابق؛ راجع النتائج قبل إنشاء طلب جديد')
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.stopping:
            self.stopping.set()
        if self.task:
            await self.task
