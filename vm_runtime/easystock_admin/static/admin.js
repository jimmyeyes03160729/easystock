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
async function session(){const s=await api('session');csrf=s.csrf;el('identity').textContent=s.email;el('lineStatus').textContent=s.line_linked?'已綁定管理員 LINE':'尚未綁定';el('unlink').hidden=!s.line_linked;if(s.line_linked)el('bindBox').hidden=true;return s;}
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
el('bind').onclick=async()=>{el('bind').disabled=true;try{const data=await api('line-bind',{method:'POST',body:{}});el('bindCode').textContent='綁定管理員 '+data.code;el('bindBox').hidden=false;message('lineMessage','新綁定碼有效五分鐘，舊碼已失效。');}catch(e){message('lineMessage',e.message,true);}finally{el('bind').disabled=false;}};
el('copy').onclick=async()=>{try{await navigator.clipboard.writeText(el('bindCode').textContent);message('lineMessage','已複製，請私訊機器人。');}catch{message('lineMessage','無法自動複製，請手動選取上方指令。',true);}};
el('checkBind').onclick=async()=>{try{const s=await session();message('lineMessage',s.line_linked?'已完成綁定。':'尚未完成，請確認已私訊機器人。');}catch(e){message('lineMessage',e.message,true);}};
el('unlink').onclick=async()=>{try{await api('line-unlink',{method:'POST',body:{}});await session();message('lineMessage','已解除 LINE 管理權限。');}catch(e){message('lineMessage',e.message,true);}};
let lineVersion=null;
el('checkUsage').onclick=async()=>{el('checkUsage').disabled=true;try{const s=await api('line-usage');message('lineUsage',`本月已用 ${s.used} / ${s.limit??'無上限'} 則，剩餘 ${s.remaining??'無上限'} 則。群組主動推播按接收人數計算，查詢回覆不扣額度。`);}catch(e){message('lineUsage',e.message,true);}finally{el('checkUsage').disabled=false;}};
const lineLabels={replies:'啟用指令回覆（總開關）',groups:'群組／聊天室指令回覆',users:'個人私訊指令回覆',trade_push:'進出場即時推播',other_push:'其他自動推播（盤前／盤後等，預設關閉）'};
function checkbox(label,checked){const wrap=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.checked=!!checked;wrap.append(input,document.createTextNode(' '+label));wrap.style.display='block';wrap.style.margin='12px 0';input.style.width='auto';return {wrap,input};}
function applyConversations(data){
  lineVersion=data.version;el('lineSwitches').replaceChildren();
  for(const [key,label] of Object.entries(lineLabels)){const c=checkbox(label,data.values[key]);c.input.dataset.policy=key;el('lineSwitches').append(c.wrap);}
  el('conversationList').replaceChildren();
  for(const row of data.conversations){
    const form=document.createElement('form'),title=document.createElement('label'),name=document.createElement('input'),save=document.createElement('button');
    title.textContent=(row.kind==='user'?'個人':'群組／聊天室')+'名稱';name.value=row.label;name.maxLength=80;name.required=true;title.append(name);
    const replies=checkbox('允許指令回覆',row.replies),push=checkbox('允許主動推播',row.push);
    save.type='submit';save.textContent='儲存此對話';form.append(title,replies.wrap,push.wrap,save);form.style.borderTop='1px solid var(--border)';form.style.padding='16px 0';
    form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{applyConversations(await api('line-conversations/'+encodeURIComponent(row.id),{method:'PUT',body:{label:name.value,replies:replies.input.checked,push:push.input.checked,version:row.version}}));message('conversationStatus','已儲存，下一次事件立即生效。');}catch(e){message('conversationStatus',e.message,true);}finally{save.disabled=false;}};
    el('conversationList').append(form);
  }
  if(!data.conversations.length)el('conversationList').textContent='尚無已登記的對話。';
}
async function reloadConversations(){applyConversations(await api('line-policy'));}
el('reloadLine').onclick=async()=>{try{await reloadConversations();message('conversationStatus','已載入最新設定。');}catch(e){message('conversationStatus',e.message,true);}};
el('linePolicyForm').onsubmit=async event=>{event.preventDefault();if(lineVersion===null)return;el('saveLine').disabled=true;try{const values={};for(const input of el('lineSwitches').querySelectorAll('input'))values[input.dataset.policy]=input.checked;applyConversations(await api('line-policy',{method:'PUT',body:{values,version:lineVersion}}));message('conversationStatus','LINE 開關已儲存。');}catch(e){message('conversationStatus',e.message,true);}finally{el('saveLine').disabled=false;}};
(async()=>{try{await enter();}catch{await loginSetup();}})();
