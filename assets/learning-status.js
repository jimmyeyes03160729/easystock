/* Public, quantitative post-close research summary.  No AI prose is required. */
(() => {
  const root = document.getElementById('learningSection');
  if (!root) return;
  const css = document.createElement('style');
  css.textContent = `
  #learningSection .learning-head{display:flex;justify-content:space-between;gap:12px;margin-bottom:18px;border-bottom:1px solid var(--border,#232f42);padding-bottom:12px}
  #learningSection .learning-columns{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid var(--border)}
  #learningSection .learning-column{min-width:0;padding:24px 24px 6px 0}
  #learningSection .learning-column+.learning-column{border-left:1px dashed var(--border);padding:24px 0 6px 24px}
  #learningSection .learning-column-head{display:flex;justify-content:space-between;gap:12px;margin-bottom:16px}
  #learningSection .learning-column h3{font-size:16px;margin:0 0 6px}
  #learningSection .learning-column-head p,#learningSection .research-summary p{color:var(--sub);font-size:12px;line-height:1.6;margin:0}
  #learningSection .learning-numbers{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}
  #learningSection .learning-numbers>div{padding:12px;border-bottom:1px dashed var(--border);min-width:0}
  #learningSection .learning-numbers strong{display:block;font:800 18px "JetBrains Mono",monospace;margin-top:5px;white-space:nowrap}
  #learningSection .learning-numbers small{display:block;color:var(--sub);font-size:11px;margin-top:3px}
  #learningSection .learning-bottom{display:grid;gap:10px;padding-top:16px}
  #learningSection progress{display:block;width:100%;margin:10px 0;accent-color:var(--accent,#f59e0b)}
  #learningSection .research-summary{margin-top:26px;border-top:2px solid var(--main);padding-top:22px}
  #learningSection .research-summary h3{font-size:23px;margin:0 0 8px}
  #learningSection .research-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:18px}
  #learningSection .research-card{border:1px solid var(--border);padding:15px;min-width:0}
  #learningSection .research-card h4{margin:0 0 10px;font-size:14px;color:var(--accent,#f59e0b)}
  #learningSection .research-card div{font-size:13px;line-height:1.9;overflow-wrap:anywhere}
  #learningSection .research-exits{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:1fr 1fr;gap:2px 12px}
  #learningSection .research-stale{border:1px solid #b45309;color:#fbbf24;padding:10px;margin-top:14px;font-size:12px;line-height:1.6}
  @media(max-width:900px){#learningSection .learning-columns,#learningSection .research-grid{grid-template-columns:1fr}#learningSection .learning-column,#learningSection .learning-column+.learning-column{padding:22px 0;border-left:0} }
  `;
  document.head.appendChild(css);
  root.innerHTML = `
    <div class="learning-head"><div><h2 id="learningTitle">盤後研究與模型狀態</h2><p style="color:var(--sub);font-size:12px;margin:4px 0 0">只顯示實際交易、樣本、標記與驗證證據；文字 AI review 不代表模型訓練或部署成功。</p></div></div>
    <div class="learning-columns">
      <article class="learning-column"><header class="learning-column-head"><div><h3>每日資料訓練</h3><p id="dailyLearningDate">等待最近交易日資料</p></div><span id="learningPhase" class="phase-badge" role="status">待資料</span></header>
        <div class="learning-numbers"><div><span>累積學習日</span><strong id="learnDays">—</strong></div><div><span>今日推薦</span><strong id="learnStocks">—</strong></div><div><span>觀察股票</span><strong id="learnObserved">—</strong></div><div><span>完成 Label</span><strong id="learnLearned">—</strong></div><div><span>研究樣本</span><strong id="learnSamples">—</strong></div><div><span>資料收集</span><strong id="learnCoverage">—</strong></div></div>
        <div class="learning-bottom"><b id="learnModel">模型狀態：待確認</b><p id="learnTraining">等待研究摘要</p><progress id="learnProgress" max="101" value="0"></progress><p id="learnUpdated">最後更新：未提供</p><p id="learnError" role="status"></p></div>
      </article>
      <article class="learning-column"><header class="learning-column-head"><div><h3>歷史資料訓練</h3><p>歷史訓練與當日研究分開計算。</p></div><span id="historyPhase" class="phase-badge" role="status">待資料</span></header>
        <div class="learning-numbers"><div><span>處理股票日</span><strong id="historyProcessed">—</strong></div><div><span>有效標記日</span><strong id="historyDays">—</strong></div><div><span>歷史樣本</span><strong id="historySamples">—</strong></div><div><span>Holdout 樣本</span><strong id="historyTestSamples">—</strong></div></div>
        <div class="learning-bottom"><b id="historyModel">歷史模型：待確認</b><p id="historyTraining">等待 VM 發布進度</p><progress id="historyProgress" max="100" value="0"></progress><p id="historyDownload">歷史下載：待確認</p><p id="historyResult">尚無本次測試結果</p><p id="historyBaseline">非實際成交勝率</p><p id="historyUpdated">摘要更新：未提供</p><p id="historyError" role="status"></p></div>
      </article>
    </div>
    <section id="researchSummary" class="research-summary" aria-labelledby="researchSummaryTitle"><header><div class="eyebrow">QUANTITATIVE POST-CLOSE REPORT</div><h3 id="researchSummaryTitle">每日盤後研究摘要</h3><p id="researchSummaryDate">最近交易日：待資料 · 最後更新：未提供</p></header><div id="researchStale" class="research-stale" hidden>資料已過期，以下為最後一次紀錄，不代表服務目前仍在執行。</div>
      <div class="research-grid"><article class="research-card"><h4>有效研究交易</h4><div id="researchTrades">研究交易：待資料</div><div id="researchClosed">研究完成：待資料</div><div id="researchPaperFilled">Paper 成交：待資料</div><div id="researchPaperSkipped">Paper 略過：待資料</div><div id="researchPaperCash">Paper 資金不足：待資料</div><div id="researchWins">獲利：待資料</div><div id="researchLosses">虧損：待資料</div><div id="researchPnl">研究淨報酬合計：待資料</div><div id="researchReturn">研究毛報酬合計：待資料</div><div id="researchAvg">平均單筆：待資料</div><div id="researchMfe">MFE：待資料</div><div id="researchMae">MAE：待資料</div><small>各研究 episode 的百分比相加；淨報酬假設一張及交易成本，不代表帳戶資金報酬。</small></article>
        <article class="research-card"><h4>研究資料與模型</h4><div id="researchSamples">新增樣本：待資料</div><div id="researchLabels">完成 Label：待資料</div><div id="researchCoverage">收集完整度：待資料</div><div id="researchFreshness">資料狀態：待資料</div><div id="researchVersion">模型版本：待確認</div><div id="researchMode">模型模式：待確認</div><div id="researchModelState">模型狀態：UNKNOWN</div><div id="researchTrained">trained_through：待提供</div><div id="researchRuntime">Runtime 已載入：待確認 · 引擎使用：待確認</div></article>
        <article class="research-card"><h4>模型驗證</h4><div id="researchValidation">Validation：待資料</div><div id="researchBrier">Brier：待提供</div><div id="researchPf">Profit Factor：待提供</div><div id="researchDrawdown">Drawdown：待提供</div><div id="researchWalkForward">Walk-forward：待提供</div><div id="researchHoldout">Holdout：待提供</div></article>
        <article class="research-card"><h4>Exit Reason</h4><ul id="researchExits" class="research-exits"><li>待資料</li></ul></article>
      </div><p id="researchError" role="status"></p>
    </section>`;
})();

