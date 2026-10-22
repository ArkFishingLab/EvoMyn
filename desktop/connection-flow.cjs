'use strict';
function endpointValue(value){
 if(typeof value!=='string')throw new Error('请粘贴完整的小智 MCP 接入点。');
 value=value.trim();let url;try{url=new URL(value);}catch{throw new Error('请粘贴从小智控制台复制的完整 wss:// 接入点。');}
 if(value.length>4096||/\s/.test(value)||url.protocol!=='wss:'||!url.hostname||url.username||url.password||url.hash)throw new Error('接入点应为完整的 wss:// 地址，请重新从小智控制台复制。');
 return value;
}
class ConnectionFlow{
 constructor({request,needsSetup}){Object.assign(this,{request,needsSetup});}
 async start(){
  let status=await this.request('status');
  if(!status.mcp_enabled)status=await this.request('start-mcp');
  return status;
 }
 async startup(){return this.request('status');}
 async useLocal(){
  let status=await this.request('set-cloud',{enabled:false});
  if(!status.mcp_enabled)status=await this.request('start-mcp');return status;
 }
 async startCloud(){
  let status=await this.request('status');
  if(!status.cloud_configured){if(status.cloud_enabled)status=await this.request('set-cloud',{enabled:false});await this.needsSetup();return status;}
  if(!status.mcp_enabled)status=await this.request('start-mcp');
  if(!status.cloud_enabled)status=await this.request('set-cloud',{enabled:true});
  return status;
 }
 async connect(value){
  if(typeof value!=='string')throw new Error('请粘贴完整的小智 MCP 接入点。');
  if(value.trim())await this.request('save-endpoint',{endpoint:endpointValue(value)});
  else{
   const status=await this.request('status');
   if(!status.cloud_configured)throw new Error('请先从小智控制台复制 MCP 接入点并粘贴到这里。');
   if(status.cloud_enabled)await this.request('set-cloud',{enabled:false});
  }
  return this.startCloud();
 }
}
module.exports={ConnectionFlow,endpointValue};
