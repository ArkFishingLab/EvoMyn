import test from 'node:test';
import assert from 'node:assert/strict';
import { uploadAttachments, attachmentUrl, attachmentRepresentsPrimary } from '../static/attachments.mjs';

const response = (value, status = 200) => new Response(JSON.stringify(value), {status});
const file = name => Object.assign(new Blob(['bytes']), {name});
test('uploads files sequentially with each returned revision, without changing the source record', async () => {
  const record = {id:'memory-1',revision:2,title:'Title',body:'Body'};
  const calls = [], updates = [];
  const latest = await uploadAttachments(record, [file('笔记.txt'),file('笔记.txt')], 'token', {
    fetchImpl: async (url, options) => {
      calls.push({url,options});
      return response({record:{...record,revision:record.revision + calls.length,attachments:[]}});
    }, onRecord: value => updates.push(value.revision)
  });
  assert.equal(record.revision, 2);
  assert.equal(latest.revision, 4);
  assert.deepEqual(updates, [3,4]);
  assert.match(calls[0].url, /revision=2$/);
  assert.match(calls[1].url, /revision=3$/);
  assert.equal(calls[0].options.headers['X-CSRF-Token'], 'token');
  assert.equal(calls[0].options.headers['X-File-Name'], encodeURIComponent('笔记.txt'));
  assert.equal(await calls[0].options.body.text(), 'bytes');
});
test('a partial conflict stops the batch and leaves successful revisions visible', async () => {
  let calls = 0;
  const revisions = [];
  await assert.rejects(uploadAttachments({id:'one',revision:1}, [file('a'),file('b'),file('c')], 'token', {
    fetchImpl: async () => ++calls === 1 ? response({record:{id:'one',revision:2,attachments:[]}}) : response({},409),
    onRecord: value => revisions.push(value.revision)
  }), error => error.status === 409);
  assert.equal(calls, 2);
  assert.deepEqual(revisions,[2]);
});
test('access, size and unverifiable responses fail before reporting success', async () => {
  let called = false;
  const fetchImpl = async () => { called = true; return response({record:{id:'other',revision:2}}); };
  await assert.rejects(uploadAttachments({id:'one',revision:1},[file('a')],'',{fetchImpl}));
  await assert.rejects(uploadAttachments({id:'one',revision:1},[{name:'big',size:52428801}],'token',{fetchImpl}));
  assert.equal(called,false);
  await assert.rejects(uploadAttachments({id:'one',revision:1},[file('a')],'token',{fetchImpl}));
});
test('download URLs derive solely from IDs and respect the viewer mount prefix', () => {
  assert.equal(attachmentUrl('record id','file-id'), './api/files/record%20id/file-id');
});
test('a legacy primary link remains visible unless the attachment list represents it', () => {
  const attachments = [{id:'new',href:'/api/files/one/new'}];
  assert.equal(attachmentRepresentsPrimary({href:'/api/files/one', attachments}), false);
  assert.equal(attachmentRepresentsPrimary({href:'/api/files/one/new', attachments}), true);
  assert.equal(attachmentRepresentsPrimary({href:'https://example.com', attachments}), false);
  assert.equal(attachmentRepresentsPrimary({href:'/api/files/one'}), false);
});
