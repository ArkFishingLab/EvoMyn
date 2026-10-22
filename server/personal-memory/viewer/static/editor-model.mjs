// Pure form and mutation logic for the memory editor.
function failure(message, properties = {}) { return Object.assign(new Error(message), properties); }
function text(value) { return String(value ?? '').trim(); }

export function recordDraft(record = {}, category = '') {
  return {category:record.category || category,title:record.title || '',body:record.body || '',date:record.date || '',date_end:record.date_end || '',tags:(record.tags || []).join('\n')};
}

function dateBounds(value) {
  if (!/^\d{4}(?:-\d{2}){0,2}$/.test(value)) return null;
  const [year, month, day] = value.split('-').map(Number);
  if (!year || (month !== undefined && (month < 1 || month > 12))) return null;
  const days = [31,year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28,31,30,31,30,31,31,30,31,30,31];
  if (day !== undefined && (day < 1 || day > days[month - 1])) return null;
  if (!month) return [`${value}-01-01`,`${value}-12-31`];
  if (!day) return [`${value}-01`,`${value}-${days[month - 1]}`];
  return [value,value];
}

function identity(record) {
  if (!record?.id || !Number.isSafeInteger(record.revision) || record.revision < 1) {
    throw failure('缺少记录版本，请关闭后刷新记录再试。');
  }
  return {id:record.id,revision:record.revision};
}

export function buildMutation(draft, {record = null, categories = []} = {}) {
  const changes = {title:text(draft.title),body:text(draft.body),date:text(draft.date),date_end:text(draft.date_end),tags:[...new Set(String(draft.tags ?? '').split(/\r?\n/).map(text).filter(Boolean))]};
  if (!changes.title) throw failure('请填写标题。',{field:'title'});
  if (!changes.body) throw failure('请填写记忆内容。',{field:'body'});
  const start = dateBounds(changes.date);
  if (changes.date && !start) throw failure('开始日期请填写有效的年份、年月或年月日，如 2024-02。',{field:'date'});
  const end = dateBounds(changes.date_end);
  if (changes.date_end && (!start || (changes.date_end !== 'ongoing' && (!end || end[1] < start[0])))) {
    throw failure('结束日期需配合开始日期填写，不能早于开始日期；持续至今可填写 ongoing。',{field:'date_end'});
  }
  if (record) return {action:'update',...identity(record),changes};
  if (!categories.includes(draft.category)) throw failure('请选择可用的分类。',{field:'category'});
  return {action:'create',record:{category:draft.category,...changes}};
}

export function deleteMutation(record) { return {action:'delete',...identity(record)}; }

export function createMutationClient(fetchImpl = (...args) => fetch(...args)) {
  let csrf = '', enabled = false, busy = false;
  return {
    get enabled() { return enabled; },
    get busy() { return busy; },
    setAccess(access = {}) { csrf = typeof access.csrf === 'string' ? access.csrf : ''; enabled = access.enabled === true && Boolean(csrf); },
    async submit(mutation) {
      if (busy) throw failure('正在保存，请稍候。',{code:'busy'});
      if (!enabled) throw failure('编辑连接不可用，请刷新后再试。',{code:'disabled'});
      busy = true;
      try {
        let response;
        try {
          response = await fetchImpl('./api/records',{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(mutation)});
        } catch { throw failure('网络连接中断，无法确认是否保存。请保留草稿，刷新记录核对后再试。'); }
        let result;
        try { result = await response.json(); } catch { result = null; }
        if (!response.ok) {
          if (response.status === 403) enabled = false;
          const messages = {400:'内容未通过校验，请检查后再试。',403:'编辑授权已失效，请刷新后再试。',409:'记录已被修改或删除。草稿已保留，请重新载入最新记录后编辑。',503:'记忆服务暂时不可用，请稍后再试。'};
          throw failure(messages[response.status] || result?.error || `保存失败（${response.status}），请稍后再试。`,{status:response.status,code:response.status === 409 ? 'conflict' : 'request'});
        }
        const valid = mutation.action === 'delete' ? result?.deleted === mutation.id : result?.record?.id && result.record.revision != null && typeof result.record.title === 'string' && typeof result.record.body === 'string' && (mutation.action !== 'update' || result.record.id === mutation.id);
        if (!valid) throw failure('服务返回了无法确认的结果。请保留草稿，刷新记录核对后再试。');
        return result;
      } finally { busy = false; }
    }
  };
}
