'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createTranslator}=require('../ui/i18n.js');
const {validateCommand}=require('../security.cjs');
test('language command accepts only supported locales and no extra fields',()=>{
 for(const language of ['zh-CN','en'])assert.doesNotThrow(()=>validateCommand('set-language',{language}));
 for(const params of [{language:'fr'},{language:'en',url:'http://example.test'}, {},{language:null}])assert.throws(()=>validateCommand('set-language',params));
});
test('Chinese default, exact translations, whitespace, missing keys and non-string content',()=>{
 const i=createTranslator({'记忆':'Memory','保存':'Save'});
 assert.equal(i.language,'zh-CN');assert.equal(i.t('记忆'),'记忆');
 i.setLanguage('en');assert.equal(i.t('记忆'),'Memory');assert.equal(i.t(' 保存 '),' Save ');
 assert.equal(i.t('我的私人经历'),'我的私人经历');assert.equal(i.t('<img src=x>'),'<img src=x>');
 assert.equal(i.t(null),null);assert.equal(i.t('toString'),'toString');
 i.setLanguage('zh-CN');assert.equal(i.t('记忆'),'记忆');
 assert.throws(()=>i.setLanguage('fr'));assert.equal(i.language,'zh-CN');
});
test('catalog changes are reflected without losing the selected language',()=>{
 const i=createTranslator();i.setLanguage('en');i.setCatalog({'保存':'Save'});assert.equal(i.t('保存'),'Save');
});
test('static markers round-trip without translating user content or form values',()=>{
 const text={nodeType:3,data:'记忆'},personal={nodeType:3,data:'记忆'},comment={data:'i18n',nextSibling:text};
 const attrs=new Map([['data-i18n-attrs','placeholder,value'],['placeholder','保存'],['value','记忆']]);
 const input={value:'私人草稿',getAttribute:key=>attrs.get(key)??null,setAttribute:(key,value)=>attrs.set(key,value)};
 const doc={documentElement:{},createTreeWalker:()=>{let done=false;return {nextNode:()=>done?null:(done=true,comment)};},querySelectorAll:()=>[input]};
 const i=createTranslator({'记忆':'Memory','保存':'Save'});i.setLanguage('en');i.applyStatic(doc);
 assert.equal(text.data,'Memory');assert.equal(personal.data,'记忆');assert.equal(input.value,'私人草稿');assert.equal(attrs.get('value'),'记忆');assert.equal(attrs.get('placeholder'),'Save');assert.equal(doc.documentElement.lang,'en');
 i.setLanguage('zh-CN');i.applyStatic(doc);assert.equal(text.data,'记忆');assert.equal(attrs.get('placeholder'),'保存');
});
test('native preference writes only language and retains service settings',async()=>{
 const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),vm=require('node:vm'),{createRequire}=require('node:module');
 const home=fs.mkdtempSync(path.join(os.tmpdir(),'evomyn-language-'));
 try{
  const main=path.resolve(__dirname,'../main.cjs'),localRequire=createRequire(main);
  const electron={app:{getPath:()=>home,getVersion:()=>'0.2.14',setPath(){},setName(){},setAppUserModelId(){},requestSingleInstanceLock:()=>false,quit(){}}};
  const context=vm.createContext({require:name=>name==='electron'?electron:localRequire(name),__dirname:path.dirname(main),process:{...process,env:{...process.env,PERSONAL_MEMORY_HOME:home}},Buffer,URL,setImmediate,setInterval,clearInterval,setTimeout,clearTimeout});
  vm.runInContext(fs.readFileSync(main,'utf8'),context);
  const before=JSON.parse(JSON.stringify(await context.perform('preferences')));
  await context.perform('set-language',{language:'en'});
  const saved=JSON.parse(fs.readFileSync(path.join(home,'preferences.json'),'utf8'));
  assert.deepEqual(saved,{...before,language:'en'});
  // Store canonical errors so changing language can retranslate the display.
  await assert.rejects(context.perform('set-startup',{enabled:true}),/安装应用后可设置开机启动/);
  await assert.rejects(context.perform('set-language',{language:'fr'}));
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(home,'preferences.json'),'utf8')),saved);
 }finally{fs.rmSync(home,{recursive:true,force:true});}
});
test('all packaged translation catalogs contain completed strings',()=>{
 const fs=require('node:fs'),path=require('node:path');
 for(const file of ['shell-en.json','viewer-en.json','native-en.json']){
  const catalog=JSON.parse(fs.readFileSync(path.join(__dirname,'../ui',file),'utf8'));
  for(const [key,value] of Object.entries(catalog))assert.ok(typeof value==='string'&&value.trim(),file+': '+key);
 }
});
