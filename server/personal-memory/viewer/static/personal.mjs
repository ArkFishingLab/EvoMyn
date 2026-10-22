// Categorized archive adaptation of wysie/mnemosyne-dashboard's app.js presentation.
// Uses its selectors, escaped HTML/empty states, drawer renderer, shell and CSS components.
// MIT License; original source and attribution are preserved in ../LICENSE and ../SOURCE.json.
import { $, $$, esc, stateHtml, showHtmlDetail } from './personal-shared.mjs';
import { categoryMap, selectRecords, relatedRecords, summarize, safeResourceUrl, formatRecordDate } from './personal-model.mjs';
import { mountCategories } from './categories.mjs';

let records = [];
let categories = categoryMap();
let category = 'overview';
let payloadSignature = '';
let ready = false;
let loading = false;
let nativeStatus = null;
let triggerRecordId = null;
let archiveError = false;
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
  const html = [['overview', '全部'], ...Object.entries(categories).map(([key, value]) => [key, value.label])].map(([key, label]) =>
    `<button data-tab="${esc(key)}" class="${category === key ? 'active' : ''}"${category === key ? ' aria-current="page"' : ''}><span aria-hidden="true">${icons[key] || 'CT'}</span>${esc(label)}${key === 'overview' ? '' : `<span class="nav-count">${summary.counts[key] || 0}</span>`}</button>`).join('');
  if ($('#categoryNav').innerHTML !== html) $('#categoryNav').innerHTML = html;
}
function renderOverview() {
  const items = selectRecords(records);
  $('#overviewContent').innerHTML = `<div class="list memory-grid">${items.length ? items.map(record => row(record)).join('') : stateHtml('empty', '暂无记忆')}</div>`;
}
function render() {
  const summary = summarize(records, categories);
  renderNav(summary);
  $('#recordTotal').hidden = category !== 'overview';
  $('#bootError').hidden = !archiveError;
  $('#recordTotal').textContent = `${records.length} 条`;
  const options = filters();
  const filtered = Boolean(options.query.trim() || options.from || options.to);
  $('#clearFilters').hidden = !filtered;
  const invalidDates = options.from && options.to && options.from > options.to;
  $('#filterStatus').textContent = invalidDates ? '开始日期晚于结束日期，请调整日期范围。' : options.from || options.to ? '按时间范围匹配，年/月记录保留原有精度。' : '';
  $('#pageTitle').textContent = category === 'overview' ? '记忆' : categories[category].label;
  $('#pageDescription').textContent = category === 'overview' ? '人物、经历与资料，妥善留存。' : categories[category].subtitle;
  const overview = category === 'overview' && !filtered;
  $('.toolbar').hidden = overview;
  $('#overview').classList.toggle('active', overview);
  $('#records').classList.toggle('active', !overview);
  if (overview) renderOverview(summary);
  else {
    const items = selectRecords(records, options);
    $('#listTitle').textContent = category === 'overview' ? '搜索全部记录' : `${categories[category].label}记录`;
    $('#resultCount').textContent = `${items.length} 条`;
    $('#recordList').classList.add('list-panel');
    $('#recordList').innerHTML = items.length ? items.map(record => row(record, category === 'overview')).join('') : stateHtml('empty', filtered ? '没有找到匹配的记录' : '还没有记录', filtered ? '试试其他关键词，或清除日期筛选。' : '通过聊天添加后，会显示在这里。');
  }
  $('#recordTotal').textContent = `${records.length} 条`;
}
function fieldValue(value) { return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value ?? ''); }
function openRecord(record) {
  $('#detailKind').textContent = categories[record.category]?.label || record.category;
  const fields = Object.entries(record.fields || {}).map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(fieldValue(value))}</dd></div>`).join('');
  const steps = record.steps?.length ? `<h3 class="detail-section-title">进展清单</h3><ul class="steps">${record.steps.map(step => `<li class="${step.done ? 'done' : ''}"><span aria-hidden="true">${step.done ? '✓' : '○'}</span><span>${esc(step.text)}</span><span class="step-status">${step.done ? '已完成' : '待推进'}</span></li>`).join('')}</ul>` : '';
  const linked = relatedRecords(records, record);
  const url = record.href ? safeResourceUrl(record.href.startsWith('/api/files/') ? '.' + record.href : record.href, location.href) : null;
  const file = url ? `<a class="resource-link" href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${url.pathname.includes('/api/files/') && url.origin === location.origin ? '下载关联文件' : '打开关联资料'} ↗</a>` : '';
  const relationships = linked.map(other => `<button class="relationship" data-record="${esc(other.id)}">${badge(categories[other.category]?.label || other.category)}<span>${esc(other.title)}</span><span class="arrow" aria-hidden="true">↗</span></button>`).join('') || '<p class="muted">暂时没有关联记录。</p>';
  showHtmlDetail(`<p class="detail-date">${esc(formatRecordDate(record))}</p>${record.index_status === 'pending' ? '<p class="danger-note">原始记录已保存，记忆索引尚未完成。</p>' : ''}<div class="detail-content">${esc(record.body)}</div>${fields ? `<dl class="detail-fields">${fields}</dl>` : ''}${steps}${file}<div class="detail-tags">${(record.tags || []).map(badge).join('')}</div><h3 class="detail-section-title">关联记录 · ${linked.length}</h3>${relationships}`, record.title);
}
function route() {
  const [requestedCategory, encodedId] = location.hash.slice(1).split('/');
  if (requestedCategory === 'backup') history.replaceState(null, '', '#overview');
  category = Object.hasOwn(categories, requestedCategory) ? requestedCategory : 'overview';
  render();
  if (encodedId && ready) {
    let id;
    try { id = decodeURIComponent(encodedId); } catch { id = ''; }
    const record = records.find(item => item.id === id);
    if (record) { openRecord(record); return; }
  }
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
  if (loading) return;
  loading = true; $('#refresh').disabled = true; $('#content').setAttribute('aria-busy', 'true');
  try {
    const [payload, status] = await Promise.all([api('./api/records'), nativeStatus ? Promise.resolve(nativeStatus) : api('./api/dashboard')]);
    if (payload.mode !== 'personal' || !Array.isArray(payload.records) || !status.database_ok || !status.read_only) throw new Error('个人数据库尚未就绪。');
    nativeStatus = status;
    $('#manageCategories').hidden = status.category_management === false;
    archiveError = false;
    $('#connectionStatus').textContent = '已连接';
    $('#connectionStatus').title = payload.pending_index ? `${payload.pending_index} 条记录等待完成索引` : '记忆已连接';
    $('#today').textContent = new Date().toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).replaceAll('/', '.');
    $('#bootError').hidden = true;
    const signature = JSON.stringify(payload);
    if (!ready || signature !== payloadSignature) {
      records = payload.records; categories = categoryMap(payload.categories, records); payloadSignature = signature; ready = true; route();
    }
  } catch (error) {
    nativeStatus = null;
    archiveError = true;
    $('#connectionStatus').textContent = '连接失败';
    $('#bootError').hidden = false;
    $('#bootError').innerHTML = `<strong>暂时无法读取记录</strong><p>${esc(error.message)} ${ready ? '当前显示的是上次读取的记录。' : ''}点击刷新重试。</p>`;
    if (!ready) { $('#overviewContent').innerHTML = ''; }
  } finally {
    loading = false; $('#refresh').disabled = false; $('#content').setAttribute('aria-busy', 'false');
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
    $('#mobileMenuToggle').setAttribute('aria-label','展开分类菜单');
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
$('#mobileMenuToggle').addEventListener('click', () => {
  const open = $('.sidebar').classList.toggle('mobile-menu-open');
  $('#mobileMenuToggle').setAttribute('aria-expanded',String(open));
  $('#mobileMenuToggle').setAttribute('aria-label',open ? '收起分类菜单' : '展开分类菜单');
});
$('#closeDetail').addEventListener('click', closeRecord);
$('#detail').addEventListener('cancel', event => { event.preventDefault(); closeRecord(); });
$('#detail').addEventListener('click', event => {
  if (event.target !== $('#detail')) return;
  const bounds = $('#detail').getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closeRecord();
});
window.addEventListener('hashchange', route);
document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
setInterval(() => { if (!document.hidden) load(); }, 15000);
route();
load();
