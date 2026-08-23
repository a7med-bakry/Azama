const KEY = "azama_v1_data";

let data = JSON.parse(localStorage.getItem(KEY) || "null") || {
  accounts: [],
  channels: [],
  videos: []
};

let state = {
  view: "dashboard",
  accountId: null,
  channelId: null
};

/* =========================
   Helpers
========================= */

function save() {
  localStorage.setItem(KEY, JSON.stringify(data));
}

function id() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function currentMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function money(value) {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(Number(value) || 0) + " $";
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  }[char]));
}

function toast(message) {
  const element = document.getElementById("toast");

  element.textContent = message;
  element.classList.add("show");

  setTimeout(() => {
    element.classList.remove("show");
  }, 1800);
}

function accountBy(accountId) {
  return data.accounts.find(account => account.id === accountId);
}

function channelBy(channelId) {
  return data.channels.find(channel => channel.id === channelId);
}

function videoBy(videoId) {
  return data.videos.find(video => video.id === videoId);
}

function accountChannels(accountId) {
  return data.channels.filter(channel => channel.accountId === accountId);
}

function channelVideos(channelId) {
  return data.videos.filter(video => video.channelId === channelId);
}

/* =========================
   PROFIT SYSTEM
   Accepted videos only
========================= */

function videoCountsForProfit(video) {
  return video.status === "accepted";
}

function videoProfit(video) {
  return videoCountsForProfit(video)
    ? Number(video.profit) || 0
    : 0;
}

function channelProfit(channelId) {
  return channelVideos(channelId)
    .reduce((total, video) => total + videoProfit(video), 0);
}

function accountProfit(accountId) {
  return accountChannels(accountId)
    .reduce((total, channel) => total + channelProfit(channel.id), 0);
}

function agencyProfit() {
  return data.accounts
    .reduce((total, account) => total + accountProfit(account.id), 0);
}

function monthlyVideoProfit(video) {
  if (!videoCountsForProfit(video)) {
    return 0;
  }

  const month = video.month || currentMonth();

  if (month !== currentMonth()) {
    return 0;
  }

  return Number(video.profit) || 0;
}

function monthlyAccountProfit(accountId) {
  return accountChannels(accountId)
    .reduce((total, channel) => {
      return total + channelVideos(channel.id)
        .reduce((sum, video) => sum + monthlyVideoProfit(video), 0);
    }, 0);
}

function monthlyAgencyProfit() {
  return data.videos
    .reduce((total, video) => total + monthlyVideoProfit(video), 0);
}

/* =========================
   Rendering
========================= */

function render() {

  document.querySelectorAll(".view").forEach(view => {
    view.classList.remove("active");
  });

  const title = {
    dashboard: "لوحة التحكم",
    accounts: "الحسابات",
    channels: "القنوات"
  }[state.view] || "عظمة";

  document.getElementById("pageTitle").textContent = title;

  const currentView = document.getElementById(
    state.view + "View"
  );

  if (currentView) {
    currentView.classList.add("active");
  }

  document.querySelectorAll(".nav-item").forEach(item => {
    item.classList.toggle(
      "active",
      item.dataset.view === state.view
    );
  });

  if (state.view === "dashboard") {
    renderDashboard();
  }

  if (state.view === "accounts") {
    renderAccounts();
  }

  if (state.view === "channels") {
    renderChannels();
  }
}

/* =========================
   Dashboard
========================= */

function renderDashboard() {

  const acceptedVideos = data.videos.filter(
    video => video.status === "accepted"
  ).length;

  const rejectedVideos = data.videos.filter(
    video => video.status === "rejected"
  ).length;

  const monthlyProfit = monthlyAgencyProfit();

  document.getElementById("dashboardView").innerHTML = `

    <div class="stats">

      <div class="stat">
        <div class="stat-label">الحسابات</div>
        <div class="stat-value">
          ${data.accounts.length}
        </div>
      </div>

      <div class="stat">
        <div class="stat-label">القنوات</div>
        <div class="stat-value">
          ${data.channels.length}
        </div>
      </div>

      <div class="stat">
        <div class="stat-label">أرباح الشهر</div>
        <div class="stat-value">
          ${money(monthlyProfit)}
        </div>
      </div>

      <div class="stat">
        <div class="stat-label">إجمالي الأرباح</div>
        <div class="stat-value">
          ${money(agencyProfit())}
        </div>
      </div>

    </div>

    <div class="stats">

      <div class="stat">
        <div class="stat-label">الفيديوهات المقبولة</div>
        <div class="stat-value">
          ${acceptedVideos}
        </div>
      </div>

      <div class="stat">
        <div class="stat-label">الفيديوهات المرفوضة</div>
        <div class="stat-value">
          ${rejectedVideos}
        </div>
      </div>

    </div>

    <div class="section-row">
      <h2>الحسابات</h2>

      <button class="secondary" onclick="openAccountModal()">
        + حساب جديد
      </button>
    </div>

    <div class="grid">

      ${
        data.accounts.length
        ? data.accounts
            .slice()
            .reverse()
            .map(accountCard)
            .join("")
        : `
          <div class="empty" style="grid-column:1/-1">
            لسه مفيش حسابات.<br>
            ابدأ بإضافة أول حساب.
          </div>
        `
      }

    </div>
  `;
}

