'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto');
const {MacUpdateInstaller}=require('../mac-updater.cjs');
const {UpdateManager}=require('../updater.cjs');
async function fixture(t){
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'evomyn-mac-update-'));t.after(()=>fs.rm(root,{recursive:true,force:true}));
 const file=path.join(root,'update.zip');await fs.writeFile(file,'test zip bytes');
 const native=new EventEmitter();native.setFeedURL=({url})=>native.url=url;native.quitAndInstall=()=>{native.installed=true;};
 return {root,file,native,installer:new MacUpdateInstaller(native,{timeout:3000})};
}
test('native Mac updater receives only the verified archive over a private loopback feed',async t=>{
 const {file,native,installer}=await fixture(t);let checked;
 native.checkForUpdates=()=>{checked=(async()=>{
  const feedUrl=new URL(native.url);assert.equal(feedUrl.hostname,'127.0.0.1');
  assert.equal((await fetch(feedUrl.origin+'/update.zip')).status,404);
  assert.equal((await fetch(native.url,{method:'POST'})).status,405);
  const feed=await fetch(native.url).then(r=>r.json());assert.equal(await fetch(feed.url).then(r=>r.text()),'test zip bytes');
  native.emit('update-downloaded');
 })();checked.catch(()=>native.emit('error',new Error('fixture failed')));};
 await installer.prepare(file);await checked;assert.equal(native.installed,undefined);installer.quitAndInstall();assert.equal(native.installed,true);
 await assert.rejects(fetch(native.url));assert.equal(native.listenerCount('error'),0);
});
test('native signature rejection and cancellation never hand off installation',async t=>{
 const {file,native,installer}=await fixture(t);
 native.checkForUpdates=()=>setImmediate(()=>native.emit('error',new Error('signature rejected')));
 await assert.rejects(installer.prepare(file),/Apple/);assert.throws(()=>installer.quitAndInstall(),/就绪/);
 native.checkForUpdates=()=>setImmediate(()=>installer.cancel());
 await assert.rejects(installer.prepare(file),/取消/);assert.equal(native.installed,undefined);
});
for(const reason of ['timeout','cancel']){
 test(`late native events after ${reason} are contained and cannot complete a retry`,async t=>{
  const {file,native,installer}=await fixture(t);let checks=0;
  installer.timeout=10;
  native.checkForUpdates=()=>{checks++;if(reason==='cancel')setImmediate(()=>installer.cancel());};
  await assert.rejects(installer.prepare(file),reason==='cancel'?/取消/:/超时/);
  assert.doesNotThrow(()=>native.emit('error',new Error('request failed after loopback server closed')));
  native.emit('update-downloaded');
  assert.throws(()=>installer.quitAndInstall(),/就绪/);
  await assert.rejects(installer.prepare(file),/重新启动/);
  assert.equal(checks,1);
  assert.equal(native.installed,undefined);
 });
}
test('Mac downloads and offline imports share signature checks and pass ZIP without NSIS flags',async t=>{
 const {root}=await fixture(t),bytes=Buffer.from('zip fixture');
 const {publicKey,privateKey}=crypto.generateKeyPairSync('ed25519');
 const payload={version:'0.3.0',platform:'darwin',arch:'arm64',url:'https://updates.example.test/mac.zip',size:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex')};
 const sign=value=>{const data=Buffer.from(JSON.stringify(value));return Buffer.from(JSON.stringify({signed:data.toString('base64'),signature:crypto.sign(null,data,privateKey).toString('base64')}));};
 const calls=[],manager=new UpdateManager({currentVersion:'0.2.15',platform:'darwin',arch:'arm64',publicKey,cacheDir:path.join(root,'cache'),feedUrl:'https://updates.example.test/mac.json',transport:{get:async()=>sign(payload),download:async(_url,file)=>fs.writeFile(file,bytes)},onBeforeInstall:async()=>calls.push('stop'),spawnInstaller:async(file,args)=>calls.push({file,args})});
 await manager.check();await manager.download();await manager.install();assert.equal(calls[0],'stop');assert.match(calls[1].file,/mac-arm64.zip$/);assert.deepEqual(calls[1].args,[]);
 const manifest=path.join(root,'release.json'),archive=path.join(root,'offline.zip');await fs.writeFile(manifest,sign({...payload,url:null}));await fs.writeFile(archive,bytes);assert.equal((await manager.importRelease(manifest,archive)).state,'ready');
 await fs.writeFile(manifest,sign({...payload,platform:'win32'}));await assert.rejects(manager.importRelease(manifest,archive),/平台/);
});
