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
function applySettings(data){version=data.version;el('maxGain').value=data.values.max_gain_pct;el('minPrice').value=data.values.min_price;el('maxPrice').value=data.values.max_price;el('version').textContent='設定版本 '+version;}
async function session(){const s=await api('session');csrf=s.csrf;el('identity').textContent=s.email;return s;}
async function enter(){await session();applySettings(await api('settings'));await reloadConversations();el('login').hidden=true;el('workspace').hidden=false;}
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
  const values={min_price:Number(el('minPrice').value),max_price:Number(el('maxPrice').value),max_gain_pct:Number(el('maxGain').value)};
  if(values.min_price>values.max_price){message('saveStatus','最低股價不得超過最高股價。',true);return;}
  el('save').disabled=true;message('saveStatus','正在儲存…');
  try{applySettings(await api('settings',{method:'PUT',body:{values,version}}));message('saveStatus','已儲存。之後的新推薦會讀取這份設定。');}
  catch(error){message('saveStatus',error.message,true);}finally{el('save').disabled=false;}
};
el('reload').onclick=async()=>{try{applySettings(await api('settings'));message('saveStatus','已載入最新設定。');}catch(e){message('saveStatus',e.message,true);}};
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
    form.append(title,name,push.wrap);if(row.platform==='line')form.append(replies.wrap);
    if(row.platform==='telegram'&&!row.configured){push.input.disabled=true;const note=document.createElement('p');note.textContent='尚未設定 Bot 憑證與群組。';form.append(note);save.disabled=true;}
    save.type='submit';save.textContent='儲存 '+title.textContent;form.append(save);form.style.padding='0 0 24px';
    form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{const body={push:push.input.checked,version:row.version};if(row.platform==='line')body.replies=replies.input.checked;applyConversations(await api('notification-groups/'+row.platform+'/'+encodeURIComponent(row.id),{method:'PUT',body}));message('conversationStatus','已儲存，下一次事件立即生效。');}catch(e){message('conversationStatus',e.message,true);}finally{save.disabled=false;}};
    el('conversationList').append(form);
  }
  if(!data.groups.some(r=>r.platform==='line'&&r.kind==='group')){const note=document.createElement('p');note.textContent='尚無已核准的 LINE 群組。';el('conversationList').append(note);}
  el('deliveryStatus').replaceChildren();
  const labels={sent:'送出成功',failed:'送出失敗',unknown:'結果不明（不重送）',pending:'處理中／中斷未確認',disabled:'已關閉'};
  for(const row of data.deliveries||[]){const p=document.createElement('p');p.textContent=`${row.channel==='line'?'LINE':'Telegram'} · ${labels[row.status]||'未知狀態'} · ${new Date(row.at*1000).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}`;el('deliveryStatus').append(p);}
  if(!data.deliveries?.length)el('deliveryStatus').textContent='尚無通知紀錄。';
}
async function reloadConversations(){applyConversations(await api('notification-groups'));}
el('reloadLine').onclick=async()=>{try{await reloadConversations();message('conversationStatus','已載入最新設定。');}catch(e){message('conversationStatus',e.message,true);}};
(async()=>{try{await enter();}catch{await loginSetup();}})();
