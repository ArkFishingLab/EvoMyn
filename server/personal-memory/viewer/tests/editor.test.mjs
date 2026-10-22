import test from 'node:test';
import assert from 'node:assert/strict';
import * as editor from '../static/editor-model.mjs';
import { mountRecordEditor } from '../static/record-editor.mjs';

const record = {id:'memory-1', revision:1, category:'journal', title:'一次讨论', body:'整理材料', date:'2024-02', date_end:'ongoing', tags:['研究,记录','材料'], href:'/api/files/example.pdf', fields:{地点:'会议室'}, steps:[{text:'继续整理',done:false}], links:['person-1']};
const categories = ['journal','people'];
const draft = () => ({category:'journal',title:' 新记忆 ',body:' 第一行\n第二行 ',date:'2024',date_end:'ongoing',tags:'研究\n材料\n研究\n'});
const response = (value, status = 200) => new Response(JSON.stringify(value), {status,headers:{'Content-Type':'application/json'}});

test('create normalizes basic fields while retaining date precision and multiline content', () => {
  assert.equal(typeof editor.buildMutation, 'function');
  assert.deepEqual(editor.buildMutation(draft(), {categories}), {action:'create',record:{category:'journal',title:'新记忆',body:'第一行\n第二行',date:'2024',date_end:'ongoing',tags:['研究','材料']}});
});

test('editing pins the original identity and revision and never sends hidden fields', () => {
  assert.equal(typeof editor.recordDraft, 'function');
  const original = structuredClone(record);
  const form = editor.recordDraft(record);
  assert.equal(form.tags, '研究,记录\n材料');
  form.category = 'people'; form.title = '新标题';
  const mutation = editor.buildMutation(form, {record:original,categories});
  assert.deepEqual(mutation, {action:'update',id:record.id,revision:1,changes:{category:'people',title:'新标题',body:record.body,date:'2024-02',date_end:'ongoing',tags:record.tags}});
  assert.deepEqual(record, original);
});

test('title, body, and a valid creation category are required', () => {
  assert.equal(typeof editor.buildMutation, 'function');
  for (const [field, value] of [['title','  '],['body','\n'],['category','unknown']]) {
    assert.throws(() => editor.buildMutation({...draft(),[field]:value},{categories}), error => error.field === field);
  }
});

test('editing rejects an unavailable category', () => {
  assert.throws(() => editor.buildMutation({...draft(),category:'missing'},{record,categories}), error => error.field === 'category');
});

test('dates accept real partial dates and reject impossible dates or backwards periods', () => {
  assert.equal(typeof editor.buildMutation, 'function');
  for (const date of ['', '2024','2024-02','2024-02-29']) assert.doesNotThrow(() => editor.buildMutation({...draft(),date,date_end:''},{categories}));
  for (const date of ['0000','2024-00','2024-13','2023-02-29','2024-04-31','2024-2','ongoing']) {
    assert.throws(() => editor.buildMutation({...draft(),date,date_end:''},{categories}), error => error.field === 'date');
  }
  for (const dates of [{date:'',date_end:'ongoing'},{date:'2024-03',date_end:'2024-02'},{date:'2024',date_end:'bad'}]) {
    assert.throws(() => editor.buildMutation({...draft(),...dates},{categories}), error => error.field === 'date_end');
  }
  assert.doesNotThrow(() => editor.buildMutation({...draft(),date:'2024-12',date_end:'2024'},{categories}));
});

test('missing revision cannot produce an unsafe update or delete', () => {
  assert.equal(typeof editor.deleteMutation, 'function');
  for (const revision of [undefined,null,'1',0,-1,1.5]) assert.throws(() => editor.deleteMutation({...record,revision}));
  assert.throws(() => editor.buildMutation(draft(),{record:{...record,revision:undefined},categories}));
  assert.deepEqual(editor.deleteMutation(record),{action:'delete',id:'memory-1',revision:1});
});

