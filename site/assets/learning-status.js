/* Allowlisted research aggregates only; model parameters and diagnostics stay private. */
(() => {
  const root=document.getElementById('learningSection');if(!root)return;
  const style=document.createElement('style');
  style.textContent=`
  #learningSection .learning-head{border-bottom:1px solid var(--border);padding-bottom:14px;margin-bottom:18px}
  #learningSection .learning-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}
  #learningSection .learning-column{min-width:0}
  #learningSection .learning-column-head{display:flex;justify-content:space-between;align-items:start;gap:12px;margin-bottom:14px}
  #learningSection h2{font-size:22px;font-weight:750}#learningSection h3{font-size:16px;font-weight:700}
  #learningSection p,#learningSection small{font-size:12px;line-height:1.8;color:var(--sub)}
  #learningSection .learning-numbers{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  #learningSection .learning-numbers>div{min-width:0;padding:12px;border:1px solid var(--border);border-radius:12px;background:var(--surface)}
  #learningSection .learning-numbers span{font-size:12px;color:var(--sub)}
  #learningSection .learning-numbers strong{display:block;font-size:20px;line-height:1.6;font-weight:750;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
  #learningSection .learning-bottom{margin-top:14px}#learningSection .learning-bottom p{margin:6px 0}
  #learningSection .research-summary{margin-top:24px;padding-top:18px;border-top:1px solid var(--border)}
  #learningSection .research-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:14px}
  #learningSection .research-card{min-width:0;padding:16px;border:1px solid var(--border);border-radius:14px;background:var(--surface)}
  #learningSection .research-card h4{font-size:14px;font-weight:700;margin-bottom:8px}
  #learningSection .research-card div{font-size:13px;line-height:1.9;overflow-wrap:anywhere}
  #learningSection .research-stale{margin-top:12px;padding:10px;border:1px solid var(--border);border-radius:8px;font-size:12px;color:var(--sub)}
  @media(max-width:900px){#learningSection .learning-columns,#learningSection .research-grid{grid-template-columns:1fr}#learningSection .learning-head{display:block}#learningSection .learning-head h2{margin-bottom:10px}#learningSection .learning-head p{max-width:none}}
  @media(max-width:480px){#learningSection .learning-column-head{display:block}#learningSection .learning-column-head .phase-badge{display:inline-block;max-width:100%;white-space:normal;margin-top:8px}}
  `;
  document.head.append(style);
  const metric=(label,id)=>`<div><span>${label}</span><strong id="${id}">—</strong></div>`;
  root.innerHTML=`
    <div class="learning-head"><h2 id="learningTitle">盤後研究與資料進度</h2><p>最近交易日的研究統計與歷史資料分開呈現；研究報酬不是帳戶報酬，樣本數不代表模型已部署。</p></div>
    <div class="learning-columns">
      <article class="learning-column"><header class="learning-column-head"><div><h3>每日研究</h3><p id="dailyLearningDate">最近交易日：待資料</p></div><span id="publicDailyState" class="phase-badge" role="status">等待狀態更新</span></header>
        <div class="learning-numbers">${metric('累積學習日','learnDays')}${metric('最近交易日推薦','learnStocks')}${metric('觀察股票','learnObserved')}${metric('完成 Label','learnLearned')}${metric('研究樣本','learnSamples')}${metric('資料收集','learnCoverage')}</div>
        <div class="learning-bottom"><p id="learnModel">模型狀態：內部診斷請至管理後臺確認</p><p id="learnTraining">累積訓練：待資料</p><p id="publicDailyTime">最後更新：未提供</p><p id="publicDailyError" role="status"></p></div>
      </article>
      <article class="learning-column"><header class="learning-column-head"><div><h3>歷史資料研究</h3><p>歷史標記樣本，不等於可直接訓練或實際成交。</p></div><span id="publicHistoryState" class="phase-badge" role="status">等待狀態更新</span></header>
        <div class="learning-numbers">${metric('處理股票日','historyProcessed')}${metric('有效標記日','historyDays')}${metric('歷史樣本','historySamples')}${metric('保留樣本','historyTestSamples')}</div>
        <div class="learning-bottom"><p id="historyDownload">歷史下載：待資料</p><p id="publicHistoryTime">最後更新：未提供</p><p id="publicHistoryError" role="status"></p></div>
      </article>
    </div>
    <section class="research-summary" aria-labelledby="researchSummaryTitle"><h3 id="researchSummaryTitle">每日盤後研究摘要</h3><p id="researchSummaryDate">最近交易日：待資料</p>
      <div id="researchStale" class="research-stale" hidden>目前顯示最後一次紀錄；更新已過期，不代表服務仍在執行。</div>
      <div class="research-grid"><article class="research-card"><h4>研究交易</h4><div id="researchTrades">研究交易：待資料</div><div id="researchClosed">研究完成：待資料</div><div id="researchWins">獲利：待資料</div><div id="researchLosses">虧損：待資料</div></article>
      <article class="research-card"><h4>研究報酬</h4><div id="researchPnl">研究淨報酬合計：待資料</div><div id="researchReturn">研究毛報酬合計：待資料</div><div id="researchAvg">平均單筆：待資料</div><div id="researchMfe">MFE：待資料</div><div id="researchMae">MAE：待資料</div><div id="researchPf">Profit Factor：待資料</div><div id="researchDrawdown">最大回撤：待資料</div><p>各筆研究訊號的百分比加總，非帳戶報酬或實盤績效。</p></article>
      <article class="research-card"><h4>資料收集</h4><div id="researchSamples">新增樣本：待資料</div><div id="researchLabels">完成 Label：待資料</div><div id="researchCoverage">收集完整度：待資料</div><p>缺少的數值保持待資料，不補成零。</p></article></div>
      <article class="research-card" style="margin-top:12px"><h4>研究出場原因</h4><ul id="researchExits"><li>待資料</li></ul><p>僅顯示公開分類；模型參數與規則細節保留於內部。</p></article>
    </section>`;
  const put=(id,text)=>{document.getElementById(id).textContent=text;};
  const number=v=>typeof v==='number'&&Number.isFinite(v)?v:null;
  const count=v=>number(v)!==null&&v>=0&&Number.isInteger(v)?v.toLocaleString('zh-TW'):'—';
  const pct=v=>number(v)===null?'待資料':`${v>=0?'+':''}${v.toFixed(2)}%`;
  const date=v=>typeof v==='string'&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'}):'未提供';
  const day=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v)?v:'待資料';
  const ratio=(a,b)=>number(a)!==null&&number(b)!==null&&a>=0&&b>=0&&Number.isInteger(a)&&Number.isInteger(b)&&a<=b?`${count(a)} / ${count(b)}`:'待資料';
  const fresh=s=>{const age=Date.now()-Date.parse(s.updated_at);return Number.isFinite(age)&&age>=-60000&&age<180000;};
  const names={collecting:'資料整理中',reviewing:'盤後研究中',training:'研究處理中',idle:'待命',failed:'服務狀態待確認',snapshotting:'資料整理中',replaying:'歷史資料研究中',completed:'本次研究完成',interrupted:'處理已中斷',not_started:'尚未開始'};
  const last={},failed={};
  function render(prefix,s){
    const current=fresh(s);put(prefix+'State',current?(names[s.phase]||'狀態待更新'):'最後紀錄已過期，狀態待確認');
    put(prefix+'Time',`最後更新：${date(s.updated_at)}`);put(prefix+'Error',current?'':'目前顯示最後一次紀錄，不代表程序仍在執行。');
    if(prefix==='publicDaily'){
      const session=s.session||{},totals=s.totals||{},r=s.research_summary||{},trades=r.trades||{};
      const reportDay=day(session.date||r.date);put('dailyLearningDate',`最近交易日：${reportDay}`);put('researchSummaryDate',`最近交易日：${reportDay} · 最後更新：${date(s.updated_at)}`);
      put('learnDays',count(totals.learning_days));put('learnStocks',count(session.recommended_stocks));put('learnObserved',count(session.observed_stocks));put('learnLearned',count(session.labeled_count??session.learned_stocks));put('learnSamples',count(session.sample_count));put('learnCoverage',ratio(session.downloaded,session.requested));
      put('learnTraining',`累積訓練：${count(totals.training_days)} 日 · ${count(totals.training_samples)} 筆樣本；不代表模型已部署。`);
      for(const[id,label,value]of [['researchTrades','研究交易',trades.research_trades??trades.count],['researchClosed','研究完成',trades.research_closed??trades.count],['researchWins','獲利',trades.wins],['researchLosses','虧損',trades.losses],['researchSamples','新增樣本',r.new_samples],['researchLabels','完成 Label',r.labels]])put(id,`${label}：${count(value)}`);
      for(const[id,label,value]of [['researchPnl','研究淨報酬合計',trades.net_pnl_pct],['researchReturn','研究毛報酬合計',trades.gross_pnl_pct],['researchAvg','平均單筆',trades.avg_pnl_pct],['researchMfe','MFE',trades.avg_mfe_pct],['researchMae','MAE',trades.avg_mae_pct]])put(id,`${label}：${pct(value)}`);
      put('researchCoverage',`收集完整度：${ratio(r.downloaded,r.requested)}`);document.getElementById('researchStale').hidden=current;
      put('researchPf',`Profit Factor：${number(trades.profit_factor)===null?'待資料':trades.profit_factor.toFixed(2)}`);put('researchDrawdown',`最大回撤：${pct(trades.max_drawdown_pct)}`);
      const exits=document.getElementById('researchExits');exits.replaceChildren();const rows=Object.entries(trades.exit_reasons||{});for(const[label,value]of rows.length?rows:[['待資料',null]]){const li=document.createElement('li');li.textContent=value===null?label:`${label}：${count(value)}`;exits.append(li);}
    }else{
      const r=s.run||{},a=s.archive||{};put('historyProcessed',ratio(r.processed_files,r.archive_files));put('historyDays',count(r.labeled_dates));put('historySamples',count(r.labeled_samples));put('historyTestSamples',count(s.training?.test_samples));put('historyDownload',`歷史下載：${ratio(a.archived_stock_days,a.target_stock_days)}`);
    }
    if(failed[prefix]){put(prefix+'State','暫時無法取得研究狀態');put(prefix+'Error','讀取失敗，保留最後一次紀錄。');}
    window.HomePresentation?.refreshSummary();
  }
  async function refresh(node,prefix){
    try{
      const r=await fetch(publicDataURL(`${FIREBASE_ROOT}/${node}.json`),{cache:'no-store',signal:AbortSignal.timeout(12000)});
      if(!r.ok)throw Error();const s=await r.json();if(s?.schema_version!==1)throw Error();failed[prefix]=false;last[prefix]=s;render(prefix,s);
    }catch{
      failed[prefix]=true;if(last[prefix])render(prefix,last[prefix]);put(prefix+'State','暫時無法取得研究狀態');put(prefix+'Error',last[prefix]?'讀取失敗，保留最後一次紀錄。':'等待可確認的研究資料。');
    }
  }
  const run=()=>Promise.all([refresh('daytrade_learning_status','publicDaily'),refresh('history_training_status','publicHistory')]);
  run();setInterval(run,60000);setInterval(()=>{for(const[prefix,s]of Object.entries(last))render(prefix,s);},30000);
})();
