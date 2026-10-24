const t = text => globalThis.EvoMynI18n?.t(text) ?? text;
// Categorized archive adaptation of wysie/mnemosyne-dashboard's app.js presentation.
// Uses its selectors, escaped HTML/empty states, drawer renderer, shell and CSS components.
// MIT License; original source and attribution are preserved in ../LICENSE and ../SOURCE.json.
import { $, $$, esc, stateHtml, showHtmlDetail } from './personal-shared.mjs';
import { categoryMap, selectRecords, relatedRecords, summarize, safeResourceUrl, formatRecordDate } from './personal-model.mjs';
import { mountCategories } from './categories.mjs';
import { mountRecordEditor } from './record-editor.mjs';

let records = [];
let categories = categoryMap();
let category = 'overview';
let payloadSignature = '';
let ready = false;
let loading = false;
let triggerRecordId = null;
let archiveError = false;
let currentRecord = null;
let mutationVersion = 0;
let reloadRequested = false;
let pendingIndex = 0;
let noticeSource = '';
let archiveErrorMessage = '';
function setNotice(source) { noticeSource = source; $('#recordNotice').textContent = t(source); $('#recordNotice').hidden = !source; }
function renderConnection() {
  $('#connectionStatus').textContent = t(archiveError ? '连接失败' : ready ? '已连接' : '连接中');
  $('#connectionStatus').title = pendingIndex ? `${pendingIndex}${t(' 条记录等待完成索引')}` : t('记忆已连接');
  const locale = globalThis.EvoMynI18n?.language === 'en' ? 'en-US' : 'zh-CN';
  $('#today').textContent = new Date().toLocaleDateString(locale, {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).replaceAll('/', '.');
  $('#recordNotice').textContent = t(noticeSource);
  const failedStatus = /^读取失败（(\d+)）$/.exec(archiveErrorMessage);
  const errorText = failedStatus ? `${t('读取失败（')}${failedStatus[1]}${t('）')}` : t(archiveErrorMessage);
  if (archiveError) $('#bootError').innerHTML = `<strong>${t('暂时无法读取记录')}</strong><p>${esc(errorText)} ${ready ? t('当前显示的是上次读取的记录。') : ''}${t('点击刷新重试。')}</p>`;
}
const recordEditor = mountRecordEditor($('#recordEditor'), {
  getCategories: () => categories,
  onAccessChange(enabled) {
    $('#createRecord').hidden = !enabled;
    $('#recordActions').hidden = !enabled || !currentRecord || currentRecord.revision == null;
  },
  onClose: () => route(),
  async onReload(id) {
    const payload = await api('./api/records');
    if (payload.mode !== 'personal' || !Array.isArray(payload.records)) throw new Error("暂时无法读取最新记录，草稿仍保留。");
    return payload.records.find(record => record.id === id) || null;
  },
  onSuccess(result, action) {
    mutationVersion++;
    payloadSignature = '';
    if (result.deleted) {
      records = records.filter(record => record.id !== result.deleted);
      history.replaceState(null, '', `#${category}`);
    } else {
      records = [...records.filter(record => record.id !== result.record.id), result.record];
      clearFilters();
      history.replaceState(null, '', `#${result.record.category}/${encodeURIComponent(result.record.id)}`);
    }
    setNotice(action === 'delete' ? '记忆及其历史版本已删除；磁盘附件和此前的备份已保留。' : result.record.index_status === 'pending' ? '记忆已保存，索引仍在处理中。' : '记忆已保存。');
    route();
    void load();
  }
});
const categoryManager = mountCategories($('#categoryManager'), {onChange(items) {
  categories = categoryMap(items, records);
  if (category !== 'overview' && !Object.hasOwn(categories, category)) history.replaceState(null, '', '#overview');
  route();
  void load();
}});

function badge(text) { return `<span class="badge">${esc(text)}</span>`; }
function row(record) {
  return `<button class="item" data-record="${esc(record.id)}"><div class="item-title"><span>${esc(record.title)}</span><span class="item-side"><span class="item-category">${esc(categories[record.category]?.label || "")}</span>${record.date ? `<span>${esc(formatRecordDate(record))}</span>` : ""}</span></div></button>`;
}
function filters() {
  return { category: category === 'overview' ? 'all' : category, query: $('#searchQuery').value, from: $('#fromDate').value, to: $('#toDate').value };
}
function renderNav(summary) {
  const icons = {overview:'OV',people:'PN',journal:'JR',background:'ME',event:'EV',resource:'FL'};
  const html = [['overview', t("全部")], ...Object.entries(categories).map(([key, value]) => [key, value.label])].map(([key, label]) =>
    `<button data-tab="${esc(key)}" class="${category === key ? 'active' : ''}"${category === key ? ' aria-current="page"' : ''}><span aria-hidden="true">${icons[key] || 'CT'}</span>${esc(label)}${key === 'overview' ? '' : `<span class="nav-count">${summary.counts[key] || 0}</span>`}</button>`).join('');
  if ($('#categoryNav').innerHTML !== html) $('#categoryNav').innerHTML = html;
}
function renderOverview() {
  const items = selectRecords(records);
  $('#overviewContent').innerHTML = `<div class="list memory-grid">${items.length ? items.map(record => row(record)).join('') : stateHtml('empty', t("暂无记忆"))}</div>`;
}
function render() {
  const summary = summarize(records, categories);
  renderNav(summary);
  $('#recordTotal').hidden = category !== 'overview';
  $('#bootError').hidden = !archiveError;
  $('#recordTotal').textContent = `${records.length}${t(" 条")}`;
  const options = filters();
  const filtered = Boolean(options.query.trim() || options.from || options.to);
  $('#clearFilters').hidden = !filtered;
  const invalidDates = options.from && options.to && options.from > options.to;
  $('#filterStatus').textContent = invalidDates ? t("开始日期晚于结束日期，请调整日期范围。") : options.from || options.to ? t("按时间范围匹配，年/月记录保留原有精度。") : '';
  $('#pageTitle').textContent = category === 'overview' ? t("记忆") : categories[category].label;
  $('#pageDescription').textContent = category === 'overview' ? t("人物、经历与资料，妥善留存。") : categories[category].subtitle;
  const overview = category === 'overview' && !filtered;
  $('.toolbar').hidden = overview;
  $('#overview').classList.toggle('active', overview);
  $('#records').classList.toggle('active', !overview);
  if (overview) renderOverview(summary);
  else {
    const items = selectRecords(records, options);
    $('#listTitle').textContent = category === 'overview' ? t("搜索全部记录") : `${categories[category].label}${t("记录")}`;
    $('#resultCount').textContent = `${items.length}${t(" 条")}`;
    $('#recordList').classList.add('list-panel');
    $('#recordList').innerHTML = items.length ? items.map(record => row(record, category === 'overview')).join('') : stateHtml('empty', filtered ? t("没有找到匹配的记录") : t("还没有记录"), filtered ? t("试试其他关键词，或清除日期筛选。") : t("通过聊天添加后，会显示在这里。"));
  }
  $('#recordTotal').textContent = `${records.length}${t(" 条")}`;
}
function fieldValue(value) { return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value ?? ''); }
function openRecord(record) {
  currentRecord = record;
  $('#recordActions').hidden = !recordEditor.enabled || record.revision == null;
  $('#detailKind').textContent = categories[record.category]?.label || record.category;
  const fields = Object.entries(record.fields || {}).map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(fieldValue(value))}</dd></div>`).join('');
  const steps = record.steps?.length ? `<h3 class="detail-section-title">${t("进展清单")}</h3><ul class="steps">${record.steps.map(step => `<li class="${step.done ? 'done' : ''}"><span aria-hidden="true">${step.done ? '✓' : '○'}</span><span>${esc(step.text)}</span><span class="step-status">${step.done ? t("已完成") : t("待推进")}</span></li>`).join('')}</ul>` : '';
  const linked = relatedRecords(records, record);
  const url = record.href ? safeResourceUrl(record.href.startsWith('/api/files/') ? '.' + record.href : record.href, location.href) : null;
  const file = url ? `<a class="resource-link" href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${url.pathname.includes('/api/files/') && url.origin === location.origin ? t("下载关联文件") : t("打开关联资料")} ↗</a>` : '';
  const relationships = linked.map(other => `<button class="relationship" data-record="${esc(other.id)}">${badge(categories[other.category]?.label || other.category)}<span>${esc(other.title)}</span><span class="arrow" aria-hidden="true">↗</span></button>`).join('') || `<p class="muted">${t("暂时没有关联记录。")}</p>`;
  showHtmlDetail(`<p class="detail-date">${esc(formatRecordDate(record))}</p>${record.index_status === 'pending' ? `<p class="danger-note">${t("原始记录已保存，记忆索引尚未完成。")}</p>` : ''}<div class="detail-content">${esc(record.body)}</div>${fields ? `<dl class="detail-fields">${fields}</dl>` : ''}${steps}${file}<div class="detail-tags">${(record.tags || []).map(badge).join('')}</div><h3 class="detail-section-title">${t("关联记录 · ")}${linked.length}</h3>${relationships}`, record.title);
}
function route() {
  const [requestedCategory, encodedId] = location.hash.slice(1).split('/');
  if (requestedCategory === 'backup') history.replaceState(null, '', '#overview');
  category = Object.hasOwn(categories, requestedCategory) ? requestedCategory : 'overview';
  render();
  // An open editor owns its draft and the revision captured when it was opened.
  // Background refreshes may replace the list, but must not replace that snapshot.
  if (recordEditor.open) return;
  if (encodedId && ready) {
    let id;
    try { id = decodeURIComponent(encodedId); } catch { id = ''; }
    const record = records.find(item => item.id === id);
    if (record) { openRecord(record); return; }
  }
  currentRecord = null;
  if ($('#detail').open) { $('#detail').close(); restoreFocus(); }
}
function restoreFocus() {
  const target = $$('[data-record]').find(node => node.dataset.record === triggerRecordId && node.getClientRects().length);
  const nav = $('#categoryNav button.active');
  (target || (nav?.getClientRects().length ? nav : $('#content'))).focus({ preventScroll: true });
}
function closeRecord() {
  $('#detail').close();
  history.replaceState(null, '', `#${category}`);
  restoreFocus();
}
function clearFilters() {
  $('#searchQuery').value = ''; $('#fromDate').value = ''; $('#toDate').value = ''; render();
}
async function api(path) {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`读取失败（${response.status}）`);
  return response.json();
}
async function load() {
  if (loading) { reloadRequested = true; return; }
  const version = mutationVersion;
  loading = true; $('#refresh').disabled = true; $('#content').setAttribute('aria-busy', 'true');
  try {
    const [payload, status] = await Promise.all([api('./api/records'), api('./api/dashboard')]);
    if (version !== mutationVersion) return;
    if (payload.mode !== 'personal' || !Array.isArray(payload.records) || !status.database_ok || !(status.read_only === true || status.record_management === true)) throw new Error("个人数据库尚未就绪。");
    $('#manageCategories').hidden = status.category_management !== true;
    let editorAccess = {enabled:false};
    if (status.record_management === true) {
      try { editorAccess = await api('./api/editor'); }
      catch { setNotice('记录已读取，编辑连接暂不可用。点击刷新重试。'); }
    }
    if (version !== mutationVersion) return;
    recordEditor.setAccess(editorAccess);
    archiveError = false;
    pendingIndex = payload.pending_index || 0;
    $('#bootError').hidden = true;
    const signature = JSON.stringify(payload);
    if (!ready || signature !== payloadSignature) {
      records = payload.records; categories = categoryMap(payload.categories, records); payloadSignature = signature; ready = true; route();
    }
    renderConnection();
  } catch (error) {
    if (version !== mutationVersion) return;
    recordEditor.setAccess({enabled:false});
    $('#manageCategories').hidden = true;
    archiveError = true;
    archiveErrorMessage = error.message;
    $('#bootError').hidden = false;
    renderConnection();
    if (!ready) { $('#overviewContent').innerHTML = ''; }
  } finally {
    loading = false; $('#refresh').disabled = false; $('#content').setAttribute('aria-busy', 'false');
    if (reloadRequested) { reloadRequested = false; void load(); }
  }
}
document.addEventListener('click', event => {
  const tab = event.target.closest('[data-tab]');
  if (tab) {
    if ($('#detail').open) $('#detail').close();
    clearFilters();
    history.pushState(null, '', `#${tab.dataset.tab}`);
    route();
    $('.sidebar').classList.remove('mobile-menu-open');
    $('#mobileMenuToggle').setAttribute('aria-expanded','false');
    $('#mobileMenuToggle').setAttribute('aria-label',t("展开分类菜单"));
    const nav = $('#categoryNav button.active');
    (nav?.getClientRects().length ? nav : $('#mobileMenuToggle')).focus({ preventScroll: true });
    return;
  }
  const record = event.target.closest('[data-record]');
  if (record) {
    const value = records.find(item => item.id === record.dataset.record);
    if (value) {
      if (!$('#detail').open) triggerRecordId = value.id;
      history.pushState(null, '', `#${value.category}/${encodeURIComponent(value.id)}`);
      route();
    }
  }
});
$('#searchQuery').addEventListener('input', render);
$('#fromDate').addEventListener('change', render);
$('#toDate').addEventListener('change', render);
$('#clearFilters').addEventListener('click', clearFilters);
$('#refresh').addEventListener('click', load);
$('#manageCategories').addEventListener('click', () => { void categoryManager.open(); });
$('#createRecord').addEventListener('click', () => recordEditor.openRecord(null, {category:category === 'overview' ? '' : category}));
$('#editRecord').addEventListener('click', () => { if (currentRecord) recordEditor.openRecord(currentRecord); });
$('#deleteRecord').addEventListener('click', () => { if (currentRecord) recordEditor.openRecord(currentRecord, {deleting:true}); });
$('#mobileMenuToggle').addEventListener('click', () => {
  const open = $('.sidebar').classList.toggle('mobile-menu-open');
  $('#mobileMenuToggle').setAttribute('aria-expanded',String(open));
  $('#mobileMenuToggle').setAttribute('aria-label',open ? t("收起分类菜单") : t("展开分类菜单"));
});
$('#closeDetail').addEventListener('click', closeRecord);
$('#detail').addEventListener('cancel', event => { event.preventDefault(); closeRecord(); });
$('#detail').addEventListener('click', event => {
  if (event.target !== $('#detail')) return;
  const bounds = $('#detail').getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closeRecord();
});
window.addEventListener('evomyn-language-change', () => {
  const active = document.activeElement;
  const recordId = active?.dataset.record, tab = active?.dataset.tab;
  route();
  renderConnection();
  $('#mobileMenuToggle').setAttribute('aria-label', t($('.sidebar').classList.contains('mobile-menu-open') ? '收起分类菜单' : '展开分类菜单'));
  if (!active?.isConnected) {
    const replacement = recordId ? $$('[data-record]').find(node => node.dataset.record === recordId) : tab ? $$('[data-tab]').find(node => node.dataset.tab === tab) : null;
    replacement?.focus({preventScroll:true});
  }
});
window.addEventListener('hashchange', route);
document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
setInterval(() => { if (!document.hidden) load(); }, 15000);
route();
load();
