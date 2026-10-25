'use strict';
// Rasterize the existing vector identity; no separate Mac branding.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
app.whenReady().then(async()=>{
 const assets=path.resolve(__dirname,'../assets'),icons=path.resolve(__dirname,'../build/EvoMyn.iconset');fs.mkdirSync(icons,{recursive:true});
 const win=new BrowserWindow({width:1024,height:1024,show:false,transparent:true,webPreferences:{sandbox:true}});
 async function render(svg,size){
  win.setContentSize(size,size);
  await win.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent('<style>html,body{margin:0;background:transparent}svg{width:100vw;height:100vh;display:block}</style>'+svg));
  return (await win.webContents.capturePage()).resize({width:size,height:size}).toPNG();
 }
 const svg=fs.readFileSync(path.join(assets,'icon.svg'),'utf8');
 for(const size of [16,32,128,256,512])for(const scale of [1,2])fs.writeFileSync(path.join(icons,`icon_${size}x${size}${scale===2?'@2x':''}.png`),await render(svg,size*scale));
 execFileSync('/usr/bin/iconutil',['-c','icns',icons,'-o',path.join(assets,'icon.icns')]);
 const template=svg.replace(/<rect[^>]*\/>/,'').replaceAll('#f4f3ef','#000000').replaceAll('#9eaf9a','#000000').replace('viewBox="0 0 256 256"','viewBox="40 50 176 160"');
 for(const scale of [1,2])fs.writeFileSync(path.join(assets,`trayTemplate${scale===2?'@2x':''}.png`),await render(template,18*scale));
 win.destroy();app.quit();
}).catch(error=>{console.error(error);app.exit(1);});
