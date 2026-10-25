'use strict';
const {EventEmitter}=require('node:events');
const crypto=require('node:crypto');
const fs=require('node:fs');
const fsp=require('node:fs/promises');
const path=require('node:path');
const https=require('node:https');
const {Transform}=require('node:stream');
const {pipeline}=require('node:stream/promises');
const {spawn}=require('node:child_process');

const MAX_INSTALLER=1024*1024*1024;
function httpsUrl(value){
 let url;try{url=new URL(value);}catch{throw new Error('请输入有效的 HTTPS 更新地址。');}
 if(url.protocol!=='https:'||url.username||url.password||url.hash)throw new Error('更新地址必须使用 HTTPS，且不能包含账号或片段。');
 return url.href;
}
function versionParts(value){
 if(typeof value!=='string'||!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(value))throw new Error('更新版本号无效。');
 const parts=value.split('.').map(Number);if(parts.some(n=>!Number.isSafeInteger(n)||n>2147483647))throw new Error('更新版本号无效。');return parts;
}
function newer(candidate,current){const a=versionParts(candidate),b=versionParts(current);for(let i=0;i<3;i++){if(a[i]!==b[i])return a[i]>b[i];}return false;}
function decode64(value,max){
 if(typeof value!=='string'||value.length>max*2||!value.length||value.length%4||!/^[A-Za-z0-9+/]+={0,2}$/.test(value))throw new Error('更新签名格式无效。');
 const data=Buffer.from(value,'base64');if(data.length>max||data.toString('base64')!==value)throw new Error('更新签名格式无效。');return data;
}
function verifyManifest(bytes,publicKey,{platform,arch,allowLocal=false}){
 if(bytes.length>65536)throw new Error('更新说明超过限制。');
 let envelope;try{envelope=JSON.parse(bytes.toString('utf8'));}catch{throw new Error('更新说明格式无效。');}
 if(!envelope||typeof envelope!=='object'||Array.isArray(envelope)||Object.keys(envelope).sort().join(',')!=='signature,signed')throw new Error('更新说明格式无效。');
 const payload=decode64(envelope.signed,32768),signature=decode64(envelope.signature,64);
 if(signature.length!==64||!crypto.verify(null,payload,publicKey,signature))throw new Error('更新签名校验失败，未下载或安装任何文件。');
 let value;try{value=JSON.parse(payload.toString('utf8'));}catch{throw new Error('更新说明格式无效。');}
 const required=['version','platform','arch','url','size','sha256'];
 if(!value||typeof value!=='object'||Array.isArray(value)||required.some(k=>!Object.hasOwn(value,k))||Object.keys(value).some(k=>![...required,'notes'].includes(k)))throw new Error('更新说明字段无效。');
 versionParts(value.version);
 if(value.platform!==platform||value.arch!==arch)throw new Error('更新包与当前系统平台不符。');
 if(!Number.isSafeInteger(value.size)||value.size<=0||value.size>MAX_INSTALLER||typeof value.sha256!=='string'||!/^[0-9a-f]{64}$/.test(value.sha256))throw new Error('更新文件校验信息无效。');
 if(value.notes!==undefined&&(typeof value.notes!=='string'||value.notes.length>8192))throw new Error('更新说明过长。');
 if(!(allowLocal&&value.url===null))value.url=httpsUrl(value.url);
 return Object.freeze({...value});
}