/* =========================
   Account Card
========================= */

function accountCard(account) {

  const profit = accountProfit(account.id);

  const monthlyProfit = monthlyAccountProfit(account.id);

  const channels = accountChannels(account.id).length;

  return `
    <div
      class="card account-card"
      onclick="openAccount('${account.id}')"
    >

      <div class="card-head">

        <div>

          <div class="card-title">
            ${esc(account.username || "بدون اسم")}
          </div>

          <div class="small muted">
            ${esc(account.email)}
          </div>

        </div>

      </div>

      <div class="money">
        ${money(monthlyProfit)}
      </div>

      <div class="small muted">
        أرباح الشهر
      </div>

      <div
        class="small muted"
        style="margin-top:8px"
      >
        إجمالي الأرباح: ${money(profit)}
      </div>

      <div
        class="small muted"
        style="margin-top:5px"
      >
        ${channels} قناة YouTube
      </div>

    </div>
  `;
}

/* =========================
   Accounts
========================= */

function renderAccounts() {

  document.getElementById("accountsView").innerHTML = `

    <div class="section-row">

      <h2>كل الحسابات</h2>

      <button
        class="primary"
        onclick="openAccountModal()"
      >
        + إضافة حساب
      </button>

    </div>

    <div class="grid">

      ${
        data.accounts.length
        ? data.accounts.map(accountCard).join("")
        : `
          <div
            class="empty"
            style="grid-column:1/-1"
          >
            لا توجد حسابات.
          </div>
        `
      }

    </div>
  `;
}

/* =========================
   Account Details
========================= */

function openAccount(accountId) {

  state.accountId = accountId;
  state.channelId = null;
  state.view = "channels";

  renderChannels();
}

/* =========================
   Channels
========================= */

function renderChannels() {

  const account = accountBy(state.accountId);

  if (!account) {
    state.view = "accounts";
    render();
    return;
  }

  const channels = accountChannels(account.id);

  document.getElementById("channelsView").innerHTML = `

    <div class="back">

      <button
        class="secondary"
        onclick="
          state.view='accounts';
          state.accountId=null;
          render();
        "
      >
        ← الحسابات
      </button>

    </div>

    <div
      class="card"
      style="margin-bottom:15px"
    >

      <div class="card-head">

        <div>

          <div class="card-title">
            ${esc(account.username)}
          </div>

          <div class="small muted">
            ${esc(account.email)}
          </div>

        </div>

      </div>

      <div class="money">
        ${money(monthlyAccountProfit(account.id))}
      </div>

      <div class="small muted">
        أرباح الشهر
      </div>

      <div
        class="small muted"
        style="margin-top:8px"
      >
        إجمالي الأرباح:
        ${money(accountProfit(account.id))}
      </div>

    </div>

    <div class="section-row">

      <h2>قنوات YouTube</h2>

      <button
        class="primary"
        onclick="openChannelModal('${account.id}')"
      >
        + إضافة قناة
      </button>

    </div>

    <div class="grid">

      ${
        channels.length
        ? channels.map(channelCard).join("")
        : `
          <div
            class="empty"
            style="grid-column:1/-1"
          >
            مفيش قنوات للحساب ده.
          </div>
        `
      }

    </div>
  `;
}