test('access is denied until explicit capability and csrf are confirmed', async () => {
  assert.equal(typeof editor.createMutationClient, 'function');
  let calls = 0;
  const client = editor.createMutationClient(async () => { calls++; return response({record}); });
  for (const access of [undefined, {enabled:false,csrf:'token'}, {enabled:true,csrf:''}]) {
    if (access) client.setAccess(access);
    await assert.rejects(client.submit({action:'create',record:draft()}));
  }
  assert.equal(calls, 0);
});

test('mutation sends csrf and prevents duplicate submissions until completion', async () => {
  assert.equal(typeof editor.createMutationClient, 'function');
  let finish, request, calls = 0;
  const client = editor.createMutationClient((url, options) => {
    calls++; request = {url,options};
    return new Promise(resolve => { finish = resolve; });
  });
  client.setAccess({enabled:true,csrf:'test-token'});
  const mutation = {action:'delete',id:record.id,revision:record.revision};
  const pending = client.submit(mutation);
  assert.equal(client.busy, true);
  await assert.rejects(client.submit(mutation), error => error.code === 'busy');
  assert.equal(calls, 1);
  assert.equal(request.url, './api/records');
  assert.equal(request.options.headers['X-CSRF-Token'], 'test-token');
  assert.equal(request.options.method, 'POST');
  assert.deepEqual(JSON.parse(request.options.body), mutation);
  finish(response({deleted:record.id}));
  assert.deepEqual(await pending, {deleted:record.id});
  assert.equal(client.busy, false);
});

test('conflict is explicit and leaves the submitted draft and original revision intact', async () => {
  assert.equal(typeof editor.createMutationClient, 'function');
  const client = editor.createMutationClient(async () => response({error:'记录已被修改'},409));
  client.setAccess({enabled:true,csrf:'test-token'});
  const form = draft(), before = structuredClone(form);
  const mutation = editor.buildMutation(form,{record,categories});
  await assert.rejects(client.submit(mutation), error => error.status === 409 && error.code === 'conflict');
  assert.deepEqual(form, before);
  assert.equal(mutation.revision,1);
  assert.equal(client.busy, false);
});

test('validation, denied access, unavailable service, and invalid success responses never report success', async () => {
  assert.equal(typeof editor.createMutationClient, 'function');
  for (const status of [400,403,503]) {
    const client = editor.createMutationClient(async () => response({error:'保存失败'},status));
    client.setAccess({enabled:true,csrf:'test-token'});
    await assert.rejects(client.submit({action:'update',id:record.id}), error => error.status === status);
    assert.equal(client.busy,false);
    if (status === 403) assert.equal(client.enabled,false);
  }
  for (const result of [{},{record:{title:'missing identity'}},{deleted:'wrong-id'}]) {
    const client = editor.createMutationClient(async () => response(result));
    client.setAccess({enabled:true,csrf:'test-token'});
    await assert.rejects(client.submit({action:result.deleted ? 'delete' : 'update',id:record.id}));
  }
});

test('network failure releases submission lock and retains an actionable error', async () => {
  assert.equal(typeof editor.createMutationClient, 'function');
  const client = editor.createMutationClient(async () => { throw new TypeError('Failed to fetch'); });
  client.setAccess({enabled:true,csrf:'test-token'});
  await assert.rejects(client.submit({action:'delete',id:record.id}), /连接|网络/);
  assert.equal(client.busy,false);
});

