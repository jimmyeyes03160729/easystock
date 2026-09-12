/* Learning panels R1: preserve the existing section anchor and daily IDs. */
(() => {
  const root=document.getElementById('learningSection');
  if(!root)return;
  const style=document.createElement('style');
  style.textContent=`
  #learningSection .learning-columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);border-top:1px solid var(--border)}
  #learningSection .learning-column{min-width:0;padding:26px 24px 6px 0}
  #learningSection .learning-column+.learning-column{border-left:1px dashed var(--border);padding:26px 0 6px 24px}
  #learningSection .learning-column-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:18px}
  #learningSection .learning-column h3{font-size:21px;margin:0 0 7px;font-weight:850;line-height:1.4}
  #learningSection .learning-column-head p{color:var(--sub);font-size:12px;margin:0;line-height:1.6}
  #learningSection .learning-column .phase-badge{font-size:12px;white-space:normal;text-align:center;flex-shrink:0;max-width:45%;line-height:1.5}
  #learningSection .learning-numbers{grid-template-columns:repeat(2,minmax(0,1fr))}
  #learningSection .learning-numbers>div{padding:16px 12px;min-width:0}
  #learningSection .learning-numbers>div:nth-child(2n){border-right:0}
  #learningSection .learning-numbers>div:nth-child(-n+2){border-bottom:1px dashed var(--border)}
  #learningSection .learning-numbers strong{font-size:clamp(25px,2.3vw,34px);overflow-wrap:anywhere}
  #learningSection .learning-numbers small{line-height:1.7}
  #learningSection .learning-bottom{grid-template-columns:1fr;gap:12px;padding-top:18px}
  #learningSection .learning-bottom b{font-size:14px;line-height:1.7}
  #learningSection .learning-bottom p{line-height:1.8;overflow-wrap:anywhere}
  #learningSection progress{appearance:none;-webkit-appearance:none;display:block;margin:12px 0;background:var(--border);border:0;border-radius:0;color:var(--main)}
  #learningSection progress::-webkit-progress-bar{background:var(--border)}
  #learningSection progress::-webkit-progress-value{background:var(--main)}
  #learningSection progress::-moz-progress-bar{background:var(--main)}
  #learningSection .learning-results{border-top:1px dashed var(--border);padding-top:12px}
  #learningSection .learning-results span{display:block;font-size:12px;color:var(--sub);line-height:1.9}
  #learningSection details p{line-height:1.9}
  @media(max-width:900px){#learningSection .learning-columns{grid-template-columns:1fr}#learningSection .learning-column{padding:22px 0}#learningSection .learning-column+.learning-column{padding:22px 0 0;border-left:0;border-top:1px solid var(--border)}}
  `;
  document.head.appendChild(style);
  root.innerHTML=`
  <div class="learning-head"><div><div class="eyebrow">收盤進修 / LEARNING LOG</div><h2 id="learningTitle">牛馬 AI 進修打卡</h2></div></div>
  <div class="learning-columns">
    <article class="learning-column" aria-labelledby="dailyLearningTitle">
      <header class="learning-column-head"><div><h3 id="dailyLearningTitle">每日資料訓練</h3><p>每天收盤，把今天的經驗留下來。</p></div><span id="learningPhase" class="phase-badge" role="status">等待每日資料</span></header>
      <div class="learning-numbers">
        <div><span>累積有效學習日</span><strong id="learnDays">—</strong><small>同一交易日只計一次</small></div>
        <div><span>今日有效學習股數</span><strong id="learnStocks">—</strong><small>有效樣本中的不重複股票</small></div>
        <div><span>今日有效樣本</span><strong id="learnSamples">—</strong><small>樣本筆數不等於股票檔數</small></div>
        <div><span>今日行情收集</span><strong id="learnCoverage">—</strong><small id="learnCoverageNote">等待收盤報告</small></div>
      </div>
      <div class="learning-bottom"><div><b id="learnModel">當沖模型：尚未取得執行狀態</b><p id="learnTraining">訓練進度待確認</p><progress id="learnProgress" max="101" value="0" aria-label="每日資料有效日期進度"></progress></div><div><b id="learnAI">今日 AI 復盤：待確認</b><p id="learnUpdated">尚未收到更新</p><p id="learnError" role="status"></p></div></div>
      <details><summary>每天有資料，就算模型已更新嗎？</summary><p>收集、標記與模型訓練是不同階段。訓練達標後仍需驗證，只有當沖引擎確認載入的版本才算已套用。</p><p id="learnLastReport"></p></details>
    </article>
    <article class="learning-column" aria-labelledby="historyLearningTitle">
      <header class="learning-column-head"><div><h3 id="historyLearningTitle">歷史資料訓練</h3><p>回看過去行情，先練習，再驗證。</p></div><span id="historyPhase" class="phase-badge" role="status">等待歷史資料</span></header>
      <div class="learning-numbers">
        <div><span>本次已處理股票日</span><strong id="historyProcessed">—</strong><small id="historyProcessedNote">一檔股票一天算一個股票日</small></div>
        <div><span>有效標記日期</span><strong id="historyDays">—</strong><small>與左側每日學習日分開計算</small></div>
        <div><span>有效標記樣本</span><strong id="historySamples">—</strong><small>通過檢查的歷史觀察窗口</small></div>
        <div><span>測試樣本</span><strong id="historyTestSamples">—</strong><small>按日期保留，未參與模型訓練</small></div>
      </div>
      <div class="learning-bottom"><div><b id="historyModel">當沖同步：尚未取得歷史訓練摘要</b><p id="historyTraining">等待 VM 發布進度</p><progress id="historyProgress" max="100" value="0" aria-label="歷史股票日處理進度"></progress><p id="historyDownload">歷史下載進度：待確認</p></div>
      <div class="learning-results"><b>15 分鐘報價表現實驗</b><span id="historyResult">完成後顯示模型篩選樣本的測試結果</span><span id="historyBaseline">這不是實際成交勝率</span><p id="historyUpdated">尚未收到更新</p><p id="historyError" role="status"></p></div></div>
      <details><summary>歷史訓練完成，會直接推薦股票嗎？</summary><p>不會。這是獨立的 15 分鐘報價表現實驗，扣除假設成本，不含實盤停利停損與完整持倉管理。模型分數不是當沖勝率，也不會把歷史日期加到每日學習天數。</p><p id="historyRunNote">每次執行只統計該次資料；結果仍需後續驗證。</p></details>
    </article>
  </div>`;
})();
/* Public summaries only. No credentials, tokens or broker calls in this page. */
(() => {
  const get=id=>document.getElementById(id),put=(id,value)=>{const n=get(id);if(n)n.textContent=value;};
  const fmt=n=>typeof n==='number'&&Number.isFinite(n)?n.toLocaleString('zh-TW'):'—';
  const day=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Taipei'}).format(new Date());
  const date=x=>Number.isFinite(Date.parse(x))?new Date(x).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'}):'未提供';
  let busy=false,last=null;
  function render(s){
    const elapsed=Date.now()-Date.parse(s.updated_at),fresh=Number.isFinite(elapsed)&&elapsed>=-60000&&elapsed<180000;
    const today=s.today?.date===day()?s.today:null,tot=s.totals||{},tr=s.training||{};
    put('learningPhase',fresh?({collecting:'盤中收集中',reviewing:'盤後復盤中',training:'模型訓練中',idle:'目前待命',failed:'服務異常',unknown:'執行狀態待確認'})[s.phase]||'狀態待確認':'更新逾時 · 狀態待確認');
    put('learnDays',fmt(tot.learning_days));put('learnStocks',fmt(today?.learned_stocks));put('learnSamples',fmt(today?.labeled_count));
    put('learnCoverage',today?.requested!=null?`${fmt(today.downloaded)} / ${fmt(today.requested)}`:'—');
    put('learnCoverageNote',today?`盤中觀察 ${fmt(today.observed_stocks)} 檔 · ${today.report_status==='partial'?'部分完成':today.report_status==='ready'?'復盤完成':'等待完整報告'}`:'今天尚未收到資料');
    const app=s.model_application||{};
    put('learnModel',app.status==='not_applied'?'當沖模型：尚未套用學習成果':'當沖模型：執行版本待確認');
    put('learnTraining',`同設定有效日期 ${fmt(tot.training_days)} / 101 · 樣本 ${fmt(tot.training_samples)} / 1,000 · ${tr.status==='candidate_only'?'候選模型待驗證':tr.status==='blocked'?'尚未達訓練條件':'尚未取得訓練結果'}`);
    get('learnProgress').value=Math.min(101,tot.training_days||0);
    put('learnAI',`今日 AI 復盤：${({ok:'完成',failed:'失敗',skipped:'尚未執行'})[today?.ai_status]||'等待資料'}`);
    put('learnUpdated',`最後狀態更新：${date(s.updated_at)}`);
    put('learnLastReport',`最近復盤：${s.last_report?.date||'尚無'} · 累積資料收集日 ${fmt(tot.collection_days)}。未達訓練門檻不代表系統停止收集。`);
    put('learnError',fresh?(s.data_errors?.length?'部分統計檔無法讀取，數值可能不完整。':''):'目前顯示最後收到的資料，不代表服務仍在執行。');
    const o=s.overnight||{};
    put('overnightHealth',`資料來源：Fugle 排程 · 最後掃描 ${date(o.generated_at)} · 原始候選 ${fmt(o.candidate_count)} 檔 · ${o.scan_date===day()?'今日報告':'尚無今日報告'}${o.enabled===false?' · 掃描被停用':''}`);
  }
  async function refresh(){
    if(busy)return;busy=true;
    const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),12000);
    try{
      const res=await fetch(`${FIREBASE_ROOT}/daytrade_learning_status.json`,{cache:'no-store',signal:abort.signal});
      if(!res.ok)throw new Error(res.status===401||res.status===403?'無法讀取學習摘要，請確認 Firebase 公開讀取規則。':'學習摘要暫時無法讀取。');
      const s=await res.json();if(!s||s.schema_version!==1)throw new Error('等待 VM 發布學習摘要；不以安裝天數推算學習進度。');
      last=s;render(s);
    }catch(e){if(last)render(last);put('learnError',e.name==='AbortError'?'讀取逾時，請稍後重試。':e.message);put('learningPhase','連線待確認');}
    finally{clearTimeout(timer);busy=false;}
  }
  refresh();setInterval(refresh,60000);setInterval(()=>{if(last&&!busy)render(last);},30000);
})();

