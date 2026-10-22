'use strict';
const $=id=>document.getElementById(id);
const labels={archive_status:'档案状态',archive_record:'保存档案',archive_update:'更新档案',archive_list:'列出档案',archive_get:'档案详情',archive_search:'搜索记忆',archive_history:'修改历史',archive_backup:'备份档案',archive_retry_index:'重试索引',planner_get_context:'当前时间',planner_create:'新建计划',planner_list:'计划列表',planner_get:'计划详情',planner_delivery:'提醒同步状态',planner_update:'修改计划',planner_complete:'完成计划',planner_cancel:'取消计划',planner_snooze:'稍后提醒',worldtime_now:'当地时间',worldtime_convert:'时区换算'};
let csrf='',pending=false,loading=false,generation=0,lastState=null,selected=null,lastJob='';
const packageRows=new Map(),catalogRows=new Map();
function el(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}
function toolList(names){const list=el('div',undefined,'tool-list');for(const name of names){const item=el('div',undefined,'tool-entry');item.append(el('span',labels[name]||'工具'),el('code',name));list.append(item);}return list;}
async function api(path,body){const response=await fetch(path,{cache:'no-store',...(body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)}:{})});if(!response.ok)throw Error(response.status===403?'会话已过期，请刷新页面。':response.status===409?'另一个操作正在执行。':'操作未完成，请刷新状态。');return response.json();}
function view(name){for(const key of ['mine','market']){$(key+'Pane').hidden=key!==name;$(key+'Tab').setAttribute('aria-selected',String(key===name));$(key+'Tab').tabIndex=key===name?0:-1;}location.hash=name==='market'?'market':'mine';}
for(const name of ['mine','market']){$(name+'Tab').onclick=()=>view(name);$(name+'Tab').onkeydown=event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?'mine':event.key==='End'?'market':name==='mine'?'market':'mine';view(next);$(next+'Tab').focus();}};}
function showDetails(ident){
  selected=ident;const item=lastState.catalog.find(item=>item.id===ident);if(!item)return;
  $('detailTitle').textContent=item.name;$('detailDescription').textContent=item.description;$('detailSetup').textContent=item.setup;
  $('detailMeta').replaceChildren();for(const [key,value] of [['来源',item.source],['作者',item.author],['版本',item.version],['许可',item.license]]){const pair=el('div');pair.append(el('span',key),el('strong',value));$('detailMeta').append(pair);}
  $('detailTools').replaceChildren(...toolList(item.tools).children);
  $('detailSource').hidden=!item.url;if(item.url)$('detailSource').href=item.url;
  $('detailAction').textContent=item.installed?'查看我的能力':'安装';$('detailAction').disabled=pending||lastState.busy;
  $('removePackage').hidden=item.builtin||!item.installed;$('removePackage').disabled=pending||lastState.busy;
  if(!$('detail').open)$('detail').showModal();
}
$('closeDetail').onclick=()=>$('detail').close();
$('detailAction').onclick=()=>{const item=lastState.catalog.find(item=>item.id===selected);$('detail').close();if(item.installed)view('mine');else install(item.id);};
$('removePackage').onclick=()=>{const item=lastState.catalog.find(item=>item.id===selected);$('detail').close();perform('api/remove',{package:item.id},'正在移除'+item.name+'…',item.name+'已移除');};
function filterCatalog(){const query=$('marketSearch').value.trim().toLowerCase();let count=0;for(const item of lastState?.catalog||[]){const row=catalogRows.get(item.id);const match=(item.name+' '+item.description+' '+item.source).toLowerCase().includes(query);row.card.hidden=!match;if(match)count++;}$('marketEmpty').hidden=count>0;}
$('marketSearch').oninput=filterCatalog;
function renderCatalog(state){
  for(const item of state.catalog){let entry=catalogRows.get(item.id);if(!entry){const card=el('article',undefined,'ability-card'),top=el('div',undefined,'card-top'),mark=el('span',({archive:'◧',planner:'◷',worldtime:'◴'})[item.id],'ability-mark'),badge=el('span','已适配','adapted-badge');top.append(mark,badge);const title=el('h2',item.name),description=el('p',item.description,'card-description'),source=el('p','来源 · '+item.source,'card-source'),footer=el('div',undefined,'card-footer'),more=el('button','详情','text-button'),action=el('button');more.onclick=()=>showDetails(item.id);action.onclick=()=>{if(lastState.catalog.find(group=>group.id===item.id).installed)view('mine');else showDetails(item.id);};footer.append(more,action);card.append(top,title,description,source,footer);$('catalog').append(card);entry={card,action};catalogRows.set(item.id,entry);}entry.action.textContent=item.installed?'管理':'安装';entry.action.className=item.installed?'':'primary-button';entry.action.disabled=pending||state.busy;}
  filterCatalog();
}
function renderPackages(state){
  const ids=new Set(state.packages.map(item=>item.id));for(const [id,entry] of packageRows){if(!ids.has(id)){entry.row.remove();packageRows.delete(id);}}
  for(const group of state.packages){let entry=packageRows.get(group.id);if(!entry){const row=el('article',undefined,'package-row'),head=el('div',undefined,'package-head'),copy=el('div',undefined,'package-copy');copy.append(el('h3',group.name),el('p',group.description),el('span','来源 · '+group.source,'package-source'));const control=el('div',undefined,'package-control'),label=el('span',undefined,'package-label'),toggle=el('button',undefined,'package-switch');toggle.type='button';toggle.setAttribute('role','switch');toggle.setAttribute('aria-label',group.name);toggle.append(el('span',undefined,'switch-knob'));toggle.onclick=()=>setPackage(group.id,toggle.getAttribute('aria-checked')!=='true',group.name);control.append(label,toggle);head.append(copy,control);row.append(head);const details=el('details',undefined,'package-tools');details.append(el('summary',group.tools.length+' 个工具'),toolList(group.tools));const more=el('button','详情','package-detail text-button');more.onclick=()=>showDetails(group.id);row.append(details,more);$('packages').append(row);entry={row,toggle,label};packageRows.set(group.id,entry);}entry.toggle.setAttribute('aria-checked',String(group.enabled));entry.toggle.disabled=pending||state.busy||state.probe_error;entry.label.textContent=group.enabled?'已开启':'已关闭';}
  for(const group of state.packages){if(group.external){const entry=packageRows.get(group.id);entry.label.textContent='圆盘内置';entry.toggle.hidden=true;entry.toggle.disabled=true;const tools=entry.row.querySelector('details');if(tools)tools.hidden=true;}}
}
function render(state){
  lastState=state;
  $('processState').textContent=state.probe_error?'无法确认':state.running?'运行中':'已停止';
  const elapsed=state.started_utc?Math.max(0,Math.floor((Date.now()-Date.parse(state.started_utc))/60000)):0;
  $('processMeta').textContent=state.desktop_managed?'由桌面应用管理':state.running?'PID '+state.process_id+' · '+(elapsed<1?'刚刚启动':'已运行 '+elapsed+' 分钟'):'';
  $('connectionState').textContent=({connected:'已连接',connecting:'连接中',stopped:'未连接',unknown:'无法确认'})[state.connection]||'无法确认';
  $('connectionMeta').textContent=state.connection==='connected'?(state.tool_count?'工具可供小智调用':state.packages.some(group=>group.enabled)?'等待工具注册':'功能包均已关闭'):state.desktop_managed&&!state.cloud_configured?'待配置小智接入点':state.desktop_managed&&!state.cloud_enabled?'小智连接已暂停':state.running?'等待云端连接':'';
  $('toolCount').textContent=state.tool_count;$('toolMeta').textContent=state.connection==='connected'?'已注册':state.tool_count?'上次注册':'';
  $('start').hidden=state.running;$('restart').hidden=!state.running;$('stop').hidden=!state.running;
  if(state.desktop_managed)for(const id of ['start','stop','restart'])$(id).hidden=true;
  $('desktopControlHint').hidden=!state.desktop_managed;
  for(const id of ['start','stop','restart'])$(id).disabled=pending||state.busy||state.probe_error;
  renderPackages(state);renderCatalog(state);
  if(state.packages_error)$('notice').textContent='功能包配置无法读取，工具暂时关闭。请重新选择开关。';
  const job=state.installation;if(job){const key=job.id+job.state+job.message;if(key!==lastJob){lastJob=key;$('notice').textContent=job.state==='success'&&state.packages.some(item=>item.id===job.package&&item.enabled)?'世界时间已安装并开启。':job.message;}}
  if($('detail').open){$('detailAction').disabled=pending||state.busy;$('removePackage').disabled=pending||state.busy;}
  $('calls').replaceChildren();const results={success:'成功',error:'失败',interrupted:'中断',running:'进行中',unknown:'未知'};
  for(const call of state.calls){const row=el('tr'),date=call.at?new Date(call.at):null,time=el('td',date?date.toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—');if(date)time.title=date.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});row.append(time);const name=el('td',call.tool);name.title=labels[call.tool]||call.tool;row.append(name);const result=el('td');result.append(el('span',results[call.status]||'未知','result '+call.status));row.append(result,el('td',call.duration_ms===null?'—':call.duration_ms<1000?call.duration_ms+' ms':(call.duration_ms/1000).toFixed(2)+' s'));$('calls').append(row);}
  if(!state.calls.length){const row=el('tr'),cell=el('td','暂无调用记录','empty');cell.colSpan=4;row.append(cell);$('calls').append(row);}
}
async function refresh(){if(loading||pending)return;loading=true;const current=++generation;try{const state=await api('api/status');if(current===generation)render(state);}catch(error){$('notice').textContent=error.message;}finally{loading=false;}}
async function perform(path,body,working,done){if(pending)return;pending=true;++generation;for(const id of ['start','stop','restart'])$(id).disabled=true;for(const entry of packageRows.values())entry.toggle.disabled=true;for(const entry of catalogRows.values())entry.action.disabled=true;$('notice').textContent=working;try{const state=await api(path,body);pending=false;render(state);if(done)$('notice').textContent=done;}catch(error){$('notice').textContent=error.message;}finally{pending=false;await refresh();}}
async function command(action){await perform('api/command',{action},({start:'正在启动…',stop:'正在停止…',restart:'正在重启…'})[action],({start:'已启动',stop:'已停止',restart:'已重启'})[action]);}
async function setPackage(ident,enabled,name){await perform('api/packages',{package:ident,enabled},'正在'+(enabled?'开启':'关闭')+name+'…',name+(enabled?'已开启':'已关闭'));}
async function install(ident){await perform('api/install',{package:ident},'正在准备安装…','');}
for(const action of ['start','stop','restart'])$(action).onclick=()=>command(action);$('refresh').onclick=refresh;
view(location.hash==='#market'?'market':'mine');
(async()=>{try{csrf=(await api('api/session')).csrf;await refresh();setInterval(()=>{if(!document.hidden)refresh();},5000);}catch(error){$('notice').textContent=error.message;}})();
