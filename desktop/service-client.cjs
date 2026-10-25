'use strict';
const {EventEmitter}=require('node:events');
const {spawn}=require('node:child_process');
const crypto=require('node:crypto');
const path=require('node:path');
const fs=require('node:fs/promises');
const {toolsPath}=require('./platform.cjs');
const MAX_LINE=1024*1024;
async function waitClients(records,options){
 if(!records.length)return;
 const code=`import json,sys,time
sys.path.insert(0,sys.argv[1])
from client import DesktopOwner
owners=[]
try:
 for record in json.load(sys.stdin):
  owner=DesktopOwner(record['pid'],record['creation'])
  if owner.alive(): owners.append(owner)
  else: owner.close()
 deadline=time.monotonic()+10
 while any(owner.alive() for owner in owners):
  if time.monotonic()>deadline: raise TimeoutError('Client helpers still running')
  time.sleep(0.05)
finally:
 for owner in owners: owner.close()`;
 await new Promise((resolve,reject)=>{
  const child=spawn(options.python,['-E','-s','-B','-X','utf8','-c',code,path.dirname(options.script)],{stdio:['pipe','ignore','ignore'],windowsHide:true});
  const timer=setTimeout(()=>{child.kill();reject(new Error('客户端退出检查超时，已取消更新。'));},15000);
  child.once('error',()=>{clearTimeout(timer);reject(new Error('无法检查客户端进程，已取消更新。'));});
  child.once('exit',code=>{clearTimeout(timer);if(code===0)resolve();else reject(new Error('仍有客户端连接正在关闭，已取消更新。请稍后重试。'));});
  child.stdin.on('error',()=>{});child.stdin.end(JSON.stringify(records));
 });
}
class ServiceClient extends EventEmitter{
 constructor({python,script,appDir,dataRoot,spawnProcess=spawn,env=process.env,shutdownTimeout=20000,killTimeout=5000,waitForClients=waitClients}){
  super();this.options={python,script,appDir,dataRoot,spawnProcess,env,shutdownTimeout,killTimeout,waitForClients};this.child=null;this.pending=new Map();this.buffer='';this.closing=false;
 }
 start(){
  if(this.child)throw new Error('后台服务已启动。');
  const o=this.options,env={...o.env};
  for(const key of Object.keys(env))if(/^PYTHON|^MCP|^PERSONAL_ARCHIVE|^MNEMOSYNE_DESKTOP|^DEVICE_GATEWAY/i.test(key))delete env[key];
  const pathKey=Object.keys(env).find(key=>key.toUpperCase()==='PATH')||'PATH';env[pathKey]=toolsPath(o.python)+path.delimiter+(env[pathKey]||'');
  const child=o.spawnProcess(o.python,['-E','-s','-B','-X','utf8','-u',o.script,'--app-dir',o.appDir,'--data-root',o.dataRoot],{env,cwd:o.appDir,stdio:['pipe','pipe','pipe'],windowsHide:true});
  this.child=child;this.closing=false;child.stdout.setEncoding('utf8');
  child.stdin.on('error',()=>this.fail(new Error('后台服务连接已关闭。')));
  child.stdout.on('error',()=>this.fail(new Error('后台服务连接已关闭。')));
  child.stdout.on('data',chunk=>this.read(chunk));
  // Backend diagnostics deliberately exclude endpoints, headers and user content.
  child.stderr.resume();
  child.on('error',()=>this.fail(new Error('后台服务无法启动，请检查安装文件和数据目录。')));
  child.on('exit',()=>{this.child=null;this.fail(new Error('后台服务已退出。'));if(!this.closing)this.emit('unavailable');});
  return this.request('status',{},100000);
 }
 read(chunk){
  this.buffer+=chunk;
  while(this.buffer.includes('\n')){
   const end=this.buffer.indexOf('\n'),line=this.buffer.slice(0,end);this.buffer=this.buffer.slice(end+1);
   if(Buffer.byteLength(line)>MAX_LINE)return this.protocolFailure();
   let value;try{value=JSON.parse(line);}catch{return this.protocolFailure();}
   const pending=this.pending.get(value.id);if(!pending)continue;
   this.pending.delete(value.id);clearTimeout(pending.timer);
   if(value.ok===true)pending.resolve(value.result);else pending.reject(new Error(typeof value.error==='string'?value.error:'后台操作失败。'));
  }
  if(Buffer.byteLength(this.buffer)>MAX_LINE)this.protocolFailure();
 }
 protocolFailure(){this.fail(new Error('后台服务返回了无效响应。'));this.child?.stdin.end();}
 fail(error){for(const pending of this.pending.values()){clearTimeout(pending.timer);pending.reject(error);}this.pending.clear();}
 request(command,params={},timeout=60000){
  if(!this.child||this.child.exitCode!==null)return Promise.reject(new Error('后台服务尚未就绪。'));
  const id=crypto.randomUUID();
  return new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error('后台操作超时，请稍后重试。'));},timeout);
   this.pending.set(id,{resolve,reject,timer});
   this.child.stdin.write(JSON.stringify({id,command,...params})+'\n',error=>{if(error){clearTimeout(timer);this.pending.delete(id);reject(new Error('后台服务连接已关闭。'));}});
  });
 }
 async stop(){
  const child=this.child;if(!child)return;this.closing=true;
  const helpers=await this.clientIdentities();
  const exited=new Promise(resolve=>child.once('exit',resolve));
  try{await this.request('shutdown',{},Math.min(5000,this.options.shutdownTimeout));}catch{}
  child.stdin.end();
  const wait=milliseconds=>new Promise(resolve=>{const timer=setTimeout(()=>resolve(false),milliseconds);exited.then(()=>{clearTimeout(timer);resolve(true);});});
  const graceful=await wait(this.options.shutdownTimeout);
  if(!graceful){
   child.kill();
   if(!await wait(this.options.killTimeout))throw new Error('后台进程尚未退出，已取消安装更新。请退出应用后重试。');
   throw new Error('后台未能正常关闭，已取消本次更新。请重新打开应用后重试。');
  }
  // Descriptor removal forbids new adapters. Confirm registered processes exited,
  // rather than assuming their cancellation timer has already released DLLs.
  for(const [identity,record] of await this.clientIdentities())helpers.set(identity,record);
  await this.options.waitForClients([...helpers.values()],this.options);
 }
 async clientIdentities(){
  const directory=path.join(this.options.dataRoot,'desktop-clients');let names;
  try{names=await fs.readdir(directory);}catch(error){if(error.code==='ENOENT')return new Map();throw error;}
  if(names.length>1024)throw new Error('客户端连接记录过多，已取消更新。');
  const identities=new Map();
  for(const name of names){
   if(!/^[a-f0-9]{32}\.json$/.test(name))continue;
   try{const file=path.join(directory,name),info=await fs.lstat(file);if(!info.isFile()||info.isSymbolicLink()||info.size>4096)throw new Error('客户端连接记录无效。');const value=JSON.parse(await fs.readFile(file,'utf8'));if(!Number.isSafeInteger(value.pid)||value.pid<=0||typeof value.creation!=='string'||value.creation.length>100)throw new Error('客户端进程记录无效。');identities.set(value.pid+':'+value.creation,{pid:value.pid,creation:value.creation});}catch(error){if(error.code!=='ENOENT')throw error;}
  }
  return identities;
 }
}
module.exports={ServiceClient,waitClients};
