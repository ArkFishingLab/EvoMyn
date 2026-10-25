'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const {validateAttachmentRequest,trustedAttachmentSender,openManagedAttachment}=require('../attachments.cjs');
test('managed download URLs keep the desktop allowlist bounded to attachment IDs',()=>{
 const {allowedDownload}=require('../security.cjs'),origin='http://127.0.0.1:12345';
 assert.equal(allowedDownload(origin+'/memory/api/files/resource-a/'+'a'.repeat(32),origin),true);
 for(const url of [origin+'/memory/api/files/resource-a/../../secret',origin+'/memory/api/files/resource-a/path.pdf','https://example.test/memory/api/files/resource-a'])assert.equal(allowedDownload(url,origin),false);
});
test('attachment requests accept identities, never renderer paths',()=>{
 assert.doesNotThrow(()=>validateAttachmentRequest({recordId:'resource-a',attachmentId:'a'.repeat(32)}));
 assert.doesNotThrow(()=>validateAttachmentRequest({recordId:'resource-a',attachmentId:'legacy'}));
 for(const value of [{recordId:'../../private',attachmentId:'legacy'},{recordId:'resource-a',attachmentId:'https://example.test'},{recordId:'resource-a',attachmentId:'legacy',path:'C:/private'},{recordId:'resource-a'},null])assert.throws(()=>validateAttachmentRequest(value));
});
test('only the current trusted dashboard main frame can open files',()=>{
 const frame={url:'http://127.0.0.1:12345/memory/'},contents={isDestroyed:()=>false,mainFrame:frame};
 const event={sender:contents,senderFrame:frame};
 assert.equal(trustedAttachmentSender(event,contents,'http://127.0.0.1:12345'),true);
 assert.equal(trustedAttachmentSender({...event,senderFrame:{...frame}},contents,'http://127.0.0.1:12345'),false);
 frame.url='https://example.test/memory/';assert.equal(trustedAttachmentSender(event,contents,'http://127.0.0.1:12345'),false);
});
test('native opening resolves from service, checks managed containment and never runs executables',async()=>{
 const path=require('node:path'),root=path.resolve('fixture-resources');let opened='';
 const params={recordId:'resource-a',attachmentId:'a'.repeat(32)};
 const service={request:async(command,value)=>{assert.equal(command,'attachment-path');assert.deepEqual(value,params);return {path:path.join(root,'a','report.pdf'),resources:root};}};
 const shell={openPath:async file=>{opened=file;return '';}};
 assert.equal(await openManagedAttachment(params,service,shell),true);assert.ok(opened.endsWith('report.pdf'));
 for(const file of [path.resolve('outside.pdf'),...['run.cmd','run.EXE','run.lnk','run.py','run.jar','run.cpl','run.scf'].map(name=>path.join(root,name))]){
  opened='';await assert.rejects(openManagedAttachment(params,{request:async()=>({path:file,resources:root})},shell));assert.equal(opened,'');
 }
});
