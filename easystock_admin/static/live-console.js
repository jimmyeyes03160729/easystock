'use strict';
(() => {
  const byId = id => document.getElementById(id);
  const text = value => value === null || value === undefined ? '未知' : String(value);
  let state = null, selected = null, verification = null, clientId = '', busy = false;
  const modal = byId('liveSellModal');
  const nav = document.querySelector('.admin-section-nav');
  if (!modal || !nav) return;
  const tab = document.createElement('button');tab.type='button';tab.dataset.adminTab='liveConsolePanel';tab.textContent='永豐實盤當沖';
  tab.addEventListener('click',()=>showAdminTab('liveConsolePanel'));nav.append(tab);
  function table(target, rows, columns, sell = false) {
    const root = byId(target);root.replaceChildren();
    if (!rows?.length) {root.textContent=state?.broker?.complete?'券商目前無資料。':'尚未確認，不代表零持倉／零成交。';return;}
    const t=document.createElement('table'),head=document.createElement('tr'),body=document.createElement('tbody');
    for(const [,label] of columns){const th=document.createElement('th');th.textContent=label;head.append(th);}t.append(head,body);
    for(const row of rows){const tr=document.createElement('tr');for(const [key] of columns){const td=document.createElement('td');td.textContent=text(row[key]);tr.append(td);}
      if(sell){const td=document.createElement('td'),button=document.createElement('button');button.type='button';button.textContent='賣出…';button.disabled=!state.ordering_guard||!state.broker_fresh||!state.broker.complete||!(row.available_to_sell>0);button.addEventListener('click',()=>openSell(row));td.append(button);tr.append(td);}body.append(tr);
    }root.append(t);
  }
  function card(root, label, value){const p=document.createElement('p');p.textContent=label+'：'+text(value);root.append(p);}
  function render(data) {
    state=data;byId('liveStatus').textContent=`${data.mode} · ${data.auto_state} · ${data.reconciliation} · 自動執行引擎未啟用`;
    byId('liveMode').value=data.mode;byId('liveMode').querySelector('[value="LIVE AUTO"]').disabled=!data.activation_allowed;
    byId('liveKill').textContent=data.kill_switch?'解除 KILL SWITCH（需確認）':'啟用 KILL SWITCH（不平倉）';
    const broker=data.broker||{},root=byId('liveBroker');root.replaceChildren();
    for(const [label,value] of [['連線',broker.connected?'Connected':'Disconnected'],['驗證',broker.authenticated?'Authenticated':'未驗證'],['遮罩帳戶',broker.account?.account_id],['Broker Sync',broker.updated_at],['持倉／委託／成交同步',broker.complete?'完成':'未知'],['最近對帳',data.reconciliation],['未實現損益',broker.pnl?.unrealized],['今日已實現損益（券商可能延遲）',broker.pnl?.realized_today]])card(root,label,value);
    table('livePositions',broker.positions,[['symbol','股票'],['name','名称'],['quantity','股數'],['average_price','均價'],['current_price','現價'],['unrealized_pnl','未實現'],['return_pct','報酬%'],['available_to_sell','可賣股數'],['strategy','策略'],['entry_time','進場'],['broker_updated_at','同步']],true);
    table('liveOrders',broker.orders,[['order_id','委託指紋'],['client_order_id','操作識別'],['symbol','股票'],['side','方向'],['qty','股數'],['price','價格'],['status','狀態'],['filled_qty','成交股數'],['created_at','時間']]);
    table('liveDeals',broker.deals,[['deal_id','成交指紋'],['symbol','股票'],['side','方向'],['qty','股數'],['price','價格'],['deal_time','時間']]);
  }
  async function refresh(){try{render(await api('api/live-console'));}catch(e){state=null;byId('liveStatus').textContent=e.message;byId('liveMode').querySelector('[value="LIVE AUTO"]').disabled=true;byId('liveSellSubmit').disabled=true;verification=null;for(const id of ['liveBroker','livePositions','liveOrders','liveDeals'])byId(id).replaceChildren();}}
  async function market(){try{const c=await api('api/market-context'),root=byId('marketContext');root.replaceChildren();
    card(root,'市場廣度狀態',c.breadth?.status||'UNKNOWN');card(root,'上漲／下跌／持平',[c.breadth?.advancers,c.breadth?.decliners,c.breadth?.unchanged].map(text).join(' / '));card(root,'快照有效覆蓋率',c.breadth?.coverage);card(root,'價格輪動',c.rotation?.rotation_state||'UNKNOWN');card(root,'資料時間',c.generated_at);
    for(const s of c.sectors?.rows||[])card(root,s.name,`${text(s.return_day)}% · 大盤相對 ${text(s.relative_to_taiex)} pp · 排名 ${text(s.rank)} · fresh ${text(s.fresh)} · 報價 ${text(s.quote_at)}`);
  }catch(e){byId('marketContext').textContent=e.message;}}
  window.loadLiveConsole=refresh;
  window.loadMarketContext=market;
  document.addEventListener('easystock:owner-ready',()=>{refresh();market();});
  byId('liveRefresh').addEventListener('click',refresh);
  byId('liveVerify').addEventListener('click',async()=>{try{const result=await api('api/order/verify',{method:'POST',body:{}});if(!result.ok)throw Error(result.message);await refresh();}catch(e){byId('liveStatus').textContent=e.message;}});
  byId('liveModeSave').addEventListener('click',async()=>{if(!window.confirm('確認只變更控制狀態？不啟用任何自動執行引擎。'))return;try{render(await api('api/live-console',{method:'PUT',body:{mode:byId('liveMode').value}}));}catch(e){byId('liveStatus').textContent=e.message;}});
  byId('liveKill').addEventListener('click',async()=>{if(!state)return;const kill=!state.kill_switch;if(!kill&&!window.confirm('確認解除 KILL SWITCH？LIVE AUTO 仍受 guard 與對帳控制。'))return;try{render(await api('api/live-console',{method:'PUT',body:{kill}}));}catch(e){byId('liveStatus').textContent=e.message;}});
  function invalidate(){verification=null;byId('liveSellSubmit').disabled=true;byId('liveSellPassword').value='';}
  function openSell(row){selected=row;clientId=crypto.randomUUID();byId('liveSellForm').reset();invalidate();byId('liveSellQty').value=Math.min(row.available_to_sell,999);byId('liveSellPrice').value=row.current_price;byId('liveSellSummary').textContent=`${row.symbol} ${row.name} · 可賣 ${row.available_to_sell} 股 · 帳戶 ${state.broker.account?.account_id}`;byId('liveSellEvidence').textContent='請先驗證，即時 bid/ask 尚未取得。';byId('liveSellResult').textContent='';modal.showModal();}
  function order(){return {client_order_id:clientId,symbol:selected.symbol,action:'SELL',quantity:Number(byId('liveSellQty').value),price:Number(byId('liveSellPrice').value),is_odd_lot:byId('liveSellOdd').checked};}
  for(const id of ['liveSellQty','liveSellPrice','liveSellOdd'])byId(id).addEventListener('input',invalidate);
  function confirmation(){byId('liveSellSubmit').disabled=busy||!verification||Date.now()>verification.deadline||byId('liveSellConfirm').value!=='SELL'||byId('liveSellAccount').value!==verification.account.account_id||!byId('liveSellPassword').value;}
  for(const id of ['liveSellConfirm','liveSellAccount','liveSellPassword'])byId(id).addEventListener('input',confirmation);
  byId('liveSellVerify').addEventListener('click',async()=>{if(busy)return;busy=true;invalidate();try{const result=await api('api/live-console/sell-verify',{method:'POST',body:order()});verification={...result,order:order(),deadline:Date.now()+result.expires_in*1000};byId('liveSellEvidence').textContent=`Bid ${result.quote.bids.map(x=>x.price).join('/')} / Ask ${result.quote.asks.map(x=>x.price).join('/')} · 限價 ${order().price} · 預估 ${result.notional} 元 · 可賣 ${result.available_to_sell} 股 · 帳戶 ${result.account.account_id} · 驗證 60 秒有效`;setTimeout(confirmation,result.expires_in*1000+1);}catch(e){byId('liveSellEvidence').textContent=e.message;}finally{busy=false;confirmation();}});
  byId('liveSellForm').addEventListener('submit',async event=>{event.preventDefault();confirmation();if(byId('liveSellSubmit').disabled)return;busy=true;byId('liveSellSubmit').disabled=true;const body={...verification.order,ca_passwd:byId('liveSellPassword').value,sell_verification_id:verification.verification_id,confirm_sell:'SELL',confirm_account:byId('liveSellAccount').value};invalidate();try{const result=await api('api/order/place',{method:'POST',body});if(!result.ok)throw Error(result.message);byId('liveSellResult').textContent='已交券商；請同步／對帳，勿重送。';await refresh();}catch(e){byId('liveSellResult').textContent=e.message+' 請對帳，勿重送。';}finally{body.ca_passwd='';busy=false;}});
  byId('liveSellClose').addEventListener('click',()=>{invalidate();modal.close();});modal.addEventListener('close',invalidate);modal.addEventListener('cancel',invalidate);
})();
