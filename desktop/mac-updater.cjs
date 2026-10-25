'use strict';
// Hand only the already Ed25519/SHA-256 verified ZIP to Squirrel.Mac. Its
// native signature check and application replacement are deliberately retained.
const http=require('node:http');
const fs=require('node:fs');
const fsp=require('node:fs/promises');
const crypto=require('node:crypto');

class MacUpdateInstaller{
 constructor(autoUpdater,{timeout=120000}={}){this.updater=autoUpdater;this.timeout=timeout;this.pending=null;this.ready=false;this.restartRequired=false;}
 async prepare(file){
  if(this.restartRequired)throw new Error('请重新启动应用后再尝试 macOS 更新。');
  if(this.pending)throw new Error('macOS 更新安装正在进行。');
  const info=await fsp.lstat(file);
  if(!info.isFile()||info.isSymbolicLink())throw new Error('macOS 更新包无效。');
  this.ready=false;
  const token=crypto.randomBytes(32).toString('hex');
  const server=http.createServer((request,response)=>{
   if(request.method!=='GET'){response.writeHead(405);response.end();return;}
   if(request.url===`/${token}/feed`){
    response.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});
    response.end(JSON.stringify({url:`http://127.0.0.1:${server.address().port}/${token}/update.zip`}));
   }else if(request.url===`/${token}/update.zip`){
    response.writeHead(200,{'Content-Type':'application/zip','Content-Length':info.size,'Cache-Control':'no-store'});
    const stream=fs.createReadStream(file);stream.on('error',()=>response.destroy());response.on('close',()=>stream.destroy());stream.pipe(response);
   }else{response.writeHead(404);response.end();}
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  try{
   await new Promise((resolve,reject)=>{
    let settled=false;
    const finish=(error,abandoned=false)=>{
     if(settled)return;settled=true;
     // Squirrel cannot cancel a check or correlate its events with a request.
     // After abandoning one, contain late errors for the remaining app lifetime
     // and forbid retries so an old completion cannot authorize another ZIP.
     if(abandoned){this.restartRequired=true;this.updater.on('error',()=>{});}
     clearTimeout(timer);this.updater.removeListener('error',failed);this.updater.removeListener('update-downloaded',downloaded);this.updater.removeListener('update-not-available',unavailable);this.pending=null;
     if(error)reject(error);else{this.ready=true;resolve();}
    };
    const failed=()=>finish(new Error('macOS 更新安装失败。请确认应用及更新包使用有效的 Apple 发布签名。'));
    const downloaded=()=>finish();
    const unavailable=()=>finish(new Error('macOS 更新包未被系统接受。'));
    const timer=setTimeout(()=>finish(new Error('macOS 更新准备超时，请重新启动应用后重试。'),true),this.timeout);
    this.pending=()=>finish(new Error('macOS 更新已取消，请重新启动应用后重试。'),true);
    this.updater.once('error',failed);this.updater.once('update-downloaded',downloaded);this.updater.once('update-not-available',unavailable);
    try{this.updater.setFeedURL({url:`http://127.0.0.1:${server.address().port}/${token}/feed`});this.updater.checkForUpdates();}catch{failed();}
   });
  }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
 }
 quitAndInstall(){if(!this.ready)throw new Error('macOS 更新尚未就绪。');this.updater.quitAndInstall();}
 cancel(){this.pending?.();}
}
module.exports={MacUpdateInstaller};