function response(url,{signal,redirects=0}={}){
 return new Promise((resolve,reject)=>{
  const request=https.get(httpsUrl(url),{signal,headers:{'User-Agent':'EvoMyn-Updater','Accept':'application/json, application/octet-stream'}},incoming=>{
   if([301,302,303,307,308].includes(incoming.statusCode)){
    incoming.resume();if(redirects>=3||!incoming.headers.location)return reject(new Error('更新服务器重定向无效。'));
    let next;try{next=httpsUrl(new URL(incoming.headers.location,url).href);}catch(error){return reject(error);}
    response(next,{signal,redirects:redirects+1}).then(resolve,reject);return;
   }
   if(incoming.statusCode!==200){incoming.resume();reject(new Error('更新服务器返回 '+incoming.statusCode+'，请稍后重试。'));return;}
   resolve(incoming);
  });
  request.setTimeout(30000,()=>request.destroy(new Error('更新连接超时。')));
  request.on('error',reject);
 });
}
const transport={
 async get(url,{maxBytes=65536,signal}={}){
  const incoming=await response(url,{signal});const chunks=[];let size=0;
  for await(const chunk of incoming){size+=chunk.length;if(size>maxBytes){incoming.destroy();throw new Error('更新说明超过限制。');}chunks.push(chunk);}
  return Buffer.concat(chunks);
 },
 async download(url,target,{maxBytes,onProgress,signal}){
  const incoming=await response(url,{signal});let size=0;
  const bounded=new Transform({transform(chunk,encoding,callback){size+=chunk.length;if(size>maxBytes)return callback(new Error('更新文件超过声明大小。'));onProgress(size);callback(null,chunk);}});
  await pipeline(incoming,bounded,fs.createWriteStream(target,{flags:'wx',mode:0o600}));
 }
};
async function verifyFile(file,manifest){
 const info=await fsp.lstat(file);if(!info.isFile()||info.isSymbolicLink()||info.size!==manifest.size)throw new Error('更新文件大小校验失败。');
 const hash=crypto.createHash('sha256');for await(const bytes of fs.createReadStream(file))hash.update(bytes);
 if(hash.digest('hex')!==manifest.sha256)throw new Error('更新文件完整性校验失败。');
}
async function spawnInstaller(file,args){
 if(process.platform!=='win32')throw new Error('安装程序仅适用于 Windows。');
 await new Promise((resolve,reject)=>{const child=spawn(file,args,{detached:true,stdio:'ignore',windowsHide:true});child.once('error',reject);child.once('spawn',()=>{child.unref();resolve();});});
}
class UpdateManager extends EventEmitter{
 constructor(options){
  super();this.options={platform:process.platform,arch:process.arch,transport,onBeforeInstall:async()=>{},spawnInstaller,...options};
  versionParts(this.options.currentVersion);this.feed='';this.candidate=null;this.file=null;this.operation=null;
  this.value={state:'not-configured',currentVersion:this.options.currentVersion,availableVersion:null,progress:0,notes:'',message:'尚未配置更新发布地址。'};
  if(options.feedUrl)this.setFeed(options.feedUrl);
 }
 status(){return {...this.value,feedConfigured:!!this.feed};}
 change(value){this.value={...this.value,...value};this.emit('status',this.status());return this.status();}
 setFeed(value){if(this.operation)throw new Error('更新操作进行中，请稍后再试。');this.feed=value?httpsUrl(value):'';this.candidate=null;this.file=null;return this.change({state:this.feed?'idle':'not-configured',availableVersion:null,progress:0,notes:'',message:this.feed?'可以检查更新。':'尚未配置更新发布地址。'});}
 async perform(action,work){
  if(this.operation)throw new Error('更新操作进行中，请稍后再试。');
  this.operation=new AbortController();
  try{return await work(this.operation.signal);}catch(error){this.change({state:'error',message:error.name==='AbortError'?'更新已取消。':error.message});throw error;}finally{this.operation=null;}
 }
 async check(){
  if(!this.feed)return this.status();
  return this.perform('check',async signal=>{
   this.candidate=null;this.file=null;this.change({state:'checking',progress:0,message:'正在检查更新…'});
   const bytes=await this.options.transport.get(this.feed,{maxBytes:65536,signal});
   const candidate=verifyManifest(bytes,this.options.publicKey,this.options);
   if(!newer(candidate.version,this.options.currentVersion))return this.change({state:'up-to-date',availableVersion:null,message:'已是最新版本。'});
   this.candidate=candidate;return this.change({state:'available',availableVersion:candidate.version,notes:candidate.notes||'',message:'新版本已就绪，确认后下载安装。'});
  });
 }
 async cache(){
  await fsp.mkdir(this.options.cacheDir,{recursive:true});
  // Cache paths belong to this application; do not install through a linked file.
  const info=await fsp.lstat(this.options.cacheDir);if(!info.isDirectory()||info.isSymbolicLink())throw new Error('更新缓存目录无效。');
  const name=this.options.platform==='darwin'?`EvoMyn-${this.candidate.version}-mac-${this.options.arch}.zip`:`EvoMyn-Setup-${this.candidate.version}-${this.options.arch}.exe`;
  return path.join(this.options.cacheDir,name);
 }
 async download(){
  if(!this.candidate||this.value.state!=='available'||!this.candidate.url)throw new Error('请先检查可用更新。');
  return this.perform('download',async signal=>{
   const target=await this.cache(),partial=target+'.part-'+crypto.randomUUID();this.file=null;
   this.change({state:'downloading',progress:0,message:'正在下载更新…'});
   try{
    await this.options.transport.download(this.candidate.url,partial,{maxBytes:this.candidate.size,signal,onProgress:received=>this.change({progress:Math.min(1,received/this.candidate.size)})});
    await verifyFile(partial,this.candidate);await this.publishFile(partial,target);this.file=target;
   }finally{await fsp.unlink(partial).catch(error=>{if(error.code!=='ENOENT')throw error;});}
   return this.change({state:'ready',progress:1,message:'下载与签名校验完成，可重启安装。'});
  });
 }
 async publishFile(temporary,target){
  try{const info=await fsp.lstat(target);if(!info.isFile()||info.isSymbolicLink())throw new Error('更新缓存文件无效。');await fsp.unlink(target);}catch(error){if(error.code!=='ENOENT')throw error;}
  await fsp.rename(temporary,target);
 }
 async importRelease(manifestFile,installerFile){
  return this.perform('import',async()=>{
   const info=await fsp.stat(manifestFile);if(info.size>65536)throw new Error('更新说明超过限制。');
   const candidate=verifyManifest(await fsp.readFile(manifestFile),this.options.publicKey,{...this.options,allowLocal:true});
   if(!newer(candidate.version,this.options.currentVersion))throw new Error('只能安装比当前版本更新的更新包。');
   await verifyFile(installerFile,candidate);this.candidate=candidate;const target=await this.cache();
   const temporary=target+'.part-'+crypto.randomUUID();
   try{await fsp.copyFile(installerFile,temporary,fs.constants.COPYFILE_EXCL);await verifyFile(temporary,candidate);await this.publishFile(temporary,target);this.file=target;}
   finally{await fsp.unlink(temporary).catch(error=>{if(error.code!=='ENOENT')throw error;});}
   return this.change({state:'ready',availableVersion:candidate.version,notes:candidate.notes||'',progress:1,message:'离线更新包校验完成，可重启安装。'});
  });
 }
 async install(){
  if(!this.candidate||!this.file||this.value.state!=='ready')throw new Error('没有已验证的更新可安装。');
  return this.perform('install',async()=>{
   await verifyFile(this.file,this.candidate);
   this.change({state:'installing',message:'正在停止服务并安装更新…'});
   await this.options.onBeforeInstall();await verifyFile(this.file,this.candidate);await this.options.spawnInstaller(this.file,this.options.platform==='darwin'?[]:['/S','--updated','--force-run']);
   return this.status();
  });
 }
 cancel(){this.operation?.abort();}
}
module.exports={UpdateManager,verifyManifest,httpsUrl,newer,verifyFile};
