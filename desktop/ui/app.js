'use strict';
const api=window.personalMemory,$=id=>document.getElementById(id);let state=null,toastTimer;
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,4500);}
async function command(action,params={}){try{const result=await api.command(action,params);if(result?.version&&'service'in result)render(result);return result;}catch(error){toast(error.message.replace(/^Error invoking remote method '[^']+': Error: /,''));await refresh();throw error;}}
async function refresh(){try{render(await api.command('status'));}catch{}}
function render(value){
 const changed=state?.page!==value.page;state=value;const s=value.service,u=value.update||{},ready=!!s?.ready;
 $('version').textContent='v'+value.version;
 document.querySelectorAll('[data-page]').forEach(button=>{const active=button.dataset.page===value.page;button.classList.toggle('active',active);if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
 $('settings').hidden=value.page!=='settings';$('loading').hidden=ready||value.page==='settings';
 $('setup').hidden=value.page!=='setup';$('loading').hidden=ready||['settings','setup'].includes(value.page);
 if(changed)$('canvas').scrollTo(0,0);
 const slow=!!value.cloudStartedAt&&Date.now()-value.cloudStartedAt>15000;
 $('summary').textContent=!ready?'准备中':!s.mcp_enabled?'已关闭':'本机运行中';
 $('quick-label').textContent=value.busy?'切换中':'MCP 服务';
 for(const id of ['quick-mcp']){$(id).checked=!!s?.mcp_enabled;$(id).disabled=!ready||value.busy;}
 $('cloud').checked=!!s?.cloud_enabled&&!!s?.cloud_configured;$('cloud').disabled=!ready||value.busy;
 $('cloud-state').textContent=!s?.cloud_configured?'未配置':s.cloud_connected?'已连接':!s.cloud_enabled?'已关闭':!s.mcp_enabled?'等待 MCP 开启':'正在连接';
 $('setup-state').textContent=!s?.cloud_configured?'等待配置':s.cloud_connected?'已连接':s.cloud_enabled&&s.mcp_enabled?(slow?'尚未连接':'连接中'):'接入点已保存';
 $('setup-message').textContent=!s?.cloud_configured?'填入接入点后，将同时开启 MCP 服务和小智连接。':s.cloud_connected?'已连接小智云端。可返回控制台查看工具是否已加载。':s.cloud_enabled&&s.mcp_enabled?(slow?'暂未连上小智。请检查电脑网络；若地址已失效，请从控制台重新复制，或点击下方重试。':'接入点已保存，正在连接小智云端…'):'可以直接使用已保存的接入点，也可以在下方更换。';
 if(value.error&&value.page==='setup')$('xiaozhi-details').open=true;
 $('setup-error').hidden=!value.error;$('setup-error').textContent=value.error||'';
 $('connect-submit').disabled=!ready||value.busy;$('use-local').disabled=!ready||value.busy;
 $('connect-submit').textContent=value.busy?'正在处理…':s?.cloud_configured?'保存 / 连接':'保存并连接';
 $('endpoint').placeholder=s?.cloud_configured?'留空使用已保存的接入点，或粘贴新地址':'粘贴完整的 wss:// 接入地址';
 $('setup-retry').hidden=!s?.cloud_configured||s.cloud_connected;$('setup-retry').disabled=!ready||value.busy;
 $('error').hidden=!value.error;$('error').textContent=value.error||'';
 $('toolbar-error').hidden=!value.error;$('toolbar-error').textContent=value.error?'操作未完成 · 查看详情':'';$('toolbar-error').title=value.error||'';
 if(value.error&&!ready){$('loading-title').textContent='服务尚未启动';$('loading-message').textContent=value.error;}
 $('startup').checked=!!value.preferences?.startAtLogin;
 if(document.activeElement!==$('feed'))$('feed').value=value.preferences?.updateFeed||'';
 $('data-path').textContent=s?.data_root?s.data_root+'\\state\\data':'服务启动后显示数据位置';
 for(const id of ['show-data','export-json','export-toml'])$(id).disabled=!ready;
 const titles={'not-configured':'等待配置更新来源',idle:'随时检查新版本',checking:'正在检查更新',available:'有新版本可用','up-to-date':'当前已是最新版本',downloading:'正在下载更新',ready:'更新已准备好',installing:'正在安装更新',error:'更新未完成'};
 $('update-title').textContent=titles[u.state]||'应用更新';$('update-message').textContent=u.message||'';$('update-version').textContent=u.availableVersion?'v'+u.availableVersion:'v'+value.version;
 $('release-notes').hidden=!u.notes;$('release-notes').textContent=u.notes||'';
 $('progress').hidden=u.state!=='downloading';$('progress').value=u.progress||0;
 $('update-check').disabled=!u.feedConfigured||['checking','downloading','installing'].includes(u.state);
 $('update-download').hidden=u.state!=='available';$('update-install').hidden=u.state!=='ready';
 $('update-import').disabled=['checking','downloading','installing'].includes(u.state);
}
function bind(id,action,params={},message){$(id).addEventListener('click',async()=>{try{const result=await command(action,params);if(message&&result)toast(message);}catch{}});}
document.querySelectorAll('[data-page]').forEach(button=>button.addEventListener('click',()=>command('view',{page:button.dataset.page}).catch(()=>{})));
for(const id of ['quick-mcp'])$(id).addEventListener('change',()=>command($(id).checked?'start-mcp':'stop-mcp').catch(()=>{}));
for(const [id,action] of [['cloud','set-cloud'],['startup','set-startup']])$(id).addEventListener('change',()=>command(action,{enabled:$(id).checked}).catch(()=>{}));
bind('loading-settings','view',{page:'settings'});bind('quit','quit');bind('show-data','show-data');bind('export-json','export-config',{format:'json'},'已导出接入配置');bind('export-toml','export-config',{format:'toml'},'已导出接入配置');
bind('open-console','open-xiaozhi-console');bind('setup-retry','connect-xiaozhi',{endpoint:''});
$('connection-form').addEventListener('submit',async event=>{event.preventDefault();try{await command('connect-xiaozhi',{endpoint:$('endpoint').value});$('endpoint').value='';}catch{}});
$('use-local').addEventListener('click',async()=>{try{await command('use-local');toast('已关闭小智连接，本机 MCP 继续运行');}catch{}});
bind('toolbar-error','view',{page:'settings'});
bind('update-check','update-check');bind('update-download','update-download');bind('update-install','update-install');bind('update-import','update-import');
$('save-feed').addEventListener('click',()=>command('set-update-feed',{url:$('feed').value.trim()}).then(()=>toast('更新来源已保存')).catch(()=>{}));
api.onStatus(render);refresh();