/* Independent history summary: never inherit a previous run's result. */
(() => {
  const get=id=>document.getElementById(id),put=(id,v)=>{const n=get(id);if(n)n.textContent=v;};
  const valid=n=>typeof n==='number'&&Number.isFinite(n)&&n>=0;
  const fmt=n=>valid(n)?n.toLocaleString('zh-TW'):'—';
  const pct=n=>typeof n==='number'&&Number.isFinite(n)?`${(n*100).toFixed(1)}%`:'—';
  const mean=n=>typeof n==='number'&&Number.isFinite(n)?`${n>0?'+':''}${n.toFixed(3)}%`:'—';
  const date=x=>typeof x==='string'&&Number.isFinite(Date.parse(x))?new Date(x).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'}):'未提供';
  const phaseNames={not_started:'尚未開始',snapshotting:'盤點歷史資料',replaying:'歷史重播中',training:'模型訓練中',completed:'本次處理完成',interrupted:'程序已中斷',failed:'本次執行失敗',unknown:'狀態待確認'};
  const reasonNames={insufficient_dates:'有效標記日期不足',insufficient_samples:'樣本數或正反例不足',dependency_missing:'訓練環境缺少依賴',other:'尚未符合訓練條件'};
  let busy=false,last=null;
  function render(s){
    const elapsed=Date.now()-Date.parse(s.updated_at),fresh=Number.isFinite(elapsed)&&elapsed>=-60000&&elapsed<180000;
    const r=s.run||{},t=s.training||{},a=s.archive||{};
    put('historyPhase',fresh?(phaseNames[r.state]||'狀態待確認'):'更新逾時 · 狀態待確認');
    put('historyProcessed',`${fmt(r.processed_files)} / ${fmt(r.archive_files)}`);
    put('historyProcessedNote',valid(r.archive_files)?'本次凍結的可用資料，不是完整下載目標':'一檔股票一天算一個股票日');
    put('historyDays',fmt(r.labeled_dates));put('historySamples',fmt(r.labeled_samples));put('historyTestSamples',fmt(t.test_samples));
    if(get('historyProgress'))get('historyProgress').value=valid(r.processed_files)&&r.archive_files>0?Math.min(100,100*r.processed_files/r.archive_files):0;
    put('historyModel',s.model_application?.status==='not_applied'?'當沖同步：尚未套用歷史模型':'當沖同步：尚待確認');
    const trainingText=t.status==='experimental_candidate'?'實驗模型已產生 · 等待後續驗證':t.status==='blocked'?`未產生模型 · ${reasonNames[t.reason_code]||reasonNames.other}`:r.state==='training'?'正在訓練與測試':r.state==='replaying'?'先建立特徵與標記，完成後再訓練':'尚未取得本次訓練結果';
    put('historyTraining',trainingText);
    const stop={quota_exhausted:'額度用完，下載暫停',quota_reserve:'保留額度，下載暫停',pair_limit:'分批處理',run_budget:'本批流量上限',pair_failed_inspect_before_retry:'有失敗紀錄',pair_limit_or_plan_complete:'本批結束'}[a.stop_reason]||'下載狀態見 VM';
    put('historyDownload',`歷史下載：${fmt(a.archived_stock_days)} / ${fmt(a.target_stock_days)} 股票日 · 失敗 ${fmt(a.failed_stock_days)} · ${stop}`);
    const m=t.model_selected,b=t.all_windows;
    put('historyResult',m?`模型篩選 ${fmt(m.samples)} 筆 · 正報價表現率 ${pct(m.positive_markout_rate)} · 平均 ${mean(m.mean_net_markout_pct)}`:'尚無本次模型測試結果');
    put('historyBaseline',b?`全部測試窗口 ${fmt(b.samples)} 筆 · 平均 ${mean(b.mean_net_markout_pct)}；非實際成交勝率`:'固定持有約 15 分鐘，扣除 0.6 個百分點假設成本；非實際成交勝率');
    put('historyUpdated',`摘要更新：${date(s.updated_at)}`);
    put('historyRunNote',r.started_at?`本次開始：${date(r.started_at)}。不合併成每日實際學習天數。`:'等待本次執行資訊。');
    put('historyError',!fresh?'目前顯示最後收到的資料，不代表程序仍在執行。':s.data_errors?.length?'部分摘要無法確認，請查看 VM 狀態。':'');
  }
  async function refresh(){
    if(busy||!get('historyPhase'))return;busy=true;
    const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),12000);
    try{
      const response=await fetch(`${FIREBASE_ROOT}/history_training_status.json`,{cache:'no-store',signal:abort.signal});
      if(!response.ok)throw new Error(response.status===401||response.status===403?'歷史摘要讀取未授權，請確認此摘要節點的 Firebase 規則。':'歷史摘要暫時無法讀取。');
      const s=await response.json();if(!s||s.schema_version!==1)throw new Error('等待 VM 發布歷史訓練摘要。');
      last=s;render(s);
    }catch(e){if(last)render(last);put('historyPhase','連線待確認');put('historyError',e.name==='AbortError'?'歷史摘要讀取逾時。':e.message);}
    finally{clearTimeout(timer);busy=false;}
  }
  refresh();setInterval(refresh,60000);setInterval(()=>{if(last&&!busy)render(last);},30000);
})();