(() => {
  const $ = id => document.getElementById(id), put = (id, value) => { const n = $(id); if (n) n.textContent = value; };
  const num = v => typeof v === 'number' && Number.isFinite(v) ? v : null;
  const fmt = v => num(v) === null ? '待資料' : v.toLocaleString('zh-TW');
  const pct = v => num(v) === null ? '待資料' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
  const date = v => typeof v === 'string' && Number.isFinite(Date.parse(v)) ? new Date(v).toLocaleString('zh-TW', {timeZone:'Asia/Taipei'}) : '未提供';
  const fresh = v => { const age = Date.now() - Date.parse(v); return Number.isFinite(age) && age >= -60000 && age < 180000; };
  const today = () => new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Taipei'}).format(new Date());
  const setList = (id, rows) => { const n=$(id); if(!n)return; n.replaceChildren(); (rows.length ? rows : ['待資料']).forEach(x => { const li=document.createElement('li'); li.textContent=x; n.appendChild(li); }); };
  const state = s => { const a=s.model_application||{}, t=s.training||{}, explicit=a.status; if(explicit==='blocked'||t.status==='blocked')return 'BLOCKED'; if(a.runtime_used===true)return 'PAPER APPLIED'; if(a.status==='approved')return 'APPROVED'; if(t.status==='candidate'||t.status==='experimental_candidate')return 'CANDIDATE'; if(a.entry_mode==='shadow')return 'SHADOW'; if(a.entry_mode==='rules')return 'RULES'; return 'UNKNOWN'; };
  function render(s) {
    const isFresh=fresh(s.updated_at), session=s.session||{}, t=s.totals||{}, app=s.model_application||{}, tr=s.training||{}, r=s.research_summary||{};
    const d=session.date||r.date;
    put('dailyLearningDate', d ? `最近交易日：${d}` : '等待最近交易日資料');
    put('learningPhase', isFresh ? ({collecting:'收集資料中',reviewing:'盤後研究中',training:'訓練中',idle:'待命',failed:'服務異常'}[s.phase]||'狀態待確認') : '更新逾時 · 狀態待確認');
    put('learnDays',fmt(t.learning_days)); put('learnStocks',fmt(session.recommended_stocks)); put('learnObserved',fmt(session.observed_stocks)); put('learnLearned',fmt(session.learned_stocks)); put('learnSamples',fmt(session.sample_count)); put('learnCoverage',session.requested!=null?`${fmt(session.downloaded)} / ${fmt(session.requested)}`:'待資料');
    put('learnModel',`模型狀態：${state(s)} · 不以訓練日期推定部署`); put('learnTraining',`訓練樣本：${fmt(t.training_samples)} · 截止：${tr.trained_through||'待提供'}`); if($('learnProgress'))$('learnProgress').value=Math.min(101,t.training_days||0); put('learnUpdated',`最後更新：${date(s.updated_at)}`); put('learnError',isFresh?'': '資料已過期，以上為最後一次紀錄。');
    const trades=r.trades||{};
    put('researchSummaryDate',`最近交易日：${d||'待資料'} · 最後更新：${date(s.updated_at)}`); put('researchTrades',`研究交易：${fmt(trades.research_trades??trades.count)}`); put('researchClosed',`研究完成：${fmt(trades.research_closed??trades.count)}`); put('researchPaperFilled',`Paper 成交：${fmt(trades.paper_filled)}`); put('researchPaperSkipped',`Paper 略過：${fmt(trades.paper_skipped)}`); put('researchPaperCash',`Paper 額度不足：${fmt(trades.paper_skipped_daily_buy_limit)} · 舊現金不足：${fmt(trades.paper_skipped_insufficient_cash)}`); put('researchWins',`獲利：${fmt(trades.wins)}`); put('researchLosses',`虧損：${fmt(trades.losses)}`); put('researchPnl',`研究淨報酬合計：${pct(trades.net_pnl_pct)}`); put('researchReturn',`研究毛報酬合計：${pct(trades.gross_pnl_pct)}`); put('researchAvg',`平均單筆：${pct(trades.avg_pnl_pct)}`); put('researchMfe',`MFE：${pct(trades.avg_mfe_pct)}`); put('researchMae',`MAE：${pct(trades.avg_mae_pct)}`);
    put('researchSamples',`新增樣本：${fmt(r.new_samples??session.sample_count)}`); put('researchLabels',`完成 Label：${fmt(r.labels??session.labeled_count)}`); put('researchCoverage',`收集完整度：${r.requested!=null?`${fmt(r.downloaded)} / ${fmt(r.requested)}`:'待資料'}`); put('researchFreshness',`資料狀態：${isFresh?'正常':'過期 / 待確認'}`); put('researchVersion',`模型版本：${app.model_version||'未提供'}`); put('researchMode',`模型模式：${app.entry_mode||'未提供'}`); put('researchModelState',`模型狀態：${state(s)}`); put('researchTrained',`trained_through：${tr.trained_through||'未提供'}`); put('researchRuntime',`Runtime 已載入：${app.runtime_loaded===true?'是':app.runtime_loaded===false?'否':'待確認'} · 引擎使用：${app.runtime_used===true?'是':app.runtime_used===false?'否':'待確認'}`);
    const v=r.validation||tr.validation||{}; put('researchValidation',`Validation：${v.status||tr.status||'待提供'}`); put('researchBrier',`Brier：${num(v.brier)===null?'待提供':v.brier.toFixed(5)}`); put('researchPf',`Profit Factor：${num(tr.profit_factor??trades.profit_factor)===null?'待提供':(tr.profit_factor??trades.profit_factor).toFixed(3)}`); put('researchDrawdown',`Drawdown：${num(tr.max_drawdown_pct??trades.max_drawdown_pct)===null?'待提供':pct(tr.max_drawdown_pct??trades.max_drawdown_pct)}`); put('researchWalkForward',`Walk-forward：${v.validation_mode==='full_walk_forward'?'已完成':'待提供'}`); put('researchHoldout',`Holdout：${v.test_samples!=null?fmt(v.test_samples):'待提供'}`); setList('researchExits',Object.entries(trades.exit_reasons||{}).map(([k,v])=>`${k} ${fmt(v)}`)); $('researchStale').hidden=isFresh; put('researchError',s.data_errors?.length?'部分資料無法讀取，數值可能不完整。':'');
  }
  let last=null,busy=false;
  async function refresh(){ if(busy)return; busy=true; const a=new AbortController(), timer=setTimeout(()=>a.abort(),12000); try { const response=await fetch(`${FIREBASE_ROOT}/daytrade_learning_status.json`,{cache:'no-store',signal:a.signal}); if(!response.ok)throw Error('盤後研究摘要讀取失敗。'); const s=await response.json(); if(!s||s.schema_version!==1)throw Error('等待 VM 發布盤後研究摘要。'); last=s; render(s); } catch(e) { if(last)render(last); put('researchError',e.name==='AbortError'?'讀取逾時。':e.message); put('learningPhase','連線待確認'); } finally {clearTimeout(timer);busy=false;} }
  refresh(); setInterval(refresh,60000); setInterval(()=>{if(last&&!busy)render(last)},30000);
})();

