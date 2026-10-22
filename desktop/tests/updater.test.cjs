'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {UpdateManager,verifyManifest}=require('../updater.cjs');

async function fixture(t,overrides={}){
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'personal-memory-update-'));
 t.after(()=>fs.rm(root,{recursive:true,force:true}));
 const {publicKey,privateKey}=crypto.generateKeyPairSync('ed25519');
 const installer=Buffer.from('isolated Windows installer fixture');
 const payload={version:'0.3.0',platform:'win32',arch:'x64',url:'https://updates.example.test/EvoMyn-Setup.exe',size:installer.length,sha256:crypto.createHash('sha256').update(installer).digest('hex'),notes:'版本说明'};
 function sign(value=payload){const data=Buffer.from(JSON.stringify(value));return Buffer.from(JSON.stringify({signed:data.toString('base64'),signature:crypto.sign(null,data,privateKey).toString('base64')}));}
 const calls=[];
 const transport={get:async()=>sign(),download:async(url,target,options)=>{calls.push('download');await fs.writeFile(target,installer,{flag:'wx'});options.onProgress(installer.length);}};
 const manager=new UpdateManager({currentVersion:'0.2.0',platform:'win32',arch:'x64',publicKey,cacheDir:root,transport,onBeforeInstall:async()=>calls.push('stop'),spawnInstaller:async(file,args)=>calls.push({file,args}),...overrides});
 return {root,manager,payload,sign,installer,privateKey,publicKey,calls,transport};
}
test('an unconfigured feed never contacts the network',async t=>{
 const f=await fixture(t);assert.equal((await f.manager.check()).state,'not-configured');assert.deepEqual(f.calls,[]);
});
test('signed update download and install stop services before installer handoff',async t=>{
 const f=await fixture(t);f.manager.setFeed('https://updates.example.test/latest.json');
 assert.equal((await f.manager.check()).state,'available');
 assert.equal((await f.manager.download()).state,'ready');
 await f.manager.install();assert.equal(f.calls[1],'stop');assert.equal(f.calls[2].file,path.join(f.root,'EvoMyn-Setup-0.3.0-x64.exe'));assert.ok(f.calls[2].args.includes('/S'));
});
test('a forged manifest is rejected before an installer is downloaded',async t=>{
 const f=await fixture(t);f.manager.setFeed('https://updates.example.test/latest.json');
 f.transport.get=async()=>Buffer.from(JSON.stringify({...JSON.parse(f.sign()),signature:Buffer.alloc(64).toString('base64')}));
 await assert.rejects(f.manager.check(),/签名/);assert.equal(f.manager.status().state,'error');assert.deepEqual(f.calls,[]);
});
test('a signed manifest for a different machine cannot be used',async t=>{
 const f=await fixture(t);for(const key of ['platform','arch'])assert.throws(()=>verifyManifest(f.sign({...f.payload,[key]:'other'}),f.publicKey,{platform:'win32',arch:'x64'}),/平台/);
});
test('invalid feed URLs and installer URLs are rejected',async t=>{
 const f=await fixture(t);for(const url of ['http://updates.test','file:///tmp/update','https://user:password@updates.test/feed','https://updates.test/feed#fragment'])assert.throws(()=>f.manager.setFeed(url),/HTTPS/);
 assert.throws(()=>verifyManifest(f.sign({...f.payload,url:'file:///tmp/update.exe'}),f.publicKey,{platform:'win32',arch:'x64'}),/HTTPS/);
});
test('older or equal versions cannot trigger installation',async t=>{
 const f=await fixture(t);f.manager.setFeed('https://updates.example.test/latest.json');
 for(const version of ['0.1.9','0.2.0']){f.transport.get=async()=>f.sign({...f.payload,version});assert.equal((await f.manager.check()).state,'up-to-date');await assert.rejects(f.manager.download(),/更新/);}
 assert.deepEqual(f.calls,[]);
});
test('a wrong hash is rejected and incomplete download is removed',async t=>{
 const f=await fixture(t);f.manager.setFeed('https://updates.example.test/latest.json');
 f.transport.get=async()=>f.sign({...f.payload,sha256:'0'.repeat(64)});await f.manager.check();await assert.rejects(f.manager.download(),/校验/);
 assert.deepEqual(await fs.readdir(f.root),[]);assert.deepEqual(f.calls,['download']);
});
test('interrupted downloads leave no executable to install',async t=>{
 const f=await fixture(t);f.manager.setFeed('https://updates.example.test/latest.json');
 f.transport.download=async(url,target)=>{await fs.writeFile(target,'partial',{flag:'wx'});throw new Error('connection interrupted');};await f.manager.check();await assert.rejects(f.manager.download(),/interrupted/);assert.deepEqual(await fs.readdir(f.root),[]);await assert.rejects(f.manager.install(),/更新/);
});
test('changed downloaded bytes are checked again before stopping services',async t=>{
 const f=await fixture(t);f.manager.setFeed('https://updates.example.test/latest.json');await f.manager.check();await f.manager.download();
 await fs.appendFile(path.join(f.root,'EvoMyn-Setup-0.3.0-x64.exe'),'tampered');await assert.rejects(f.manager.install(),/校验/);assert.deepEqual(f.calls,['download']);
});
test('malformed sizes, versions and hashes cannot pass signature validation',async t=>{
 const f=await fixture(t);for(const changes of [{size:-1},{size:2**40},{version:'../../escape'},{version:'01.2.0'},{sha256:'not a hash'},{notes:'x'.repeat(10000)}])assert.throws(()=>verifyManifest(f.sign({...f.payload,...changes}),f.publicKey,{platform:'win32',arch:'x64'}));
});
test('a signed local release can be verified without a public hosting address',async t=>{
 const f=await fixture(t);const manifest=path.join(f.root,'local-release.json'),source=path.join(f.root,'source.exe');await fs.writeFile(manifest,f.sign({...f.payload,url:null}));await fs.writeFile(source,f.installer);
 assert.equal((await f.manager.importRelease(manifest,source)).state,'ready');await f.manager.install();assert.equal(f.calls[0],'stop');
});
