'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const {createUpdateTransport,createElectronFetch}=require('../update-transport.cjs');
const {EventEmitter}=require('node:events'),{Readable}=require('node:stream');
test('Electron request adapter exposes redirects and streams through the bounded transport',async()=>{
 const calls=[];
 const request=options=>{
  calls.push(options);const pending=new EventEmitter();
  pending.abort=()=>pending.emit('close');
  pending.end=()=>queueMicrotask(()=>{
   if(calls.length===1)pending.emit('redirect',302,'GET','https://assets.example.test/feed');
   else{const incoming=Readable.from([Buffer.from('signed bytes')]);incoming.statusCode=200;pending.emit('response',incoming);}
  });return pending;
 };
 const result=await createUpdateTransport(createElectronFetch(request)).get('https://updates.example.test/feed');
 assert.equal(result.toString(),'signed bytes');assert.equal(calls.length,2);assert.equal(calls[0].credentials,'omit');assert.equal(calls[0].redirect,'manual');
});
test('the supplied system-aware fetch follows bounded HTTPS redirects without cookies',async()=>{
 const calls=[];
 const transport=createUpdateTransport(async(url,options)=>{calls.push({url,options});return calls.length<3?new Response(null,{status:302,headers:{location:calls.length===1?'/version/latest.json':'https://assets.example.test/latest.json'}}):new Response('signed envelope');});
 assert.equal((await transport.get('https://updates.example.test/latest.json')).toString(),'signed envelope');
 assert.equal(calls.length,3);assert.equal(calls[0].options.redirect,'manual');assert.equal(calls[0].options.credentials,'omit');assert.equal(calls[2].url,'https://assets.example.test/latest.json');
});
test('redirects cannot downgrade HTTPS or loop forever',async()=>{
 const downgrade=createUpdateTransport(async()=>new Response(null,{status:302,headers:{location:'http://assets.example.test/file'}}));
 await assert.rejects(downgrade.get('https://updates.example.test/file'),/HTTPS/);
 let calls=0;const loop=createUpdateTransport(async()=>{calls++;return new Response(null,{status:302,headers:{location:'/again'}});});
 await assert.rejects(loop.get('https://updates.example.test/file'),/重定向/);assert.equal(calls,4);
});
test('manifest and installer stream limits apply even without content length',async t=>{
 const transport=createUpdateTransport(async()=>new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array(8));c.enqueue(new Uint8Array(8));c.close();}})));
 await assert.rejects(transport.get('https://updates.example.test/feed',{maxBytes:12}),/限制/);
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'evomyn-transport-'));t.after(()=>fs.rm(dir,{recursive:true,force:true}));
 await assert.rejects(transport.download('https://updates.example.test/file',path.join(dir,'partial'),{maxBytes:12,onProgress:()=>{}}),/大小/);
});
test('installer bytes stream to an exclusive file and report progress',async t=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'evomyn-transport-'));t.after(()=>fs.rm(dir,{recursive:true,force:true}));
 const file=path.join(dir,'update.exe'),progress=[];
 const transport=createUpdateTransport(async()=>new Response('verified bytes'));
 await transport.download('https://updates.example.test/file',file,{maxBytes:100,onProgress:n=>progress.push(n)});
 assert.equal(await fs.readFile(file,'utf8'),'verified bytes');assert.equal(progress.at(-1),14);
 await assert.rejects(transport.download('https://updates.example.test/file',file,{maxBytes:100,onProgress:()=>{}}),{code:'EEXIST'});
});
test('idle timeout aborts the transport and cancellation is preserved',async()=>{
 const stalled=async(_url,{signal})=>new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(signal.reason),{once:true}));
 await assert.rejects(createUpdateTransport(stalled,{timeoutMs:15}).get('https://updates.example.test/feed'),/超时/);
 const abort=new AbortController();abort.abort();
 await assert.rejects(createUpdateTransport(stalled).get('https://updates.example.test/feed',{signal:abort.signal}),{name:'AbortError'});
});
