const KEY="azama_v1_data";
let data=JSON.parse(localStorage.getItem(KEY)||"null")||{accounts:[],channels:[],videos:[],month:new Date().toISOString().slice(0,7)};
let state={view:"dashboard",accountId:null,channelId:null};

function save(){localStorage.setItem(KEY,JSON.stringify(data));}
function id(){return Date.now().toString(36)+Math.random().toString(36).slice(2,7)}
function money(n){return new Intl.NumberFormat("en-US",{minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(n)||0)+" $"}
function esc(s){return String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]))}
function toast(t){const e=document.getElementById("toast");e.textContent=t;e.classList.add("show");setTimeout(()=>e.classList.remove("show"),1800)}
function ensureMonth(){const m=new Date().toISOString().slice(0,7);if(data.month!==m){data.accounts.forEach(a=>a.monthlyProfit=0);data.month=m;save()}}
ensureMonth();

const accountBy=id=>data.accounts.find(x=>x.id===id);
const channelBy=id=>data.channels.find(x=>x.id===id);
const videosOf=id=>data.videos.filter(x=>x.channelId===id);
function accountChannels(id){return data.channels.filter(c=>c.accountId===id)}

function render(){
  ensureMonth();
  document.querySelectorAll(".view").forEach(v=>v.classList.remove("active"));
  const title={dashboard:"لوحة التحكم",accounts:"الحسابات",channels:"القنوات"}[state.view]||"عظمة";
  document.getElementById("pageTitle").textContent=title;
  document.getElementById(state.view+"View").classList.add("active");
  document.querySelectorAll(".nav-item").forEach(n=>n.classList.toggle("active",n.dataset.view===state.view));
  if(state.view==="dashboard")renderDashboard();
  if(state.view==="accounts")renderAccounts();
  if(state.view==="channels")renderChannels();
}
function renderDashboard(){
 const total=data.accounts.reduce((s,a)=>s+(+a.monthlyProfit||0),0);
 const pending=data.videos.filter(v=>v.status==="accepted").reduce((s,v)=>s+(+v.profit||0),0);
 document.getElementById("dashboardView").innerHTML=`
 <div class="stats">
  <div class="stat"><div class="stat-label">الحسابات</div><div class="stat-value">${data.accounts.length}</div></div>
  <div class="stat"><div class="stat-label">القنوات</div><div class="stat-value">${data.channels.length}</div></div>
  <div class="stat"><div class="stat-label">أرباح الشهر</div><div class="stat-value">${money(total)}</div></div>
  <div class="stat"><div class="stat-label">أرباح مقبولة</div><div class="stat-value">${money(pending)}</div></div>
 </div>
 <div class="section-row"><h2>آخر الحسابات</h2><button class="secondary" onclick="openAccountModal()">+ حساب جديد</button></div>
 <div class="grid">${data.accounts.slice(-6).reverse().map(accountCard).join("")||'<div class="empty" style="grid-column:1/-1">لسه مفيش حسابات. ابدأ بإضافة أول حساب.</div>'}</div>`;
}
function accountCard(a){return `<div class="card account-card" onclick="openAccount('${a.id}')">
 <div class="card-head"><div><div class="card-title">${esc(a.username||"بدون اسم")}</div><div class="small muted">${esc(a.email)}</div></div><span class="pill">${esc(a.platform)}</span></div>
 <div class="money">${money(a.monthlyProfit)}</div><div class="small muted">${accountChannels(a.id).length} قناة YouTube</div>
 </div>`}
