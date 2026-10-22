'use strict';
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('personalMemory',Object.freeze({
 command:(action,parameters={})=>ipcRenderer.invoke('personal-memory:command',action,parameters),
 onStatus:callback=>{if(typeof callback!=='function')return()=>{};const listener=(_event,value)=>callback(value);ipcRenderer.on('personal-memory:status',listener);return()=>ipcRenderer.removeListener('personal-memory:status',listener);}
}));
