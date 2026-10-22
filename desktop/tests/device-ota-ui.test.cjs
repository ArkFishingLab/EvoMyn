'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {createRequire}=require('node:module');
const root=path.resolve(__dirname,'..'),mainFile=path.join(root,'main.cjs');
function nativeFixture(selection){
 const calls=[],dialogs=[],initial={ready:true,mcp_enabled:false,cloud_enabled:false,device_ota:{state:'error',running:false,version:'2.5.7'}};
 const electron={app:{getPath:()=>root,getVersion:()=>'0.2.13',setPath(){},setName(){},setAppUserModelId(){},requestSingleInstanceLock:()=>false,quit(){}},dialog:{showOpenDialog:async(_window,options)=>{dialogs.push(options);return selection;}}};
 const localRequire=createRequire(mainFile),context=vm.createContext({require:name=>name==='electron'?electron:localRequire(name),__dirname:root,process,Buffer,URL,setImmediate,setInterval,clearInterval,setTimeout,clearTimeout,initial,request:async(action,params)=>{calls.push({action,params});return {...initial,device_ota:{state:'ready',running:true,version:'2.5.7'}};}});
 vm.runInContext(fs.readFileSync(mainFile,'utf8'),context,{filename:mainFile});
 vm.runInContext('serviceStatus=initial;service={request};',context);
 return {calls,dialogs,setUpdater(value){context.testUpdater=value;vm.runInContext('updater=testUpdater;service.child={};',context);},setFirmware(value){context.testFirmware=value;vm.runInContext('firmware=testFirmware;',context);},perform:(action,params={})=>context.perform(action,params)};
}
test('OTA imports pass only native-selected absolute paths to the service',async()=>{
 for(const [action,key,selected,kind] of [['ota-import-pairing','directory',path.join(root,'fixture-runtime'),'openDirectory'],['ota-import-release','manifest',path.join(root,'fixture-release','manifest.json'),'openFile']]){
  const f=nativeFixture({canceled:false,filePaths:[selected]});const result=await f.perform(action);
  assert.equal(f.dialogs.length,1);assert.ok(f.dialogs[0].properties.includes(kind));
  assert.equal(f.calls.length,1);assert.equal(f.calls[0].action,action);assert.equal(f.calls[0].params[key],selected);
  assert.deepEqual(Object.keys(f.calls[0].params),[key]);assert.equal(result.service.device_ota.state,'ready');assert.equal(result.service.mcp_enabled,false);
 }
});
test('canceling either OTA import leaves the service untouched',async()=>{
 for(const action of ['ota-import-pairing','ota-import-release']){
  const f=nativeFixture({canceled:true,filePaths:[]});const result=await f.perform(action);
  assert.equal(f.calls.length,0);assert.equal(result.service.device_ota.state,'error');assert.equal(result.busy,false);
 }
});
test('OTA retry requests only OTA restart while MCP is disabled',async()=>{
 const f=nativeFixture();const result=await f.perform('ota-retry');
 assert.equal(f.dialogs.length,0);assert.deepEqual(f.calls.map(call=>call.action),['ota-retry']);assert.equal(result.service.mcp_enabled,false);
});
test('renderer cannot bypass native OTA selection with a supplied path',async()=>{
 const f=nativeFixture();await assert.rejects(f.perform('ota-import-pairing',{directory:root}));assert.equal(f.calls.length,0);assert.equal(f.dialogs.length,0);
});
function rendererFixture(){
 const html=fs.readFileSync(path.join(root,'ui','index.html'),'utf8'),elements=new Map();
 for(const [,id] of html.matchAll(/\bid="([^"]+)"/g))elements.set(id,{hidden:false,disabled:false,textContent:'',value:'',handlers:{},addEventListener(name,handler){this.handlers[name]=handler;},scrollTo(){}});
 const calls=[],api={command:async(action,params)=>{calls.push({action,params});return null;},onStatus(){}};
 const context=vm.createContext({window:{personalMemory:api},document:{getElementById:id=>elements.get(id),querySelectorAll:()=>[],activeElement:null},setTimeout:()=>0,clearTimeout(){}});
 vm.runInContext(fs.readFileSync(path.join(root,'ui','app.js'),'utf8'),context);
 const render=(ota,overrides={})=>context.render({version:'0.2.13',page:'settings',service:{ready:true,mcp_enabled:false,device_ota:ota},...overrides});
 return {html,elements,calls,render};
}
test('OTA settings explain automatic availability and manual installation without a toggle',()=>{
 const f=rendererFixture();assert.match(f.html,/ESP 设备更新/);assert.match(f.html,/同一局域网/);assert.match(f.html,/设备上确认安装/);
 assert.match(f.html,/<details[^>]*id="ota-details"/);assert.doesNotMatch(f.html,/<input[^>]*id="(?:ota|device-sync)[^"]*"/);
});
test('OTA settings show firmware version separately and offer retry for failures only',()=>{
 const f=rendererFixture();
 for(const [state,title,retry] of [['unconfigured','等待配对',false],['no-firmware','等待固件',false],['invalid-config','配对配置无效',true],['invalid-firmware','固件校验未通过',true],['starting','正在启动',false],['ready','可供设备更新',false],['error','更新服务未启动',true]]){
  f.render({state,version:'2.5.7',message:'测试状态说明',running:state==='ready'});
  assert.equal(f.elements.get('ota-state')?.textContent,title);assert.equal(f.elements.get('ota-version')?.textContent,'本机已准备 v2.5.7');
  assert.equal(f.elements.get('ota-message')?.textContent,'测试状态说明');assert.equal(f.elements.get('ota-retry')?.hidden,!retry);
  assert.equal(f.elements.get('ota-import-pairing')?.disabled,state==='starting');
 }
 f.render(null);assert.equal(f.elements.get('ota-version')?.textContent,'本机尚未准备固件');
 f.render({state:'error'},{busy:true});assert.equal(f.elements.get('ota-retry')?.disabled,true);
 f.render(null,{service:null});assert.equal(f.elements.get('ota-import-release')?.disabled,true);
});
test('OTA buttons issue argument-free renderer commands',async()=>{
 const f=rendererFixture();
 for(const action of ['ota-retry','ota-import-pairing','ota-import-release']){
  assert.equal(typeof f.elements.get(action)?.handlers.click,'function');await f.elements.get(action).handlers.click();
  const call=f.calls.at(-1);assert.equal(call.action,action);assert.deepEqual(Object.keys(call.params),[]);
 }
});
test('online firmware shows remote and prepared versions separately, progress and retry',()=>{
 const f=rendererFixture();f.render({state:'ready',version:'2.5.7'},{firmware:{state:'available',latestVersion:'2.5.8',canDownload:true,message:'可下载',notes:'修复提醒'}});
 assert.equal(f.elements.get('ota-latest')?.textContent,'最新可下载 v2.5.8');assert.equal(f.elements.get('ota-version')?.textContent,'本机已准备 v2.5.7');assert.equal(f.elements.get('firmware-download')?.hidden,false);
 f.render(null,{firmware:{state:'downloading',latestVersion:'2.5.8',progress:0.5}});assert.equal(f.elements.get('firmware-progress')?.value,0.5);assert.equal(f.elements.get('firmware-check')?.disabled,true);
 f.render(null,{firmware:{state:'error',latestVersion:'2.5.8',canDownload:true,message:'连接中断'}});assert.equal(f.elements.get('firmware-download')?.hidden,false);assert.equal(f.elements.get('firmware-download')?.textContent,'重试下载');assert.equal(f.elements.get('firmware-message')?.textContent,'连接中断');
});
test('online firmware buttons use fixed argument-free actions',async()=>{const f=rendererFixture();for(const action of ['firmware-check','firmware-download']){assert.equal(typeof f.elements.get(action)?.handlers.click,'function');await f.elements.get(action).handlers.click();assert.equal(f.calls.at(-1).action,action);assert.deepEqual(Object.keys(f.calls.at(-1).params),[]);}const {validateCommand}=require('../security.cjs');for(const action of ['firmware-check','firmware-download']){assert.doesNotThrow(()=>validateCommand(action,{}));assert.throws(()=>validateCommand(action,{url:'https://evil.test'}));}});

