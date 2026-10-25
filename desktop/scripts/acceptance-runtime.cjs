'use strict';
const path=require('node:path'),{spawn}=require('node:child_process');
const {pythonPath}=require('../platform.cjs');
const desktop=path.resolve(__dirname,'..');
const packaged=process.env.EVOMYN_ACCEPTANCE_APP;
const executable=packaged?path.resolve(packaged):require('electron');
const base=packaged?(process.platform==='darwin'?path.resolve(path.dirname(executable),'../Resources/backend'):path.join(path.dirname(executable),'resources/backend')):path.join(desktop,'build/runtime');
async function stopChild(child){
 if(child.exitCode!==null||!child.pid)return;
 if(process.platform==='win32')await new Promise(resolve=>{const killer=spawn('taskkill.exe',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});killer.once('error',resolve);killer.once('exit',resolve);});
 else{child.kill('SIGTERM');await new Promise(resolve=>{const timer=setTimeout(()=>{child.kill('SIGKILL');resolve();},5000);child.once('exit',()=>{clearTimeout(timer);resolve();});});}
}
module.exports={executable,args:packaged?[]:[desktop],python:pythonPath(base),scripts:packaged?path.join(base,'scripts'):path.join(desktop,'backend'),stopChild};
