'use strict';
// Real Electron acceptance using a new, disposable profile; never installed data.
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process'),assert=require('node:assert/strict');
const desktop=path.resolve(__dirname,'..'),home=path.join(desktop,'build','attachments-acceptance-'+Date.now());
fs.mkdirSync(home,{recursive:true});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function freePort(){const net=require('node:net'),server=net.createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port;await new Promise(resolve=>server.close(resolve));return port;}
async function until(read,predicate=value=>!!value){for(let n=0;n<180;n++){try{const value=await read();if(predicate(value))return value;}catch{}await sleep(500);}throw new Error('Acceptance wait timed out');}
async function connect(target){
 const socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{socket.close();reject(new Error('Debugger connection timed out'));},8000);socket.onopen=()=>{clearTimeout(timer);resolve();};socket.onerror=error=>{clearTimeout(timer);reject(error);};});
 let serial=0;const pending=new Map();
 socket.onmessage=event=>{const value=JSON.parse(event.data);if(pending.has(value.id)){const request=pending.get(value.id);clearTimeout(request.timer);request.resolve(value);pending.delete(value.id);}};
 socket.onclose=()=>{for(const request of pending.values()){clearTimeout(request.timer);request.reject(new Error('Debugger disconnected'));}pending.clear();};
 function send(method,params){const id=++serial;return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{pending.delete(id);reject(new Error('Debugger request timed out: '+method+' '+String(params?.expression||'').slice(0,90)));},10000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});}
 return {close:()=>socket.close(),async evaluate(expression){const value=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(value.error||value.result?.exceptionDetails)throw new Error(JSON.stringify(value.error||value.result.exceptionDetails));return value.result.result.value;},async screenshot(file){const value=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(file,Buffer.from(value.result.data,'base64'));}};
}
(async()=>{
 const port=await freePort(),child=spawn(path.join(desktop,'node_modules/electron/dist/electron.exe'),[desktop,'--remote-debugging-address=127.0.0.1','--remote-debugging-port='+port],{windowsHide:true,env:{...process.env,PERSONAL_MEMORY_HOME:home,MNEMOSYNE_NO_EMBEDDINGS:'1',HF_HUB_OFFLINE:'1',TRANSFORMERS_OFFLINE:'1'}});
 const log=fs.openSync(path.join(home,'electron.log'),'w');child.stdout.on('data',bytes=>fs.writeSync(log,bytes));child.stderr.on('data',bytes=>fs.writeSync(log,bytes));
 let shell,memory;const evidence={};
 try{
  const targets=()=>fetch('http://127.0.0.1:'+port+'/json/list').then(response=>response.json());
  shell=await connect(await until(async()=>(await targets()).find(item=>item.url.startsWith('file:'))));
  await until(()=>shell.evaluate("window.personalMemory.command('status').then(value=>value.service?.ready)"));
  const code=`import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from client import rpc
root=Path(sys.argv[2]);source=root.parent/'inputs'
for folder,content in [('one',b'first original'),('two',b'second original')]:
 p=source/folder/'report.txt';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
def call(name,args):
 r=rpc(root,'call-tool',name=name,arguments=args)
 assert not r.get('isError'),r
 return r.get('structuredContent') or json.loads(next(c['text'] for c in r['content'] if c['type']=='text'))
assert 'archive_attach' in [t['name'] for t in rpc(root,'list-tools')]
r=call('archive_record',{'category':'resource','title':'Attachment acceptance fixture','body':'Isolated test only','file_path':str(source/'one/report.txt')})
assert len(r['attachments'])==1,r
r=call('archive_attach',{'record_id':r['id'],'file_paths':[str(source/'two/report.txt')],'expected_revision':r['revision']})
assert len(r['attachments'])==2 and len({e['file_path'] for e in r['attachments']})==2
for p in source.rglob('report.txt'):p.unlink()
print(json.dumps({'id':r['id'],'revision':r['revision']}))`;
  const {execFileSync}=require('node:child_process');
  const result=JSON.parse(execFileSync(path.join(desktop,'build/runtime/python/python.exe'),['-E','-s','-X','utf8','-c',code,path.join(desktop,'backend'),path.join(home,'service')],{encoding:'utf8',windowsHide:true,timeout:60000,env:{...process.env,MNEMOSYNE_NO_EMBEDDINGS:'1'}}));console.log('MCP import verified');evidence.mcpImport=true;evidence.originalsRemoved=true;
  memory=await connect(await until(async()=>(await targets()).find(item=>/\/memory\/$/.test(item.url))));
  await memory.evaluate("document.getElementById('refresh').click()");
  await until(()=>memory.evaluate(`fetch('./api/records').then(r=>r.json()).then(v=>v.records.some(r=>r.id===${JSON.stringify(result.id)}))`));
  await memory.evaluate(`location.hash='#resource/'+${JSON.stringify(result.id)};document.getElementById('refresh').click()`);
  await until(()=>memory.evaluate("document.getElementById('detail').open&&document.querySelectorAll('.attachment-links a').length===2"));
  assert.equal(await memory.evaluate("typeof window.evomynAttachments?.open"),'function');assert.equal(await memory.evaluate("typeof window.personalMemory"),'undefined');
  await memory.evaluate("const transfer=new DataTransfer();transfer.items.add(new File(['browser imported bytes'],'中文附件.txt',{type:'text/plain'}));const input=document.getElementById('attachmentFiles');input.files=transfer.files;input.dispatchEvent(new Event('change'))");
  await until(()=>memory.evaluate("document.querySelectorAll('.attachment-links a').length===3&&!document.getElementById('addAttachments').disabled"));
  console.log('UI import visible');const info=await memory.evaluate(`fetch('./api/records').then(r=>r.json()).then(v=>v.records.find(r=>r.id===${JSON.stringify(result.id)}))`);
  assert.equal(info.attachments.length,3);assert.equal('file_path' in info,false);assert.ok(info.attachments.every(item=>!('file_path'in item)));
  console.log('Public metadata verified');const bytes=await memory.evaluate("Promise.all([...document.querySelectorAll('.attachment-links a')].map(a=>fetch(a.href).then(r=>{if(!r.ok)throw new Error('Download failed');return r.text()})))");
  assert.deepEqual(bytes,['first original','second original','browser imported bytes']);evidence.uiImport=true;evidence.downloadBytes=true;
  console.log('Download bytes verified');await memory.screenshot(path.join(home,'attachments-zh.png'));
  await shell.evaluate("window.personalMemory.command('set-language',{language:'en'})");
  assert.equal(await memory.evaluate("document.getElementById('addAttachments').textContent.trim()"),'Add attachments');
  assert.equal(await memory.evaluate("document.querySelectorAll('.attachment-links a').length"),3);evidence.bilingual=true;
  await memory.screenshot(path.join(home,'attachments-en.png'));
  fs.writeFileSync(path.join(home,'result.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({home,...evidence}));
 }finally{
  memory?.close();if(shell){try{await shell.evaluate("window.personalMemory.command('quit')");}catch{}shell.close();}
  for(let n=0;n<40&&child.exitCode===null;n++)await sleep(250);
  if(child.exitCode===null&&child.pid)await new Promise(resolve=>{const killer=spawn('taskkill.exe',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});killer.once('error',resolve);killer.once('exit',resolve);});
  fs.closeSync(log);
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