// A small DOM port exercises the actual controller without adding browser
// dependencies to this static viewer. Network responses remain explicit fixtures.
function dialogFixture(t) {
  const previous = {document:globalThis.document,window:globalThis.window,fetch:globalThis.fetch};
  t.after(() => Object.assign(globalThis,previous));
  class Element extends EventTarget {
    constructor() { super(); this.value = ''; this.hidden = false; this.disabled = false; this.dataset = {}; this.attributes = new Map(); this.options = []; this.isConnected = true; }
    setAttribute(key,value) { this.attributes.set(key,value); }
    removeAttribute(key) { this.attributes.delete(key); }
    focus() { document.activeElement = this; }
    append(option) { this.options.push(option); }
    replaceChildren() { this.options = []; }
    showModal() { this.open = true; }
    close() { this.open = false; this.dispatchEvent(new Event('close')); }
  }
  const selectors = ['[data-editor-form]','[data-editor-fields]','[data-editor-submit]','[data-editor-error]','[data-editor-confirm]','[data-editor-reload]','[data-editor-delete-title]','#editorCategoryHelp','[data-editor-confirm-message]','[data-editor-discard]','[data-editor-keep]','[data-editor-close]','[data-editor-cancel]','#recordEditorTitle','[data-editor-deletion]'];
  const nodes = Object.fromEntries(selectors.map(selector => [selector,new Element()]));
  const inputs = Object.fromEntries(['category','title','body','date','date_end','tags'].map(name => [name,new Element()]));
  const form = nodes['[data-editor-form]']; form.elements = {namedItem:name => inputs[name]};
  const dialog = new Element(); dialog.open = false;
  dialog.querySelector = selector => nodes[selector];
  dialog.querySelectorAll = selector => selector.split(',').map(part => nodes[part.trim()]);
  globalThis.document = {activeElement:new Element(),createElement:() => new Element()};
  globalThis.window = new EventTarget();
  const click = selector => nodes[selector].dispatchEvent(new Event('click'));
  const submit = async () => { form.dispatchEvent(new Event('submit',{cancelable:true})); await new Promise(setImmediate); };
  return {dialog,nodes,inputs,click,submit};
}

test('controller keeps unsaved text until an explicit discard and protects window closing', t => {
  const ui = dialogFixture(t);
  const controller = mountRecordEditor(ui.dialog,{getCategories:() => ({journal:{label:'日志'}}),onSuccess:() => {},onReload:async () => record});
  controller.openRecord(record);
  assert.equal(ui.dialog.open,false);
  controller.setAccess({enabled:true,csrf:'token'});
  controller.openRecord(record);
  ui.inputs.body.value = '尚未保存的草稿';
  const unload = new Event('beforeunload',{cancelable:true});
  window.dispatchEvent(unload);
  assert.equal(unload.defaultPrevented,true);
  ui.click('[data-editor-cancel]');
  assert.equal(ui.dialog.open,true);
  assert.equal(ui.nodes['[data-editor-confirm]'].hidden,false);
  ui.click('[data-editor-keep]');
  assert.equal(ui.inputs.body.value,'尚未保存的草稿');
  ui.click('[data-editor-close]');
  ui.click('[data-editor-discard]');
  assert.equal(ui.dialog.open,false);
});

test('controller pins open revision, retains conflict draft, and reloads only after explicit consent', async t => {
  const ui = dialogFixture(t);
  let original = structuredClone(record), posted, reloads = 0, saves = 0;
  const latest = {...record,revision:2,title:'他处更新',body:'最新正文'};
  globalThis.fetch = async (_url,options) => { posted = JSON.parse(options.body); return response({error:'changed'},409); };
  const controller = mountRecordEditor(ui.dialog,{getCategories:() => ({journal:{label:'日志'}}),onSuccess:() => { saves++; },onReload:async () => { reloads++; return latest; }});
  controller.setAccess({enabled:true,csrf:'token'});
  controller.openRecord(original);
  original.revision = 2; original.body = '后台刷新';
  ui.inputs.body.value = '我的草稿';
  await ui.submit();
  assert.equal(posted.revision,1);
  assert.equal(ui.inputs.body.value,'我的草稿');
  assert.equal(saves,0);
  assert.equal(ui.nodes['[data-editor-submit]'].disabled,true);
  assert.equal(ui.nodes['[data-editor-reload]'].hidden,false);
  ui.click('[data-editor-reload]');
  assert.equal(reloads,0);
  assert.equal(ui.nodes['[data-editor-confirm]'].hidden,false);
  ui.click('[data-editor-keep]');
  assert.equal(ui.inputs.body.value,'我的草稿');
  ui.click('[data-editor-reload]'); ui.click('[data-editor-discard]');
  await new Promise(setImmediate);
  assert.equal(reloads,1);
  assert.equal(ui.inputs.body.value,'最新正文');
  globalThis.fetch = async (_url,options) => { posted = JSON.parse(options.body); return response({record:{...latest,revision:3}}); };
  await ui.submit();
  assert.equal(posted.revision,2);
  assert.equal(saves,1);
  assert.equal(ui.dialog.open,false);
});

