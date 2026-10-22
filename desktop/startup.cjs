'use strict';
const path=require('node:path');

function migrateLoginItem(app,{executable,enabled,platform=process.platform,isolated=false}){
 if(platform!=='win32'||!app.isPackaged||isolated)return;
 const legacyPath=path.win32.join(path.win32.dirname(executable),'PersonalMemory.exe').toLowerCase();
 const entries=(app.getLoginItemSettings({path:legacyPath}).launchItems||[]).filter(item=>
  item.scope==='user'&&path.win32.normalize(item.path).toLowerCase()===legacyPath);
 if(!entries.length)return;
 if(enabled)app.setLoginItemSettings({openAtLogin:true,name:'EvoMyn',path:executable,args:['--background'],enabled:entries.some(item=>item.enabled)});
 for(const item of entries){
  if(enabled&&item.name==='EvoMyn')continue;
  app.setLoginItemSettings({openAtLogin:false,name:item.name});
 }
}
module.exports={migrateLoginItem};
