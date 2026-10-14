(async () => {
  const waitFor = async (condition, label) => {
    const deadline = Date.now() + 5000;
    while (!condition()) {
      if (Date.now() > deadline) throw new Error('Timed out: ' + label);
      await new Promise(resolve => setTimeout(resolve, 30));
    }
  };
  let accountReady = false, job = null;
  const requests = [];
  const originalFetch = window.fetch;
  window.fetch = async (url, options = {}) => {
    const path = new URL(url, location.origin).pathname;
    const method = options.method || 'GET';
    requests.push({path,method});
    let data;
    const account = {id:'synthetic-account',username:'synthetic_account',status:'ready',updated_at:'2026-10-14T00:00:00+00:00'};
    if (path === '/api/accounts') data = accountReady ? [account] : [];
    else if (path === '/api/jobs' && method === 'GET') data = job ? [job] : [];
    else if (path === '/api/logins/synthetic-attempt/code') {
      const body = JSON.parse(options.body);
      if (body.code !== '123456' || body.challenge_id !== 'synthetic-challenge') throw new Error('Wrong challenge submitted');
      accountReady = true;
      data = {id:'synthetic-attempt',account_id:account.id,status:'ready',message:'تم حفظ السيشن التجريبية'};
    } else if (path.startsWith('/api/logins')) data = {id:'synthetic-attempt',account_id:account.id,status:'awaiting_code',message:'أدخل الكود',challenge:'email',challenge_id:'synthetic-challenge'};
    else if (path === '/api/jobs' && method === 'POST') {
      const body = JSON.parse(options.body);
      if (body.quantity !== 1 || body.account_ids[0] !== account.id || body.action !== 'comment') throw new Error('Invalid job payload');
      job = {...body,id:'synthetic-job',status:'completed',completed:1,failed:0,created_at:account.updated_at,message:'انتهى الطلب التجريبي',results:[{account_id:account.id,success:true,message:'تمت العملية التجريبية'}]};
      data = job;
    } else throw new Error('Unexpected request: ' + path);
    return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
  };
  const set = (id,value) => { document.getElementById(id).value = value; };
  try {
    document.getElementById('connection-button').click();
    set('api-url', location.origin); set('admin-key','synthetic-browser-test-key-1234567890');
    document.getElementById('connection-form').requestSubmit();
    await waitFor(() => !document.getElementById('connection-dialog').open, 'connection');
    document.getElementById('add-account').click(); set('username','synthetic_account'); set('password','synthetic-password');
    document.getElementById('login-form').requestSubmit();
    await waitFor(() => !document.getElementById('code-form').hidden, 'challenge');
    if (document.getElementById('password').value !== '') throw new Error('Password not cleared');
    set('code','123456'); document.getElementById('code-form').requestSubmit();
    await waitFor(() => !document.getElementById('login-dialog').open && document.getElementById('stat-accounts').textContent === '1', 'saved account');
    const checkbox = document.querySelector('#account-picker input'); checkbox.checked = true; checkbox.dispatchEvent(new Event('change',{bubbles:true}));
    const radio = document.querySelector('input[value="comment"]'); radio.checked = true; radio.dispatchEvent(new Event('change',{bubbles:true}));
    set('post-url','https://www.instagram.com/reel/SYNTHETIC/'); set('comment','تعليق تجريبي');
    document.getElementById('job-form').requestSubmit();
    await waitFor(() => document.getElementById('stat-completed').textContent === '1', 'job');
    document.querySelector('button[data-view="accounts"]').click();
    if (document.getElementById('accounts-view').hidden) throw new Error('Accounts navigation failed');
    document.querySelector('button[data-view="jobs"]').click();
    if (document.getElementById('jobs-section').hidden || !document.getElementById('overview-view').hidden) throw new Error('Jobs navigation failed');
    document.getElementById('disconnect-button').click();
    if (document.getElementById('stat-accounts').textContent !== '0') throw new Error('Disconnect failed');
    return {passed:true,checks:['connect','challenge','clear-password','submit-code','saved-account','create-comment-job','counters','navigation','disconnect'],requests:requests.length};
  } finally { window.fetch = originalFetch; }
})()
