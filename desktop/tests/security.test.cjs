const test=require('node:test');const assert=require('node:assert/strict');const {pathToFileURL}=require('node:url');
const {trustedShell,dashboardOrigin,allowedDashboard,allowedDownload,allowedSource,validateCommand}=require('../security.cjs');
test('marketplace source links allow only explicit public HTTPS destinations',()=>{
 for(const value of ['https://registry.modelcontextprotocol.io/','https://github.com/modelcontextprotocol/servers'])assert.equal(allowedSource(value),true);
 for(const value of ['file:///C:/private','https://github.com.evil.test/','http://github.com/','https://user:pass@github.com/','https://github.com:8443/','https://127.0.0.1/','https://evil.test/'])assert.equal(allowedSource(value),false);
});
test('native IPC accepts only the exact trusted top-level shell frame',()=>{
 const file='C:/fixture/ui/index.html',frame={url:pathToFileURL(file).href},contents={mainFrame:frame,isDestroyed:()=>false};
 assert.equal(trustedShell({sender:contents,senderFrame:frame},contents,file),true);
 assert.equal(trustedShell({sender:contents,senderFrame:{url:frame.url}},contents,file),false);
 assert.equal(trustedShell({sender:{},senderFrame:frame},contents,file),false);
 frame.url='http://127.0.0.1:4321/memory/';assert.equal(trustedShell({sender:contents,senderFrame:frame},contents,file),false);
});
test('embedded view restricts origin and navigation paths',()=>{
 const origin=dashboardOrigin('http://127.0.0.1:4321/memory/');
 assert.equal(allowedDashboard(origin+'/memory/mcp/#mine',origin),true);assert.equal(allowedDashboard(origin+'/setup/?saved=1',origin),true);
 for(const value of ['https://127.0.0.1:4321/memory/','http://127.0.0.1:4322/memory/','http://evil.test/memory/',origin+'/rpc',origin+'/memory/../../private','file:///C:/secret'])assert.equal(allowedDashboard(value,origin),false);
 assert.throws(()=>dashboardOrigin('http://user:pass@127.0.0.1:4321/'));
});
test('commands reject arbitrary native actions and malformed arguments',()=>{
 validateCommand('stop-mcp',{});validateCommand('set-cloud',{enabled:false});validateCommand('export-config',{format:'toml'});
 validateCommand('connect-xiaozhi',{endpoint:'wss://cloud.example.test/mcp'});validateCommand('open-xiaozhi-console',{});
 assert.throws(()=>validateCommand('open-xiaozhi-console',{url:'file:///private'}));assert.throws(()=>validateCommand('connect-xiaozhi',{endpoint:'x'.repeat(4097)}));
 for(const [action,value] of [['exec',{}],['stop-mcp',{path:'C:/'}],['set-cloud',{enabled:'false'}],['view',{page:'file:///'}],['export-config',{format:'js'}],['quit',null]])assert.throws(()=>validateCommand(action,value));
});
test('downloads allow user-selected dashboard exports and recovery blobs only',()=>{
 const origin='http://127.0.0.1:4321';
 for(const value of ['/setup/clients/codex.toml','/setup/clients/claude.json','/memory/backup/restore-tool.py','/memory/backup/api/download/abc-123','/memory/api/files/record-123'])assert.equal(allowedDownload(origin+value,origin),true);
 assert.equal(allowedDownload('blob:'+origin+'/123',origin),true);
 for(const value of ['https://evil.test/file.exe',origin+'/rpc',origin+'/memory/backup/api/download/../private','blob:https://evil.test/123'])assert.equal(allowedDownload(value,origin),false);
});
test('retired device sync commands cannot enter native IPC',()=>{
 for(const params of [{},{directory:'C:/private'},{token:'secret'},{path:'C:/private'}])assert.throws(()=>validateCommand('import-device-sync',params));
 for(const params of [{enabled:true},{enabled:false},{enabled:'true'},{enabled:true,host:'0.0.0.0'},{}])assert.throws(()=>validateCommand('set-device-sync',params));
});
test('OTA commands accept no renderer-provided paths or configuration',()=>{
 for(const action of ['ota-retry','ota-import-pairing','ota-import-release']){
  assert.doesNotThrow(()=>validateCommand(action,{}));
  for(const params of [{directory:'C:/private'},{manifest:'C:/private/manifest.json'},{enabled:true},{url:'https://example.test/'},{token:'secret'}])assert.throws(()=>validateCommand(action,params));
 }
});
