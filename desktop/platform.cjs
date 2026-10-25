'use strict';
const path=require('node:path');

function dataHome(appData,platform=process.platform,override){
 if(override)return path.resolve(override);
 return platform==='win32'?path.win32.join(appData,'..','Local','PersonalMemory'):path.posix.join(appData,'EvoMyn');
}
function pythonPath(base,platform=process.platform){
 return path.join(base,'python',...(platform==='win32'?['python.exe']:['bin','python3.11']));
}
function toolsPath(python,platform=process.platform){
 return path.resolve(path.dirname(python),...(platform==='win32'?['..','tools']:['..','..','tools']));
}
function loginSettings(enabled,executable,platform=process.platform){
 return platform==='darwin'?{openAtLogin:enabled,openAsHidden:true}:{openAtLogin:enabled,name:'EvoMyn',path:executable,args:['--background']};
}
function applicationMenu(t,reveal){
 return [
  {label:'EvoMyn',submenu:[{role:'about'},{type:'separator'},{label:t('打开EvoMyn'),click:reveal},{type:'separator'},{role:'services'},{type:'separator'},{role:'hide'},{role:'hideOthers'},{role:'unhide'},{type:'separator'},{role:'quit'}]},
  {role:'editMenu'},{role:'windowMenu'}
 ];
}
module.exports={dataHome,pythonPath,toolsPath,loginSettings,applicationMenu};
