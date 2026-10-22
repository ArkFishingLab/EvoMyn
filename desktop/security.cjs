'use strict';
const {pathToFileURL}=require('node:url');
const ROUTES=['/memory/','/setup/'];
function trustedShell(event,contents,shellFile){
 return !!contents&&!contents.isDestroyed()&&event.sender===contents&&event.senderFrame===contents.mainFrame&&event.senderFrame.url===pathToFileURL(shellFile).href;
}
function dashboardOrigin(value){
 const url=new URL(value);
 if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||!url.port||url.username||url.password)throw new Error('看板地址无效。');
 return url.origin;
}
function allowedDashboard(value,origin){
 try{const url=new URL(value);return url.origin===origin&&!url.username&&!url.password&&ROUTES.some(route=>url.pathname.startsWith(route));}catch{return false;}
}
function allowedDownload(value,origin){
 try{
  if(value.startsWith('blob:'))return new URL(value.slice(5)).origin===origin;
  const url=new URL(value);return url.origin===origin&&!url.username&&!url.password&&
   (/^\/setup\/clients\/(?:codex\.toml|claude\.json)$/.test(url.pathname)||url.pathname==='/memory/backup/restore-tool.py'||/^\/memory\/backup\/api\/download\/[A-Za-z0-9_-]+$/.test(url.pathname)||/^\/memory\/api\/files\/[A-Za-z0-9_-]+$/.test(url.pathname));
 }catch{return false;}
}
function allowedSource(value){
 try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password&&!url.port&&['registry.modelcontextprotocol.io','github.com'].includes(url.hostname);}catch{return false;}
}
function validateCommand(action,parameters){
 if(typeof action!=='string'||!parameters||typeof parameters!=='object'||Array.isArray(parameters))throw new Error('操作格式无效。');
 const keys=Object.keys(parameters).sort().join(',');
 if(['status','start-mcp','stop-mcp','show-data','update-status','update-check','update-download','update-install','update-import','preferences','quit','use-local','open-xiaozhi-console'].includes(action)&&keys==='')return;
 if(action==='connect-xiaozhi'&&keys==='endpoint'&&typeof parameters.endpoint==='string'&&parameters.endpoint.length<=4096)return;
 if(action==='import-device-sync'&&keys==='')return;
 if(['set-cloud','set-device-sync'].includes(action)&&keys==='enabled'&&typeof parameters.enabled==='boolean')return;
 if(action==='save-endpoint'&&keys==='endpoint'&&typeof parameters.endpoint==='string'&&parameters.endpoint.length<=8192)return;
 if(action==='export-config'&&keys==='format'&&['json','toml'].includes(parameters.format))return;
 if(action==='set-startup'&&keys==='enabled'&&typeof parameters.enabled==='boolean')return;
 if(action==='set-update-feed'&&keys==='url'&&typeof parameters.url==='string'&&parameters.url.length<=4096)return;
 if(action==='view'&&keys==='page'&&['memory','mcp','setup','settings'].includes(parameters.page))return;
 throw new Error('不支持此操作。');
}
module.exports={trustedShell,dashboardOrigin,allowedDashboard,allowedDownload,allowedSource,validateCommand};
