// Extracted/adapted from wysie/mnemosyne-dashboard static/app.js.
// MIT License, Copyright (c) 2026 Agent Hammy contributors; see ../LICENSE.
export const $ = (s) => document.querySelector(s);
export const $$ = (s) => [...document.querySelectorAll(s)];
export function esc(s){ return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
export function stateHtml(kind, title, body=''){
  return `<div class="state-card state-${esc(kind)}"><strong>${esc(title)}</strong>${body ? `<p>${esc(body)}</p>` : ''}</div>`;
}
// Upstream's HTML detail renderer, adapted to a native accessible modal.
export function showHtmlDetail(html, title='详情'){
  $('.drawer-title').textContent = title;
  $('#detailBody').innerHTML = html;
  const drawer = $('#detail');
  if (!drawer.open) drawer.showModal();
}
