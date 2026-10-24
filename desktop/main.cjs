'use strict';
const {app,BrowserWindow,WebContentsView,Tray,Menu,ipcMain,dialog,shell,session,net}=require('electron');
const path=require('node:path');const fs=require('node:fs');const fsp=require('node:fs/promises');const crypto=require('node:crypto');
const {pathToFileURL}=require('node:url');
const {ServiceClient}=require('./service-client.cjs');const {UpdateManager,httpsUrl}=require('./updater.cjs');
const {FirmwareUpdater}=require('./firmware-updater.cjs');
const {DEFAULT_UPDATE_FEED,resolveUpdateFeed}=require('./update-source.cjs');
const {createUpdateTransport,createElectronFetch}=require('./update-transport.cjs');
const {ConnectionFlow}=require('./connection-flow.cjs');
const {contentBounds,contentSpacing}=require('./layout.cjs');
const {migrateLoginItem}=require('./startup.cjs');
const {trustedShell,dashboardOrigin,allowedDashboard,allowedDownload,allowedSource,validateCommand}=require('./security.cjs');
const home=process.env.PERSONAL_MEMORY_HOME?path.resolve(process.env.PERSONAL_MEMORY_HOME):path.join(app.getPath('appData'),'..','Local','PersonalMemory');
// Keep the legacy data location so renaming does not create an empty profile.
app.setPath('userData',home);
app.setName('EvoMyn');
if(process.platform==='win32')app.setAppUserModelId('com.personal-memory.desktop');
const shellFile=path.join(__dirname,'ui','index.html');
const dashboardCSS=['tokens.css','dashboard.css'].map(file=>fs.readFileSync(path.join(__dirname,'ui',file),'utf8')).join('\n');
const languageSource=fs.readFileSync(path.join(__dirname,'ui','i18n.js'),'utf8');
const languageCatalog=Object.assign({},...['shell-en.json','viewer-en.json','native-en.json'].map(file=>JSON.parse(fs.readFileSync(path.join(__dirname,'ui',file),'utf8'))));
const nativeLanguage=require('./ui/i18n.js').createTranslator(languageCatalog);
const t=value=>nativeLanguage.t(value);
let window,view,tray,service,updater,firmware,connection,poll,origin='',page='memory',quitting=false,busy=false,cloudStartedAt=null;
let serviceStatus=null,errorMessage='',preferences={updateFeed:DEFAULT_UPDATE_FEED,startAtLogin:false,language:'zh-CN'};
const preferenceFile=path.join(home,'preferences.json');
function snapshot(){return {version:app.getVersion(),service:serviceStatus,update:updater?.status(),firmware:firmware?.status(),preferences:{...preferences},busy,error:errorMessage,page,cloudStartedAt};}
function broadcast(){if(window&&!window.isDestroyed())window.webContents.send('personal-memory:status',snapshot());updateTray();}
async function persist(){await fsp.mkdir(home,{recursive:true});const temporary=preferenceFile+'.tmp';await fsp.writeFile(temporary,JSON.stringify(preferences),{mode:0o600});await fsp.rename(temporary,preferenceFile);}
async function applyLanguage(contents){
 if(!contents||contents.isDestroyed())return;
 const url=contents.getURL();
 if(contents===window?.webContents?url!==pathToFileURL(shellFile).href:!allowedDashboard(url,origin))return;
 await contents.executeJavaScript(languageSource+'\n;window.EvoMynI18n.setCatalog('+JSON.stringify(languageCatalog)+');window.EvoMynI18n.setLanguage('+JSON.stringify(preferences.language)+');');
}
function guard(contents){
 contents.setWindowOpenHandler(({url})=>{if(contents===view?.webContents){if(allowedDownload(url,origin))contents.downloadURL(url);else if(allowedSource(url))shell.openExternal(url).catch(()=>report(new Error('无法打开来源页面，请稍后重试。')));}return {action:'deny'};});
 contents.on('will-attach-webview',event=>event.preventDefault());
 contents.on('will-navigate',(event,url)=>{if(contents===view?.webContents&&allowedDashboard(url,origin)&&new URL(url).pathname==='/setup/'){event.preventDefault();showPage('setup').catch(report);return;}const permitted=contents===window?.webContents?url===pathToFileURL(shellFile).href:allowedDashboard(url,origin);if(!permitted)event.preventDefault();});
 contents.on('will-redirect',(event,url)=>{if(!allowedDashboard(url,origin))event.preventDefault();});
}
function resizeView(){if(!window||!view)return;const [width,height]=window.getContentSize();const bounds=contentBounds(width,height);if(!bounds)return;view.setBounds(bounds);const spacing=contentSpacing(width);view.webContents.executeJavaScript(`document.documentElement?.style.setProperty('--desktop-page-x','${spacing.x}px');document.documentElement?.style.setProperty('--desktop-page-top','${spacing.top}px')`).catch(()=>{});}
function updateTray(){
 if(!tray)return;
 tray.setToolTip(`EvoMyn · MCP ${serviceStatus?.mcp_enabled?t('运行中'):t('已关闭')}`);
 tray.setContextMenu(Menu.buildFromTemplate([
  {label:t('打开EvoMyn'),click:reveal},
  {label:t('MCP 服务'),type:'checkbox',checked:!!serviceStatus?.mcp_enabled,enabled:!!serviceStatus?.ready&&!busy,click:item=>perform(item.checked?'start-mcp':'stop-mcp').catch(report)},
  {label:t('小智云端'),type:'checkbox',checked:!!serviceStatus?.cloud_enabled&&!!serviceStatus?.cloud_configured,enabled:!!serviceStatus?.ready&&!busy,click:item=>perform('set-cloud',{enabled:item.checked}).catch(report)},
  {type:'separator'},{label:t('退出'),click:()=>quit()}
 ]));
}
function reveal(){if(!window)return;if(window.isMinimized())window.restore();window.show();window.focus();}
function report(error){errorMessage=error?.message||'操作失败，请重试。';if(!serviceStatus?.ready)view?.setVisible(false);broadcast();}
async function startService(){
 const base=app.isPackaged?path.join(process.resourcesPath,'backend'):path.join(__dirname,'build','runtime');
 service=new ServiceClient({python:path.join(base,'python','python.exe'),script:path.join(app.isPackaged?path.join(base,'scripts'):path.join(__dirname,'backend'),'service.py'),appDir:path.join(base,'application'),dataRoot:path.join(home,'service')});
 service.on('unavailable',()=>{serviceStatus=null;report(new Error('后台服务已退出，请重新打开应用。'));});
 serviceStatus=await service.start();origin=dashboardOrigin(serviceStatus.dashboard_url);
 serviceStatus=await connection.startup();
 if(serviceStatus.cloud_enabled)cloudStartedAt=Date.now();
 if(page!=='settings')await showPage(page);broadcast();beginPolling();
}
function beginPolling(){clearInterval(poll);poll=setInterval(async()=>{if(busy||quitting||!service?.child)return;try{serviceStatus=await service.request('status',{},5000);broadcast();}catch{}},3000);}
async function showPage(next){
 page=next;if(!view)return;
 const visible=!['settings','setup'].includes(page)&&!!serviceStatus;
 view.setVisible(visible);
 if(visible){const target=({memory:serviceStatus.dashboard_url,mcp:serviceStatus.capabilities_url,setup:serviceStatus.setup_url})[page];if(!allowedDashboard(target,origin))throw new Error('看板导航地址无效。');if(view.webContents.getURL()!==target)await view.webContents.loadURL(target);resizeView();}
 broadcast();
}
async function perform(action,parameters={}){
 validateCommand(action,parameters);
 if(action==='status')return snapshot();
 if(action==='preferences')return {...preferences};
 if(action==='set-language'){
  const previous=preferences.language;preferences.language=parameters.language;
  try{await persist();}catch(error){preferences.language=previous;throw error;}
  nativeLanguage.setLanguage(preferences.language);
  await Promise.all([applyLanguage(window?.webContents),applyLanguage(view?.webContents)]);
  broadcast();return snapshot();
 }
 if(action==='update-status')return updater.status();
 if(action==='view'){await showPage(parameters.page);return snapshot();}
 if(action==='quit'){setImmediate(quit);return true;}
 if(action==='open-xiaozhi-console'){await shell.openExternal('https://xiaozhi.me/');return true;}
 if(action==='show-data'){await shell.openPath(path.join(home,'service','state','data'));return true;}
 if(action==='firmware-check'){if(busy)throw new Error('服务正在切换，请稍后重试。');errorMessage='';broadcast();return firmware.check();}
 if(action==='update-check')return updater.check();
 if(action==='update-download')return updater.download();
 if(action==='update-install'){
  if(busy||firmware?.operation)throw new Error('固件或服务操作进行中，请稍后再试。');
  busy=true;errorMessage='';broadcast();let handedOff=false;
  try{await updater.install();handedOff=true;setImmediate(()=>{quitting=true;app.quit();});return true;}
  catch(error){if(!service.child){try{await startService();}catch{}}throw error;}
  // Retain the guard after successful handoff until the scheduled quit runs.
  finally{if(!handedOff){busy=false;broadcast();}}
 }
 if(action==='set-update-feed'){const feed=parameters.url.trim()?httpsUrl(parameters.url.trim()):DEFAULT_UPDATE_FEED;updater.setFeed(feed);preferences.updateFeed=feed;await persist();broadcast();return updater.status();}
 if(action==='set-startup'){
  if(!app.isPackaged)throw new Error('安装应用后可设置开机启动。');
  app.setLoginItemSettings({openAtLogin:parameters.enabled,name:'EvoMyn',path:process.execPath,args:['--background']});preferences.startAtLogin=parameters.enabled;await persist();broadcast();return snapshot();
 }
 if(action==='update-import'){
  const manifest=await dialog.showOpenDialog(window,{title:t('选择签名更新说明'),properties:['openFile'],filters:[{name:t('签名更新说明'),extensions:['json']}]});if(manifest.canceled)return updater.status();
  const installer=await dialog.showOpenDialog(window,{title:t('选择对应安装包'),properties:['openFile'],filters:[{name:t('Windows 安装包'),extensions:['exe']}]});if(installer.canceled)return updater.status();
  return updater.importRelease(manifest.filePaths[0],installer.filePaths[0]);
 }
 if(action==='export-config'){
  const value=await service.request('client-config',parameters);const result=await dialog.showSaveDialog(window,{title:t('导出 MCP 接入配置'),defaultPath:`evomyn.${parameters.format}`,filters:[{name:t('MCP 配置'),extensions:[parameters.format]}]});
  if(!result.canceled)await fsp.writeFile(result.filePath,value,{encoding:'utf8',mode:0o600});return !result.canceled;
 }
 if(busy)throw new Error('服务正在切换，请稍后重试。');busy=true;errorMessage='';broadcast();
 try{
  if(action==='firmware-download'){
   if(!serviceStatus?.ready)throw new Error('请等待后台服务启动后再下载固件。');
   await firmware.download();
  }
  else if(action==='ota-import-pairing'||action==='ota-import-release'){
   const pairing=action==='ota-import-pairing';
   const selected=await dialog.showOpenDialog(window,pairing
    ?{title:t('选择原有设备配对运行目录'),properties:['openDirectory']}
    :{title:t('选择可信本地固件的 manifest.json'),properties:['openFile'],filters:[{name:t('固件说明 manifest.json'),extensions:['json']}]});
   if(!selected.canceled)serviceStatus=await service.request(action,pairing?{directory:selected.filePaths[0]}:{manifest:selected.filePaths[0]});
  }
  else if(action==='start-mcp')serviceStatus=await connection.start();
  else if(action==='connect-xiaozhi'){cloudStartedAt=Date.now();serviceStatus=await connection.connect(parameters.endpoint);}
  else if(action==='use-local'){serviceStatus=await connection.useLocal();cloudStartedAt=null;}
  else if(action==='set-cloud'&&parameters.enabled){cloudStartedAt=Date.now();serviceStatus=await connection.startCloud();}
  else serviceStatus=await service.request(action,parameters);
  if(serviceStatus?.cloud_enabled&&!serviceStatus.cloud_connected&&!cloudStartedAt)cloudStartedAt=Date.now();
  if(!serviceStatus?.cloud_enabled||!serviceStatus?.mcp_enabled)cloudStartedAt=null;
 }finally{busy=false;broadcast();}
 return snapshot();
}
async function quit(){
 if(quitting)return;quitting=true;clearInterval(poll);updater?.cancel();firmware?.cancel();
 if(window&&!window.isDestroyed())window.hide();
 try{await service?.stop();}catch(error){report(error);}finally{tray?.destroy();app.quit();}
}
async function create(){
 await fsp.mkdir(home,{recursive:true});
 try{const saved=JSON.parse(await fsp.readFile(preferenceFile,'utf8'));preferences={updateFeed:resolveUpdateFeed(saved?.updateFeed),startAtLogin:saved?.startAtLogin===true,language:saved?.language==='en'?'en':'zh-CN'};}catch{}
 nativeLanguage.setLanguage(preferences.language);
 migrateLoginItem(app,{executable:process.execPath,enabled:preferences.startAtLogin,isolated:!!process.env.PERSONAL_MEMORY_HOME});
 connection=new ConnectionFlow({request:async(command,params)=>{const status=await service.request(command,params);serviceStatus=status;return status;},needsSetup:async()=>{reveal();await showPage('setup');await window.webContents.executeJavaScript("document.getElementById('xiaozhi-details').open=true;document.getElementById('endpoint').focus();document.getElementById('endpoint').scrollIntoView({block:'center'})");}});
 const trust=require('./update-trust.json');
 updater=new UpdateManager({currentVersion:app.getVersion(),publicKey:crypto.createPublicKey({key:Buffer.from(trust.publicKey,'base64'),format:'der',type:'spki'}),cacheDir:path.join(home,'updates'),transport:createUpdateTransport(createElectronFetch(net.request.bind(net))),onBeforeInstall:async()=>{clearInterval(poll);await service.stop();},feedUrl:preferences.updateFeed});
 updater.on('status',broadcast);
 firmware=new FirmwareUpdater({publicKey:crypto.createPublicKey({key:Buffer.from(trust.publicKey,'base64'),format:'der',type:'spki'}),temporaryDir:path.join(home,'firmware-downloads'),localDir:path.join(home,'service','device-updates'),transport:createUpdateTransport(createElectronFetch(net.request.bind(net))),activate:async manifest=>{if(quitting)throw new Error('应用正在退出。');serviceStatus=await service.request('ota-import-release',{manifest});broadcast();}});
 firmware.on('status',broadcast);
 session.defaultSession.setPermissionRequestHandler((_webContents,_permission,callback)=>callback(false));
 session.defaultSession.setPermissionCheckHandler(()=>false);
 session.defaultSession.on('will-download',(event,item,contents)=>{
  if(contents!==view?.webContents||!allowedDownload(item.getURL(),origin)){event.preventDefault();return;}
  const filename=path.basename(item.getFilename()).replace(/[<>:"/\\|?*\x00-\x1f]/g,'_');
  item.setSaveDialogOptions({title:t('保存到这台电脑'),defaultPath:path.join(app.getPath('downloads'),filename)});
  item.once('done',(_event,state)=>{if(state!=='completed'){errorMessage=state==='cancelled'?t('下载已取消。'):t('文件下载失败，请重试。');broadcast();dialog.showMessageBox(window,{type:'warning',title:t('文件未保存'),message:errorMessage});}});
 });
 window=new BrowserWindow({width:1180,height:840,minWidth:880,minHeight:640,show:false,title:'EvoMyn',icon:path.join(__dirname,'assets','icon.ico'),backgroundColor:'#f3f3f1',autoHideMenuBar:true,webPreferences:{preload:path.join(__dirname,'preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true,webviewTag:false,backgroundThrottling:false}});
 Menu.setApplicationMenu(null);guard(window.webContents);window.webContents.on('dom-ready',()=>applyLanguage(window.webContents).catch(report));
 view=new WebContentsView({webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,webviewTag:false,backgroundThrottling:false}});view.setBorderRadius(11);guard(view.webContents);view.webContents.on('dom-ready',()=>{if(allowedDashboard(view.webContents.getURL(),origin)){view.webContents.insertCSS(dashboardCSS).catch(report);applyLanguage(view.webContents).catch(report);}});view.webContents.on('did-navigate',(_event,url)=>{if(['memory','mcp'].includes(page)&&allowedDashboard(url,origin)&&new URL(url).pathname.startsWith('/memory/')){page=new URL(url).pathname.startsWith('/memory/mcp/')?'mcp':'memory';broadcast();}});view.setVisible(false);window.contentView.addChildView(view);resizeView();
 window.on('resize',resizeView);window.on('close',event=>{if(!quitting){event.preventDefault();window.hide();}});
 tray=new Tray(path.join(__dirname,'assets','icon.ico'));tray.on('double-click',reveal);tray.on('click',reveal);updateTray();
 ipcMain.handle('personal-memory:command',async(event,action,params)=>{
  if(!trustedShell(event,window?.webContents,shellFile))throw new Error('此页面没有桌面控制权限。');
  try{return await perform(action,params);}catch(error){report(error);throw new Error(error.message);}
 });
 await window.loadFile(shellFile);if(!process.argv.includes('--background'))reveal();
 try{await startService();}catch(error){report(error);}
 if(process.argv.includes('--smoke-test')||process.env.PERSONAL_MEMORY_SMOKE_EXPECT_VERSION===app.getVersion())await smokeTest();
 else if(process.argv.includes('--smoke-update'))await smokeUpdate();
 else if(process.argv.includes('--smoke-onboarding'))await smokeOnboarding();
}
function isolatedSmoke(){if(!process.env.PERSONAL_MEMORY_HOME||!fs.existsSync(path.join(home,'.desktop-smoke-fixture')))throw new Error('Smoke mode requires an isolated fixture.');}
async function smokeMcp(category='journal'){
 const {execFile}=require('node:child_process');const config=JSON.parse(await service.request('client-config',{format:'json'})).mcpServers['evomyn'];
 const code=`import asyncio,json,sys,os
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters,stdio_client
async def main():
 config=json.loads(sys.argv[1])
 params=StdioServerParameters(command=config['command'],args=config['args'],env=dict(os.environ))
 async with stdio_client(params) as streams:
  async with ClientSession(*streams) as session:
   initialized=await session.initialize()
   assert initialized.server_info.name=='EvoMyn', initialized.server_info
   tools=await session.list_tools()
   assert 'archive_record' in [tool.name for tool in tools.tools]
   before=await session.call_tool('archive_list',{})
   category=sys.argv[2]
   title='Desktop acceptance fixture' if category=='journal' else 'Custom category acceptance'
   preserved=title in str(before)
   if not preserved:
    saved=await session.call_tool('archive_record',{'category':category,'title':title,'body':'Isolated installer and update acceptance only.'})
    assert not saved.is_error
   listed=await session.call_tool('archive_list',{})
   assert not listed.is_error and title in str(listed)
   print(json.dumps({'name':initialized.server_info.name,'tools':len(tools.tools),'record':True,'preserved':preserved}))
asyncio.run(main())`;
 return new Promise((resolve,reject)=>execFile(config.command,['-E','-s','-X','utf8','-c',code,JSON.stringify(config),category],{windowsHide:true,timeout:60000,maxBuffer:1024*1024,env:{...process.env,MNEMOSYNE_NO_EMBEDDINGS:'1'}},(error,stdout)=>{if(error)reject(new Error('Packaged MCP acceptance failed: '+error.message));else{try{resolve(JSON.parse(stdout.trim()));}catch(error){reject(error);}}}));
}
async function smokeUpdate(){
 isolatedSmoke();const mcp=await smokeMcp();
 await updater.importRelease(process.env.PERSONAL_MEMORY_SMOKE_MANIFEST,process.env.PERSONAL_MEMORY_SMOKE_INSTALLER);
 await fsp.writeFile(path.join(home,'upgrade-begin.json'),JSON.stringify({from:app.getVersion(),target:updater.status().availableVersion,mcp}));
 await perform('update-install');
}
async function smokeOnboarding(){
 isolatedSmoke();const assert=require('node:assert/strict'),evidence={version:app.getVersion(),packaged:app.isPackaged,startupError:errorMessage};
 const wait=async predicate=>{const deadline=Date.now()+20000;while(!await predicate()){if(Date.now()>deadline)throw new Error('Onboarding acceptance timed out');await new Promise(resolve=>setTimeout(resolve,100));}};
 const capture=async contents=>{let shot;await wait(async()=>{try{shot=await contents.capturePage(undefined,{stayHidden:true,stayAwake:true});return !shot.isEmpty();}catch(error){if(error.message!=='UnknownVizError')throw error;return false;}});return shot.toPNG();};
 try{
  assert.equal(new URL(process.env.PERSONAL_MEMORY_SMOKE_ENDPOINT).hostname,'127.0.0.1');
  assert.equal(app.getName(),'EvoMyn');assert.equal(window.getTitle(),'EvoMyn');
  assert.equal(await window.webContents.executeJavaScript("document.querySelector('.identity strong').textContent"),'EvoMyn');
  assert.equal(preferences.updateFeed,DEFAULT_UPDATE_FEED);assert.equal(updater.status().feedConfigured,true);
  assert.equal(await window.webContents.executeJavaScript("document.getElementById('update-check').disabled"),false);
  await perform('set-update-feed',{url:'https://updates.example.test/latest.json'});assert.equal(preferences.updateFeed,'https://updates.example.test/latest.json');
  await perform('set-update-feed',{url:''});assert.equal(preferences.updateFeed,DEFAULT_UPDATE_FEED);evidence.embeddedUpdateFeed=true;
  assert.equal(await view.webContents.executeJavaScript('document.title'),'记忆 · EvoMyn');evidence.brand='EvoMyn';
  assert.equal(serviceStatus.mcp_enabled,true);assert.equal(page,'memory');evidence.localStartup=true;evidence.localMcp=await smokeMcp();
  assert.equal(await window.webContents.executeJavaScript("!!document.querySelector('#setup #export-json')&&!!document.querySelector('#setup #export-toml')&&!document.querySelector('#settings #mcp')&&!document.querySelector('#settings #cloud')&&document.querySelectorAll('[aria-label=\"MCP 服务总开关\"]').length===1"),true,'Connections own client configuration; settings do not duplicate service controls');
  evidence.navigationSeparation=true;
  assert.equal(await window.webContents.executeJavaScript("(()=>{const n=document.querySelector('.toolbar nav').getBoundingClientRect(),t=document.querySelector('.toolbar').getBoundingClientRect();return t.width<240&&t.height>=innerHeight&&n.height>n.width/2&&!!document.getElementById('canvas');})()"),true,'Desktop navigation occupies a persistent left rail');
  let releaseNavigation;
  session.defaultSession.webRequest.onBeforeRequest({urls:[origin+'/memory/mcp/']},(_details,callback)=>{releaseNavigation=callback;});
  const pendingNavigation=showPage('mcp');await wait(()=>!!releaseNavigation);await showPage('settings');releaseNavigation({cancel:false});await pendingNavigation;
  session.defaultSession.webRequest.onBeforeRequest(null);
  assert.equal(page,'settings','A late dashboard navigation cannot replace a selected native page');assert.equal(view.getVisible(),false);evidence.navigationRace=true;
  const captureLayout=async(size,label)=>{
   const headingPositions={};
   window.setContentSize(...size);
   for(const target of ['memory','mcp','setup','settings']){
    await showPage(target);await new Promise(resolve=>setTimeout(resolve,250));
    const shellLayout=await window.webContents.executeJavaScript("(()=>{const t=document.querySelector('.toolbar').getBoundingClientRect(),c=document.getElementById('canvas').getBoundingClientRect(),n=document.querySelector('.toolbar nav').getBoundingClientRect(),q=document.querySelector('.quick-control').getBoundingClientRect();return {overflow:document.documentElement.scrollWidth>innerWidth||document.getElementById('canvas').scrollWidth>c.width,heading:document.querySelector('main:not([hidden]) h1')?.textContent,railRight:t.right,canvasLeft:c.left,canvasTop:c.top,navBottom:n.bottom,controlTop:q.top};})()");
    assert.equal(shellLayout.overflow,false);assert.ok(shellLayout.navBottom<shellLayout.controlTop);assert.equal(shellLayout.railRight,shellLayout.canvasLeft);assert.equal(shellLayout.canvasTop,8);
    if(['memory','mcp'].includes(target)){
     assert.deepEqual(view.getBounds(),contentBounds(...window.getContentSize()));
     assert.ok(Math.abs(view.getBounds().x-shellLayout.canvasLeft-1)<=1,JSON.stringify({bounds:view.getBounds(),shell:shellLayout,size:window.getContentSize(),viewport:await window.webContents.executeJavaScript('({width:innerWidth,height:innerHeight,ratio:devicePixelRatio})')}));
     const heading=await view.webContents.executeJavaScript("(()=>{const r=document.querySelector('.hero h1').getBoundingClientRect();return {x:r.left,y:r.top};})()");headingPositions[target]={x:heading.x+view.getBounds().x,y:heading.y+view.getBounds().y};
     if(target==='memory')await wait(()=>view.webContents.executeJavaScript("document.getElementById('connectionStatus')?.textContent==='已连接'&&document.querySelectorAll('.item').length>0"));
     const controls=await view.webContents.executeJavaScript(target==='memory'?"({kind:'categories',count:[...document.querySelectorAll('#categoryNav button')].filter(b=>b.getClientRects().length>0).length,menuDisplay:getComputedStyle(document.getElementById('sidebarMenu')).display})":"({kind:'tabs',width:document.querySelector('.ability-tabs').getBoundingClientRect().width,radius:getComputedStyle(document.getElementById('mineTab')).borderRadius})");
     if(target==='memory')assert.equal(controls.count,5,JSON.stringify(controls));else {assert.ok(controls.width<360,JSON.stringify(controls));assert.equal(controls.radius,'7px');}
     if(target==='memory'){
      await view.webContents.executeJavaScript("document.querySelector('.item').click()");assert.equal(await view.webContents.executeJavaScript("document.getElementById('detail').open"),true);await view.webContents.executeJavaScript("document.getElementById('closeDetail').click();location.hash='backup'");
      await wait(()=>view.webContents.executeJavaScript("location.hash==='#overview'&&document.getElementById('overview').classList.contains('active')"));assert.equal(await view.webContents.executeJavaScript("!!document.querySelector('[data-tab=backup]')||!!document.getElementById('backup')"),false);evidence.cloudBackupDeferred=true;
      await view.webContents.executeJavaScript("document.getElementById('searchQuery').value='unmatched-fixture-query';document.getElementById('searchQuery').dispatchEvent(new Event('input',{bubbles:true}))");assert.equal(await view.webContents.executeJavaScript("document.querySelectorAll('#records .item').length"),0);await view.webContents.executeJavaScript("document.getElementById('searchQuery').value='';document.getElementById('searchQuery').dispatchEvent(new Event('input',{bubbles:true}))");
     }else{
      await view.webContents.executeJavaScript("document.getElementById('marketTab').click()");await wait(()=>view.webContents.executeJavaScript("!document.getElementById('marketPane').hidden&&document.querySelectorAll('.ability-card').length>0"));assert.equal(await view.webContents.executeJavaScript("document.getElementById('minePane').textContent.includes('计划提醒')||document.getElementById('marketPane').textContent.includes('计划提醒')"),false);evidence.deviceBuiltinsExcluded=true;assert.equal(await view.webContents.executeJavaScript('document.documentElement.scrollWidth<=innerWidth'),true);await fsp.writeFile(path.join(home,`layout-market-${label}-content.png`),await capture(view.webContents));await view.webContents.executeJavaScript("document.getElementById('mineTab').click()");await new Promise(resolve=>setTimeout(resolve,180));
     }
     assert.equal(await view.webContents.executeJavaScript("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('.primary-nav a')].filter(a=>a.getAttribute('href')!=='/memory/planner/').every(a=>getComputedStyle(a).display==='none')"),true);
     await fsp.writeFile(path.join(home,`layout-${target}-${label}-content.png`),await capture(view.webContents));
    }else {assert.equal(shellLayout.heading,target==='setup'?'客户端接入':'应用设置');headingPositions[target]=await window.webContents.executeJavaScript("(()=>{const r=document.querySelector('main:not([hidden]) h1').getBoundingClientRect();return {x:r.left,y:r.top};})()");}
    await fsp.writeFile(path.join(home,`layout-${target}-${label}.png`),await capture(window.webContents));
   }
   await fsp.writeFile(path.join(home,`heading-positions-${label}.json`),JSON.stringify(headingPositions));
   for(const target of ['memory','mcp']){assert.ok(Math.abs(headingPositions[target].x-headingPositions.setup.x)<=1,JSON.stringify(headingPositions));assert.ok(Math.abs(headingPositions[target].y-headingPositions.setup.y)<=1,JSON.stringify(headingPositions));}
  };
  await captureLayout([1180,800],'normal');await captureLayout([880,640],'compact');window.setContentSize(1180,800);evidence.responsiveLayout=true;
  await showPage('memory');
  const categoryJS=script=>view.webContents.executeJavaScript(script);
  await categoryJS("document.getElementById('manageCategories').click()");
  await wait(()=>categoryJS("document.getElementById('categoryManager').open&&document.getElementById('categoryManager').getAttribute('aria-busy')==='false'&&document.querySelector('[data-category-add] button').disabled===false"));
  assert.equal(await categoryJS("[...document.querySelectorAll('[data-category-rename] input')].some(n=>n.value==='个人')"),true);
  const addCategory=async label=>{
   await categoryJS("(()=>{const f=document.querySelector('[data-category-add]');f.elements.label.value="+JSON.stringify(label)+";f.elements.label.dispatchEvent(new Event('input',{bubbles:true}));f.requestSubmit();})()");
   await wait(()=>categoryJS("document.getElementById('categoryManager').getAttribute('aria-busy')==='false'&&[...document.querySelectorAll('[data-category-rename] input')].some(n=>n.value==="+JSON.stringify(label)+")"));
   return categoryJS("[...document.querySelectorAll('[data-category-rename]')].find(f=>f.elements.label.value==="+JSON.stringify(label)+").dataset.categoryRename");
  };
  const customId=await addCategory('阅读 <img src=x>');
  assert.equal(await categoryJS("document.getElementById('categoryManager').querySelectorAll('img').length"),0);evidence.categoryEscaping=true;
  evidence.customCategoryMcp=await smokeMcp(customId);
  await categoryJS("(()=>{const f=document.querySelector('[data-category-rename=\""+customId+"\"]');f.elements.label.value='阅读笔记';f.elements.label.dispatchEvent(new Event('input',{bubbles:true}));f.requestSubmit();})()");
  await wait(()=>categoryJS("document.getElementById('categoryManager').getAttribute('aria-busy')==='false'&&document.getElementById('categoryNav').textContent.includes('阅读笔记')"));
  assert.equal(await categoryJS("document.querySelector('[data-category-delete=\""+customId+"\"]').disabled"),true);
  await categoryJS("document.querySelector('[data-category-up=\""+customId+"\"]').click()");
  await wait(()=>categoryJS("document.getElementById('categoryManager').getAttribute('aria-busy')==='false'&&document.querySelectorAll('[data-category-rename]')[3].dataset.categoryRename==='"+customId+"'"));
  const emptyId=await addCategory('临时分类');await categoryJS("document.querySelector('[data-category-delete=\""+emptyId+"\"]').click()");
  await wait(()=>categoryJS("document.getElementById('categoryManager').getAttribute('aria-busy')==='false'&&!document.querySelector('[data-category-rename=\""+emptyId+"\"]')"));
  await fsp.writeFile(path.join(home,'categories-normal.png'),await capture(view.webContents));
  window.setContentSize(880,640);await new Promise(resolve=>setTimeout(resolve,250));
  assert.equal(await categoryJS("(()=>{const d=document.getElementById('categoryManager'),r=d.getBoundingClientRect();return d.scrollWidth<=d.clientWidth&&r.left>=0&&r.right<=innerWidth;})()"),true);
  await fsp.writeFile(path.join(home,'categories-compact.png'),await capture(view.webContents));window.setContentSize(1180,800);
  await categoryJS("document.querySelector('[data-category-close]').click()");await view.webContents.reload();
  await wait(()=>categoryJS("document.getElementById('connectionStatus')?.textContent==='已连接'&&document.getElementById('categoryNav').textContent.includes('阅读笔记')"));
  await categoryJS("document.querySelector('[data-tab=\""+customId+"\"]').click()");
  assert.equal(await categoryJS("document.getElementById('pageTitle').textContent"),'阅读笔记');
  assert.equal(await categoryJS("document.querySelectorAll('#records .item').length"),1);evidence.categoryPersistence=true;evidence.categoryManagement=true;
  await fsp.writeFile(path.join(home,'categories-records.png'),await capture(view.webContents));
  await window.webContents.executeJavaScript("window.personalMemory.command('view',{page:'settings'})");
  await window.webContents.executeJavaScript("document.getElementById('quick-mcp').click()");
  await wait(()=>!busy&&!serviceStatus.mcp_enabled);await wait(()=>window.webContents.executeJavaScript("!document.getElementById('quick-mcp').disabled&&!document.getElementById('quick-mcp').checked"));await window.webContents.executeJavaScript("document.getElementById('quick-mcp').click()");
  await wait(()=>!busy&&serviceStatus.mcp_enabled);assert.equal(page,'settings');assert.equal(serviceStatus.cloud_enabled,false);evidence.independentMcpSwitch=true;
  await window.webContents.executeJavaScript("window.personalMemory.command('view',{page:'setup'})");
  await wait(()=>window.webContents.executeJavaScript("!document.getElementById('cloud').disabled"));await window.webContents.executeJavaScript("document.getElementById('cloud').click()");
  await wait(()=>!busy&&page==='setup');assert.equal(serviceStatus.mcp_enabled,true);assert.equal(serviceStatus.cloud_enabled,false);evidence.cloudSetupGuard=true;
  await wait(()=>window.webContents.executeJavaScript("!document.getElementById('setup').hidden"));
  assert.equal(await window.webContents.executeJavaScript("(()=>{const r=document.getElementById('endpoint').getBoundingClientRect();return r.top>=9&&r.bottom<=innerHeight-9&&document.activeElement.id==='endpoint';})()"),true,'Missing cloud setup must reveal and focus the endpoint field');
  await fsp.writeFile(path.join(home,'onboarding-guide.png'),await capture(window.webContents));
  await window.webContents.executeJavaScript("document.getElementById('endpoint').value='https://xiaozhi.me/';document.getElementById('connection-form').requestSubmit()");
  await wait(()=>!busy&&!!errorMessage);assert.equal(serviceStatus.cloud_configured,false);assert.equal(serviceStatus.mcp_enabled,true);evidence.invalidRejected=true;
  await window.webContents.executeJavaScript("document.getElementById('endpoint').value="+JSON.stringify(process.env.PERSONAL_MEMORY_SMOKE_ENDPOINT)+";document.getElementById('connection-form').requestSubmit()");
  await wait(()=>!busy&&serviceStatus.cloud_connected);await new Promise(resolve=>setTimeout(resolve,600));
  assert.equal(serviceStatus.mcp_enabled,true);assert.equal(serviceStatus.cloud_enabled,true);
  assert.equal(await window.webContents.executeJavaScript("document.getElementById('endpoint').value"),'');
  assert.equal(JSON.stringify(snapshot()).includes('isolated-onboarding-fixture'),false);evidence.saveAndConnect=true;evidence.writeOnly=true;
  await fsp.writeFile(path.join(home,'onboarding-connected.png'),await capture(window.webContents));
  await showPage('mcp');await wait(()=>view.webContents.executeJavaScript("document.getElementById('connectionState')?.textContent==='已连接'&&Number(document.getElementById('toolCount')?.textContent)>0"));
  assert.equal(await view.webContents.executeJavaScript("['start','stop','restart'].every(id=>document.getElementById(id).hidden)"),true);evidence.capabilitiesConsistent=true;
  await view.webContents.executeJavaScript("document.querySelector('#desktopControlHint a').click()");await wait(()=>page==='setup');evidence.embeddedSetupRoutesToGuide=true;
  await perform('stop-mcp');assert.equal(serviceStatus.cloud_connected,false);await perform('start-mcp');await wait(()=>serviceStatus.cloud_connected);evidence.savedEndpointReconnect=true;
  await perform('set-cloud',{enabled:false});assert.equal(serviceStatus.mcp_enabled,true);assert.equal(serviceStatus.cloud_enabled,false);evidence.independentCloudPause=true;
  await service.stop();assert.equal(fs.existsSync(path.join(home,'service','desktop-session.json')),false);evidence.cleanShutdown=true;
  await fsp.writeFile(path.join(home,'onboarding-result.json'),JSON.stringify(evidence,null,2));quitting=true;tray.destroy();app.exit(0);
 }catch(error){await fsp.writeFile(path.join(home,'onboarding-result.json'),JSON.stringify({...evidence,error:error.message,stack:error.stack},null,2));try{await service?.stop();}catch{}quitting=true;app.exit(1);}
}
async function smokeTest(){
 // Explicit, isolated acceptance mode. Never run against the normal profile.
 isolatedSmoke();
 const assert=require('node:assert/strict'),evidence={version:app.getVersion(),packaged:app.isPackaged,startupError:errorMessage};
 try{
  if(!serviceStatus?.mcp_enabled)await perform('use-local');await showPage('memory');
  assert.equal(serviceStatus.ready,true);assert.equal(await view.webContents.executeJavaScript('document.title'), '记忆 · EvoMyn');
  evidence.dashboard=true;evidence.mcp=await smokeMcp();if(process.env.PERSONAL_MEMORY_SMOKE_EXPECT_VERSION)assert.equal(evidence.mcp.preserved,true);
  const wait=async predicate=>{const deadline=Date.now()+20000;while(!await predicate()){if(Date.now()>deadline)throw new Error('Memory editor acceptance timed out');await new Promise(resolve=>setTimeout(resolve,100));}};
  await view.webContents.reload();
  await wait(()=>view.webContents.executeJavaScript("document.getElementById('connectionStatus')?.textContent==='已连接'&&!document.getElementById('createRecord').hidden"));
  const archive=()=>view.webContents.executeJavaScript("fetch('./api/records').then(response=>response.json())");
  const before=await archive(),original=before.records.find(record=>record.title==='Desktop acceptance fixture');assert.ok(original);
  const targetCategory=original.category==='journal'?'people':'journal';
  await view.webContents.executeJavaScript('location.hash='+JSON.stringify('#'+original.category+'/'+encodeURIComponent(original.id)));
  await wait(()=>view.webContents.executeJavaScript("document.getElementById('detail').open&&!document.getElementById('recordActions').hidden"));
  await view.webContents.executeJavaScript("document.getElementById('editRecord').click()");
  assert.equal(await view.webContents.executeJavaScript("document.querySelector('[data-editor-form]').elements.category.disabled"),false);
  await view.webContents.executeJavaScript("(()=>{const form=document.querySelector('[data-editor-form]');form.elements.category.value="+JSON.stringify(targetCategory)+";form.elements.category.dispatchEvent(new Event('input',{bubbles:true}));form.requestSubmit();})()");
  await wait(()=>view.webContents.executeJavaScript("!document.getElementById('recordEditor').open"));
  const after=await archive(),edited=after.records.find(record=>record.id===original.id);assert.ok(edited);
  assert.equal(after.records.length,before.records.length);assert.equal(edited.category,targetCategory);assert.equal(edited.revision,original.revision+1);
  for(const field of ['id','title','body','tags','fields','links','steps','href'])assert.deepEqual(edited[field],original[field]);
  for(const field of ['date','date_end'])assert.equal(edited[field]||'',original[field]||'');
  evidence.categoryEditing={idPreserved:true,revisionAdvanced:true,countPreserved:true,category:targetCategory};
  await window.webContents.executeJavaScript("window.personalMemory.command('stop-mcp')");assert.equal(serviceStatus.mcp_enabled,false);assert.equal(serviceStatus.ready,true);evidence.nativeIPC=true;
  await perform('set-cloud',{enabled:true});assert.equal(serviceStatus.mcp_enabled,false);assert.equal(serviceStatus.cloud_connected,false);assert.equal(page,'setup');
  await perform('use-local');assert.equal(serviceStatus.mcp_enabled,true);evidence.switches=true;
  const config=JSON.parse(await service.request('client-config',{format:'json'}));assert.ok(config.mcpServers['evomyn'].command);evidence.clientConfig=true;
  window.close();assert.equal(window.isVisible(),false);reveal();assert.equal(window.isVisible(),true);evidence.trayLifecycle=true;
  await showPage('settings');await new Promise(resolve=>setTimeout(resolve,1000));
  evidence.settingsDOM=await window.webContents.executeJavaScript("({page:state?.page,hidden:document.getElementById('settings').hidden,active:document.querySelector('.nav.active')?.dataset.page})");assert.equal(evidence.settingsDOM.hidden,false);assert.equal(evidence.settingsDOM.active,'settings');
  assert.equal('device_sync' in serviceStatus,false);
  assert.equal(await window.webContents.executeJavaScript("document.querySelector('[id^=device-sync]')===null"),true);
  evidence.localReminders=true;
  assert.equal(await window.webContents.executeJavaScript("!!document.getElementById('ota-state')"),true);
  assert.equal(await window.webContents.executeJavaScript("!!document.getElementById('firmware-check') && !!document.getElementById('firmware-download')"),true);
  assert.equal(await window.webContents.executeJavaScript("!document.getElementById('ota-version').textContent.includes('已安装')"),true);
  if(process.env.PERSONAL_MEMORY_SMOKE_OTA==='1'){
   assert.equal(serviceStatus.device_ota.running,true);assert.equal(serviceStatus.device_ota.version,'2.5.7');
   assert.equal(await window.webContents.executeJavaScript("document.getElementById('ota-version').textContent.includes('2.5.7')"),true);
   evidence.deviceOTA={running:true,version:serviceStatus.device_ota.version};
  }
  await fsp.writeFile(path.join(home,'desktop-settings.png'),(await window.webContents.capturePage()).toPNG());
  await window.webContents.executeJavaScript("document.getElementById('ota-title').scrollIntoView({block:'start'})");
  await new Promise(resolve=>setTimeout(resolve,300));
  await fsp.writeFile(path.join(home,'desktop-firmware-settings.png'),(await window.webContents.capturePage()).toPNG());
  await showPage('memory');await new Promise(resolve=>setTimeout(resolve,600));await fsp.writeFile(path.join(home,'desktop-dashboard.png'),(await window.capturePage()).toPNG());
  await service.stop();assert.equal(fs.existsSync(path.join(home,'service','desktop-session.json')),false);evidence.cleanShutdown=true;
  await fsp.writeFile(path.join(home,'smoke-result.json'),JSON.stringify(evidence,null,2));quitting=true;tray.destroy();app.exit(0);
 }catch(error){await fsp.writeFile(path.join(home,'smoke-result.json'),JSON.stringify({...evidence,error:error.message,stack:error.stack},null,2));await service?.stop();quitting=true;app.exit(1);}
}
if(!app.requestSingleInstanceLock())app.quit();else{
 app.on('second-instance',reveal);app.on('before-quit',event=>{if(!quitting){event.preventDefault();quit();}});
 app.on('window-all-closed',()=>{});app.whenReady().then(create).catch(async error=>{report(error);await quit();});
}
