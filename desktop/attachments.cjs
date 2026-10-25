'use strict';
const path=require('node:path');
const {allowedDashboard}=require('./security.cjs');
function validateAttachmentRequest(value){
 if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).sort().join(',')!=='attachmentId,recordId'||
  typeof value.recordId!=='string'||!value.recordId.length||value.recordId.length>120||/[\\/\x00-\x1f]/.test(value.recordId)||
  typeof value.attachmentId!=='string'||!(/^[a-f0-9]{32}$/.test(value.attachmentId)||value.attachmentId==='legacy'))throw new Error('附件请求无效。');
}
function trustedAttachmentSender(event,contents,origin){
 return !!contents&&!contents.isDestroyed()&&event.sender===contents&&event.senderFrame===contents.mainFrame&&
  allowedDashboard(event.senderFrame.url,origin)&&new URL(event.senderFrame.url).pathname.startsWith('/memory/');
}
async function openManagedAttachment(value,service,shell){
 validateAttachmentRequest(value);
 const result=await service.request('attachment-path',value);
 if(!result||typeof result.path!=='string'||typeof result.resources!=='string'||!path.isAbsolute(result.path)||!path.isAbsolute(result.resources))throw new Error('附件不可用。');
 const relative=path.relative(result.resources,result.path);
 if(!relative||relative==='..'||relative.startsWith('..'+path.sep)||path.isAbsolute(relative))throw new Error('附件不可用。');
 if(!/\.(?:pdf|txt|md|markdown|csv|tsv|json|yaml|yml|xml|log|rtf|doc|docx|odt|xls|xlsx|ods|ppt|pptx|odp|png|jpe?g|gif|webp|bmp|tiff?|heic|mp3|wav|flac|m4a|ogg|mp4|mkv|mov|avi|webm|zip|7z|rar|tar|gz)$/i.test(result.path))throw new Error('此文件类型不能直接打开，可下载后手动处理。');
 const error=await shell.openPath(result.path);if(error)throw new Error('无法打开附件，请确认已安装支持此格式的应用。');
 return true;
}
module.exports={validateAttachmentRequest,trustedAttachmentSender,openManagedAttachment};
