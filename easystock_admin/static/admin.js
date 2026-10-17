'use strict';
const el=id=>document.getElementById(id);
let csrf='',liveRefreshTimer=0;
let pipelineVersion=null;
function message(id,text,error=false){el(id).textContent=text;el(id).classList.toggle('error',error);}
async function api(path,{method='GET',body}={}){
  const response=await fetch('/admin/'+path,{method,credentials:'same-origin',headers:{...(body!==undefined?{'Content-Type':'application/json'}:{}),...(csrf?{'X-CSRF-Token':csrf}:{})},...(body!==undefined?{body:JSON.stringify(body)}:{})});
  const data=await response.json();
  if(!response.ok)throw Object.assign(new Error(data.error||'登入已失效，請重新登入。'),{code:data.code});
  return data;
}
function showAdminTab(id){
  const panels=[...document.querySelectorAll('.admin-tab-panel')];
  if(!panels.some(panel=>panel.id===id))id='healthPanel';
  for(const panel of panels)panel.hidden=panel.id!==id;
  for(const button of document.querySelectorAll('[data-admin-tab]'))button.setAttribute('aria-selected',String(button.dataset.adminTab===id));
  const selected=document.querySelector(`[data-admin-tab="${id}"]`),nav=selected?.closest('.admin-section-nav');
  if(nav)nav.scrollLeft+=selected.getBoundingClientRect().left-nav.getBoundingClientRect().left-(nav.clientWidth-selected.getBoundingClientRect().width)/2;
  if(id==='manualOrderPanel' && typeof window.loadManualOrders==='function')window.loadManualOrders();
  if(id==='guardianPanel' && typeof window.loadGuardian==='function')window.loadGuardian();
}
const healthLabels={ok:'正常',warning:'注意',error:'異常',idle:'等待'};
function healthBadge(row){if(row.key==='paper_trade')return row.state==='ok'?'已啟用・等待交易時段':'已暫停';if(row.key==='market_session'&&row.state==='idle')return '今日休市';if(['market_credentials','firebase'].includes(row.key)&&row.state==='ok')return '已設定';if(row.key==='admin_store'&&row.state==='ok')return '可讀取';if(['training_worker','daily_learning_worker','download_worker'].includes(row.key)&&row.state==='idle')return '排程中';if(row.key==='history_collection'&&row.state==='idle')return '等待時段';return healthLabels[row.state]||'未知';}
function healthMetric(label,value){if(value===null||value===undefined)return null;const node=document.createElement('span');const number=Number(value);node.textContent=`${label} ${typeof value==='number'&&Number.isFinite(number)?number.toLocaleString('zh-TW'):String(value)}`;return node;}
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
    const names={setting_version:'設定版本',samples:'樣本',labeled:'已標記',candidate_count:'候選數',completed_stock_days:'完成股票日',target_stock_days:'目標股票日',failed_stock_days:'失敗股票日',daily_buy_limit:'每日買進額度',daily_buy_used:'今日已用額度',daily_buy_remaining:'今日剩餘額度'};
    for(const [key,value] of Object.entries(row.metrics||{})){const metric=healthMetric(names[key]||key,value);if(metric)metrics.append(metric);}
    if(row.updated_at){const updated=document.createElement('span');updated.textContent=`更新 ${new Date(row.updated_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}`;metrics.append(updated);}
    if(metrics.childNodes.length)card.append(metrics);target.append(card);
  }
  if(!rows.length)target.textContent='尚未收到檢測資料。';
  renderProviderHealth(data.provider_health);
}
function renderProviderHealth(data){
  const target=el('providerHealthDetails');if(!target)return;target.replaceChildren();
  el('providerHealthSummary').textContent=data?`市場：${data.market_state==='OPEN'?'盤中':data.market_state==='CLOSED'?'休市／盤後':'待確認'} · 即時市場資料${data.market_data?.usable?'可用':'尚未確認可用'}`:'尚未收到資料來源證據。';
  const labels={shioaji:'永豐行情',esun:'玉山行情',fugle:'Fugle',firebase:'Firebase'};
  const statuses={ONLINE:'正常',DEGRADED:'延遲／部分異常',OFFLINE:'離線',UNKNOWN:'未知／待命',MARKET_CLOSED:'休市／盤後'};
  const metrics={latency_ms:'延遲 ms',age_seconds:'資料秒數',heartbeat_age_seconds:'心跳秒數',consecutive_failures:'連續失敗',reconnect_count:'重連次數',subscription_count:'訂閱數',provider_version:'版本'};
  for(const [key,label] of Object.entries(labels)){
    const row=data?.providers?.[key]||{},card=document.createElement('article');card.className='health-card';
    const title=document.createElement('h4');title.textContent=label+' · '+(statuses[row.status]||'未知');card.append(title);
    const details=document.createElement('div');details.className='health-metrics';
    for(const [name,text] of Object.entries(metrics)){const node=healthMetric(text,row[name]);if(node)details.append(node);}
    for(const [name,text] of Object.entries({last_ok_at:'最近成功',last_data_at:'最近收件',quote_at:'報價時間',last_error_at:'最近錯誤'})){
      if(row[name]){const node=document.createElement('span');node.textContent=text+' '+new Date(row[name]).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'});details.append(node);}
    }
    if(key==='fugle'&&row.kind==='scheduled'){
      for(const [name,text] of Object.entries({scan_date:'掃描日期',expected_scan_date:'應完成日期',data_generated_at:'資料產生',last_success_at:'最近成功',next_due_at:'下次期限',workflow_source:'排程來源',freshness:'新鮮度',run_id:'執行編號',run_attempt:'嘗試次數'})){
        const node=healthMetric(text,row[name]);if(node)details.append(node);
      }
    }
    const flags=document.createElement('p');flags.textContent=key==='fugle'&&row.kind==='scheduled'
      ?`批次排程 · 狀態原因 ${row.error_code||'無'}`
      :`連線 ${row.connected===true?'已連線':row.connected===false?'斷線':'待確認'} · 訂閱 ${row.subscribed===true?'完成':row.subscribed===false?'未完成':'不適用'} · 錯誤 ${row.error_code||'無'}`;
    card.append(details,flags);target.append(card);
  }
  const gate=data?.market_gate;
  if(gate && gate.status!=='not_observed'){
    const card=document.createElement('article');card.className='health-card';
    const title=document.createElement('h4');title.textContent='當沖市場閘門 · '+(gate.status==='current'?'盤中狀態':'上次狀態／已過時');card.append(title);
    const details=document.createElement('div');details.className='health-metrics';
    const values={market_level:'市場燈號',data_health:'資料品質',selected_source:'採用來源',
      premarket_date:'盤前資料日',model_ready:'模型就緒',radar_candidate_count:'雷達候選',
      market_condition_reason:'市場判定',gate_reason:'進場閘門',
      shioaji_age: '永豐報價秒數',esun_age:'玉山報價秒數',
      market_red_blocks:'市場紅燈攔截',data_unavailable_blocks:'資料不可用攔截'};
    const row={...gate,model_ready:gate.model_ready?'是':'否',
      shioaji_age:gate.sources?.shioaji?.age_seconds,esun_age:gate.sources?.esun?.age_seconds,
      market_red_blocks:gate.entry_block_evaluations?.market_risk_red,
      data_unavailable_blocks:gate.entry_block_evaluations?.market_data_unavailable};
    for(const [key,label] of Object.entries(values)){const node=healthMetric(label,row[key]);if(node)details.append(node);}
    card.append(details);target.append(card);
  }
}
async function loadHealth(){try{renderHealth(await api('health'));}catch(error){el('healthSummary').textContent=error.message;el('healthSignals').replaceChildren();}}
async function loadMaintenance(){try{const data=await api('maintenance');const names={history_download:'資料抓取',history_train:'歷史訓練',intraday:'當沖服務',learning:'每日訓練'};const states={active:'進行中',inactive:'未執行',activating:'啟動中',deactivating:'停止中',failed:'失敗'};const parts=Object.entries(names).map(([key,label])=>`${label}：${states[data[key]]||'未知'}`);message('maintenanceStatus',data.detail||parts.join('｜'),!data.available);el('restartIntraday').disabled=!data.available;}catch(error){message('maintenanceStatus',error.message,true);}}
function applyPipeline(data){pipelineVersion=data.version;const v=data.values;el('pTarget').value=v.history_target_symbols;el('pSymbols').value=v.history_symbols.join(',');el('pPairs').value=v.history_max_pairs;el('pStart').value=v.history_window_start;el('pEnd').value=v.history_window_end;el('pWeekend').checked=v.history_weekends;el('pLearning').checked=v.learning_enabled;el('pLearningTime').value=v.learning_time;el('pDates').value=v.min_training_dates;el('pSamples').value=v.min_training_samples;el('pClass').value=v.min_class_samples;el('pHoldout').value=v.holdout_days;el('pRetrainDays').value=v.model_retrain_every_days;el('pForwardDays').value=v.forward_observe_days;el('pFormalLive').checked=v.formal_candidate_for_live;el('pThreshold').value=v.model_threshold;el('pFee').value=v.fee_rate;el('pMinFee').value=v.minimum_fee_twd;el('pTax').value=v.sell_tax_rate;el('pSlip').value=v.slippage_bps;el('pShares').value=v.shares;}
async function loadPipeline(){try{applyPipeline(await api('pipeline-settings'));}catch(error){message('pipelineStatus',error.message,true);}}
async function maintenance(action,confirmation,label){if(!confirm(`確認要${label}嗎？\n此操作會受到時段、工作衝突與冷卻限制。`))return;const button=el('restartIntraday');button.disabled=true;message('maintenanceStatus','正在送出受控維護要求…');try{const result=await api('maintenance/'+action,{method:'POST',body:{confirmation}});message('maintenanceStatus',result.detail||'操作已送出。',!result.available);}catch(error){message('maintenanceStatus',error.message,true);}finally{await loadMaintenance();}}
async function session(){const s=await api('session');csrf=s.csrf;el('identity').textContent=s.email;return s;}
function startLiveRefresh(){if(liveRefreshTimer)clearInterval(liveRefreshTimer);liveRefreshTimer=setInterval(()=>{if(!document.hidden){loadHealth();loadMaintenance();if(typeof window.loadMarketContext==='function')window.loadMarketContext();if(!el('manualOrderPanel')?.hidden && typeof window.loadManualOrders==='function')window.loadManualOrders();}},30000);}
async function enter(){await session();await loadNotifications();el('login').hidden=true;el('workspace').hidden=false;await loadHealth();await loadMaintenance();await loadPipeline();startLiveRefresh();document.dispatchEvent(new Event('easystock:owner-ready'));}
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
el('reloadHealth').onclick=async()=>{const button=el('reloadHealth');button.disabled=true;try{await loadHealth();}finally{button.disabled=false;}};
el('restartIntraday').onclick=()=>maintenance('restart-intraday','RESTART_INTRADAY','重啟當沖');
el('pipelineForm').onsubmit=async event=>{event.preventDefault();const values={history_target_symbols:+el('pTarget').value,history_symbols:el('pSymbols').value.split(',').map(x=>x.trim()).filter(Boolean),history_max_pairs:+el('pPairs').value,history_weekends:el('pWeekend').checked,history_window_start:el('pStart').value,history_window_end:el('pEnd').value,learning_enabled:el('pLearning').checked,learning_time:el('pLearningTime').value,min_training_dates:+el('pDates').value,min_training_samples:+el('pSamples').value,min_class_samples:+el('pClass').value,holdout_days:+el('pHoldout').value,model_retrain_every_days:+el('pRetrainDays').value,forward_observe_days:+el('pForwardDays').value,formal_candidate_for_live:el('pFormalLive').checked,model_threshold:+el('pThreshold').value,fee_rate:+el('pFee').value,minimum_fee_twd:+el('pMinFee').value,sell_tax_rate:+el('pTax').value,slippage_bps:+el('pSlip').value,shares:+el('pShares').value};const save=confirm_profile_change=>api('pipeline-settings',{method:'PUT',body:{values,version:pipelineVersion,...(confirm_profile_change?{confirm_profile_change:true}:{})}});try{let data;try{data=await save(false);}catch(error){if(error.code!=='profile_change_confirmation_required'||!confirm(error.message))throw error;data=await save(true);}applyPipeline(data);message('pipelineStatus','已儲存。下一次抓取／訓練會讀取這份計畫。');}catch(error){message('pipelineStatus',error.message,true);}};
for(const button of document.querySelectorAll('[data-admin-tab]'))button.onclick=()=>showAdminTab(button.dataset.adminTab);
el('logout').onclick=async()=>{try{await api('logout',{method:'POST',body:{}});location.reload();}catch(e){alert(e.message);}};
el('checkUsage').onclick=async()=>{el('checkUsage').disabled=true;try{const s=await api('line-quota');message('lineUsage',s.limit===null?`本月已使用 ${s.used}；LINE 未設定月上限。最後查詢：${new Date(s.checked_at*1000).toLocaleString('zh-TW')}`:`已使用：${s.used}｜當月上限：${s.limit}｜剩餘：${s.remaining}｜最後查詢：${new Date(s.checked_at*1000).toLocaleString('zh-TW')}`);}catch(_){message('lineUsage','額度暫時無法取得',true);}finally{el('checkUsage').disabled=false;}};
let notificationVersion=null;
function applyNotifications(data){
  notificationVersion=data.version;
  el('lineConfigured').textContent='狀態：'+(data.line.configured?'已設定':'未設定');
  el('telegramConfigured').textContent='狀態：'+(data.telegram.configured?'已設定':'未設定');
  el('lineTrade').checked=!!data.line.trade;el('lineSummary').checked=!!data.line.summary;
  el('telegramTrade').checked=!!data.telegram.trade;el('telegramSummary').checked=!!data.telegram.summary;
  el('deliveryStatus').replaceChildren();
  const labels={sent:'送出成功',failed:'送出失敗',unknown:'結果不明（不重送）',pending:'處理中／中斷未確認',disabled:'已關閉'};
  for(const row of data.deliveries||[]){const p=document.createElement('p');p.textContent=`${row.channel==='line'?'LINE':'Telegram'} ${row.kind} · ${labels[row.status]||'未知狀態'} · ${new Date(row.at*1000).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}`;el('deliveryStatus').append(p);}
  if(!data.deliveries?.length)el('deliveryStatus').textContent='尚無通知紀錄。';
}
async function loadNotifications(){applyNotifications(await api('notifications'));}
el('notificationForm').onsubmit=async event=>{event.preventDefault();const button=el('saveNotifications');button.disabled=true;try{applyNotifications(await api('notifications',{method:'PUT',body:{line_trade:el('lineTrade').checked,line_summary:el('lineSummary').checked,telegram_trade:el('telegramTrade').checked,telegram_summary:el('telegramSummary').checked,version:notificationVersion}}));message('conversationStatus','已儲存，下一次事件立即生效。');}catch(e){message('conversationStatus',e.message,true);}finally{button.disabled=false;}};
(async()=>{try{await enter();showAdminTab('healthPanel');}catch{await loginSetup();}})();
