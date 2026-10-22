export const categories = {
  people: { label: '人脉', subtitle: '认识的人，以及一起经历的事', number: '01' },
  journal: { label: '日志', subtitle: '按日回看，留住事情的经过', number: '02' },
  background: { label: '个人', subtitle: '关于自己、履历与个人积累', number: '03' },
  event: { label: '事件', subtitle: '要求、进展与接下来要做的事', number: '04' },
  resource: { label: '资料', subtitle: '与人物、经历和事件关联的文件', number: '05' },
};

export function categoryMap(entries, records = []) {
  const source = Array.isArray(entries) ? entries : Object.entries(categories).map(([id, value]) => ({id, ...value}));
  const result = Object.create(null);
  const reserved = new Set(['overview', 'backup', 'all', '__proto__', 'constructor', 'prototype']);
  for (const entry of source) {
    if (!entry || typeof entry.id !== 'string' || reserved.has(entry.id) || !entry.id || typeof entry.label !== 'string') continue;
    result[entry.id] = {...categories[entry.id], ...entry, subtitle: entry.subtitle || '此分类下的记忆'};
  }
  for (const record of records) {
    if (typeof record.category === 'string' && !reserved.has(record.category) && !Object.hasOwn(result, record.category)) {
      result[record.category] = categories[record.category] || {label: record.category, subtitle: '此分类下的记忆'};
    }
  }
  return result;
}

function dateBounds(value) {
  if (typeof value !== 'string' || !/^\d{4}(?:-\d{2}){0,2}$/.test(value)) return null;
  const [year, month, day] = value.split('-').map(Number);
  if (year < 1 || year > 9999) return null;
  if (!month) return value.length === 4 ? [`${value}-01-01`, `${value}-12-31`] : null;
  const days = [31, year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (month > 12 || (day !== undefined && (day < 1 || day > days[month - 1]))) return null;
  return value.length === 7 ? [`${value}-01`, `${value}-${days[month - 1]}`] : [value, value];
}
function periodBounds(record) {
  const bounds = dateBounds(record.date);
  if (!bounds) return null;
  if (record.date_end) bounds[1] = record.date_end === 'ongoing' ? new Date().toLocaleDateString('sv-SE', {timeZone:'Asia/Shanghai'}) : dateBounds(record.date_end)?.[1] || bounds[1];
  return bounds;
}
export function formatRecordDate(record) {
  function label(value) {
    if (value === 'ongoing') return '至今';
    if (value.length === 4) return `${value}年`;
    if (value.length === 7) return `${value.slice(0, 4)}年${Number(value.slice(5))}月`;
    return value;
  }
  if (!record.date) return '日期未记录';
  return label(record.date) + (record.date_end ? ` — ${label(record.date_end)}` : '');
}

export function selectRecords(records, { category = 'all', query = '', from = '', to = '' } = {}) {
  const term = query.trim().toLocaleLowerCase();
  return records.filter(record => {
    if (category !== 'all' && record.category !== category) return false;
    const bounds = periodBounds(record);
    if ((from || to) && (!bounds || (from && bounds[1] < from) || (to && bounds[0] > to))) return false;
    if (!term) return true;
    const text = [record.title, record.body, ...Object.values(record.fields || {}), ...(record.tags || [])].join(' ').toLocaleLowerCase();
    return text.includes(term);
  }).sort((a, b) => (periodBounds(b)?.[0] || '').localeCompare(periodBounds(a)?.[0] || '') || a.id.localeCompare(b.id));
}

export function relatedRecords(records, record) {
  return records.filter(other => other.id !== record.id && (
    (record.links || []).includes(other.id) || (other.links || []).includes(record.id)
  ));
}

export function summarize(records, catalog = categories) {
  const counts = Object.fromEntries(Object.keys(catalog).map(key => [key, 0]));
  let activeEvents = 0;
  for (const record of records) {
    if (typeof record.category === 'string') counts[record.category] = (Object.hasOwn(counts, record.category) ? counts[record.category] : 0) + 1;
    if (record.category === 'event' && !['已完成', '已归档'].includes(record.fields?.状态)) activeEvents++;
  }
  return { counts, activeEvents, total: records.length };
}

export function safeResourceUrl(href, baseUrl) {
  if (typeof href !== 'string' || !href.trim()) return null;
  try {
    const url = new URL(href, baseUrl);
    if (['http:', 'https:'].includes(url.protocol)) return url;
    const base = new URL(baseUrl);
    const bundledRoot = new URL('dist/files/', base);
    if (base.protocol === 'file:' && url.protocol === 'file:' && !/^[a-z][\w+.-]*:/i.test(href) && !href.startsWith('//') && url.href.startsWith(bundledRoot.href)) return url;
    return null;
  } catch { return null; }
}
