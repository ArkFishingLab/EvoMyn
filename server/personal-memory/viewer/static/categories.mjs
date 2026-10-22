import { esc } from './personal-shared.mjs';

export function mountCategories(dialog, { onChange }) {
  let items = [], csrf = '', busy = false, error = '', newLabel = '';
  const drafts = new Map();
  const list = dialog.querySelector('[data-category-list]');
  const status = dialog.querySelector('[data-category-status]');
  const add = dialog.querySelector('[data-category-add]');
  const name = add.elements.label;

  function render() {
    status.textContent = error;
    status.hidden = !error;
    list.innerHTML = items.map((item, index) => `<div class="category-row" data-category="${esc(item.id)}">
      <form data-category-rename="${esc(item.id)}"><input name="label" value="${esc(drafts.get(item.id) ?? item.label)}" maxlength="24" required aria-label="${esc(item.label)} 分类名称"${busy ? ' disabled' : ''}>
      <button class="category-save" type="submit"${busy || (drafts.get(item.id) ?? item.label) === item.label ? ' disabled' : ''}>保存</button></form>
      <span class="category-meta">${item.builtin ? '默认 · ' : ''}${Number(item.count) || 0} 条</span>
      <div class="category-actions"><button type="button" data-category-up="${esc(item.id)}" aria-label="上移 ${esc(item.label)}" title="上移"${busy || !index ? ' disabled' : ''}>↑</button>
      <button type="button" data-category-down="${esc(item.id)}" aria-label="下移 ${esc(item.label)}" title="下移"${busy || index === items.length - 1 ? ' disabled' : ''}>↓</button>
      <button type="button" data-category-delete="${esc(item.id)}" aria-label="删除 ${esc(item.label)}" title="${item.builtin ? '默认分类可改名，不能删除' : item.count ? '此分类还有记忆，不能删除' : '删除空分类'}"${busy || item.builtin || item.count ? ' disabled' : ''}>×</button></div></div>`).join('');
    name.value = newLabel;
    name.disabled = busy;
    add.querySelector('button').disabled = busy || !csrf;
    dialog.setAttribute('aria-busy', String(busy));
  }

  async function mutate(value) {
    if (busy || !csrf) return;
    busy = true; error = ''; render();
    try {
      const response = await fetch('./api/categories', {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify(value)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '分类未能保存，请重试。');
      items = result.categories;
      if (value.action === 'create') newLabel = '';
      if (value.action === 'rename' || value.action === 'delete') drafts.delete(value.id);
      onChange(items);
    } catch (failure) { error = failure.message || '分类未能保存，请重试。'; }
    finally { busy = false; render(); }
  }

  add.addEventListener('input', () => { newLabel = name.value; });
  add.addEventListener('submit', event => { event.preventDefault(); void mutate({action:'create',label:name.value}); });
  list.addEventListener('input', event => {
    const form = event.target.closest('[data-category-rename]');
    if (!form) return;
    const id = form.dataset.categoryRename;
    drafts.set(id, form.elements.label.value);
    form.querySelector('button').disabled = form.elements.label.value === items.find(item => item.id === id)?.label;
  });
  list.addEventListener('submit', event => {
    event.preventDefault(); const form = event.target.closest('[data-category-rename]');
    if (form) void mutate({action:'rename',id:form.dataset.categoryRename,label:form.elements.label.value});
  });
  list.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button || button.disabled) return;
    if (button.dataset.categoryDelete) return void mutate({action:'delete',id:button.dataset.categoryDelete});
    const id = button.dataset.categoryUp || button.dataset.categoryDown;
    if (!id) return;
    const order = items.map(item => item.id), index = order.indexOf(id);
    const next = index + (button.dataset.categoryUp ? -1 : 1);
    if (index < 0 || next < 0 || next >= order.length) return;
    [order[index], order[next]] = [order[next], order[index]];
    void mutate({action:'reorder',order});
  });
  dialog.querySelector('[data-category-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => document.getElementById('manageCategories').focus({preventScroll:true}));

  return {async open() {
    if (dialog.open || busy) return;
    drafts.clear(); newLabel = ''; error = ''; csrf = ''; busy = true; items = []; render(); dialog.showModal();
    try {
      const response = await fetch('./api/categories', {cache:'no-store'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '暂时无法读取分类。');
      items = result.categories; csrf = result.csrf;
    } catch (failure) { error = failure.message || '暂时无法读取分类。'; }
    finally { busy = false; render(); if (dialog.open) name.focus(); }
  }};
}
