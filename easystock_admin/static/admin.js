'use strict';
const el=id=>document.getElementById(id);
let csrf='',version=null;
function message(id,text,error=false){el(id).textContent=text;el(id).classList.toggle('error',error);}
async function api(path,{method='GET',body}={}){
  const response=await fetch('/admin/'+path,{method,credentials:'same-origin',headers:{...(body!==undefined?{'Content-Type':'application/json'}:{}),...(csrf?{'X-CSRF-Token':csrf}:{})},...(body!==undefined?{body:JSON.stringify(body)}:{})});
  const data=await response.json();
  if(!response.ok)throw new Error(data.error||'登入已失效，請重新登入。');
  return data;
}
function applySettings(data){version=data.version;el('maxGain').value=data.values.max_gain_pct;el('maxRecommendations').value=data.values.max_recommendations;el('minPrice').value=data.values.min_price;el('maxPrice').value=data.values.max_price;el('version').textContent='設定版本 '+version;}
function showAdminTab(id){
  const panels=[...document.querySelectorAll('.admin-tab-panel')];
  if(!panels.some(panel=>panel.id===id))id='healthPanel';
  for(const panel of panels)panel.hidden=panel.id!==id;
  for(const button of document.querySelectorAll('[data-admin-tab]'))button.setAttribute('aria-selected',String(button.dataset.adminTab===id));
}
const healthLabels={ok:'正常',warning:'注意',error:'異常',idle:'等待'};
function healthMetric(label,value){if(value===null||value===undefined)return null;const node=document.createElement('span');node.textContent=`${label} ${Number(value).toLocaleString('zh-TW')}`;return node;}
function renderHealth(data){
  const rows=Array.isArray(data.signals)?data.signals:[];const target=el('healthSignals');target.replaceChildren();
  const counts=rows.reduce((out,row)=>{out[row.state]=(out[row.state]||0)+1;return out;},{});
  el('healthSummary').textContent=`最後檢查：${new Date(data.generated_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})} · 正常 ${counts.ok||0} · 注意 ${counts.warning||0} · 異常 ${counts.error||0} · 等待 ${counts.idle||0}`;
  for(const row of rows){
    const card=document.createElement('article');card.className=`health-card health-${row.state||'idle'}`;
    const head=document.createElement('div');head.className='health-card-head';
    const title=document.createElement('h3');title.textContent=row.label||'未命名檢查';
    const badge=document.createElement('span');badge.className='health-badge';badge.textContent=healthLabels[row.state]||'未知';head.append(title,badge);
    const detail=document.createElement('p');detail.textContent=row.detail||'沒有附加說明。';card.append(head,detail);
    const metrics=document.createElement('div');metrics.className='health-metrics';
    const names={setting_version:'設定版本',samples:'樣本',labeled:'已標記',candidate_count:'候選數',completed_stock_days:'完成股票日',target_stock_days:'目標股票日',failed_stock_days:'失敗股票日'};
    for(const [key,value] of Object.entries(row.metrics||{})){const metric=healthMetric(names[key]||key,value);if(metric)metrics.append(metric);}
    if(row.updated_at){const updated=document.createElement('span');updated.textContent=`更新 ${new Date(row.updated_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}`;metrics.append(updated);}
    if(metrics.childNodes.length)card.append(metrics);target.append(card);
  }
  if(!rows.length)target.textContent='尚未收到檢測資料。';
}
async function loadHealth(){try{renderHealth(await api('health'));}catch(error){el('healthSummary').textContent=error.message;el('healthSignals').replaceChildren();}}
async function loadMaintenance(){try{const data=await api('maintenance');const parts=[];for(const [key,value] of Object.entries(data)){if(key!=='available'&&key!=='detail')parts.push(`${key}: ${value}`);}message('maintenanceStatus',data.detail||parts.join(' · ')||'維護狀態未知',!data.available);for(const id of ['restartIntraday','syncVm'])el(id).disabled=!data.available;}catch(error){message('maintenanceStatus',error.message,true);}}
async function maintenance(action,confirmation,label){if(!confirm(`確認要${label}嗎？\n此操作會受到時段、工作衝突與冷卻限制。`))return;const id=action==='restart-intraday'?'restartIntraday':'syncVm';const button=el(id);button.disabled=true;message('maintenanceStatus','正在送出受控維護要求…');try{const result=await api('maintenance/'+action,{method:'POST',body:{confirmation}});message('maintenanceStatus',result.detail||'操作已送出。',!result.available);}catch(error){message('maintenanceStatus',error.message,true);}finally{await loadMaintenance();}}
async function session(){const s=await api('session');csrf=s.csrf;el('identity').textContent=s.email;return s;}
async function enter(){await session();applySettings(await api('settings'));await reloadConversations();try{await loadBotPolicy();}catch(_){}el('login').hidden=true;el('workspace').hidden=false;await loadHealth();await loadMaintenance();}
async function loginSetup(){
  try{
    const config=await api('config');
    if(!config.ready){message('loginStatus','管理員登入尚未設定完成，請先完成 Google 登入設定。');return;}
    if(!window.google?.accounts?.id)throw new Error('Google 登入元件無法載入，請檢查網路後重試。');
    const challenge=await api('challenge',{method:'POST',body:{}});
    google.accounts.id.initialize({client_id:config.client_id,nonce:challenge.nonce,auto_select:false,callback:async response=>{
      message('loginStatus','正在驗證帳號…');
      try{const result=await api('login',{method:'POST',body:{credential:response.credential}});csrf=result.csrf;await enter();}
      catch(error){message('loginStatus',error.message,true);el('retryLogin').hidden=false;}
    }});
    el('googleButton').replaceChildren();
    google.accounts.id.renderButton(el('googleButton'),{type:'standard',theme:'outline',size:'large',text:'signin_with',locale:'zh_TW'});
    message('loginStatus','僅限已授權的管理員帳號。');
  }catch(error){message('loginStatus',error.message,true);el('retryLogin').hidden=false;}
}
el('retryLogin').onclick=()=>location.reload();
el('theme').onclick=()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;try{localStorage.setItem('easystock-admin-theme',theme);}catch{}};
try{if(localStorage.getItem('easystock-admin-theme')==='light')document.documentElement.dataset.theme='light';}catch{}
el('settingsForm').onsubmit=async event=>{
  event.preventDefault();if(version===null)return;
  const values={min_price:Number(el('minPrice').value),max_price:Number(el('maxPrice').value),max_gain_pct:Number(el('maxGain').value),max_recommendations:Number(el('maxRecommendations').value)};
  if(values.min_price>values.max_price){message('saveStatus','最低股價不得超過最高股價。',true);return;}
  if(!Number.isInteger(values.max_recommendations)||values.max_recommendations<1||values.max_recommendations>30){message('saveStatus','推薦股票上限數量須為 1 至 30 的整數。',true);return;}
  el('save').disabled=true;message('saveStatus','正在儲存…');
  try{applySettings(await api('settings',{method:'PUT',body:{values,version}}));message('saveStatus','已儲存。之後的新推薦會讀取這份設定。');}
  catch(error){message('saveStatus',error.message,true);}finally{el('save').disabled=false;}
};
el('reload').onclick=async()=>{try{applySettings(await api('settings'));message('saveStatus','已載入最新設定。');}catch(e){message('saveStatus',e.message,true);}};
el('reloadHealth').onclick=async()=>{const button=el('reloadHealth');button.disabled=true;try{await loadHealth();}finally{button.disabled=false;}};
el('restartIntraday').onclick=()=>maintenance('restart-intraday','RESTART_INTRADAY','重啟當沖');
el('syncVm').onclick=()=>maintenance('sync-vm','SYNC_VM','同步 VM');
for(const button of document.querySelectorAll('[data-admin-tab]'))button.onclick=()=>showAdminTab(button.dataset.adminTab);
el('logout').onclick=async()=>{try{await api('logout',{method:'POST',body:{}});location.reload();}catch(e){message('saveStatus',e.message,true);}};
el('checkUsage').onclick=async()=>{el('checkUsage').disabled=true;try{const s=await api('line-usage');message('lineUsage',`本月已用 ${s.used} / ${s.limit??'無上限'} 則，剩餘 ${s.remaining??'無上限'} 則。群組主動推播按接收人數計算，查詢回覆不扣額度。`);}catch(e){message('lineUsage',e.message,true);}finally{el('checkUsage').disabled=false;}};
function checkbox(label,checked){const wrap=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.checked=!!checked;wrap.append(input,document.createTextNode(' '+label));wrap.style.display='block';wrap.style.margin='12px 0';input.style.width='auto';return {wrap,input};}
function applyConversations(data){
  el('conversationList').replaceChildren();
  for(const row of data.groups.filter(r=>r.kind==='group')){
    const form=document.createElement('form'),title=document.createElement('h3'),name=document.createElement('p'),save=document.createElement('button');
    title.textContent=row.platform==='line'?'LINE':'Telegram';name.textContent=row.label;
    const replies=checkbox('群組查詢回覆',row.replies),push=checkbox('進出場通知',row.push);
    push.input.dataset.platform=row.platform;push.input.dataset.control='push';replies.input.dataset.control='replies';
    form.append(title,name,push.wrap,replies.wrap);
    if(row.platform==='telegram'&&!row.configured){push.input.disabled=true;replies.input.disabled=true;const note=document.createElement('p');note.textContent='尚未設定 Bot 憑證與群組。';form.append(note);save.disabled=true;}
    save.type='submit';save.textContent='儲存 '+title.textContent;form.append(save);form.style.padding='0 0 24px';
    form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{const body={push:push.input.checked,replies:replies.input.checked,version:row.version};applyConversations(await api('notification-groups/'+row.platform+'/'+encodeURIComponent(row.id),{method:'PUT',body}));message('conversationStatus','已儲存，下一次事件立即生效。');}catch(e){message('conversationStatus',e.message,true);}finally{save.disabled=false;}};
    el('conversationList').append(form);
  }
  if(!data.groups.some(r=>r.platform==='line'&&r.kind==='group')){const note=document.createElement('p');note.textContent='尚無已核准的 LINE 群組。';el('conversationList').append(note);}
  el('deliveryStatus').replaceChildren();
  const labels={sent:'送出成功',failed:'送出失敗',unknown:'結果不明（不重送）',pending:'處理中／中斷未確認',disabled:'已關閉'};
  for(const row of data.deliveries||[]){const p=document.createElement('p');p.textContent=`${row.channel==='line'?'LINE':'Telegram'} · ${labels[row.status]||'未知狀態'} · ${new Date(row.at*1000).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}`;el('deliveryStatus').append(p);}
  if(!data.deliveries?.length)el('deliveryStatus').textContent='尚無通知紀錄。';
}
let botPolicyVersion=1;
async function loadBotPolicy(){
  try{
    const p=await api('bot-policy');
    if(p&&p.auto_reply_on_follow!==undefined){
      if(el('autoReplyToggle'))el('autoReplyToggle').checked=!!p.auto_reply_on_follow;
      botPolicyVersion=p.version||1;
    }
  }catch(_){}
}
if(el('saveBotPolicy')){
  el('saveBotPolicy').onclick=async()=>{
    const btn=el('saveBotPolicy');btn.disabled=true;message('botPolicyStatus','正在儲存…');
    try{
      const auto_reply_on_follow=!!el('autoReplyToggle')?.checked;
      const res=await api('bot-policy',{method:'PUT',body:{auto_reply_on_follow,version:botPolicyVersion}});
      botPolicyVersion=res.version;
      message('botPolicyStatus','已儲存！'+(auto_reply_on_follow?'已啟用加入好友自動回覆':'已關閉加入好友自動回覆'));
    }catch(e){message('botPolicyStatus',e.message,true);}finally{btn.disabled=false;}
  };
}
async function reloadConversations(){applyConversations(await api('notification-groups'));try{await loadBotPolicy();}catch(_){}}
el('reloadLine').onclick=async()=>{try{await reloadConversations();message('conversationStatus','已載入最新設定。');}catch(e){message('conversationStatus',e.message,true);}};
(async()=>{try{await enter();showAdminTab('healthPanel');}catch{await loginSetup();}})();
