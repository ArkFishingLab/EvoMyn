const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class Element {
  constructor() { this.children=[];this.value='';this.textContent='';this.selected=false;this.open=false;this.classList={toggle(){}}; }
  append(e) { this.children.push(e); }
  replaceChildren() { this.children=[]; }
  get selectedOptions() { return this.children.filter(e=>e.selected); }
  showModal() { this.open=true; }
  close() { this.open=false; }
}
const elements=new Map();
const element=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const sent=[],requests=[],confirmations=[];
let idCounter=0,failNextWrite=false,pendingWrite=null;
const context=vm.createContext({window:{confirm(message){confirmations.push(message);return true;}},document:{getElementById:element,querySelectorAll:()=>[],createElement:()=>new Element()},crypto:{randomUUID:()=> 'test-id-'+(++idCounter)},setInterval(){},console,Date,Set,Map,Array,fetch:async(url,options)=>{
  requests.push(url);
  if(options?.body){const body=JSON.parse(options.body);sent.push(body);if(failNextWrite){failNextWrite=false;throw Error('response lost after server commit');}if(pendingWrite)await pendingWrite;return {ok:true,json:async()=>({id:'test',...body})};}
  if(url.startsWith('api/delivery?'))return {ok:true,json:async()=>({current_occurrence_id:url.includes('chosen_date=')?'chosen-real-instance':'current-real-instance',current_occurrence_date:url.includes('chosen_date=')?'2026-10-18':'2026-10-17',next_occurrence_id:'tomorrow-instance'})};
  return {ok:true,json:async()=>url==='api/session'?{csrf:'token'}:url==='api/archive-choices'?{records:[{id:'archive1',title:'<script>literal</script>'}]}:{tasks:[],local_date:'2026-10-16'}};
}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../vendor/planner_web/app.js'),'utf8'),context);
(async()=>{
  await new Promise(setImmediate);
  element('status').value='pending';
  vm.runInContext("tasks=[{id:'a',title:'First',body:'Needle in body',kind:'task',status:'pending',repeat:'none'},{id:'b',title:'Second',body:'Other',kind:'task',status:'pending',repeat:'none'}]",context);
  element('search').value='needle';vm.runInContext('render()',context);
  assert.equal(element('tasks').children.length,1);
  assert.equal(element('tasks').children[0].children[0].children[0].textContent,'First');
  await vm.runInContext("open({id:'a',title:'Linked',body:'',kind:'task',repeat:'none',revision:1,archive_links:['archive1']})",context);
  assert.equal(element('form-error').textContent,'');
  assert.equal(element('archive-links').selectedOptions[0].value,'archive1');
  assert.equal(element('archive-links').children[0].textContent,'<script>literal</script> · archive1');
  await element('form').onsubmit({preventDefault(){}});
  assert.deepEqual(sent[0].changes.archive_links,['archive1']);
  // If choices cannot be loaded or an ID was removed externally, preserve the
  // existing selection until the user explicitly removes it.
  vm.runInContext("archiveChoices=[];renderArchiveLinks(['archive-existing'])",context);
  assert.equal(element('archive-links').selectedOptions[0]?.value,'archive-existing');
  element('search').value='';
  vm.runInContext("tasks=[{id:'daily',title:'Daily',body:'',kind:'task',status:'pending',repeat:'daily',revision:1}];render()",context);
  assert.equal(element('tasks').children[0].children[1].children[1].textContent,'选择本次完成日期');
  await vm.runInContext("mutate('complete',tasks[0])",context);
  assert.equal(sent.at(-1).op,'complete');
  assert.equal(sent.at(-1).occurrence_id,'current-real-instance');
  assert.ok(confirmations[0].includes('2026-10-17'));
  element('day').value='2026-10-18';
  vm.runInContext("view='day';tasks=[{id:'daily',title:'Daily',body:'',kind:'task',status:'pending',due_at:1792166400,repeat:'daily',revision:1}];render()",context);
  assert.equal(element('tasks').children[0].children[1].children[1].textContent,'完成2026-10-18本次');
  await vm.runInContext("mutate('complete',tasks[0])",context);
  assert.ok(requests.some(url=>url.includes('chosen_date=2026-10-18')));
  assert.equal(sent.at(-1).occurrence_id,'chosen-real-instance');
  await vm.runInContext('open()',context);element('title').value='Retry same draft';
  failNextWrite=true;await element('form').onsubmit({preventDefault(){}});const failedId=sent.at(-1).request_id;
  await element('form').onsubmit({preventDefault(){}});assert.equal(sent.at(-1).request_id,failedId);
  await vm.runInContext('open()',context);element('title').value='Change draft';
  failNextWrite=true;await element('form').onsubmit({preventDefault(){}});const changedId=sent.at(-1).request_id;
  element('title').value='Changed content';await element('form').onsubmit({preventDefault(){}});assert.notEqual(sent.at(-1).request_id,changedId);
  await vm.runInContext('open()',context);element('title').value='Explicit new draft';
  failNextWrite=true;await element('form').onsubmit({preventDefault(){}});const abandonedId=sent.at(-1).request_id;
  await vm.runInContext('open()',context);element('title').value='Explicit new draft';await element('form').onsubmit({preventDefault(){}});assert.notEqual(sent.at(-1).request_id,abandonedId);
  let release;pendingWrite=new Promise(resolve=>{release=resolve;});
  await vm.runInContext('open()',context);element('title').value='No double submit';const countBefore=sent.length;
  const firstSubmit=element('form').onsubmit({preventDefault(){}});await element('form').onsubmit({preventDefault(){}});assert.equal(sent.length,countBefore+1);release();pendingWrite=null;await firstSubmit;
  const daily="{id:'daily',title:'Daily',body:'',kind:'task',status:'pending',repeat:'daily',revision:1}";
  failNextWrite=true;await vm.runInContext("mutate('complete',"+daily+")",context);const failedAction=sent.at(-1);const reads=requests.filter(url=>url.startsWith('api/delivery?')).length;
  await vm.runInContext("mutate('complete',"+daily+")",context);assert.equal(sent.at(-1).request_id,failedAction.request_id);assert.equal(sent.at(-1).occurrence_id,failedAction.occurrence_id);assert.equal(requests.filter(url=>url.startsWith('api/delivery?')).length,reads);
  console.log('planner web: search, links, exact-date completion, durable retry IDs and double-submit guards passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
