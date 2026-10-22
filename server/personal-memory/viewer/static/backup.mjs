import { esc } from './personal-shared.mjs';

const BASE = '/memory/backup/';

export function createBackupApi(fetcher = globalThis.fetch.bind(globalThis)) {
  let csrf = '';
  async function request(path, options = {}) {
    let response;
    try { response = await fetcher(BASE + path, { credentials: 'same-origin', cache: 'no-store', ...options }); }
    catch { throw new Error('无法连接备份服务，请稍后刷新重试。'); }
    let value;
    try { value = await response.json(); } catch { value = {}; }
    if (!response.ok) {
      if ([401, 403].includes(response.status) && path !== 'api/session') {
        csrf = '';
        try { await session(); } catch { /* Preserve the original action failure. */ }
        throw new Error('会话已更新或需要重新登录，请再次点击操作；刚才的操作未自动重试。');
      }
      throw new Error(typeof value.error === 'string' ? value.error : `备份服务请求失败（${response.status}）。`);
    }
    return value;
  }
  async function session() {
    const value = await request('api/session');
    if (typeof value.csrf !== 'string' || !value.csrf) throw new Error('备份会话未就绪，请刷新重试。');
    csrf = value.csrf;
  }
  return {
    session,
    get: path => request(path),
    async post(path, body) {
      if (!csrf) await session();
      return request(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify(body) });
    },
  };
}

export function missingRequirements(config = {}) {
  return [!config.repository && '私有仓库', !config.token_configured && 'GitHub Token', !config.key_fingerprint && '恢复公钥'].filter(Boolean);
}

function pem(label, buffer) {
  const encoded = btoa(String.fromCharCode(...new Uint8Array(buffer)));
  return `-----BEGIN ${label}-----\n${encoded.match(/.{1,64}/g).join('\n')}\n-----END ${label}-----\n`;
}

export async function generateRecoveryKey() {
  if (!globalThis.crypto?.subtle) throw new Error('当前浏览器无法生成恢复密钥，请通过 HTTPS 或本机安全连接打开此页面。');
  const pair = await crypto.subtle.generateKey({ name: 'RSA-OAEP', modulusLength: 3072, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['encrypt', 'decrypt']);
  return {
    publicKeyPem: pem('PUBLIC KEY', await crypto.subtle.exportKey('spki', pair.publicKey)),
    privateKeyPem: pem('PRIVATE KEY', await crypto.subtle.exportKey('pkcs8', pair.privateKey)),
  };
}

export function safeReleaseUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'github.com' && !url.username && !url.password && /^\/[^/]+\/[^/]+\/releases\//.test(url.pathname) ? url.href : null;
  } catch { return null; }
}

