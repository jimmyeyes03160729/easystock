'use strict';
const el=id=>document.getElementById(id);
let csrf='',version=null,liveRefreshTimer=0;
let pipelineVersion=null;
let modelLogPage=1;
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
  if(id==='modelLogPanel')loadModelLog();
}
const healthLabels={ok:'正常',warning:'注意',error:'異常',idle:'等待'};
function healthBadge(row){if(row.key==='paper_trade')return row.state==='ok'?'已啟用・等待交易時段':'已暫停';if(row.key==='market_session'&&row.state==='idle')return '今日休市';if(['market_credentials','firebase'].includes(row.key)&&row.state==='ok')return '已設定';if(row.key==='admin_store'&&row.state==='ok')return '可讀取';if(['training_worker','daily_learning_worker','download_worker'].includes(row.key)&&row.state==='idle')return '排程中';if(row.key==='candidate_model'&&row.state==='idle')return '尚無模型';if(row.key==='history_collection'&&row.state==='idle')return '等待時段';return healthLabels[row.state]||'未知';}
function healthMetric(label,value){if(value===null||value===undefined)return null;const node=document.createElement('span');const number=Number(value);node.textContent=`${label} ${typeof value==='number'&&Number.isFinite(number)?number.toLocaleString('zh-TW'):String(value)}`;return node;}
function runtimeFallback(reason='後端尚未提供盤中模型狀態'){return {status:'RUNTIME_UNKNOWN',reason,runtime:null,runtime_status:null,approved:null,match:false};}
function renderHealth(data){
  const rows=Array.isArray(data.signals)?data.signals:[];const target=el('healthSignals');target.replaceChildren();
  const counts=rows.reduce((out,row)=>{out[row.state]=(out[row.state]||0)+1;return out;},{});
  el('healthSummary').textContent=`最後檢查：${new Date(data.generated_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})} · 正常 ${counts.ok||0} · 注意 ${counts.warning||0} · 異常 ${counts.error||0} · 等待 ${counts.idle||0}`;
  for(const row of rows){
    const card=document.createElement('article');card.className=`health-card health-${row.state||'idle'}`;
    const head=document.createElement('div');head.className='health-card-head';
    const title=document.createElement('h3');title.textContent=row.label||'未命名檢查';
    const badge=document.createElement('span');badge.className='health-badge';badge.textContent=healthBadge(row);head.append(title,badge);
    const detail=document.createElement('p');detail.textContent=row.detail||'沒有附加說明。';card.append(head,detail);
    const metrics=document.createElement('div');metrics.className='health-metrics';
    const names={setting_version:'設定版本',samples:'樣本',labeled:'已標記',candidate_count:'候選數',completed_stock_days:'完成股票日',target_stock_days:'目標股票日',failed_stock_days:'失敗股票日',initial_capital:'起始本金',current_capital:'目前資金'};
    for(const [key,value] of Object.entries(row.metrics||{})){const metric=healthMetric(names[key]||key,value);if(metric)metrics.append(metric);}
    if(row.updated_at){const updated=document.createElement('span');updated.textContent=`更新 ${new Date(row.updated_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}`;metrics.append(updated);}
    if(metrics.childNodes.length)card.append(metrics);target.append(card);
  }
  if(!rows.length)target.textContent='尚未收到檢測資料。';
  renderRuntimeModel(data.model_runtime_consistency||runtimeFallback());
}
function renderRuntimeModel(c){
  const statusIcons={OK:'✅',MISMATCH:'⚠️',RUNTIME_UNKNOWN:'❌',RUNTIME_STALE:'❌',APPROVED_MISSING:'❌',APPROVED_INVALID:'❌',PROFILE_MISMATCH:'⚠️',VERSION_MISMATCH:'⚠️'};
  const statusText={OK:'一致：盤中使用目前核准模型',MISMATCH:'注意：盤中仍使用另一版本模型',RUNTIME_UNKNOWN:'無法確認盤中模型',RUNTIME_STALE:'盤後：最後一次盤中載入狀態',APPROVED_MISSING:'找不到目前核准模型',APPROVED_INVALID:'目前核准模型格式無效',PROFILE_MISMATCH:'模型設定不一致',VERSION_MISMATCH:'模型版本資訊不一致'};
  const rt=c.runtime||{};
  const runtimeStatus=c.runtime_status||{};
  const ap=(c.approved&&c.approved.error)?{}:c.approved||{};
  el('runtimeModelStatus').textContent=`${statusIcons[c.status]||'❓'} ${statusText[c.status]||'模型狀態未知'}${c.reason?`（${c.reason}）`:''}`;
  el('rtVersion').textContent=rt.version||'--';
  el('rtProfile').textContent='模型設定：'+(rt.profile||'--');
  el('rtTrained').textContent='訓練截至：'+(rt.trained_through||'--');
  el('rtLoaded').textContent='載入時間：'+(rt.loaded_at?new Date(rt.loaded_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'}):'--');
  el('rtSha').textContent='檔案指紋：'+(rt.artifact_sha256||'--').slice(0,12);
  el('apVersion').textContent=ap.version||'--';
  el('apProfile').textContent='模型設定：'+(ap.profile||'--');
  el('apTrained').textContent='訓練截至：'+(ap.trained_through||'--');
  el('apSha').textContent='檔案指紋：'+(ap.artifact_sha256||'--').slice(0,12);
  el('rtMode').textContent='決策模式：'+(runtimeStatus.entry_mode==='rules'?'規則模式（模型僅供診斷）':runtimeStatus.entry_mode==='model'?'模型模式':'--');
  const rulesDiagnostic=runtimeStatus.entry_mode==='rules'&&c.status==='OK';
  el('rtConsistency').textContent=(statusIcons[c.status]||'❓')+' '+(rulesDiagnostic?'Rules mode（模型僅供診斷）':(statusText[c.status]||c.status));
  el('rtReason').textContent=[c.reason,rt.load_reason].filter(Boolean).join('；')||'目前沒有其他說明';
}
async function loadHealth(){try{renderHealth(await api('health'));}catch(error){el('healthSummary').textContent=error.message;el('healthSignals').replaceChildren();renderRuntimeModel(runtimeFallback('健康檢查 API 無法取得'));}}
function logValue(value,digits=0){const number=Number(value);return Number.isFinite(number)?number.toLocaleString('zh-TW',{minimumFractionDigits:digits,maximumFractionDigits:digits}):'—';}
function logMetric(label,value){const box=document.createElement('div');box.className='model-log-metric';const name=document.createElement('span'),strong=document.createElement('strong');name.textContent=label;strong.textContent=value;box.append(name,strong);return box;}
function renderModelLog(data){
  const rows=Array.isArray(data.entries)?data.entries:[],target=el('modelLogEntries');target.replaceChildren();
  modelLogPage=Number(data.page)||1;
  el('modelLogSummary').textContent=rows.length?(data.has_more?`本頁 ${rows.length} 筆，還有下一頁；最新紀錄在最上方。`:`目前共有 ${rows.length} 筆模型晉升紀錄。這是稽核紀錄數量，不代表只能使用一個模型。`):'目前沒有模型晉升紀錄；這不會阻止目前 approved model 使用。';
  el('modelLogPage').textContent=`第 ${modelLogPage} 頁`;
  el('modelLogPrevious').disabled=!data.has_previous;
  el('modelLogNext').disabled=!data.has_more;
  for(const row of rows){
    const card=document.createElement('article');card.className='model-log-card';
    const head=document.createElement('div');head.className='model-log-head';
    const title=document.createElement('h3');title.textContent=row.promoted_model||'未命名模型';
    const time=document.createElement('time');time.className='model-log-time';time.textContent=row.promoted_at?new Date(row.promoted_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'}):'時間未知';head.append(title,time);
    const route=document.createElement('p');route.className='model-log-route';route.textContent=`前一版：${row.previous_model||'無'} · 訓練截至：${row.trained_through||'未知'} · 備份：${row.backup_file||'首次晉升，無舊檔'}`;
    card.append(head,route);
    const validations=Array.isArray(row.validation)?row.validation:[];
    for(const fold of validations){
      const section=document.createElement('div');section.className='model-log-fold';
      const foldTitle=document.createElement('div');foldTitle.className='model-log-fold-title';foldTitle.textContent=`驗證區段 ${fold.fold||1}${fold.test_from&&fold.test_through?` · ${fold.test_from} ～ ${fold.test_through}`:''}`;
      const grid=document.createElement('div');grid.className='model-log-grid';
      grid.append(logMetric('測試集樣本',logValue(fold.test_samples)),logMetric('挑出筆數',logValue(fold.selected_count)),logMetric('期望值',fold.expected_value_pct===null||fold.expected_value_pct===undefined?'—':`${logValue(fold.expected_value_pct,3)}%`),logMetric('Brier 分數',logValue(fold.brier,4)));
      section.append(foldTitle,grid);card.append(section);
    }
    if(!validations.length){const empty=document.createElement('p');empty.className='hint';empty.textContent='這筆舊紀錄沒有驗證明細。';card.append(empty);}
    target.append(card);
  }
}
async function loadModelLog(page=modelLogPage){const button=el('reloadModelLog');if(button)button.disabled=true;try{renderModelLog(await api(`model-log?page=${Math.max(1,Number(page)||1)}`));}catch(error){el('modelLogSummary').textContent=error.message;el('modelLogEntries').replaceChildren();}finally{if(button)button.disabled=false;}}
async function loadMaintenance(){try{const data=await api('maintenance');const names={history_download:'資料抓取',history_train:'歷史訓練',intraday:'當沖服務',learning:'每日訓練',sync:'VM 同步'};const states={active:'進行中',inactive:'未執行',activating:'啟動中',deactivating:'停止中',failed:'失敗',idle:'尚未同步',running:'同步中',succeeded:'已完成'};const parts=Object.entries(names).map(([key,label])=>`${label}：${states[data[key]]||'未知'}`);message('maintenanceStatus',data.detail||parts.join('｜'),!data.available);for(const id of ['restartIntraday','syncVm'])el(id).disabled=!data.available;}catch(error){message('maintenanceStatus',error.message,true);}}
function applyPipeline(data){pipelineVersion=data.version;const v=data.values;el('pTarget').value=v.history_target_symbols;el('pSymbols').value=v.history_symbols.join(',');el('pPairs').value=v.history_max_pairs;el('pStart').value=v.history_window_start;el('pEnd').value=v.history_window_end;el('pWeekend').checked=v.history_weekends;el('pLearning').checked=v.learning_enabled;el('pLearningTime').value=v.learning_time;el('pDates').value=v.min_training_dates;el('pSamples').value=v.min_training_samples;el('pClass').value=v.min_class_samples;el('pHoldout').value=v.holdout_days;el('pRetrainDays').value=v.model_retrain_every_days;el('pForwardDays').value=v.forward_observe_days;el('pFormalLive').checked=v.formal_candidate_for_live;el('pThreshold').value=v.model_threshold;el('pFee').value=v.fee_rate;el('pTax').value=v.sell_tax_rate;el('pSlip').value=v.slippage_bps;el('pShares').value=v.shares;}
async function loadPipeline(){try{applyPipeline(await api('pipeline-settings'));}catch(error){message('pipelineStatus',error.message,true);}}
async function maintenance(action,confirmation,label){if(!confirm(`確認要${label}嗎？\n此操作會受到時段、工作衝突與冷卻限制。`))return;const id=action==='restart-intraday'?'restartIntraday':'syncVm';const button=el(id);button.disabled=true;message('maintenanceStatus','正在送出受控維護要求…');try{const result=await api('maintenance/'+action,{method:'POST',body:{confirmation}});message('maintenanceStatus',result.detail||'操作已送出。',!result.available);}catch(error){message('maintenanceStatus',error.message,true);}finally{await loadMaintenance();}}
async function session(){const s=await api('session');csrf=s.csrf;el('identity').textContent=s.email;return s;}
function startLiveRefresh(){if(liveRefreshTimer)clearInterval(liveRefreshTimer);liveRefreshTimer=setInterval(()=>{if(!document.hidden){loadHealth();loadMaintenance();}},30000);}
async function enter(){await session();applySettings(await api('settings'));await reloadConversations();try{await loadBotPolicy();}catch(_){}el('login').hidden=true;el('workspace').hidden=false;await loadHealth();await loadMaintenance();await loadPipeline();startLiveRefresh();}
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
el('reloadModelLog').onclick=()=>loadModelLog();
el('modelLogPrevious').onclick=()=>loadModelLog(modelLogPage-1);
el('modelLogNext').onclick=()=>loadModelLog(modelLogPage+1);
el('restartIntraday').onclick=()=>maintenance('restart-intraday','RESTART_INTRADAY','重啟當沖');
el('syncVm').onclick=()=>maintenance('sync-vm','SYNC_VM','同步 VM');
el('pipelineForm').onsubmit=async event=>{event.preventDefault();const values={history_target_symbols:+el('pTarget').value,history_symbols:el('pSymbols').value.split(',').map(x=>x.trim()).filter(Boolean),history_max_pairs:+el('pPairs').value,history_weekends:el('pWeekend').checked,history_window_start:el('pStart').value,history_window_end:el('pEnd').value,learning_enabled:el('pLearning').checked,learning_time:el('pLearningTime').value,min_training_dates:+el('pDates').value,min_training_samples:+el('pSamples').value,min_class_samples:+el('pClass').value,holdout_days:+el('pHoldout').value,model_retrain_every_days:+el('pRetrainDays').value,forward_observe_days:+el('pForwardDays').value,formal_candidate_for_live:el('pFormalLive').checked,model_threshold:+el('pThreshold').value,fee_rate:+el('pFee').value,minimum_fee_twd:20,sell_tax_rate:+el('pTax').value,slippage_bps:+el('pSlip').value,shares:+el('pShares').value};try{applyPipeline(await api('pipeline-settings',{method:'PUT',body:{values,version:pipelineVersion}}));message('pipelineStatus','已儲存。此計畫將在 VM 同步後由下一次抓取／訓練讀取。');}catch(error){message('pipelineStatus',error.message,true);}};
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