/* Independent daily Gemini + OpenAI review. Only sanitized public summaries. */
(() => {
  const host=document.getElementById('learningSection');if(!host)return;
  const style=document.createElement('style');
  style.textContent=`#dualReview{margin-top:26px;border-top:2px solid var(--main);padding-top:24px}#dualReview h3{font-size:23px;margin:0 0 8px}#dualReview h4{font-size:16px;margin:0 0 10px}#dualReview .dual-head{display:flex;gap:16px;justify-content:space-between;align-items:flex-start}#dualReview p{font-size:13px;line-height:1.85;color:var(--sub);overflow-wrap:anywhere}#dualReview .dual-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;margin-top:18px}#dualReview .dual-card{border:1px solid var(--border);padding:18px;min-width:0}#dualReview .dual-card>p:first-of-type{color:var(--main)}#dualReview .dual-meta{font-size:12px}#dualReview ul{padding-left:18px;font-size:13px;line-height:1.9;overflow-wrap:anywhere}#dualReview .dual-compare{margin-top:18px;padding:18px;border:1px dashed var(--border)}#dualReview .dual-compare>div{margin-bottom:18px}#dualReview .dual-compare>div:last-child{margin-bottom:0}#dualReview .dual-facts{font-variant-numeric:tabular-nums;padding:10px 0;border-bottom:1px dashed var(--border)}@media(max-width:900px){#dualReview .dual-grid{grid-template-columns:1fr}#dualReview .dual-head{flex-direction:column}}`;
  document.head.appendChild(style);
  const section=document.createElement('section');section.id='dualReview';section.setAttribute('aria-labelledby','dualTitle');
  section.innerHTML=`<header class="dual-head"><div><div class="eyebrow">收盤雙重復盤 / SECOND OPINION</div><h3 id="dualTitle">Gemini × OpenAI 雙重復盤</h3><p id="dualDate">等待收盤復盤摘要</p></div><span class="phase-badge" id="dualPhase" role="status">尚未收到資料</span></header>
  <p class="dual-facts" id="dualFacts">只分析同一份收盤統計，兩邊先獨立回答，再交叉比對。</p>
  <div class="dual-grid"><article class="dual-card"><h4>Gemini 復盤</h4><p id="dualGeminiSummary">等待分析</p><p class="dual-meta" id="dualGeminiMeta">—</p><details><summary>查看待驗證研究方向</summary><ul id="dualGeminiIdeas"></ul></details></article><article class="dual-card"><h4>OpenAI 復盤</h4><p id="dualOpenaiSummary">等待分析</p><p class="dual-meta" id="dualOpenaiMeta">—</p><details><summary>查看待驗證研究方向</summary><ul id="dualOpenaiIdeas"></ul></details></article></div>
  <div class="dual-compare"><div><h4>共同研究方向</h4><ul id="dualAgreement"><li>等待雙方完成</li></ul></div><div><h4>意見分歧</h4><ul id="dualDisagreement"><li>等待交叉比對</li></ul></div><div><h4>證據不足</h4><ul id="dualInsufficient"><li>等待分析</li></ul></div><details><summary>指定數值判斷核對</summary><ul id="dualChecks"></ul><p>只核對指定題目與原始匯總數字是否相符，不代表所有文字、因果或策略效果已獲證實。</p></details></div>
  <p id="dualNotice">AI 共識只供研究；不會自動修改當沖規則或套用模型。</p><p id="dualError" role="status"></p>`;
  host.appendChild(section);
  const get=id=>document.getElementById(id),put=(id,v)=>{const n=get(id);if(n)n.textContent=v;};
  const fmt=n=>typeof n==='number'&&Number.isFinite(n)?n.toLocaleString('zh-TW'):'—';
  const date=v=>typeof v==='string'&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'}):'未提供';
  const statuses={ok:'分析完成',failed:'API 呼叫失敗',rejected:'回覆未通過檢查',missing_config:'缺少金鑰或模型設定',daily_limit:'已達今日嘗試上限',monthly_limit:'已達本月呼叫上限'};
  const stances={test:'待回測',hold:'暫不優先',insufficient:'證據不足'};
  const titles={data_quality:'資料品質',gain_filter:'進場漲幅條件',volume_confirmation:'量能確認',vwap_filter:'VWAP 條件'};
  function list(id,rows,empty){const n=get(id);if(!n)return;n.replaceChildren();for(const line of rows.length?rows:[empty]){const li=document.createElement('li');li.textContent=line;n.appendChild(li);}}
  function render(s){
    put('dualPhase',({complete:'雙方完成 · 已比對',partial:'部分完成',waiting_report:'等待當日報告',no_samples:'當日沒有觀察樣本'})[s.status]||'狀態待確認');
    put('dualDate',`資料日期：${s.date||'未提供'} · 摘要更新：${date(s.updated_at)}`);
    const f=s.facts||{};
    put('dualFacts',`觀察樣本 ${fmt(f.sample_count)} · 有效標記 ${fmt(f.labeled_count)} · 行情收集 ${fmt(f.downloaded)} / ${fmt(f.requested)}。數值由程式讀取報告，不由 AI 推估。`);
    for(const [key,part] of [['gemini','Gemini'],['openai','Openai']]){
      const p=s.providers?.[key]||{},review=p.status==='ok'?p.review:null;
      put('dual'+part+'Summary',review?.summary||statuses[p.status]||'等待分析');
      put('dual'+part+'Meta',`${p.model||'模型待確認'} · ${statuses[p.status]||'尚未執行'} · ${p.source==='cache'?'沿用同資料快取':p.source==='api'?'本次 API 呼叫':'未呼叫'}${p.http_status?' · HTTP '+p.http_status:''}${p.error_type?' · '+p.error_type:''}`);
      list('dual'+part+'Ideas',(review?.hypotheses||[]).map(x=>`${titles[x.id]||x.id}：${stances[x.stance]||'待確認'}。${x.reason||''}`),'尚無研究方向');
    }
    const c=s.comparison||{},paired=c.status==='compared';
    list('dualAgreement',paired?(c.agreements||[]).map(x=>`${x.title}：雙方${stances[x.stance]||'待確認'}`):[],paired?'沒有共同研究方向':'尚未完成雙方比對');
    list('dualDisagreement',paired?(c.disagreements||[]).map(x=>`${x.title}：Gemini ${stances[x.gemini]}／OpenAI ${stances[x.openai]}`):[],paired?'本次指定研究方向沒有相反選擇':'等待雙方完成');
    list('dualInsufficient',paired?(c.insufficient||[]).map(x=>`${x.title}：至少一方認為資料不足`):[],paired?'指定題目未標示資料不足；仍不代表策略已驗證':'單方結果不能當成雙重確認');
    list('dualChecks',paired?(c.verified_observations||[]).map(x=>`${x.title} → ${({yes:'是',no:'否',insufficient:'資料不足'})[x.verdict]||'待確認'}`):[], '尚未完成雙方數值核對');
    put('dualError','');
  }
  let busy=false;
  async function refresh(){
    if(busy)return;busy=true;const a=new AbortController(),timer=setTimeout(()=>a.abort(),12000);
    try{const r=await fetch(`${FIREBASE_ROOT}/dual_review_status.json`,{cache:'no-store',signal:a.signal});if(!r.ok)throw new Error(r.status===401||r.status===403?'雙重復盤摘要讀取未授權。':'雙重復盤摘要暫時無法讀取。');const s=await r.json();if(!s||s.schema_version!==1)throw new Error('等待 VM 發布第一份雙重復盤。');render(s);}
    catch(e){put('dualPhase','連線待確認');put('dualError',e.name==='AbortError'?'讀取逾時；現有內容是先前收到的結果。':e.message);}
    finally{clearTimeout(timer);busy=false;}
  }
  refresh();setInterval(refresh,60000);
})();