function dateText(value, fallback = '暂无') {
  if (!value) return fallback;
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? fallback : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}
function sizeText(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size <= 0) return '—';
  if (size < 1024) return `${size} B`;
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 ** 2).toFixed(1)} MB`;
}
function downloadPrivateKey(value) {
  const url = URL.createObjectURL(new Blob([value], { type: 'application/x-pem-file' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `mnemosyne-recovery-${new Date().toISOString().replace(/[:.]/g, '-')}.pem`;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function mountBackup(root) {
  const api = createBackupApi();
  let state = null;
  let visible = false;
  let timer = null;
  let refreshing = false;
  let pending = '';
  let dirty = false;
  let filled = false;
  let serviceError = false;
  let publicKey = '';
  root.innerHTML = `
    <div class="backup-heading"><div><p class="backup-eyebrow">PRIVATE ARCHIVE · ENCRYPTED COPY</p><h2>为记忆，留一份副本。</h2><p>加密后保存到你的 GitHub 私有仓库。恢复私钥由你单独保管。</p></div><button type="button" class="quiet-button" id="backupRefresh">刷新状态 ↻</button></div>
    <div id="backupNotice" class="backup-notice" role="status" aria-live="polite" hidden></div>
    <div class="backup-summary" aria-label="备份状态">
      <div><span>自动备份</span><strong id="backupScheduleState">正在读取…</strong><small id="backupNextRun">每天 · Asia/Shanghai</small></div>
      <div><span>最近成功</span><strong id="backupLastSuccess">—</strong><small id="backupLastDetail">尚未读取备份记录</small></div>
      <div><span>当前任务</span><strong id="backupJobState">—</strong><small id="backupJobDetail">先完成下方配置</small></div>
    </div>
    <div class="backup-layout">
      <form id="backupForm" class="backup-panel" autocomplete="off">
        <div class="backup-panel-head"><span class="backup-step">01</span><div><h3>备份设置</h3><p>保存配置后，可验证连接或立即执行一次备份。</p></div><span id="backupDirty" class="backup-unsaved" hidden>未保存</span></div>
        <fieldset id="backupFields" disabled>
          <label class="backup-field" for="backupRepository"><span>GitHub 私有仓库</span><input id="backupRepository" name="repository" type="text" placeholder="owner/repository 或完整 GitHub 仓库地址" maxlength="250" spellcheck="false" autocapitalize="off" required><small>使用已创建、含 README 或已有提交的私有仓库。</small></label>
          <label class="backup-field" for="backupToken"><span>Fine-grained Personal Access Token <em id="backupTokenState">尚未配置</em></span><input id="backupToken" name="token" type="password" placeholder="输入 Token" autocomplete="new-password" spellcheck="false" autocapitalize="off"><small>仅授权这个仓库，Repository permissions → Contents 选择 Read and write。Token 只用于服务器备份，保存后不回显。</small></label>
          <div class="backup-schedule"><label class="backup-toggle"><input id="backupEnabled" name="enabled" type="checkbox"><span><strong>启用每日自动备份</strong><small>默认关闭；开启并保存后按服务器时间执行。</small></span></label><label class="backup-field backup-time" for="backupTime"><span>每天执行时间</span><input id="backupTime" name="time" type="time" value="03:00" required><small>北京时间 · Asia/Shanghai</small></label></div>
          <div class="backup-retention"><label class="backup-field" for="backupDaily"><span>每日版本保留</span><div class="backup-number"><input id="backupDaily" name="keep_daily" type="number" min="1" max="90" value="30" required><span>份</span></div></label><label class="backup-field" for="backupMonthly"><span>每月版本保留</span><div class="backup-number"><input id="backupMonthly" name="keep_monthly" type="number" min="1" max="24" value="12" required><span>份</span></div></label></div>
          <div class="backup-actions"><button id="backupSave" class="primary" type="submit">保存配置</button><span id="backupSaveHint">自动备份尚未启用</span></div>
        </fieldset>
      </form>
      <div class="backup-side">
        <section class="backup-panel backup-key-panel" aria-labelledby="backupKeyTitle"><div class="backup-panel-head"><span class="backup-step">02</span><div><h3 id="backupKeyTitle">恢复密钥</h3><p>私钥只在当前浏览器生成并下载。</p></div></div><p class="backup-key-caption">服务器保存的公钥指纹 · SHA-256</p><code id="backupFingerprint">尚未配置恢复公钥</code><p class="backup-key-note">请把下载的私钥单独妥善保存。恢复备份时必须使用对应私钥；服务器无法替你找回。</p><button id="backupGenerateKey" type="button" disabled>生成并下载恢复私钥 ↓</button><div id="backupKeyPending" class="backup-key-pending" hidden><strong>新公钥待保存</strong><label class="backup-toggle"><input id="backupKeyAcknowledged" type="checkbox"><span>我已保存刚下载的私钥，确认将对应公钥用于之后的备份。</span></label><small>勾选后点击左侧「保存配置」。离开或刷新页面将丢弃待保存公钥。</small></div><a class="backup-tool-link" href="/memory/backup/restore-tool.py" download="restore_backup.py">下载离线恢复工具 ↗</a><small class="backup-restore-note">在本机配合加密备份与私钥恢复；本页面不直接覆盖生产数据。</small></section>
        <section class="backup-panel backup-run-panel" aria-labelledby="backupRunTitle"><div class="backup-panel-head"><span class="backup-step">03</span><div><h3 id="backupRunTitle">验证与执行</h3><p>使用已保存的配置。</p></div></div><p id="backupPrerequisites" class="backup-preconditions">正在读取配置…</p><button id="backupCheck" type="button" disabled>验证仓库连接</button><button id="backupRun" type="button" class="primary" disabled>立即备份并上传</button><small>任务在服务器后台运行，关闭页面后仍会继续。</small></section>
      </div>
    </div>
    <section class="backup-history" aria-labelledby="backupHistoryTitle"><div class="section-head"><h2 id="backupHistoryTitle">备份记录</h2><span id="backupHistoryCount">尚未读取</span></div><div id="backupHistoryList" class="backup-history-list"><p class="backup-empty">正在读取备份记录…</p></div><p class="backup-history-note">仅在上传验证成功后清理超出保留数量的版本。下载的备份为加密文件。</p></section>`;
  const $ = selector => root.querySelector(selector);
  const form = $('#backupForm');

  function notice(message, error = false) {
    $('#backupNotice').textContent = message;
    $('#backupNotice').hidden = !message;
    $('#backupNotice').classList.toggle('is-error', error);
    $('#backupNotice').setAttribute('role', error ? 'alert' : 'status');
  }
  function fill(config) {
    $('#backupRepository').value = config.repository || '';
    $('#backupTime').value = config.time || '03:00';
    $('#backupEnabled').checked = config.enabled === true;
    $('#backupDaily').value = config.keep_daily ?? 30;
    $('#backupMonthly').value = config.keep_monthly ?? 12;
    filled = true;
  }
  function controls() {
    const blocked = !state || serviceError || Boolean(pending) || Boolean(state.running);
    $('#backupFields').disabled = blocked;
    $('#backupGenerateKey').disabled = blocked;
    $('#backupKeyAcknowledged').disabled = blocked;
    $('#backupRefresh').disabled = refreshing || Boolean(pending);
    const missing = missingRequirements(state?.config);
    $('#backupCheck').disabled = blocked || dirty || !state?.config?.repository || !state?.config?.token_configured;
    $('#backupRun').disabled = blocked || dirty || missing.length > 0;
    $('#backupDirty').hidden = !dirty;
    $('#backupPrerequisites').textContent = !state ? '等待备份服务连接。' : state.running ? '备份正在运行，完成后可继续操作。' : dirty ? '有未保存的更改，请先保存配置。' : missing.length ? `还需配置：${missing.join('、')}。` : '仓库、Token 与恢复公钥已配置。可先验证连接。';
    $('#backupSave').textContent = pending === 'save' ? '正在保存…' : '保存配置';
    $('#backupGenerateKey').textContent = pending === 'key' ? '正在生成密钥…' : state?.config?.key_fingerprint ? '生成并下载新的恢复私钥 ↓' : '生成并下载恢复私钥 ↓';
    $('#backupCheck').textContent = pending === 'check' ? '正在验证连接…' : '验证仓库连接';
    $('#backupRun').textContent = pending === 'run' ? '正在提交任务…' : state?.running ? '正在备份并上传…' : '立即备份并上传';
    $('#backupSaveHint').textContent = $('#backupEnabled').checked ? '保存后启用每日自动备份' : '自动备份保持关闭';
    root.setAttribute('aria-busy', String(Boolean(pending)));
  }
  function renderState() {
    if (!state) { controls(); return; }
    const config = state.config || {};
    if (!filled || !dirty) fill(config);
    $('#backupScheduleState').textContent = config.enabled ? '已启用' : '未启用';
    $('#backupNextRun').textContent = config.enabled ? `下次 ${dateText(state.next_run, '等待调度')} · 北京时间` : '每日计划关闭 · 可手动备份';
    const success = state.last_success;
    $('#backupLastSuccess').textContent = dateText(typeof success === 'string' ? success : success?.created_at, '尚无成功备份');
    $('#backupLastDetail').textContent = success ? `已加密并上传${success.size ? ` · ${sizeText(success.size)}` : ''}` : '完成首次备份后显示';
    $('#backupJobState').textContent = state.running ? '备份进行中' : '空闲';
    $('#backupJobDetail').textContent = state.running ? '正在打包、加密或上传，请稍候' : '等待手动操作或每日计划';
    $('#backupTokenState').textContent = config.token_configured ? '已配置' : '尚未配置';
    $('#backupToken').placeholder = config.token_configured ? '已配置 · 留空保留现有 Token' : '输入 Token';
    $('#backupFingerprint').textContent = config.key_fingerprint || '尚未配置恢复公钥';
    const history = Array.isArray(state.history) ? state.history : [];
    $('#backupHistoryCount').textContent = `${history.length} 条 · 北京时间`;
    $('#backupHistoryList').innerHTML = history.length ? history.map(item => {
      const status = { success: '成功', failed: '失败', running: '进行中' }[item.status] || '状态未知';
      const release = safeReleaseUrl(item.url);
      const local = item.local_available && /^[a-zA-Z0-9_-]+$/.test(item.id || '');
      return `<article class="backup-history-item"><div class="backup-history-main"><span class="backup-result ${item.status === 'success' ? 'is-success' : item.status === 'failed' ? 'is-failed' : ''}">${status}</span><time>${esc(dateText(item.created_at))}</time><span class="backup-file-size">${esc(sizeText(item.size))}</span></div>${item.error ? `<p class="backup-history-error">${esc(item.error)}</p>` : ''}${item.warning ? `<p class="backup-history-warning">${esc(item.warning)}</p>` : ''}<div class="backup-history-meta">${item.sha256 ? `<details><summary>SHA-256 校验值</summary><code>${esc(item.sha256)}</code></details>` : '<span></span>'}<div class="backup-history-links">${local ? `<a href="${BASE}api/download/${encodeURIComponent(item.id)}" download>下载加密备份 ↓</a>` : ''}${release ? `<a href="${esc(release)}" target="_blank" rel="noopener noreferrer">GitHub Release ↗</a>` : ''}</div></div></article>`;
    }).join('') : '<div class="backup-empty"><strong>还没有备份记录</strong><p>完成设置并保存恢复私钥后，可执行第一次备份。</p></div>';
    controls();
  }
  async function refresh() {
    if (refreshing || pending) return;
    refreshing = true; controls();
    try {
      const value = await api.get('api/state');
      if (!value.config || value.service_ok !== true) throw new Error('备份服务暂未就绪，请稍后重试。');
      const recovered = serviceError;
      state = value; serviceError = false; renderState();
      if (recovered) notice('备份服务已重新连接。');
    } catch (error) { serviceError = true; notice(error.message, true); }
    finally { refreshing = false; controls(); }
  }
  async function action(name, callback) {
    if (pending || state?.running) return;
    pending = name; notice(''); controls();
    try { await callback(); }
    catch (error) { notice(error.message, true); }
    finally { pending = ''; controls(); }
  }
  form.addEventListener('input', () => { dirty = true; controls(); });
  $('#backupKeyAcknowledged').addEventListener('change', controls);
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    if (publicKey && !$('#backupKeyAcknowledged').checked) { notice('请确认已妥善保存刚下载的恢复私钥，再保存新公钥。', true); $('#backupKeyAcknowledged').focus(); return; }
    const token = $('#backupToken').value.trim();
    const body = { repository: $('#backupRepository').value.trim(), time: $('#backupTime').value, enabled: $('#backupEnabled').checked, keep_daily: Number($('#backupDaily').value), keep_monthly: Number($('#backupMonthly').value) };
    if (token) body.token = token;
    if (publicKey) body.public_key = publicKey;
    if (body.enabled && (!body.repository || !(token || state?.config?.token_configured) || !(publicKey || state?.config?.key_fingerprint))) { notice('启用每日备份前，请先填写私有仓库、Token，并生成和保存恢复私钥。', true); return; }
    action('save', async () => {
      const value = await api.post('api/config', body);
      if (!value.config) throw new Error('服务器未返回保存结果，请刷新状态确认。');
      state = value; serviceError = false; dirty = false; publicKey = ''; $('#backupKeyAcknowledged').checked = false; $('#backupKeyPending').hidden = true;
      $('#backupToken').value = '';
      fill(state.config); renderState(); notice(state.config.enabled ? '配置已保存，每日自动备份已启用。' : '配置已保存，自动备份保持关闭。');
    }).finally(() => { delete body.token; });
  });
  $('#backupGenerateKey').addEventListener('click', () => {
    if ((state?.config?.key_fingerprint || publicKey) && !window.confirm('生成新的恢复密钥将替换之后备份使用的公钥。旧备份仍需原来的私钥恢复，请继续保留旧私钥。确定生成并下载新私钥吗？')) return;
    action('key', async () => {
      const pair = await generateRecoveryKey();
      downloadPrivateKey(pair.privateKeyPem);
      pair.privateKeyPem = '';
      publicKey = pair.publicKeyPem; dirty = true;
      $('#backupKeyAcknowledged').checked = false; $('#backupKeyPending').hidden = false;
      notice('恢复私钥已发起下载。请确认下载完成并妥善保存，再勾选确认并保存配置。');
    });
  });
  $('#backupCheck').addEventListener('click', () => action('check', async () => {
    const result = await api.post('api/check', {});
    if (!result.ok) throw new Error(result.message || '仓库连接验证失败。');
    notice(`${result.message || '私有仓库连接正常'}${result.repository ? ` · ${result.repository}` : ''}`);
  }));
  $('#backupRun').addEventListener('click', () => action('run', async () => {
    const value = await api.post('api/run', {});
    if (!value.config) throw new Error('服务器未返回任务状态，请刷新状态确认。');
    state = value; renderState(); notice('备份任务已提交，正在服务器后台执行。');
  }));
  $('#backupRefresh').addEventListener('click', refresh);
  controls();
  return {
    show() {
      if (visible) return;
      visible = true;
      refresh();
      timer = setInterval(() => { if (!document.hidden) refresh(); }, 15000);
    },
    hide() { visible = false; clearInterval(timer); timer = null; },
  };
}
