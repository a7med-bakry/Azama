'use strict';
const $ = id => document.getElementById(id);
const state = {api: '', token: '', accounts: [], jobs: [], attempt: null, poll: null, loginPoll: null, view: 'overview', connected: false, refreshing: false, epoch: 0};
const labels = {queued:'في الانتظار', running:'جاري التشغيل', completed:'مكتمل', finished_with_errors:'انتهى بأخطاء', cancelled:'ملغي', interrupted:'متوقف'};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(message, error = false) { $('toast').textContent = message; $('toast').classList.toggle('error', error); $('toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').hidden = true, 5000); }
async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 25000);
  try {
    const response = await fetch(state.api + path, {...options, signal: controller.signal, headers: {Authorization: 'Bearer ' + state.token, ...(options.body ? {'Content-Type':'application/json'} : {})}});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'تعذر تنفيذ الطلب');
    return data;
  } catch (error) {
    if (error.name === 'AbortError' || error instanceof TypeError) throw new Error('تعذر الاتصال بالسيرفر. راجع العنوان وإعدادات الاتصال.');
    throw error;
  } finally { clearTimeout(timer); }
}
function serverStatus(connected) {
  state.connected = connected;
  $('server-dot').classList.toggle('online', connected);
  $('server-label').textContent = connected ? 'السيرفر متصل' : 'السيرفر غير متصل';
  $('connection-notice').hidden = connected;
  $('submit-job').disabled = !connected || !state.accounts.length;
}
function empty(title, description, add = false) { return `<div class="empty-state"><span class="empty-icon">◎</span><strong>${esc(title)}</strong><p>${esc(description)}</p>${add ? '<button class="button subtle" data-add-account>＋ إضافة أول حساب</button>' : ''}</div>`; }
function accountRow(account) {
  return `<div class="account-row"><span class="account-avatar">${esc(account.username.slice(0,2).toUpperCase())}</span><div><div class="account-name">@${esc(account.username)}</div><div class="account-detail">سيشن محفوظة · ${esc(new Date(account.updated_at).toLocaleDateString('ar-EG'))}</div></div><div class="account-actions"><span class="badge">جاهز</span><button class="text-button" data-relogin="${esc(account.username)}">دخول جديد</button><button class="delete-button" data-delete="${esc(account.id)}">حذف</button></div></div>`;
}
function render() {
  const selected = new Set([...document.querySelectorAll('#account-picker input:checked')].map(x => x.value));
  $('stat-accounts').textContent = $('nav-count').textContent = state.accounts.length;
  $('stat-running').textContent = state.jobs.filter(j => ['queued','running'].includes(j.status)).length;
  $('stat-completed').textContent = state.jobs.reduce((s,j) => s + j.completed, 0);
  $('stat-failed').textContent = state.jobs.reduce((s,j) => s + j.failed, 0);
  const accountEmpty = empty('لسه مفيش حسابات', 'أضف أول حساب عشان تحفظ السيشن وتبدأ إدارة طلباتك.', true);
  $('overview-accounts').innerHTML = state.accounts.length ? state.accounts.slice(0,3).map(accountRow).join('') : accountEmpty;
  $('accounts-list').innerHTML = state.accounts.length ? state.accounts.map(accountRow).join('') : accountEmpty;
  $('account-picker').innerHTML = state.accounts.length ? state.accounts.map(a => `<label class="picker-row"><input type="checkbox" value="${esc(a.id)}" ${selected.has(a.id) ? 'checked' : ''}><span>@${esc(a.username)}</span></label>`).join('') : '<p class="muted">أضف حسابًا مسجلًا لتبدأ.</p>';
  updateSelected();
  const names = new Map(state.accounts.map(a => [a.id,a.username]));
  $('jobs-list').innerHTML = state.jobs.length ? `<div class="table-scroll"><table class="jobs-table"><thead><tr><th>الطلب</th><th>الحالة</th><th>النتيجة</th><th>التاريخ</th><th></th></tr></thead><tbody>${state.jobs.slice(0,50).map(j => `<tr><td><a href="${esc(j.url)}" target="_blank" rel="noopener noreferrer">${j.action === 'like' ? '♡ لايكات' : '☷ تعليقات'} ↗</a><div class="job-meta">${esc(j.message)}</div></td><td><span class="badge ${esc(j.status)}">${esc(labels[j.status] || j.status)}</span></td><td>${j.completed} ناجح / ${j.quantity}<div class="job-meta">${j.failed} لم تتأكد</div><details><summary>نتائج الحسابات</summary><ul>${j.results.map(r => `<li>@${esc(names.get(r.account_id) || r.account_id.slice(0,8))}: ${esc(r.message)}</li>`).join('') || '<li>لم تبدأ العمليات بعد</li>'}</ul></details></td><td><span class="job-meta">${esc(new Date(j.created_at).toLocaleString('ar-EG'))}</span></td><td>${['queued','running'].includes(j.status) ? `<button class="text-button" data-cancel="${esc(j.id)}" ${j.cancel_requested ? 'disabled' : ''}>${j.cancel_requested ? 'جاري الإيقاف' : 'إيقاف'}</button>` : '—'}</td></tr>`).join('')}</tbody></table></div>` : empty('طلباتك هتظهر هنا', 'أنشئ طلبك الأول وتابع حالة التنفيذ ونتيجة كل حساب.');
  $('submit-job').disabled = !state.connected || !state.accounts.length;
}
function updateSelected() { const count = document.querySelectorAll('#account-picker input:checked').length; $('selected-count').textContent = `${count} محدد`; $('quantity').max = Math.max(1,count); }
async function refresh(showError = false) {
  if (!state.token || state.refreshing) return;
  const epoch = state.epoch;
  state.refreshing = true;
  try {
    const [accounts,jobs] = await Promise.all([api('/api/accounts'),api('/api/jobs')]);
    if (epoch !== state.epoch) return;
    state.accounts = accounts; state.jobs = jobs; serverStatus(true); render();
  } catch (error) { if (epoch === state.epoch) { serverStatus(false); if (showError) toast(error.message,true); } }
  finally { state.refreshing = false; }
}
function openConnection() { $('api-url').value = state.api || localStorage.getItem('instaflow_api') || (location.hostname === 'localhost' || location.hostname === '127.0.0.1' ? location.origin : ''); $('connection-error').textContent = ''; $('connection-dialog').showModal(); }
function changeView(view) {
  state.view = view;
  document.querySelectorAll('.nav').forEach(n => n.classList.toggle('active',n.dataset.view === view));
  $('overview-view').hidden = view !== 'overview'; $('accounts-view').hidden = view !== 'accounts'; $('jobs-section').hidden = view === 'accounts';
  $('page-title').textContent = {overview:'كل حساباتك. في مكان واحد.', accounts:'حساباتك، جاهزة للخطوة الجاية.', jobs:'تابع كل طلب. خطوة بخطوة.'}[view];
  $('breadcrumb').textContent = {overview:'نظرة عامة',accounts:'الحسابات',jobs:'الطلبات'}[view];
  $('page-description').textContent = {overview:'أضف حساباتك، نظّم الطلبات، وتابع كل عملية من البداية للنهاية.',accounts:'أضف حسابًا أو أعد تسجيل الدخول لتحديث السيشن.',jobs:'راجع النتائج الفعلية، وأوقف العمليات المتبقية وقت ما تحتاج.'}[view];
}
function openLogin(username = '') {
  if (!state.connected) { openConnection(); return; }
  state.attempt = null; clearTimeout(state.loginPoll);
  $('login-form').reset(); $('username').value = username; $('login-form').hidden = false;
  $('login-progress').hidden = true; $('code-form').hidden = true; $('login-error').textContent = ''; $('retry-login').hidden = true; $('login-dialog').showModal();
}
function closeLogin() {
  clearTimeout(state.loginPoll);
  const attempt = state.attempt; state.attempt = null;
  if (attempt && !['ready','failed','expired'].includes(attempt.status)) api('/api/logins/' + attempt.id,{method:'DELETE'}).catch(() => {});
}
function updateLogin(attempt) {
  clearTimeout(state.loginPoll);
  state.attempt = attempt;
  $('login-message').textContent = attempt.message;
  const awaiting = attempt.status === 'awaiting_code'; $('code-form').hidden = !awaiting;
  $('code-label').textContent = attempt.challenge === 'two_factor' ? 'كود تطبيق المصادقة الثنائية' : (attempt.challenge === 'sms' ? 'كود التحقق المرسل للهاتف' : 'كود التحقق المرسل للإيميل');
  if (attempt.challenge_id !== updateLogin.challengeId) { $('code').value = ''; updateLogin.challengeId = attempt.challenge_id; if (awaiting) $('code').focus(); }
  $('retry-login').hidden = !['failed','expired'].includes(attempt.status);
  if (attempt.status === 'ready') { toast(attempt.message); $('login-dialog').close(); refresh(true); return; }
  if (!['failed','expired'].includes(attempt.status)) state.loginPoll = setTimeout(pollLogin,1500);
}
async function pollLogin() {
  const attemptId = state.attempt?.id;
  if (!attemptId || !$('login-dialog').open) return;
  try { const attempt = await api('/api/logins/' + attemptId); if (state.attempt?.id === attemptId && $('login-dialog').open) updateLogin(attempt); }
  catch(error) { $('login-error').textContent = error.message; $('retry-login').hidden = false; }
}
$('connection-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter || event.currentTarget.querySelector('button[type="submit"]'); button.disabled = true; $('connection-error').textContent = '';
  try {
    const url = new URL($('api-url').value.trim());
    if (url.username || url.password || url.search || url.hash || url.pathname !== '/' || !['http:','https:'].includes(url.protocol)) throw new Error('استخدم عنوان السيرفر فقط بدون مسار أو بيانات دخول.');
    if (url.protocol !== 'https:' && !['localhost','127.0.0.1'].includes(url.hostname)) throw new Error('استخدم HTTPS للسيرفر؛ HTTP متاح محليًا فقط.');
    state.epoch++; state.api = url.origin; state.token = $('admin-key').value;
    const accounts = await api('/api/accounts'); const jobs = await api('/api/jobs');
    localStorage.setItem('instaflow_api',state.api); state.accounts = accounts; state.jobs = jobs;
    $('admin-key').value = ''; serverStatus(true); render(); $('connection-dialog').close();
    clearInterval(state.poll); state.poll = setInterval(() => refresh(),5000); toast('تم الاتصال بالسيرفر');
  } catch(error) { state.token = ''; serverStatus(false); $('connection-error').textContent = error.message; }
  finally { button.disabled = false; }
});
$('login-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter || event.currentTarget.querySelector('button[type="submit"]'); button.disabled = true; $('login-error').textContent = '';
  const payload = {username:$('username').value.trim(),password:$('password').value};
  try { const attempt = await api('/api/logins',{method:'POST',body:JSON.stringify(payload)}); if (!$('login-dialog').open) { await api('/api/logins/' + attempt.id,{method:'DELETE'}); return; } $('login-form').hidden = true; $('login-progress').hidden = false; updateLogin(attempt); }
  catch(error) { $('login-error').textContent = error.message; }
  finally { $('password').value = ''; payload.password = ''; button.disabled = false; }
});
$('code-form').addEventListener('submit',async event => {
  event.preventDefault(); const button = event.submitter || event.currentTarget.querySelector('button[type="submit"]'); button.disabled = true; clearTimeout(state.loginPoll); $('login-error').textContent = '';
  try { updateLogin(await api(`/api/logins/${state.attempt.id}/code`,{method:'POST',body:JSON.stringify({code:$('code').value,challenge_id:state.attempt.challenge_id})})); }
  catch(error) { $('login-error').textContent = error.message; state.loginPoll = setTimeout(pollLogin,1500); }
  finally { $('code').value = ''; button.disabled = false; }
});
$('job-form').addEventListener('submit',async event => {
  event.preventDefault(); const account_ids = [...document.querySelectorAll('#account-picker input:checked')].map(x => x.value);
  const quantity = Number($('quantity').value);
  if (!account_ids.length || quantity > account_ids.length) { toast('اختر حسابات بعدد العمليات المطلوبة أو أكثر.',true); return; }
  const button = event.submitter || event.currentTarget.querySelector('button[type="submit"]'); button.disabled = true;
  try {
    await api('/api/jobs',{method:'POST',body:JSON.stringify({action:document.querySelector('input[name=action]:checked').value,url:$('post-url').value,quantity,account_ids,comment:$('comment').value})});
    toast('تم إنشاء الطلب'); await refresh(true);
  } catch(error) { toast(error.message,true); }
  finally { button.disabled = !state.connected; }
});
$('job-form').addEventListener('change',() => { const comment = document.querySelector('input[name=action]:checked').value === 'comment'; $('comment-field').hidden = !comment; $('comment').required = comment; updateSelected(); });
$('retry-login').addEventListener('click',() => { closeLogin(); $('login-form').hidden = false; $('login-progress').hidden = true; $('login-error').textContent = ''; });
$('login-dialog').addEventListener('close',() => { closeLogin(); $('password').value = ''; $('code').value = ''; });
$('connection-dialog').addEventListener('close',() => $('admin-key').value = '');
$('connection-button').onclick = $('connect-notice').onclick = openConnection;
$('add-account').onclick = () => openLogin(); $('refresh-button').onclick = () => state.token ? refresh(true) : openConnection();
$('disconnect-button').onclick = () => { closeLogin(); if ($('login-dialog').open) $('login-dialog').close(); state.epoch++; clearInterval(state.poll); state.token = ''; state.accounts = []; state.jobs = []; serverStatus(false); render(); toast('تم قطع الاتصال'); };
document.addEventListener('click',async event => {
  const target = event.target.closest('button'); if (!target) return;
  if (target.dataset.close) $(target.dataset.close).close();
  if (target.dataset.view) changeView(target.dataset.view);
  if (target.dataset.go) changeView(target.dataset.go);
  if (target.hasAttribute('data-add-account')) openLogin();
  if (target.dataset.relogin) openLogin(target.dataset.relogin);
  if (target.dataset.delete && confirm('حذف الحساب والسيشن المحفوظة؟')) {
    try { await api('/api/accounts/' + target.dataset.delete,{method:'DELETE'}); await refresh(true); toast('تم حذف الحساب'); } catch(error) { toast(error.message,true); }
  }
  if (target.dataset.cancel) { target.disabled = true; try { await api('/api/jobs/' + target.dataset.cancel + '/cancel',{method:'POST'}); await refresh(true); toast('تم طلب إيقاف العمليات المتبقية'); } catch(error) { toast(error.message,true); target.disabled = false; } }
});
render(); serverStatus(false);
