'use strict';
// Real Electron acceptance using a new, disposable profile; never installed data.
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process'),assert=require('node:assert/strict');
const desktop=path.resolve(__dirname,'..'),home=path.join(desktop,'build','language-acceptance-'+Date.now());
fs.mkdirSync(home,{recursive:true});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function freePort(){const net=require('node:net'),server=net.createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port;await new Promise(resolve=>server.close(resolve));return port;}
async function until(read,predicate=value=>!!value){for(let n=0;n<180;n++){try{const value=await read();if(predicate(value))return value;}catch{}await sleep(500);}throw new Error('Acceptance wait timed out');}
async function connect(target){
 const socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{socket.close();reject(new Error('Debugger connection timed out'));},8000);socket.onopen=()=>{clearTimeout(timer);resolve();};socket.onerror=error=>{clearTimeout(timer);reject(error);};});
 let serial=0;const pending=new Map();
 socket.onmessage=event=>{const value=JSON.parse(event.data);if(pending.has(value.id)){const request=pending.get(value.id);clearTimeout(request.timer);request.resolve(value);pending.delete(value.id);}};
 socket.onclose=()=>{for(const request of pending.values()){clearTimeout(request.timer);request.reject(new Error('Debugger disconnected'));}pending.clear();};
 function send(method,params){const id=++serial;return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{pending.delete(id);reject(new Error('Debugger request timed out'));},10000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});}
 return {close:()=>socket.close(),async evaluate(expression){const value=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(value.error||value.result?.exceptionDetails)throw new Error(JSON.stringify(value.error||value.result.exceptionDetails));return value.result.result.value;},async screenshot(file){const value=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(file,Buffer.from(value.result.data,'base64'));}};
}
(async()=>{
 const evidence={};
 for(let launch=0;launch<2;launch++){
  const port=await freePort(),child=spawn(path.join(desktop,'node_modules/electron/dist/electron.exe'),[desktop,'--background','--remote-debugging-address=127.0.0.1','--remote-debugging-port='+port],{windowsHide:true,env:{...process.env,PERSONAL_MEMORY_HOME:home,MNEMOSYNE_NO_EMBEDDINGS:'1',HF_HUB_OFFLINE:'1',TRANSFORMERS_OFFLINE:'1'}});
  const log=fs.openSync(path.join(home,'electron-'+launch+'.log'),'w');child.stdout.on('data',bytes=>fs.writeSync(log,bytes));child.stderr.on('data',bytes=>fs.writeSync(log,bytes));
  let shell,memory;
  const targets=()=>fetch('http://127.0.0.1:'+port+'/json/list').then(response=>response.json());
  try{
   const target=await until(async()=>(await targets()).find(item=>item.url.startsWith('file:')));shell=await connect(target);
   await until(()=>shell.evaluate("window.personalMemory.command('status').then(value=>value.service?.ready)"));
   if(launch===1){assert.equal(await shell.evaluate("document.documentElement.lang"),'en');evidence.restartPersistence=true;continue;}
   await shell.evaluate("window.personalMemory.command('view',{page:'settings'})");
   // Exercise the actual settings selector and its IPC handler.
   await shell.evaluate("document.getElementById('language').value='en';document.getElementById('language').dispatchEvent(new Event('change'))");
   await until(()=>shell.evaluate("document.documentElement.lang==='en'&&document.querySelector('[data-page=memory] span').textContent==='Memory'"));
   assert.equal(JSON.parse(fs.readFileSync(path.join(home,'preferences.json'),'utf8')).language,'en');
   await shell.screenshot(path.join(home,'settings-en.png'));
   await shell.evaluate("window.personalMemory.command('view',{page:'memory'})");
   memory=await connect(await until(async()=>(await targets()).find(item=>/\/memory\/$/.test(item.url))));
   await until(()=>memory.evaluate("document.documentElement.lang==='en'&&!document.getElementById('createRecord').hidden"));
   assert.equal(await memory.evaluate("document.getElementById('pageTitle').textContent"),'Memory');
   await memory.evaluate("document.getElementById('createRecord').click();document.querySelector('[name=title]').value='记忆：私人中文草稿';document.querySelector('[name=body]').value='Do not change my record';document.querySelector('[name=title]').dispatchEvent(new Event('input',{bubbles:true}))");
   await shell.evaluate("window.personalMemory.command('set-language',{language:'zh-CN'})");
   assert.equal(await memory.evaluate("document.querySelector('[name=title]').value"),'记忆：私人中文草稿');
   assert.equal(await memory.evaluate("document.getElementById('recordEditorTitle').textContent"),'新增记忆');
   await shell.evaluate("window.personalMemory.command('set-language',{language:'en'})");
   assert.equal(await memory.evaluate("document.querySelector('[name=title]').value"),'记忆：私人中文草稿');
   assert.equal(await memory.evaluate("document.getElementById('recordEditorTitle').textContent"),'Add memory');
   evidence.draftPreserved=true;
   // Discard only this isolated, unsaved draft before navigating away.
   await memory.evaluate("document.getElementById('recordEditor').close()");
   await shell.evaluate("window.personalMemory.command('view',{page:'mcp'})");memory.close();memory=null;
   const abilities=await connect(await until(async()=>(await targets()).find(item=>item.url.includes('/memory/mcp/'))));
   try{await until(()=>abilities.evaluate("document.documentElement.lang==='en'&&document.querySelector('#mineTab').textContent.includes('My')"));await abilities.screenshot(path.join(home,'abilities-en.png'));evidence.abilities=true;}finally{abilities.close();}
   await shell.evaluate("window.personalMemory.command('view',{page:'settings'})");evidence.liveSwitch=true;
  }finally{
   memory?.close();if(shell){try{await shell.evaluate("window.personalMemory.command('quit')");}catch{}shell.close();}
   for(let n=0;n<40&&child.exitCode===null;n++)await sleep(250);
   if(child.exitCode===null&&child.pid){
    // Terminate only this newly spawned fixture's process tree on failure.
    await new Promise(resolve=>{const killer=spawn('taskkill.exe',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});killer.once('error',resolve);killer.once('exit',resolve);});
   }
   fs.closeSync(log);
  }
 }
 fs.writeFileSync(path.join(home,'result.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({home,...evidence}));
})().catch(error=>{console.error(error);process.exitCode=1;});
