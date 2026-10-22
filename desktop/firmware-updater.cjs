'use strict';
const {EventEmitter}=require('node:events');
const crypto=require('node:crypto');
const fs=require('node:fs/promises');
const path=require('node:path');
const {httpsUrl,newer,verifyFile}=require('./updater.cjs');
const FIRMWARE_FEED='https://github.com/ArkFishingLab/EvoMyn/releases/download/firmware-stable/firmware-latest.json';
const MAX_FIRMWARE=4*1024*1024;
function decode64(value,limit){
 if(typeof value!=='string'||!value.length||value.length>limit*2||value.length%4||!/^[A-Za-z0-9+/]+={0,2}$/.test(value))throw new Error('固件签名格式无效。');
 const bytes=Buffer.from(value,'base64');if(bytes.length>limit||bytes.toString('base64')!==value)throw new Error('固件签名格式无效。');return bytes;
}
function validateFirmware(value){
 const fields=['type','version','board','project','partition','size','sha256','url','notes'];
 if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).sort().join(',')!==fields.sort().join(','))throw new Error('固件说明字段无效。');
 if(value.type!=='evomyn-firmware'||value.board!=='round-voice-175c'||value.project!=='xiaozhi'||value.partition!=='v2/32m')throw new Error('固件类型、板型、项目或分区不兼容。');
 newer(value.version,'2.5.7');if(newer('2.5.7',value.version))throw new Error('固件版本低于兼容要求。');
 if(!Number.isSafeInteger(value.size)||value.size<288||value.size>MAX_FIRMWARE||typeof value.sha256!=='string'||!/^[0-9a-f]{64}$/.test(value.sha256))throw new Error('固件大小或哈希无效。');
 if(typeof value.notes!=='string'||Buffer.byteLength(value.notes,'utf8')>2048||value.notes.includes('\0'))throw new Error('固件说明过长或无效。');
 const url=new URL(httpsUrl(value.url));
 // A signed artifact is pinned to one version, never a mutable stable/latest alias.
 const prefix='/ArkFishingLab/EvoMyn/releases/download/firmware-v'+value.version+'/';
 if(url.hostname!=='github.com'||url.port||url.search||!url.pathname.startsWith(prefix)||!/^[-A-Za-z0-9_.]+\.bin$/.test(url.pathname.slice(prefix.length)))throw new Error('固件地址必须是官方版本专属的 HTTPS 文件。');
 return Object.freeze({...value,url:url.href});
}
function verifyFirmwareManifest(bytes,publicKey){
 if(bytes.length>65536)throw new Error('固件说明超过限制。');
 let envelope;try{envelope=JSON.parse(bytes.toString('utf8'));}catch{throw new Error('固件说明格式无效。');}
 if(!envelope||typeof envelope!=='object'||Array.isArray(envelope)||Object.keys(envelope).sort().join(',')!=='signature,signed')throw new Error('固件说明格式无效。');
 const payload=decode64(envelope.signed,32768),signature=decode64(envelope.signature,64);
 if(signature.length!==64||publicKey.asymmetricKeyType!=='ed25519'||!crypto.verify(null,payload,publicKey,signature))throw new Error('固件签名校验失败。');
 let value;try{value=JSON.parse(payload.toString('utf8'));}catch{throw new Error('固件说明格式无效。');}
 return validateFirmware(value);
}
async function safeDirectory(directory){
 // Reject linked ancestors as well as the leaf before staging public bytes.
 const absolute=path.resolve(directory),parent=path.dirname(absolute);
 if(parent!==absolute)await safeDirectory(parent);
 try{const info=await fs.lstat(absolute);if(!info.isDirectory()||info.isSymbolicLink())throw new Error('固件缓存目录无效。');}
 catch(error){if(error.code!=='ENOENT')throw error;await fs.mkdir(absolute,{mode:0o700});}
}
class FirmwareUpdater extends EventEmitter{
 constructor(options){super();this.options=options;this.candidate=null;this.operation=null;this.value={state:'idle',latestVersion:null,progress:0,notes:'',message:'检查可下载的兼容固件。',canDownload:false};}
 status(){return {...this.value};}
 change(value){this.value={...this.value,...value};this.emit('status',this.status());return this.status();}
 async local(){
  const file=path.join(this.options.localDir,'manifest.json');
  try{
   const info=await fs.lstat(file);if(info.isSymbolicLink()||!info.isFile()||info.size>16384)return {};
   const value=JSON.parse(await fs.readFile(file,'utf8'));newer(value.version,'0.0.0');
   let valid=false;
   if(value.board==='round-voice-175c'&&value.project==='xiaozhi'&&value.partition==='v2/32m'&&Number.isSafeInteger(value.size)&&value.size>=288&&value.size<=MAX_FIRMWARE&&/^[0-9a-f]{64}$/.test(value.sha256)){
    try{await verifyFile(path.join(this.options.localDir,value.sha256+'.bin'),value);valid=true;}catch{}
   }
   return {version:value.version,sha256:value.sha256,valid};
  }catch(error){if(error.code&&error.code!=='ENOENT')throw error;return {};}
 }
 async perform(work){
  if(this.operation)throw new Error('固件操作进行中，请稍后再试。');
  const controller=new AbortController();this.operation=controller;
  try{return await work(controller.signal);}
  catch(error){this.change({state:'error',message:controller.signal.aborted?'固件下载已取消，可重试。':/返回 404/.test(error.message)?'兼容固件尚未发布或暂不可用，请稍后重新检查。':error.message,canDownload:!!this.candidate});throw error;}
  finally{this.operation=null;}
 }
 async check(){return this.perform(async signal=>{
  this.candidate=null;this.change({state:'checking',latestVersion:null,notes:'',progress:0,canDownload:false,message:'正在检查兼容固件…'});
  const candidate=verifyFirmwareManifest(await this.options.transport.get(FIRMWARE_FEED,{maxBytes:65536,signal}),this.options.publicKey);
  signal.throwIfAborted();const local=await this.local();signal.throwIfAborted();
  const shared={latestVersion:candidate.version,notes:candidate.notes};
  if(local.version&&newer(local.version,candidate.version))return this.change({...shared,state:'local-newer',message:'本机已准备较新固件，保留当前版本。'});
  if(local.valid&&local.version===candidate.version&&local.sha256===candidate.sha256)return this.change({...shared,state:'ready',progress:1,message:'最新固件已准备好，请在设备上检查并确认安装。'});
  this.candidate=candidate;return this.change({...shared,state:'available',canDownload:true,message:'兼容固件可下载，下载后由设备确认安装。'});
 });}
 async download(){
  if(this.operation)throw new Error('固件操作进行中，请稍后再试。');
  if(!this.candidate||!this.value.canDownload)throw new Error('请先检查可下载的兼容固件。');
  return this.perform(async signal=>{
   const candidate=this.candidate;let temporary;
   this.change({state:'downloading',progress:0,canDownload:false,message:'正在下载固件…'});
   try{
    await safeDirectory(this.options.temporaryDir);signal.throwIfAborted();temporary=await fs.mkdtemp(path.join(this.options.temporaryDir,'firmware-'));
    const file=path.join(temporary,candidate.sha256+'.bin');
    await this.options.transport.download(candidate.url,file,{maxBytes:candidate.size,signal,onProgress:received=>this.change({progress:Math.min(1,received/candidate.size)})});
    signal.throwIfAborted();await verifyFile(file,candidate);
    const local=await this.local();if(local.version&&newer(local.version,candidate.version))throw new Error('本机已准备较新固件，不能降级。');
    const {type,...manifest}=candidate;manifest.url='/updates/firmware/'+candidate.sha256+'.bin';
    const manifestFile=path.join(temporary,'manifest.json');await fs.writeFile(manifestFile,JSON.stringify(manifest),{mode:0o600,flag:'wx'});
    signal.throwIfAborted();this.change({state:'activating',message:'正在校验并准备设备更新…'});
    // The existing importer validates the ESP image and atomically switches its cache.
    await this.options.activate(manifestFile);
    this.candidate=null;return this.change({state:'ready',canDownload:false,progress:1,message:'固件已准备好，请在设备上检查并确认安装。'});
   }finally{if(temporary)await fs.rm(temporary,{recursive:true,force:true});}
  });
 }
 cancel(){this.operation?.abort();}
}
module.exports={FirmwareUpdater,verifyFirmwareManifest,validateFirmware,FIRMWARE_FEED,MAX_FIRMWARE};