/* History is a separate public status node and never inherits daily results. */
(() => {
  const $=id=>document.getElementById(id), put=(id,v)=>{const n=$(id);if(n)n.textContent=v;}, fmt=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('zh-TW'):'—', date=v=>typeof v==='string'&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'}):'未提供';
  const names={not_started:'尚未開始',snapshotting:'盤點歷史資料',replaying:'歷史重播中',training:'模型訓練中',completed:'本次處理完成',interrupted:'程序已中斷',failed:'本次執行失敗'}; let last=null,busy=false;
  function render(s){const age=Date.now()-Date.parse(s.updated_at),fresh=Number.isFinite(age)&&age<180000,r=s.run||{},t=s.training||{},a=s.archive||{},app=s.model_application||{}; put('historyPhase',fresh?(names[r.state]||'狀態待確認'):'更新逾時 · 狀態待確認'); put('historyProcessed',`${fmt(r.processed_files)} / ${fmt(r.archive_files)}`); put('historyDays',fmt(r.labeled_dates)); put('historySamples',fmt(r.labeled_samples)); put('historyTestSamples',fmt(t.test_samples)); if($('historyProgress'))$('historyProgress').value=r.archive_files>0?Math.min(100,100*r.processed_files/r.archive_files):0; put('historyModel',`歷史模型：${app.model_version||'待確認'} · 狀態 ${app.status||'UNKNOWN'}`); put('historyTraining',`訓練：${t.status||'待資料'} · trained_through：${t.trained_through||'未提供'}`); put('historyDownload',`歷史下載：${fmt(a.archived_stock_days)} / ${fmt(a.target_stock_days)} · ${a.stop_reason||'待確認'}${a.available_start?`。每天 14:00 續抓、22:10 離線訓練；規劃至 ${a.planned_start||'待更新'}，最早 ${a.available_start}；2010～2020 缺口不能由此 API 補齊`:''}`); put('historyResult',t.model_selected?`模型篩選 ${fmt(t.model_selected.samples)} 筆 · 正報價表現率 ${typeof t.model_selected.positive_markout_rate==='number'?(t.model_selected.positive_markout_rate*100).toFixed(1)+'%':'—'}`:'尚無本次測試結果'); put('historyBaseline','歷史測試非實際成交勝率'); put('historyUpdated',`摘要更新：${date(s.updated_at)}`); put('historyError',fresh?(s.data_errors?.length?'部分摘要無法確認。':''):'目前顯示最後紀錄，不代表程序仍在執行。'); }
  async function refresh(){if(busy||!$('historyPhase'))return;busy=true;try{const r=await fetch(`${FIREBASE_ROOT}/history_training_status.json`,{cache:'no-store'});if(!r.ok)throw Error('歷史摘要讀取未授權。');const s=await r.json();if(!s||s.schema_version!==1)throw Error('等待 VM 發布歷史訓練摘要。');last=s;render(s)}catch(e){if(last)render(last);put('historyError',e.message)}finally{busy=false}} refresh();setInterval(refresh,60000);
})();
