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
  #learningSection .learning-numbers>div:nth-child(-n+4){border-bottom:1px dashed var(--border)}
  #learningSection .learning-numbers strong{font-size:clamp(25px,2.3vw,34px);overflow-wrap:anywhere}
  #learningSection .learning-numbers small{line-height:1.7}
  #learningSection .learning-bottom{grid-template-columns:1fr;gap:12px;padding-top:18px}
  #learningSection .learning-bottom b{font-size:14px;line-height:1.7}
  #learningSection .learning-bottom p{line-height:1.8;overflow-wrap:anywhere}
  #learningSection progress{appearance:none;-webkit-appearance:none;display:block;margin:12px 0;background:var(--border);border:0;border-radius:0;color:var(--main)}
  #learningSection progress::-webkit-progress-bar{background:var(--border)}
  #learningSection progress::-webkit-progress-value{background:var(--accent,#f59e0b)}
  #learningSection progress::-moz-progress-bar{background:var(--accent,#f59e0b)}
  #learningSection .learning-results{border-top:1px dashed var(--border);padding-top:12px}
  #learningSection .learning-results span{display:block;font-size:12px;color:var(--sub);line-height:1.9}
  #learningSection details p{line-height:1.9}
  @media(max-width:900px){#learningSection .learning-columns{grid-template-columns:1fr}#learningSection .learning-column{padding:22px 0}#learningSection .learning-column+.learning-column{padding:22px 0 0;border-left:0;border-top:1px solid var(--border)}}
  `;
  document.head.appendChild(style);
  root.innerHTML=`
  <div class="learning-head">
    <div>
      <div class="eyebrow">收盤加班進修 / DRONE SURVIVAL LOG</div>
      <h2 id="learningTitle">🐮 牛馬 AI 加班進修打卡室</h2>
      <p style="color:var(--sub);font-size:13px;margin:4px 0 0">白天當沖摸魚被主力修理，晚上留在工位加班覆盤；不求暴富，只求換個便當與湊齊離職自由金。</p>
    </div>
  </div>
  <div class="learning-columns">
    <article class="learning-column" aria-labelledby="dailyLearningTitle">
      <header class="learning-column-head">
        <div>
          <h3 id="dailyLearningTitle">每日資料訓練 · 工位自救</h3>
          <p id="dailyLearningDate">記住每一筆被割肉的痛，隔天開盤不再重蹈覆轍</p>
        </div>
        <span id="learningPhase" class="phase-badge" role="status">等待每日資料</span>
      </header>
      <div class="learning-numbers">
        <div><span>累積血汗進修日</span><strong id="learnDays">—</strong><small>同一交易日只計一次，不灌水</small></div>
        <div><span>今日摸魚推薦</span><strong id="learnStocks">—</strong><small>當沖引擎觸發推薦股票檔數</small></div>
        <div><span>盤中盯盤記錄</span><strong id="learnObserved">—</strong><small>主力急漲急跌留痕檔數</small></div>
        <div><span>收盤復盤學會</span><strong id="learnLearned">—</strong><small>完成有效特徵標記的股票</small></div>
        <div><span>有效自救樣本</span><strong id="learnSamples">—</strong><small>含進場急漲、停損出場真實特徵</small></div>
        <div><span>行情報價收集</span><strong id="learnCoverage">—</strong><small id="learnCoverageNote">等待收盤報告</small></div>
      </div>
      <div class="learning-bottom">
        <div>
          <b id="learnModel">當沖模型：載入中…</b>
          <p id="learnTraining">離職自救進修進度（目標 101 個交易日）</p>
          <progress id="learnProgress" max="101" value="0" aria-label="每日資料有效日期進度"></progress>
        </div>
        <div>
          <b id="learnAI">今日檢討週報：待確認</b>
          <p id="learnUpdated">尚未收到更新</p>
          <p id="learnError" role="status"></p>
        </div>
      </div>
      <details>
        <summary>💡 為什麼牛馬 AI 每天都要進修？</summary>
        <p>盤中即時記錄每一檔急漲特徵，收盤後標記勝率與停損停利。當沖模型隔天開盤會載入最新驗證版本，讓每一次被修理的經驗都轉化為防守武器。AI 復盤完成不代表勝率必然提高，但能防範盲目追高。</p>
        <p id="learnLastReport"></p>
      </details>
    </article>
    <article class="learning-column" aria-labelledby="historyLearningTitle">
      <header class="learning-column-head">
        <div>
          <h3 id="historyLearningTitle">歷史資料訓練 · 十年特訓</h3>
          <p>回看過去崩跌與大漲行情，在模擬沙盤中先被痛打一萬次。</p>
        </div>
        <span id="historyPhase" class="phase-badge" role="status">等待歷史資料</span>
      </header>
      <div class="learning-numbers">
        <div><span>已扒取歷史股票日</span><strong id="historyProcessed">—</strong><small id="historyProcessedNote">一檔股票一天算一個股票日</small></div>
        <div><span>有效標記交易日</span><strong id="historyDays">—</strong><small>與左側每日學習日分開計算</small></div>
        <div><span>歷史血淚觀察窗</span><strong id="historySamples">—</strong><small>通過安全檢查的歷史窗口</small></div>
        <div><span>盲測考卷樣本</span><strong id="historyTestSamples">—</strong><small>按日期保留，未參與模型訓練</small></div>
      </div>
      <div class="learning-bottom">
        <div>
          <b id="historyModel">當沖同步：尚未取得歷史訓練摘要</b>
          <p id="historyTraining">等待 VM 發布進度</p>
          <progress id="historyProgress" max="100" value="0" aria-label="歷史股票日處理進度"></progress>
          <p id="historyDownload">歷史下載進度：待確認</p>
        </div>
        <div class="learning-results">
          <b>15 分鐘極限報價實驗</b>
          <span id="historyResult">完成後顯示模型篩選樣本的測試結果</span>
          <span id="historyBaseline">這不是實際成交勝率</span>
          <p id="historyUpdated">尚未收到更新</p>
          <p id="historyError" role="status"></p>
        </div>
      </div>
      <details>
        <summary>📊 歷史訓練對我有什麼幫助？</summary>
        <p>歷史特訓能在不賠本金的前提下，驗證特徵在過去 6,600 個股票日的表現，替牛馬築起更嚴格的停損防護網。</p>
        <p id="historyRunNote">每次執行只統計該次資料；結果仍需後續驗證。</p>
      </details>
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
    const today=s.today?.date===day()?s.today:null,session=s.session||today||{},tot=s.totals||{},tr=s.training||{};
    const sessionDate=session?.date||null;
    const sessionLabel=sessionDate===day()?'今日交易日':'最近交易日';
    put('dailyLearningDate',sessionDate?`${sessionLabel}：${sessionDate} · 記住每一筆被割肉的痛`:'等待最近交易日資料');
    put('learningPhase',fresh?({collecting:'🏃 工位摸魚看盤中',reviewing:'📑 盤後留下來寫檢討週報',training:'💡 深夜模型再進修（自救訓練中）',idle:'☕ 裝忙待命中',failed:'服務異常',unknown:'執行狀態待確認'})[s.phase]||'狀態待確認':'更新逾時 · 狀態待確認');
    put('learnDays',fmt(tot.learning_days));
    put('learnStocks',fmt(session?.recommended_stocks));
    put('learnObserved',fmt(session?.observed_stocks));
    put('learnLearned',fmt(session?.learned_stocks));
    put('learnSamples',fmt(session?.labeled_count));
    put('learnCoverage',session?.requested!=null?`${fmt(session.downloaded)} / ${fmt(session.requested)}`:'—');
    put('learnCoverageNote',sessionDate?`盤中盯盤 ${fmt(session.observed_stocks)} 檔 · ${session.report_status==='partial'?'部分完成':session.report_status==='ready'?'復盤完成':'等待完整報告'}`:'等待最近交易日資料');
    const app=s.model_application||{};
    const pl=s.paper_learning?.training||{};
    const trainedDate=pl.trained_through||(app.model_version?.match(/\d{4}-\d{2}-\d{2}/)?.[0]);
    if(trainedDate){
      window.__LATEST_LEARNING_DATE=trainedDate;
      const topBadge=document.getElementById('intradayModelBadge');
      if(topBadge){
        topBadge.textContent=`當沖模組：${trainedDate}`;
        topBadge.title=`模型版本: ${app.model_version||pl.version||trainedDate}${pl.train_samples?` · 樣本數: ${fmt(pl.train_samples)} 筆`:''}`;
      }
      const metaModel=document.getElementById('metaDaytradeModel');
      if(metaModel){
        metaModel.textContent=`${trainedDate}`;
        metaModel.title=`牛馬 AI 實盤當沖模組基準日: ${trainedDate}`;
      }
    }
    const modelText = trainedDate
      ? `當沖模型：採用 ${trainedDate} 學習版本${pl.train_samples ? `（${fmt(pl.train_samples)} 筆樣本）` : ''}`
      : ({applied:`當沖模型：已載入${app.model_version||''}`,experimental_paper:`當沖模型：AI 模擬已載入`,not_applied:'當沖模型：尚未套用學習成果'}[app.status]||'當沖模型：執行版本待確認');
    put('learnModel',modelText);
    const cycleText={waiting_for_history:'等待 6,600 個有效股票日',waiting_for_archive_lock:'等待歷史下載／實驗釋放資料鎖',building_history_seed:'建立固定歷史種子中',training:'模型訓練與向前驗證中',completed:'本次模型週期完成',blocked:'候選未通過安全條件',paused_for_market_hours:'盤中暫停，避免影響當沖'}[app.cycle_state]||'等待模型週期';
    const trainDetail=pl.forward_samples!=null?`每日實盤累積：${fmt(pl.forward_samples)} 筆新樣本 · 資料基準日 ${trainedDate||'待確認'}`:`每日資料：同設定 ${fmt(tot.training_days)} 日、${fmt(tot.training_samples)} 筆`;
    put('learnTraining',`${trainDetail} · 歷史特訓：${cycleText}`);
    get('learnProgress').value=Math.min(101,tot.training_days||0);
    put('learnAI',`今日檢討週報：${({ok:'完成',failed:'失敗',skipped:'尚未執行'})[session?.ai_status]||'等待資料'}`);
    put('learnUpdated',`最後狀態更新：${date(s.updated_at)}`);
    put('learnLastReport',`最近交易日：${sessionDate||'尚無'} · 推薦 ${fmt(session?.recommended_stocks)} 檔 · 觀察 ${fmt(session?.observed_stocks)} 檔 · 有效學習 ${fmt(session?.learned_stocks)} 檔。最近復盤：${s.last_report?.date||'尚無'} · 累積資料收集日 ${fmt(tot.collection_days)}。`);
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
    const app=s.model_application||{},version=app.model_version?` ${app.model_version}`:'';
    put('historyModel',({applied:`當沖同步：已載入${version}`,experimental_paper:`當沖同步：AI 模擬已載入${version}`,experimental_paper_unreviewed:`當沖同步：AI 模擬已載入，執行檔待確認${version}`,scheduled:`當沖同步：驗證通過，等待引擎載入${version}`,installed_waiting_validation:'當沖同步：已連接，等待候選驗證合格',model_not_connected:'當沖同步：模型尚未連接引擎',not_applied:'當沖同步：尚未套用歷史模型',unknown:'當沖同步：尚待確認'})[app.status]||'當沖同步：尚待確認');
    const cycleNames={waiting_for_history:'等待 6,600 個有效股票日',waiting_for_archive_lock:'等待資料鎖',building_history_seed:'固定歷史種子建立中',training:'正式模型驗證中',completed:'正式模型週期完成',blocked:'候選未通過安全條件',paused_for_market_hours:'盤中暫停'};
    const experiment=t.status==='experimental_candidate'?'獨立 15 分鐘實驗已完成':t.status==='blocked'?`獨立實驗未產生模型 · ${reasonNames[t.reason_code]||reasonNames.other}`:r.state==='training'?'獨立實驗正在訓練':r.state==='replaying'?'獨立實驗建立特徵中':'等待獨立實驗結果';
    const trainingText=`${cycleNames[app.cycle_state]||'正式模型週期待確認'} · ${experiment}`;
    put('historyTraining',trainingText);
    const stop={quota_exhausted:'額度用完，下次排程續抓',quota_reserve:'保留額度，下次排程續抓',pair_limit:'分批處理',run_budget:'本批流量上限',pair_failed_inspect_before_retry:'有失敗紀錄',pair_limit_or_plan_complete:'本批結束',downloading:'自動下載中',outside_window:'等待明日 14:00',disk_reserve:'磁碟空間不足，需處理',user_stopped:'手動暫停',transient_error:'連線異常，15 分鐘後續跑',available_range_scanned_with_gaps:'可取得期間已掃描，缺口仍需確認',credentials_missing:'登入設定缺失',error:'下載異常，將自動重試'}[a.stop_reason]||'下載狀態見 VM';
    put('historyDownload',`歷史下載：${fmt(a.archived_stock_days)} / ${fmt(a.target_stock_days)} 股票日 · 失敗 ${fmt(a.failed_stock_days)} · ${stop}`);
    if(a.available_start)put('historyDownload',get('historyDownload').textContent+`。每天 14:00 續抓、22:10 離線訓練；目標筆數隨日期擴展。目前規劃至 ${a.planned_start||'待更新'}，永豐最早 ${a.available_start}；2010～2020 缺口不能由此 API 補齊。`);
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

/* Independent daily OpenAI review. */
(() => {
  const host=document.getElementById('learningSection');
  if(!host)return;

  const style=document.createElement('style');

  style.textContent=`
  #dualReview{
    margin-top:26px;
    border-top:2px solid var(--main);
    padding-top:24px
  }
  #dualReview h3{
    font-size:23px;
    margin:0 0 8px
  }
  #dualReview h4{
    font-size:16px;
    margin:0 0 10px
  }
  #dualReview .dual-head{
    display:flex;
    gap:16px;
    justify-content:space-between;
    align-items:flex-start
  }
  #dualReview p{
    font-size:13px;
    line-height:1.85;
    color:var(--sub);
    overflow-wrap:anywhere
  }
  #dualReview .dual-card{
    border:1px solid var(--border);
    padding:18px;
    margin-top:18px
  }
  #dualReview .dual-card>p:first-of-type{
    color:var(--main)
  }
  #dualReview .dual-meta{
    font-size:12px
  }
  #dualReview ul{
    padding-left:18px;
    font-size:13px;
    line-height:1.9;
    overflow-wrap:anywhere
  }
  #dualReview .dual-checks{
    margin-top:18px;
    padding:18px;
    border:1px dashed var(--border)
  }
  #dualReview .dual-facts{
    font-variant-numeric:tabular-nums;
    padding:10px 0;
    border-bottom:1px dashed var(--border)
  }
  @media(max-width:900px){
    #dualReview .dual-head{
      flex-direction:column
    }
  }`;

  document.head.appendChild(style);

  const section=document.createElement('section');
  section.id='dualReview';
  section.setAttribute('aria-labelledby','dualTitle');

  section.innerHTML=`
    <header class="dual-head">
      <div>
        <div class="eyebrow">收盤 AI 反省週報 / DAILY DEBRIEF</div>
        <h3 id="dualTitle">OpenAI 每日復盤</h3>
        <p id="dualDate">今日當沖輸贏都在這，哪裡追高被套、哪裡停損太慢，AI 幫你客觀寫進小本本。</p>
      </div>
      <span
        class="phase-badge"
        id="dualPhase"
        role="status">
        尚未收到資料
      </span>
    </header>

    <p
      class="dual-facts"
      id="dualFacts">
      等待行情收集與有效標記完成。
    </p>

    <article class="dual-card">
      <h4 style="color:var(--accent,#f59e0b);font-weight:700">📝 社畜自嘲反省核心摘要</h4>

      <p id="dualOpenaiSummary" style="font-size:14px;line-height:1.75;color:var(--main);margin:10px 0">
        等待分析
      </p>

      <p
        class="dual-meta"
        id="dualOpenaiMeta">
        —
      </p>

      <details style="margin-top:10px">
        <summary>查看待驗證自救研究方向</summary>
        <ul id="dualOpenaiIdeas"></ul>
      </details>
    </article>

    <div class="dual-checks">
      <details>
        <summary>指定數值判斷客觀核對</summary>
        <ul id="dualChecks"></ul>
        <p style="font-size:11px;color:var(--sub);margin-top:8px">
          數值判斷由程式依原始報告核對，杜絕幻覺。
          OpenAI 負責摘要及提出待驗證研究方向；
          不代表因果或策略效果已證實。
        </p>
      </details>
    </div>

    <p id="dualNotice" style="font-size:11px;color:var(--sub);margin-top:12px">
      ⚠️ 社畜保命提示：OpenAI 復盤僅供研究反思，不保證明日勝率；嚴格執行停利停損才是活命之道。
    </p>

    <p
      id="dualError"
      role="status">
    </p>
  `;

  host.appendChild(section);

  const get=id=>document.getElementById(id);

  const put=(id,v)=>{
    const n=get(id);
    if(n)n.textContent=v;
  };

  const fmt=n=>
    typeof n==='number'&&Number.isFinite(n)
      ?n.toLocaleString('zh-TW')
      :'—';

  const date=v=>
    typeof v==='string'&&Number.isFinite(Date.parse(v))
      ?new Date(v).toLocaleString(
          'zh-TW',
          {timeZone:'Asia/Taipei'}
        )
      :'未提供';

  const statuses={
    ok:'分析完成',
    failed:'API 呼叫失敗',
    rejected:'回覆未通過檢查',
    missing_config:'缺少金鑰或模型設定',
    daily_limit:'已達今日嘗試上限',
    monthly_limit:'已達本月呼叫上限'
  };

  const stances={
    test:'待回測',
    hold:'暫不優先',
    insufficient:'證據不足'
  };

  const titles={
    data_quality:'資料品質',
    gain_filter:'進場漲幅條件',
    volume_confirmation:'量能確認',
    vwap_filter:'VWAP 條件'
  };

  const verdicts={
    yes:'是',
    no:'否',
    insufficient:'資料不足'
  };

  function list(id,rows,empty){
    const n=get(id);
    if(!n)return;

    n.replaceChildren();

    for(const line of rows.length?rows:[empty]){
      const li=document.createElement('li');
      li.textContent=line;
      n.appendChild(li);
    }
  }

  function render(s){
    put(
      'dualPhase',
      ({
        complete:'OpenAI 復盤完成',
        partial:'復盤未完成',
        waiting_report:'等待當日資料',
        no_samples:'當日沒有觀察樣本'
      })[s.status]||'狀態待確認'
    );

    put(
      'dualDate',
      `資料日期：${s.date||'未提供'} · 摘要更新：${date(s.updated_at)}`
    );

    const f=s.facts||{};

    put(
      'dualFacts',
      `觀察樣本 ${fmt(f.sample_count)} · `+
      `有效標記 ${fmt(f.labeled_count)} · `+
      `行情收集 ${fmt(f.downloaded)} / ${fmt(f.requested)}。`+
      `數值由程式讀取報告，不由 AI 推估。`
    );

    const p=s.providers?.openai||{};
    const review=p.status==='ok'?p.review:null;

    put(
      'dualOpenaiSummary',
      review?.summary||
      statuses[p.status]||
      '等待分析'
    );

    put(
      'dualOpenaiMeta',
      `${p.model||'模型待確認'} · `+
      `${statuses[p.status]||'尚未執行'} · `+
      `${
        p.source==='cache'
          ?'沿用同資料快取'
          :p.source==='api'
          ?'本次 API 呼叫'
          :'未呼叫'
      }`+
      `${p.http_status?' · HTTP '+p.http_status:''}`+
      `${p.error_type?' · '+p.error_type:''}`
    );

    list(
      'dualOpenaiIdeas',
      (review?.hypotheses||[]).map(
        x=>
          `${titles[x.id]||x.id}：`+
          `${stances[x.stance]||'待確認'}。`+
          `${x.reason||''}`
      ),
      '尚無研究方向'
    );

    const checks=
      s.verification?.observations||[];

    list(
      'dualChecks',
      checks.map(
        x=>
          `${x.title} → `+
          `${verdicts[x.verdict]||'待確認'}`
      ),
      '等待資料完成後進行數值核對'
    );

    put('dualError','');
  }

  let busy=false;

  async function refresh(){
    if(busy)return;

    busy=true;

    const a=new AbortController();
    const timer=setTimeout(
      ()=>a.abort(),
      12000
    );

    try{
      const r=await fetch(
        `${FIREBASE_ROOT}/dual_review_status.json`,
        {
          cache:'no-store',
          signal:a.signal
        }
      );

      if(!r.ok){
        throw new Error(
          r.status===401||r.status===403
            ?'OpenAI 復盤摘要讀取未授權。'
            :'OpenAI 復盤摘要暫時無法讀取。'
        );
      }

      const s=await r.json();

      if(!s||s.schema_version!==1){
        throw new Error(
          '等待 VM 發布第一份 OpenAI 復盤。'
        );
      }

      render(s);

    }catch(e){

      put(
        'dualPhase',
        '連線待確認'
      );

      put(
        'dualError',
        e.name==='AbortError'
          ?'讀取逾時；現有內容是先前收到的結果。'
          :e.message
      );

    }finally{

      clearTimeout(timer);
      busy=false;
    }
  }

  refresh();
  setInterval(refresh,60000);
})();

/* Actual structured feedback and numerical training, independent of prose review. */
(() => {
  const parent=document.getElementById('dualOpenaiSummary')?.parentElement;
  if(!parent)return;
  const panel=document.createElement('section');panel.setAttribute('aria-label','OpenAI 學習回饋與訓練結果');
  panel.style.cssText='border-top:1px dashed var(--border);margin-top:18px;padding-top:18px';
  panel.innerHTML='<h4>學習回饋 → 模擬模型訓練</h4><p id="paperTrainingState">等待實際訓練紀錄</p><p id="paperTrainingCounts"></p><p id="paperTrainingValidation"></p><p id="paperFeedbackState"></p><p id="paperFeedbackSummary"></p><p id="paperTrainingVersion"></p><p id="paperTrainingError" role="status"></p><small>樣本權重經檢查後才用於訓練；不刪除真實虧損。新特徵只保存待驗證。歷史測試不代表明日勝率。</small>';
  parent.appendChild(panel);
  const notice=document.getElementById('dualNotice');
  if(notice)notice.textContent='文字復盤共識只供研究；結構化樣本回饋另外經程式檢查後，供下一次模擬模型訓練。';
  const put=(id,v)=>{document.getElementById(id).textContent=v;};
  const fmt=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('zh-TW'):'—';
  const date=v=>typeof v==='string'&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'}):'未提供';
  let busy=false;
  async function refresh(){
    if(busy)return;busy=true;const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
    try{
      const response=await fetch(`${FIREBASE_ROOT}/daytrade_learning_status.json`,{cache:'no-store',signal:controller.signal});
      if(!response.ok)throw new Error('訓練摘要讀取失敗');
      const status=await response.json(),p=status?.paper_learning;
      if(!p)throw new Error('等待伺服器發布新訓練摘要');
      const t=p.training||{},f=p.feedback||{},v=t.validation||{};
      put('paperTrainingState',`${t.status==='active_for_next_paper_session'?'訓練完成 · 供下一場模擬載入':'尚無完成的訓練紀錄'}｜資料截至 ${t.trained_through||'未提供'}`);
      put('paperTrainingCounts',`訓練 ${fmt(t.train_samples)} 筆 · 新增盤中樣本 ${fmt(t.forward_samples)} 筆 · 本版實際降權 ${fmt(t.feedback_weighted_samples)} 筆`);
      put('paperTrainingValidation',`歷史日期切割測試 ${fmt(v.test_samples)} 筆 · Brier 誤差 ${typeof v.brier==='number'?v.brier.toFixed(5):'—'}（越低越好，不是勝率；最終模擬版會再合併資料訓練）`);
      put('paperFeedbackState',`OpenAI 結構化回饋：${({complete:'完成',failed:'失敗，維持預設權重',waiting_labels:'等待有效標記'})[f.status]||'待確認'} · 樣本日期 ${f.date||'未提供'} · 審查 ${fmt(f.reviewed_samples)} 筆／降權 ${fmt(f.downweighted_samples)} 筆 · 特徵建議 ${fmt(f.feature_proposals)} 項（未套用）`);
      put('paperFeedbackSummary',f.summary||'尚無結構化回饋；不以文字復盤冒充已訓練。');
      put('paperTrainingVersion',`版本 ${t.version||'未提供'} · 訓練完成 ${date(t.updated_at)} · 回饋完成 ${date(f.reviewed_at)}`);
      const age=Date.now()-Date.parse(status.updated_at);
      put('paperTrainingError',!Number.isFinite(age)||age>180000?'摘要更新逾時：以上為最後紀錄，不代表服務正在執行。':'');
    }catch(e){put('paperTrainingError',`${e.name==='AbortError'?'讀取逾時':e.message}；保留上次結果。`);}
    finally{clearTimeout(timer);busy=false;}
  }
  refresh();setInterval(refresh,60000);
})();

/* Simple home R1. Move existing nodes so live updates and share handlers survive. */
