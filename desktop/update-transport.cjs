'use strict';
const fs=require('node:fs');
const {Readable}=require('node:stream');
const {pipeline}=require('node:stream/promises');
const {httpsUrl}=require('./updater.cjs');

// Electron's request uses the Windows/system proxy, including PAC configuration.
// Keep redirect validation and streaming bounds independent of that network stack.
function createElectronFetch(request){
 return (url,options)=>new Promise((resolve,reject)=>{
  options.signal?.throwIfAborted();
  const pending=request({url,redirect:'manual',credentials:'omit',cache:'no-store',headers:options.headers});
  const abort=()=>{reject(options.signal.reason);pending.abort();};
  options.signal?.addEventListener('abort',abort,{once:true});
  pending.on('close',()=>options.signal?.removeEventListener('abort',abort));
  pending.on('error',reject);
  pending.on('redirect',(status,_method,location)=>{resolve(new Response(null,{status,headers:{location}}));pending.abort();});
  pending.on('response',incoming=>{try{resolve({status:incoming.statusCode,body:Readable.toWeb(incoming)});}catch(error){reject(error);pending.abort();}});
  pending.end();
 });
}
function createUpdateTransport(fetch,{timeoutMs=30000}={}){
 async function response(url,signal,consume){
  signal?.throwIfAborted();
  const controller=new AbortController();let timer,timedOut=false;
  const abort=()=>controller.abort(signal.reason);
  const touch=()=>{clearTimeout(timer);timer=setTimeout(()=>{timedOut=true;controller.abort();},timeoutMs);};
  signal?.addEventListener('abort',abort,{once:true});
  try{
   touch();
   for(let redirects=0;;redirects++){
    const incoming=await fetch(httpsUrl(url),{redirect:'manual',credentials:'omit',cache:'no-store',signal:controller.signal,headers:{'User-Agent':'EvoMyn-Updater','Accept':'application/json, application/octet-stream'}});
    touch();
    if([301,302,303,307,308].includes(incoming.status)){
     const location=incoming.headers.get('location');await incoming.body?.cancel();
     if(redirects>=3||!location)throw new Error('更新服务器重定向无效。');
     url=httpsUrl(new URL(location,url).href);continue;
    }
    if(incoming.status!==200){await incoming.body?.cancel();throw new Error('更新服务器返回 '+incoming.status+'，请稍后重试。');}
    return await consume(incoming,touch,controller.signal);
   }
  }catch(error){if(timedOut)throw new Error('更新连接超时。');throw error;}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.abort();}
 }
 return {
  get(url,{maxBytes=65536,signal}={}){return response(url,signal,async(incoming,touch)=>{
   const chunks=[];let size=0;
   for await(const chunk of incoming.body){touch();size+=chunk.length;if(size>maxBytes)throw new Error('更新说明超过限制。');chunks.push(Buffer.from(chunk));}
   return Buffer.concat(chunks);
  });},
  download(url,target,{maxBytes,onProgress,signal}){return response(url,signal,async(incoming,touch,activeSignal)=>{
   async function* bounded(){let size=0;for await(const chunk of incoming.body){touch();size+=chunk.length;if(size>maxBytes)throw new Error('更新文件超过声明大小。');onProgress(size);yield Buffer.from(chunk);}}
   await pipeline(Readable.from(bounded()),fs.createWriteStream(target,{flags:'wx',mode:0o600}),{signal:activeSignal});
  });}
 };
}
module.exports={createUpdateTransport,createElectronFetch};