function channelCard(channel) {

  const videos = channelVideos(channel.id);

  return `
    <div
      class="card account-card"
      onclick="openChannel('${channel.id}')"
    >

      <div class="card-head">

        <div class="card-title">
          ▶ ${esc(channel.name)}
        </div>

        <span class="pill">
          ${videos.length} فيديو
        </span>

      </div>

      <div class="money">
        ${money(channelProfit(channel.id))}
      </div>

      <div class="small muted">
        إجمالي أرباح القناة
      </div>

      <div class="actions">

        <button
          class="danger"
          onclick="
            event.stopPropagation();
            deleteChannel('${channel.id}')
          "
        >
          حذف
        </button>

      </div>

    </div>
  `;
}

/* =========================
   Channel Details
========================= */

function openChannel(channelId) {

  state.channelId = channelId;

  const channel = channelBy(channelId);

  if (!channel) return;

  const account = accountBy(channel.accountId);

  const videos = channelVideos(channel.id);

  document.getElementById("channelsView").innerHTML = `

    <div class="back">

      <button
        class="secondary"
        onclick="openAccount('${account.id}')"
      >
        ← ${esc(account.username)}
      </button>

    </div>

    <div class="section-row">

      <div>

        <h2>
          ${esc(channel.name)}
        </h2>

        <div class="small muted">
          ${esc(account.username)}
        </div>

        <div
          class="money"
          style="margin-top:8px"
        >
          ${money(channelProfit(channel.id))}
        </div>

        <div class="small muted">
          إجمالي أرباح القناة — المقبول فقط
        </div>

      </div>

      <button
        class="primary"
        onclick="openVideoModal('${channel.id}')"
      >
        + إضافة فيديو
      </button>

    </div>

    <div class="table-wrap">

      <table class="table">

        <thead>

          <tr>

            <th>اسم الفيديو</th>

            <th>الحالة</th>

            <th>إجمالي الربح</th>

            <th>موعد تسليم الربح</th>

            <th></th>

          </tr>

        </thead>

        <tbody>

          ${
            videos.length
            ? videos.map(videoRow).join("")
            : `
              <tr>
                <td
                  colspan="5"
                  class="muted"
                >
                  لا توجد فيديوهات.
                </td>
              </tr>
            `
          }

        </tbody>

      </table>

    </div>
  `;
}

function videoRow(video) {

  return `
    <tr>

      <td>
        ${esc(video.name)}
      </td>

      <td>

        <div class="status">

          <button
            class="${
              video.status === "accepted"
              ? "selected good"
              : ""
            }"
            onclick="
              setStatus('${video.id}', 'accepted')
            "
          >
            مقبول
          </button>

          <button
            class="${
              video.status === "rejected"
              ? "selected bad"
              : ""
            }"
            onclick="
              setStatus('${video.id}', 'rejected')
            "
          >
            مرفوض
          </button>

        </div>

      </td>

      <td>

        ${
          video.status === "accepted"
          ? money(video.profit)
          : `
            <span class="muted">
              $0.00
            </span>
          `
        }

      </td>

      <td>

        ${
          video.due
          ? new Date(video.due).toLocaleString("ar-EG")
          : "—"
        }

      </td>

      <td>

        <button
          class="danger"
          onclick="
            deleteVideo('${video.id}')
          "
        >
          حذف
        </button>

      </td>

    </tr>
  `;
}

/* =========================
   Add Account
========================= */

function openAccountModal() {

  showModal(`

    <h2>إضافة حساب</h2>

    <form
      class="form"
      id="accountForm"
    >

      <div class="field">

        <label>
          الإيميل
        </label>

        <input
          name="email"
          type="email"
          required
          placeholder="example@email.com"
        >

      </div>

      <div class="field">

        <label>
          Username
        </label>

        <input
          name="username"
          required
          placeholder="@username"
        >

      </div>

      <div class="modal-actions">

        <button
          class="primary"
        >
          حفظ الحساب
        </button>

        <button
          type="button"
          class="secondary"
          onclick="closeModal()"
        >
          إلغاء
        </button>

      </div>

    </form>
  `);

  document.getElementById("accountForm").onsubmit = event => {

    event.preventDefault();

    const form = new FormData(event.target);

    data.accounts.push({

      id: id(),

      email: form.get("email"),

      username: form.get("username")

    });

    save();

    closeModal();

    toast("تم إضافة الحساب");

    render();
  };
}

/* =========================
   Add Channel
========================= */

