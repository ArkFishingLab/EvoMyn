const test=require('node:test'),assert=require('node:assert/strict');
const {ConnectionFlow}=require('../connection-flow.cjs');
function fixture(initial={}){
 const status={ready:true,mcp_enabled:false,cloud_enabled:false,cloud_configured:false,cloud_connected:false,...initial},calls=[];let prompted=0;
 const request=async(command,params={})=>{calls.push(command);if(command==='start-mcp')status.mcp_enabled=true;if(command==='stop-mcp')status.mcp_enabled=false;if(command==='set-cloud')status.cloud_enabled=params.enabled;if(command==='save-endpoint'){if(params.endpoint.includes('invalid-token'))throw Error('save failed');status.cloud_configured=true;}return {...status};};
 const flow=new ConnectionFlow({request,needsSetup:async()=>{prompted++;}});
 return {flow,status,calls,prompted:()=>prompted};
}
test('MCP can start without Xiaozhi and never forces the cloud guide',async()=>{
 const f=fixture();const result=await f.flow.start();assert.equal(result.mcp_enabled,true);assert.equal(result.cloud_enabled,false);assert.equal(f.prompted(),0);
});
test('saved Xiaozhi credentials do not opt a local MCP user into cloud',async()=>{
 const f=fixture({cloud_configured:true});const result=await f.flow.start();assert.equal(result.mcp_enabled,true);assert.equal(result.cloud_enabled,false);assert.equal(f.calls.includes('set-cloud'),false);
});
test('unconfigured startup keeps the independently usable local service',async()=>{
 const f=fixture({mcp_enabled:true});const result=await f.flow.startup();assert.equal(result.mcp_enabled,true);assert.equal(f.prompted(),0);
});
test('only the Xiaozhi switch requests missing setup without stopping MCP',async()=>{
 const f=fixture({mcp_enabled:true});const result=await f.flow.startCloud();assert.equal(result.mcp_enabled,true);assert.equal(result.cloud_enabled,false);assert.equal(f.prompted(),1);assert.equal(f.calls.includes('stop-mcp'),false);
});
test('only local option can start MCP while pausing Xiaozhi',async()=>{
 const f=fixture({cloud_enabled:true});const result=await f.flow.useLocal();assert.equal(result.mcp_enabled,true);assert.equal(result.cloud_enabled,false);assert.equal(f.prompted(),0);
});
test('saving a valid endpoint continues Xiaozhi setup and enables both services',async()=>{
 const f=fixture();const result=await f.flow.connect('wss://cloud.example.test/mcp');assert.equal(f.calls[0],'save-endpoint');assert.equal(result.mcp_enabled,true);assert.equal(result.cloud_enabled,true);
});
test('invalid and failed saves never change local availability',async()=>{
 for(const endpoint of ['', 'https://xiaozhi.me/', 'wss://user:pass@cloud.example.test/mcp', 'wss://cloud.example.test/mcp#fragment', 'wss://cloud.example.test/mcp?invalid-token']){
  const f=fixture({mcp_enabled:true});await assert.rejects(f.flow.connect(endpoint));assert.equal(f.status.mcp_enabled,true);assert.equal(f.calls.includes('set-cloud'),false);assert.equal(f.calls.includes('stop-mcp'),false);
 }
});
test('existing endpoint can reconnect without being read back or reentered',async()=>{
 const f=fixture({cloud_configured:true});const result=await f.flow.connect('');assert.equal(result.cloud_enabled,true);assert.equal(result.mcp_enabled,true);assert.equal(f.calls.includes('save-endpoint'),false);
});
test('intentional cloud pause survives startup and a later MCP start',async()=>{
 const f=fixture({mcp_enabled:true,cloud_configured:true,cloud_enabled:false});await f.flow.startup();await f.flow.start();assert.equal(f.status.cloud_enabled,false);assert.equal(f.prompted(),0);
});
test('explicit Xiaozhi enable with saved credentials starts the master if needed',async()=>{
 const f=fixture({cloud_configured:true});const result=await f.flow.startCloud();assert.equal(result.mcp_enabled,true);assert.equal(result.cloud_enabled,true);assert.equal(f.prompted(),0);
});
test('missing endpoint clears a stale cloud toggle without stopping local MCP',async()=>{
 const f=fixture({mcp_enabled:true,cloud_enabled:true});const result=await f.flow.startCloud();assert.equal(result.cloud_enabled,false);assert.equal(result.mcp_enabled,true);assert.equal(f.prompted(),1);
});
