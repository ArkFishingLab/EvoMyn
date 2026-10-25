'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const {dataHome,pythonPath,toolsPath,loginSettings,applicationMenu}=require('../platform.cjs');
const {defaultUpdateFeed,resolveUpdateFeed}=require('../update-source.cjs');
test('platform paths preserve the Windows installed profile and use Application Support on Mac',()=>{
 assert.equal(dataHome('C:\\Users\\example\\AppData\\Roaming','win32'),'C:\\Users\\example\\AppData\\Local\\PersonalMemory');
 assert.equal(dataHome('/Users/example/Library/Application Support','darwin'),'/Users/example/Library/Application Support/EvoMyn');
 const root=path.resolve('fixture');
 for(const platform of ['win32','darwin'])assert.equal(toolsPath(pythonPath(root,platform),platform),path.join(root,'tools'));
 assert.equal(dataHome('unused','darwin',root),root);
});
test('Mac login and application menus preserve edit shortcuts and background launch',()=>{
 assert.deepEqual(loginSettings(true,'unused','darwin'),{openAtLogin:true,openAsHidden:true});
 assert.deepEqual(loginSettings(true,'EvoMyn.exe','win32').args,['--background']);
 const menu=applicationMenu(x=>x,()=>{});
 assert.ok(menu.some(item=>item.role==='editMenu'));
 assert.ok(menu[0].submenu.some(item=>item.role==='quit'));
});
test('Mac architecture feeds stay separate while old Windows clients keep latest.json',()=>{
 assert.match(defaultUpdateFeed('win32','x64'),/\/latest.json$/);
 for(const arch of ['arm64','x64']){
  assert.ok(defaultUpdateFeed('darwin',arch).endsWith(`/latest-darwin-${arch}.json`));
  assert.equal(resolveUpdateFeed(defaultUpdateFeed('win32','x64'),'darwin',arch),defaultUpdateFeed('darwin',arch));
 }
 assert.equal(resolveUpdateFeed('https://updates.example.test/custom','darwin','arm64'),'https://updates.example.test/custom');
});
