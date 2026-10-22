import { recordDraft, buildMutation, deleteMutation, createMutationClient } from './editor-model.mjs';

export function mountRecordEditor(dialog, {getCategories, onSuccess, onReload, onClose = () => {}, onAccessChange = () => {}}) {
  const find = selector => dialog.querySelector(selector);
  const form = find('[data-editor-form]');
  const fields = find('[data-editor-fields]');
  const submit = find('[data-editor-submit]');
  const errorBox = find('[data-editor-error]');
  const confirm = find('[data-editor-confirm]');
  const reload = find('[data-editor-reload]');
  const client = createMutationClient();
  const names = ['category','title','body','date','date_end','tags'];
  let original = null, mode = 'create', baseline = '', conflict = false, reloading = false, confirmation = null, trigger = null, accessError = false;

  function values() { return Object.fromEntries(names.map(name => [name,form.elements.namedItem(name).value])); }
  function dirty() { return dialog.open && mode !== 'delete' && JSON.stringify(values()) !== baseline; }
  function setError(message = '') { errorBox.textContent = message; errorBox.hidden = !message; }
  function controls() {
    const busy = client.busy || reloading;
    fields.disabled = busy;
    form.elements.namedItem('category').disabled = mode !== 'create';
    submit.disabled = busy || !client.enabled || conflict || Boolean(confirmation);
    submit.textContent = busy ? (reloading ? '正在载入…' : mode === 'delete' ? '正在删除…' : '正在保存…') : mode === 'delete' ? '删除这条记忆' : '保存记忆';
    reload.hidden = !conflict;
    reload.disabled = busy || Boolean(confirmation);
    for (const button of dialog.querySelectorAll('[data-editor-close], [data-editor-cancel], [data-editor-discard], [data-editor-keep]')) button.disabled = busy;
    dialog.setAttribute('aria-busy', String(busy));
  }
  function fill(record, category = '') {
    original = record ? structuredClone(record) : null;
    const draft = recordDraft(original || {}, category);
    const select = form.elements.namedItem('category');
    select.replaceChildren();
    for (const [id, item] of Object.entries(getCategories())) {
      const option = document.createElement('option'); option.value = id; option.textContent = item.label; select.append(option);
    }
    if (!draft.category) draft.category = select.options[0]?.value || '';
    for (const name of names) { form.elements.namedItem(name).value = draft[name]; form.elements.namedItem(name).removeAttribute('aria-invalid'); }
    baseline = JSON.stringify(values());
    find('[data-editor-delete-title]').textContent = original?.title || '';
    find('#editorCategoryHelp').textContent = mode === 'create' ? '可在「管理分类」中修改分类名称和顺序。' : '编辑时保留所属分类；分类名称和顺序可在「管理分类」中修改。';
    conflict = false; accessError = false; confirmation = null; confirm.hidden = true; setError(); controls();
  }
  function showConfirmation(action) {
    confirmation = action; confirm.hidden = false;
    find('[data-editor-confirm-message]').textContent = action === 'reload' ? '重新载入会放弃当前草稿，改为最新版本。' : '还有未保存的内容。要放弃这份草稿吗？';
    find('[data-editor-discard]').textContent = action === 'reload' ? '放弃草稿并载入' : '放弃草稿';
    controls(); find('[data-editor-keep]').focus();
  }
  function close() { confirmation = null; confirm.hidden = true; dialog.close(); }
  function requestClose() {
    if (client.busy || reloading) return;
    if (dirty()) showConfirmation('close'); else close();
  }
  async function reloadLatest() {
    if (client.busy || reloading || !original) return;
    reloading = true; confirmation = null; confirm.hidden = true; setError(); controls();
    try {
      const latest = await onReload(original.id);
      if (!latest) throw new Error('这条记忆已被删除，当前草稿仍保留。请复制需要的内容后关闭。');
      if (latest.revision == null || latest.id !== original.id) throw new Error('无法确认最新版本，当前草稿仍保留，请稍后重试。');
      fill(latest);
    } catch (error) { setError(error.message || '无法读取最新记录，草稿仍保留。'); }
    finally { reloading = false; controls(); if (dialog.open) (mode === 'delete' ? find('[data-editor-cancel]') : form.elements.namedItem('title')).focus(); }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (client.busy || reloading || !client.enabled || conflict || confirmation) return;
    setError();
    for (const name of names) form.elements.namedItem(name).removeAttribute('aria-invalid');
    let mutation;
    try { mutation = mode === 'delete' ? deleteMutation(original) : buildMutation(values(),{record:original,categories:Object.keys(getCategories())}); }
    catch (error) {
      setError(error.message);
      if (error.field) { const field = form.elements.namedItem(error.field); field.setAttribute('aria-invalid','true'); field.focus(); }
      return;
    }
    const pending = client.submit(mutation); controls();
    let result;
    try { result = await pending; }
    catch (error) {
      conflict = error.code === 'conflict'; setError(error.message || '未能保存，请稍后重试。');
      onAccessChange(client.enabled);
      controls();
      if (conflict) reload.focus();
      return;
    } finally { controls(); }
    close();
    onSuccess(result, mutation.action);
  });
  form.addEventListener('input', event => { event.target.removeAttribute('aria-invalid'); });
  for (const button of dialog.querySelectorAll('[data-editor-close], [data-editor-cancel]')) button.addEventListener('click', requestClose);
  dialog.addEventListener('cancel', event => { event.preventDefault(); requestClose(); });
  dialog.addEventListener('close', () => {
    if (trigger?.isConnected && !trigger.hidden) trigger.focus({preventScroll:true});
    onClose();
  });
  reload.addEventListener('click', () => { if (dirty()) showConfirmation('reload'); else void reloadLatest(); });
  find('[data-editor-keep]').addEventListener('click', () => { confirmation = null; confirm.hidden = true; controls(); form.elements.namedItem('title').focus(); });
  find('[data-editor-discard]').addEventListener('click', () => { if (confirmation === 'reload') void reloadLatest(); else close(); });
  window.addEventListener('beforeunload', event => { if (dirty() || client.busy) { event.preventDefault(); event.returnValue = ''; } });

  return {
    get open() { return dialog.open; },
    get enabled() { return client.enabled; },
    setAccess(access) {
      client.setAccess(access); onAccessChange(client.enabled);
      if (dialog.open && !client.enabled && !client.busy) { setError('编辑连接暂不可用，草稿已保留。恢复连接后可继续保存。'); accessError = true; }
      else if (accessError && client.enabled) { setError(); accessError = false; }
      controls();
    },
    openRecord(record = null, {category = '', deleting = false} = {}) {
      if (dialog.open || client.busy || !client.enabled) return;
      trigger = document.activeElement;
      mode = deleting ? 'delete' : record ? 'update' : 'create'; dialog.dataset.mode = mode;
      find('#recordEditorTitle').textContent = deleting ? '删除记忆' : record ? '编辑记忆' : '新增记忆';
      fields.hidden = deleting; find('[data-editor-deletion]').hidden = !deleting;
      fill(record, category); dialog.showModal();
      (deleting ? find('[data-editor-cancel]') : form.elements.namedItem('title')).focus();
    }
  };
}