function openChannelModal(accountId) {

  showModal(`

    <h2>إضافة قناة YouTube</h2>

    <form
      class="form"
      id="channelForm"
    >

      <div class="field">

        <label>
          اسم القناة
        </label>

        <input
          name="name"
          required
          placeholder="اسم قناة YouTube"
        >

      </div>

      <div class="modal-actions">

        <button
          class="primary"
        >
          حفظ القناة
        </button>

        <button
          type="button"
          class="secondary"
          onclick="closeModal()"
        >
          إلغاء
        </button>

      </div>

    </form>
  `);

  document.getElementById("channelForm").onsubmit = event => {

    event.preventDefault();

    const form = new FormData(event.target);

    data.channels.push({

      id: id(),

      accountId: accountId,

      name: form.get("name")

    });

    save();

    closeModal();

    toast("تم إضافة القناة");

    renderChannels();
  };
}

/* =========================
   Add Video
========================= */

function openVideoModal(channelId) {

  showModal(`

    <h2>إضافة فيديو</h2>

    <form
      class="form"
      id="videoForm"
    >

      <div class="field">

        <label>
          اسم الفيديو
        </label>

        <input
          name="name"
          required
          placeholder="اسم الفيديو"
        >

      </div>

      <div class="field">

        <label>
          الحالة
        </label>

        <select name="status">

          <option value="accepted">
            مقبول
          </option>

          <option value="rejected">
            مرفوض
          </option>

        </select>

      </div>

      <div class="field">

        <label>
          الربح ($)
        </label>

        <input
          name="profit"
          type="number"
          step="0.01"
          min="0"
          value="0"
        >

      </div>

      <div class="field">

        <label>
          موعد تسليم الربح
        </label>

        <input
          name="due"
          type="datetime-local"
        >

      </div>

      <div class="modal-actions">

        <button
          class="primary"
        >
          حفظ الفيديو
        </button>

        <button
          type="button"
          class="secondary"
          onclick="closeModal()"
        >
          إلغاء
        </button>

      </div>

    </form>
  `);

  document.getElementById("videoForm").onsubmit = event => {

    event.preventDefault();

    const form = new FormData(event.target);

    const status = form.get("status");

    const profit = Number(form.get("profit")) || 0;

    data.videos.push({

      id: id(),

      channelId: channelId,

      name: form.get("name"),

      status: status,

      profit: profit,

      due: form.get("due"),

      month: currentMonth(),

      createdAt: new Date().toISOString()

    });

    save();

    closeModal();

    toast("تم إضافة الفيديو");

    openChannel(channelId);
  };
}

/* =========================
   Status
========================= */

function setStatus(videoId, status) {

  const video = videoBy(videoId);

  if (!video) return;

  video.status = status;

  save();

  openChannel(video.channelId);

  toast(
    status === "accepted"
      ? "تم قبول الفيديو — الربح اتضاف"
      : "تم رفض الفيديو — الربح اتشال"
  );
}

/* =========================
   Delete Video
========================= */

function deleteVideo(videoId) {

  if (!confirm("حذف الفيديو؟")) {
    return;
  }

  const video = videoBy(videoId);

  if (!video) return;

  const channelId = video.channelId;

  data.videos = data.videos.filter(
    item => item.id !== videoId
  );

  save();

  toast("تم حذف الفيديو");

  openChannel(channelId);
}

/* =========================
   Delete Channel
========================= */

function deleteChannel(channelId) {

  if (!confirm("حذف القناة وكل فيديوهاتها؟")) {
    return;
  }

  data.videos = data.videos.filter(
    video => video.channelId !== channelId
  );

  data.channels = data.channels.filter(
    channel => channel.id !== channelId
  );

  save();

  toast("تم حذف القناة");

  renderChannels();
}

/* =========================
   Modal
========================= */

function showModal(html) {

  document.getElementById("modal").innerHTML = html;

  document
    .getElementById("modalBackdrop")
    .classList.add("open");
}

function closeModal() {

  document
    .getElementById("modalBackdrop")
    .classList.remove("open");
}

document
  .getElementById("modalBackdrop")
  .addEventListener("click", event => {

    if (event.target.id === "modalBackdrop") {
      closeModal();
    }

  });

/* =========================
   Navigation
========================= */

document
  .querySelectorAll(".nav-item")
  .forEach(item => {

    item.onclick = () => {

      state.view = item.dataset.view;

      state.accountId = null;

      state.channelId = null;

      render();
    };

  });

document
  .getElementById("quickAdd")
  .onclick = openAccountModal;

/* =========================
   Start
========================= */

render();