test('controller confirms deletion using the original title and revision', async t => {
  const ui = dialogFixture(t);
  let posted, result;
  globalThis.fetch = async (_url,options) => { posted = JSON.parse(options.body); return response({deleted:record.id}); };
  const controller = mountRecordEditor(ui.dialog,{getCategories:() => ({journal:{label:'日志'}}),onSuccess:value => { result = value; },onReload:async () => record});
  controller.setAccess({enabled:true,csrf:'token'});
  controller.openRecord(record,{deleting:true});
  assert.equal(ui.nodes['[data-editor-fields]'].hidden,true);
  assert.equal(ui.nodes['[data-editor-delete-title]'].textContent,record.title);
  assert.equal(document.activeElement,ui.nodes['[data-editor-cancel]']);
  assert.equal(posted,undefined);
  await ui.submit();
  assert.deepEqual(posted,{action:'delete',id:record.id,revision:record.revision});
  assert.deepEqual(result,{deleted:record.id});
});

test('capability loss preserves draft and blocks submission until capability returns', async t => {
  const ui = dialogFixture(t);
  let calls = 0;
  globalThis.fetch = async () => { calls++; return response({record}); };
  const controller = mountRecordEditor(ui.dialog,{getCategories:() => ({journal:{label:'日志'}}),onSuccess:() => {},onReload:async () => record});
  controller.setAccess({enabled:true,csrf:'token'}); controller.openRecord(record);
  ui.inputs.body.value = '保留我的内容';
  controller.setAccess({enabled:false});
  assert.equal(ui.nodes['[data-editor-submit]'].disabled,true);
  assert.equal(ui.inputs.body.value,'保留我的内容');
  await ui.submit(); assert.equal(calls,0);
  controller.setAccess({enabled:true,csrf:'renewed'});
  assert.equal(ui.nodes['[data-editor-submit]'].disabled,false);
  assert.equal(ui.inputs.body.value,'保留我的内容');
});


test('controller allows a category-only edit and preserves draft until save', async t => {
  const ui = dialogFixture(t);
  let posted, saved;
  globalThis.fetch = async (_url,options) => { posted = JSON.parse(options.body); return response({record:{...record,category:'people',revision:2}}); };
  const controller = mountRecordEditor(ui.dialog,{getCategories:() => ({journal:{label:'日志'},people:{label:'人脉'}}),onSuccess:value => {saved=value;},onReload:async()=>record});
  controller.setAccess({enabled:true,csrf:'token'});
  controller.openRecord(record);
  assert.equal(ui.inputs.category.disabled,false);
  ui.inputs.category.value = 'people';
  ui.click('[data-editor-cancel]');
  assert.equal(ui.nodes['[data-editor-confirm]'].hidden,false);
  ui.click('[data-editor-keep]');
  assert.equal(ui.inputs.category.value,'people');
  await ui.submit();
  assert.equal(posted.changes.category,'people');
  assert.equal(posted.id,record.id);
  assert.equal(posted.revision,1);
  assert.equal(saved.record.category,'people');
  assert.equal(ui.dialog.open,false);
});
