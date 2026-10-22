const test=require('node:test');const assert=require('node:assert/strict');const {EventEmitter}=require('node:events');const {PassThrough}=require('node:stream');
const {ServiceClient}=require('../service-client.cjs');
function fixture({shutdown=true,kill=true}={}){
 const child=new EventEmitter();child.stdin=new PassThrough();child.stdout=new PassThrough();child.stderr=new PassThrough();child.exitCode=null;
 child.kill=()=>{if(kill)setImmediate(()=>{child.exitCode=1;child.emit('exit',1);});return kill;};
 child.stdin.on('data',data=>{const request=JSON.parse(data);setImmediate(()=>{child.stdout.write(JSON.stringify({id:request.id,ok:true,result:{ready:true}})+'\n');if(request.command==='shutdown'&&shutdown){child.exitCode=0;child.emit('exit',0);}});});
 const options={python:'python.exe',script:'service.py',appDir:'fixture',dataRoot:'fixture-data',spawnProcess:(...args)=>{child.arguments=args;return child;},env:{PATH:'fixture',PYTHONPATH:'untrusted',PYTHONHOME:'untrusted'},shutdownTimeout:20,killTimeout:20,helperGrace:1};
 return {child,client:new ServiceClient(options)};
}
test('service pipe correlates responses and launches isolated bundled Python',async()=>{
 const {client,child}=fixture();assert.equal((await client.start()).ready,true);
 assert.deepEqual(child.arguments[1].slice(0,5),['-E','-s','-X','utf8','-u']);assert.equal(child.arguments[2].env.PYTHONPATH,undefined);assert.equal(child.arguments[2].env.PYTHONHOME,undefined);
 await client.stop();assert.equal(client.child,null);
});
test('a force-killed supervisor aborts update handoff even after exit',async()=>{
 const {client,child}=fixture({shutdown:false});await client.start();await assert.rejects(client.stop(),/未能正常关闭/);assert.notEqual(child.exitCode,null);
});
test('stop cannot succeed when the child refuses termination',async()=>{
 const {client,child}=fixture({shutdown:false,kill:false});await client.start();await assert.rejects(client.stop(),/进程尚未退出/);assert.equal(child.exitCode,null);child.exitCode=0;child.emit('exit',0);
});
test('bounded pipe parsing rejects malformed backend output',async()=>{
 const {client,child}=fixture();await client.start();const pending=client.request('status');child.stdout.emit('data','not-json\n');await assert.rejects(pending,/无效响应/);child.exitCode=0;child.emit('exit',0);
});
test('normal shutdown waits for a registered external helper to actually exit',async()=>{
 const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path'),{spawn}=require('node:child_process');
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'desktop-helper-test-')),directory=path.join(root,'desktop-clients');await fs.mkdir(directory);
 const helper=spawn(process.execPath,['-e','setTimeout(()=>{},450)'],{stdio:'ignore',windowsHide:true});const exited=new Promise(resolve=>helper.once('exit',resolve));
 const lease=path.join(directory,'a'.repeat(32)+'.json');await fs.writeFile(lease,JSON.stringify({pid:helper.pid,creation:'fixture'}));
 const {client}=fixture();client.options.dataRoot=root;client.options.waitForClients=async records=>{assert.deepEqual(records,[{pid:helper.pid,creation:'fixture'}]);await exited;};await client.start();await client.stop();assert.throws(()=>process.kill(helper.pid,0),{code:'ESRCH'});await exited;
 await fs.unlink(lease);await fs.rmdir(directory);await fs.rmdir(root);
});
test('closed backend stdin emits a handled error and rejects pending calls',async()=>{
 const {client,child}=fixture();await client.start();const request=client.request('status');child.stdin.emit('error',new Error('EPIPE'));await assert.rejects(request,/连接已关闭/);child.exitCode=0;child.emit('exit',0);
});