function renderAccounts(){
 document.getElementById("accountsView").innerHTML=`
 <div class="section-row"><h2>كل الحسابات</h2><button class="primary" onclick="openAccountModal()">+ إضافة حساب</button></div>
 <div class="grid">${data.accounts.map(a=>accountCard(a)+`<div class="actions" style="display:none"></div>`).join("")||'<div class="empty" style="grid-column:1/-1">لا توجد حسابات.</div>'}</div>`;
}
function openAccount(idv){
 state.accountId=idv; const a=accountBy(idv); state.view="channels"; renderChannels(a);
}
function renderChannels(a=accountBy(state.accountId)){
 if(!a){state.view="accounts";render();return}
 document.getElementById("channelsView").innerHTML=`
 <div class="back"><button class="secondary" onclick="state.view='accounts';render()">← الحسابات</button></div>
 <div class="card" style="margin-bottom:15px"><div class="card-head"><div><div class="card-title">${esc(a.username)}</div><div class="small muted">${esc(a.email)}</div></div><span class="pill">${esc(a.platform)}</span></div><div class="money">${money(a.monthlyProfit)} <span class="small muted">هذا الشهر</span></div></div>
 <div class="section-row"><h2>قنوات YouTube</h2><button class="primary" onclick="openChannelModal('${a.id}')">+ إضافة قناة</button></div>
 <div class="grid">${accountChannels(a.id).map(c=>`<div class="card account-card" onclick="openChannel('${c.id}')"><div class="card-head"><div class="card-title">▶ ${esc(c.name)}</div><span class="pill">${videosOf(c.id).length} فيديو</span></div><div class="money">${money(videosOf(c.id).reduce((s,v)=>s+(+v.profit||0),0))}</div><div class="actions"><button class="danger" onclick="event.stopPropagation();deleteChannel('${c.id}')">حذف</button></div></div>`).join("")||'<div class="empty" style="grid-column:1/-1">مفيش قنوات للحساب ده.</div>'}</div>`;
}
function renderChannelsRoot(){state.view="channels";state.accountId=null;render()}
function openChannel(cid){
 state.channelId=cid; const c=channelBy(cid); const a=accountBy(c.accountId);
 document.getElementById("channelsView").innerHTML=`
 <div class="back"><button class="secondary" onclick="openAccount('${a.id}')">← ${esc(a.username)}</button></div>
 <div class="section-row"><div><h2>${esc(c.name)}</h2><div class="small muted">${esc(a.username)}</div></div><button class="primary" onclick="openVideoModal('${c.id}')">+ إضافة فيديو</button></div>
 <div class="table-wrap"><table class="table"><thead><tr><th>اسم الفيديو</th><th>الحالة</th><th>إجمالي الربح</th><th>موعد تسليم الربح</th><th></th></tr></thead><tbody>
 ${videosOf(c.id).map(v=>`<tr><td>${esc(v.name)}</td><td><div class="status">
 <button class="${v.status==="accepted"?"selected good":""}" onclick="setStatus('${v.id}','accepted')">مقبول</button>
 <button class="${v.status==="rejected"?"selected bad":""}" onclick="setStatus('${v.id}','rejected')">مرفوض</button>
 </div></td><td>${money(v.profit)}</td><td>${v.due?new Date(v.due).toLocaleString("ar-EG"):"—"}</td><td><button class="danger" onclick="deleteVideo('${v.id}')">حذف</button></td></tr>`).join("")||'<tr><td colspan="5" class="muted">لا توجد فيديوهات.</td></tr>'}
 </tbody></table></div>`;
}
function openAccountModal(){
 showModal(`<h2>إضافة حساب</h2><form class="form" id="accountForm">
 <div class="field"><label>المنصة</label><select name="platform"><option>Whop</option><option>Content Rewards</option></select></div>
 <div class="field"><label>الإيميل</label><input name="email" type="email" required></div>
 <div class="field"><label>Username</label><input name="username" required></div>
 <div class="field"><label>ربح الشهر الحالي ($)</label><input name="profit" type="number" step="0.01" value="0"></div>
 <div class="modal-actions"><button class="primary">حفظ</button><button type="button" class="secondary" onclick="closeModal()">إلغاء</button></div></form>`);
 document.getElementById("accountForm").onsubmit=e=>{e.preventDefault();const f=new FormData(e.target);data.accounts.push({id:id(),platform:f.get("platform"),email:f.get("email"),username:f.get("username"),monthlyProfit:+f.get("profit")||0});save();closeModal();toast("تم إضافة الحساب");render()}
}
function openChannelModal(accountId){
 showModal(`<h2>إضافة قناة YouTube</h2><form class="form" id="channelForm"><div class="field"><label>اسم القناة</label><input name="name" required></div><div class="modal-actions"><button class="primary">حفظ</button><button type="button" class="secondary" onclick="closeModal()">إلغاء</button></div></form>`);
 document.getElementById("channelForm").onsubmit=e=>{e.preventDefault();const f=new FormData(e.target);data.channels.push({id:id(),accountId,name:f.get("name")});save();closeModal();toast("تم إضافة القناة");renderChannels()}
}
function openVideoModal(channelId){
 showModal(`<h2>إضافة فيديو</h2><form class="form" id="videoForm">
 <div class="field"><label>اسم الفيديو</label><input name="name" required></div>
 <div class="field"><label>الحالة</label><select name="status"><option value="accepted">مقبول</option><option value="rejected">مرفوض</option></select></div>
 <div class="field"><label>إجمالي الربح ($)</label><input name="profit" type="number" step="0.01" value="0"></div>
 <div class="field"><label>موعد تسليم الربح</label><input name="due" type="datetime-local"></div>
 <div class="modal-actions"><button class="primary">حفظ</button><button type="button" class="secondary" onclick="closeModal()">إلغاء</button></div></form>`);
 document.getElementById("videoForm").onsubmit=e=>{e.preventDefault();const f=new FormData(e.target);data.videos.push({id:id(),channelId,name:f.get("name"),status:f.get("status"),profit:+f.get("profit")||0,due:f.get("due")});save();closeModal();toast("تم إضافة الفيديو");openChannel(channelId)}
}
function setStatus(vid,status){const v=data.videos.find(x=>x.id===vid);if(v){v.status=status;save();openChannel(v.channelId);toast(status==="accepted"?"تم قبول الفيديو":"تم رفض الفيديو")}}
function deleteVideo(vid){if(!confirm("حذف الفيديو؟"))return;data.videos=data.videos.filter(v=>v.id!==vid);save();openChannel(state.channelId);toast("تم حذف الفيديو")}
function deleteChannel(cid){if(!confirm("حذف القناة وكل فيديوهاتها؟"))return;data.videos=data.videos.filter(v=>v.channelId!==cid);data.channels=data.channels.filter(c=>c.id!==cid);save();renderChannels()}
function showModal(html){document.getElementById("modal").innerHTML=html;document.getElementById("modalBackdrop").classList.add("open")}
function closeModal(){document.getElementById("modalBackdrop").classList.remove("open")}
document.getElementById("modalBackdrop").addEventListener("click",e=>{if(e.target.id==="modalBackdrop")closeModal()});
document.querySelectorAll(".nav-item").forEach(n=>n.onclick=()=>{state.view=n.dataset.view;state.accountId=null;state.channelId=null;render()});
document.getElementById("quickAdd").onclick=openAccountModal;
render();
