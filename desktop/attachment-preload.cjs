'use strict';
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('evomynAttachments',Object.freeze({
 open:(recordId,attachmentId)=>ipcRenderer.invoke('evomyn:open-attachment',{recordId,attachmentId})
}));
