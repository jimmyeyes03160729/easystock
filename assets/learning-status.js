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
