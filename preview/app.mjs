import { HOME_TILES, safeWidth } from './round-layout.mjs';
import { loadSettings, updateSettings } from './settings-model.mjs';

const $ = id => document.getElementById(id);
const storageKey = 'round-ui-preview-settings-v1';
let settings;
try { settings = loadSettings(localStorage.getItem(storageKey)); }
catch { settings = loadSettings(null); }
let selectedNetwork = '';
const names = { home:'应用首页',chat:'语音对话',weather:'天气',settings:'设置',wifi:'Wi-Fi 联网',agent:'配置智能体' };

function show(id) {
  document.querySelectorAll('.view').forEach(view => view.classList.toggle('hidden',view.id !== id));
  $('status').textContent = id === 'home' ? '点击屏幕图标，查看中文页面。' : names[id]+' · 当前为交互预览';
}
document.querySelectorAll('.app').forEach((button,index) => {
  const r = HOME_TILES[index];
  Object.assign(button.style,{left:r.x+'px',top:r.y+'px',width:r.w+'px',height:r.h+'px'});
  button.addEventListener('click',() => show(button.dataset.app));
});
document.querySelectorAll('.back').forEach(button => button.addEventListener('click',() => show(button.dataset.back || 'home')));
$('home-button').addEventListener('click',() => show('home'));
$('safe-toggle').addEventListener('click',() => {
  const visible = $('screen').classList.toggle('safe');
  $('safe-toggle').setAttribute('aria-pressed',String(visible));
  $('safe-toggle').textContent = visible ? '隐藏安全边界' : '显示安全边界';
});

function renderSettings() {
  $('volume').value = settings.volume;
  $('brightness').value = settings.brightness;
  $('volume-value').textContent = settings.volume === 0 ? '静音' : settings.volume+'%';
  $('brightness-value').textContent = settings.brightness+'%';
  $('screen').style.setProperty('--display-brightness',0.2+settings.brightness*0.008);
  $('wifi-toggle').setAttribute('aria-checked',String(settings.wifiEnabled));
  $('wifi-state').textContent = settings.wifiEnabled ? '已开启' : '已关闭';
  $('wifi-summary').textContent = !settings.wifiEnabled ? '已关闭' : selectedNetwork ? '模拟已连接' : '未连接';
  $('agent-status').textContent = selectedNetwork && settings.wifiEnabled ? '等待设备上的真实验证码' : '请先连接 Wi-Fi';
  $('network-state').textContent = !settings.wifiEnabled ? '无线网络已关闭' : selectedNetwork ? '模拟已连接：'+selectedNetwork : '选择示例网络，体验连接流程';
  document.querySelectorAll('.network').forEach(button => {
    button.disabled = !settings.wifiEnabled;
    button.setAttribute('aria-pressed',String(button.dataset.network === selectedNetwork));
    button.querySelector('.network-mark').textContent = button.dataset.network === selectedNetwork ? '✓' : '›';
  });
}
function saveSettings(patch) {
  settings = updateSettings(settings,patch);
  if (!settings.wifiEnabled) selectedNetwork = '';
  try { localStorage.setItem(storageKey,JSON.stringify(settings)); } catch {}
  renderSettings();
}
$('open-wifi').addEventListener('click',() => show('wifi'));
$('open-agent').addEventListener('click',() => show('agent'));
$('wifi-toggle').addEventListener('click',() => saveSettings({wifiEnabled:!settings.wifiEnabled}));
document.querySelectorAll('.network').forEach(button => button.addEventListener('click',() => {
  if (!settings.wifiEnabled) return;
  selectedNetwork = button.dataset.network;
  renderSettings();
}));
for (const key of ['volume','brightness']) $(key).addEventListener('input',event => saveSettings({[key]:Number(event.target.value)}));
renderSettings();

function clock() { $('clock').textContent = new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false}); }
clock(); setInterval(clock,10000);
new ResizeObserver(() => $('device').style.setProperty('--scale',Math.min(1,($('stage').clientWidth-8)/508))).observe($('stage'));
document.querySelectorAll('.caption,.page-title,.subtitle').forEach(el => {
  const y=el.classList.contains('caption')?371:el.classList.contains('page-title')?65:108;
  el.style.maxWidth=safeWidth(y,el.classList.contains('page-title')?40:23)+'px';
});
document.addEventListener('keydown',event => { if(event.key==='Escape') show('home'); });
