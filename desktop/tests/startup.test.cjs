'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {migrateLoginItem}=require('../startup.cjs');

function fixture(entries){
 const calls=[];
 return {calls,app:{isPackaged:true,getLoginItemSettings:()=>({launchItems:entries}),setLoginItemSettings:value=>calls.push(value)}};
}
const executable='C:\\Apps\\EvoMyn\\EvoMyn.exe';
const legacy={name:'old-app-id',path:'c:\\apps\\evomyn\\PersonalMemory.exe',args:['--background'],scope:'user',enabled:true};
test('renamed executable replaces only its own legacy startup entry',()=>{
 const f=fixture([legacy,{...legacy,name:'other-copy',path:'C:\\Other\\PersonalMemory.exe'},{...legacy,name:'machine',scope:'machine'}]);
 migrateLoginItem(f.app,{executable,enabled:true,platform:'win32'});
 assert.deepEqual(f.calls,[{openAtLogin:true,name:'EvoMyn',path:executable,args:['--background'],enabled:true},{openAtLogin:false,name:'old-app-id'}]);
});
test('Windows-disabled startup stays disabled and opted-out startup is removed',()=>{
 const disabled=fixture([{...legacy,enabled:false}]);
 migrateLoginItem(disabled.app,{executable,enabled:true,platform:'win32'});
 assert.equal(disabled.calls[0].enabled,false);
 const optedOut=fixture([legacy]);
 migrateLoginItem(optedOut.app,{executable,enabled:false,platform:'win32'});
 assert.deepEqual(optedOut.calls,[{openAtLogin:false,name:'old-app-id'}]);
});
test('fresh installs, development and isolated acceptance do not change login items',()=>{
 for(const options of [{isolated:true},{platform:'linux'},{}]){
  const f=fixture(options.isolated||options.platform?[legacy]:[]);
  migrateLoginItem(f.app,{executable,enabled:true,platform:'win32',...options});assert.deepEqual(f.calls,[]);
 }
 const f=fixture([legacy]);f.app.isPackaged=false;
 migrateLoginItem(f.app,{executable,enabled:true,platform:'win32'});assert.deepEqual(f.calls,[]);
});