test('native online check and download call the controller without renderer parameters',async()=>{
 const f=nativeFixture();let checked=0,downloaded=0;f.setFirmware({status:()=>({latestVersion:'2.5.8'}),check:async()=>{checked++;return {state:'available'};},download:async()=>{downloaded++;}});
 assert.equal((await f.perform('firmware-check')).state,'available');const result=await f.perform('firmware-download');assert.equal(checked,1);assert.equal(downloaded,1);assert.equal(result.firmware.latestVersion,'2.5.8');assert.equal(result.busy,false);assert.equal(f.calls.length,0);assert.equal(f.dialogs.length,0);
 await assert.rejects(f.perform('firmware-download',{manifest:'anything'}));assert.equal(downloaded,1);
});

function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
test('native install holds the service guard through handoff and rejects new firmware work',async()=>{
 const f=nativeFixture(),pending=deferred();let firmwareCalls=0;
 f.setUpdater({status:()=>({state:'installing'}),install:()=>pending.promise});
 f.setFirmware({status:()=>({}),check:async()=>{firmwareCalls++;},download:async()=>{firmwareCalls++;}});
 const installing=f.perform('update-install');
 try{
  await assert.rejects(f.perform('firmware-check'));await assert.rejects(f.perform('firmware-download'));
  assert.equal(firmwareCalls,0);assert.equal((await f.perform('status')).busy,true);
 }finally{pending.resolve();await installing;}
 await assert.rejects(f.perform('firmware-download'));assert.equal((await f.perform('status')).busy,true);
});
test('native firmware work blocks installer in either firmware operation',async()=>{
 for(const action of ['firmware-check','firmware-download']){
  const f=nativeFixture(),pending=deferred();let installs=0;
  f.setUpdater({status:()=>({}),install:async()=>{installs++;}});
  const firmware={operation:null,status:()=>({})};firmware.check=firmware.download=async()=>{firmware.operation={};try{await pending.promise;}finally{firmware.operation=null;}};f.setFirmware(firmware);
  const working=f.perform(action);try{await assert.rejects(f.perform('update-install'));assert.equal(installs,0);}finally{pending.resolve();await working;}
 }
});
test('failed installer releases service guard for firmware retry',async()=>{
 const f=nativeFixture();f.setUpdater({status:()=>({state:'error'}),install:async()=>{throw Error('installer failed');}});let calls=0;f.setFirmware({status:()=>({}),download:async()=>{calls++;}});
 await assert.rejects(f.perform('update-install'),/installer failed/);assert.equal((await f.perform('status')).busy,false);await f.perform('firmware-download');assert.equal(calls,1);
});
test('firmware controls are disabled throughout application installation',()=>{
 const f=rendererFixture();f.render(null,{busy:false,update:{state:'installing'},firmware:{state:'available',canDownload:true}});
 assert.equal(f.elements.get('firmware-check').disabled,true);assert.equal(f.elements.get('firmware-download').disabled,true);
});
