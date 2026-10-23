/* Public service status only. Detailed model and research diagnostics stay private. */
(() => {
  const root=document.getElementById('learningSection');if(!root)return;
  root.innerHTML='<div class="learning-head"><h2>每日研究進度</h2></div><div class="learning-columns"><article class="learning-column"><h3>每日研究</h3><p id="publicDailyState">等待狀態更新</p><small id="publicDailyTime"></small></article><article class="learning-column"><h3>歷史資料研究</h3><p id="publicHistoryState">等待狀態更新</p><small id="publicHistoryTime"></small></article></div><p class="text-xs text-sub mt-4">研究進度不代表模型已部署，也不代表實際成交績效。</p>';
  const names={collecting:'資料整理中',reviewing:'盤後研究中',training:'研究處理中',idle:'待命',failed:'服務狀態待確認',snapshotting:'資料整理中',replaying:'歷史資料研究中',completed:'本次研究完成',interrupted:'處理已中斷'};
  async function refresh(node,prefix){
    try{
      const r=await fetch(publicDataURL(`${FIREBASE_ROOT}/${node}.json`),{cache:'no-store',signal:AbortSignal.timeout(12000)});
      if(!r.ok)throw Error();const s=await r.json();const age=Date.now()-Date.parse(s?.updated_at);
      const fresh=s?.schema_version===1&&Number.isFinite(age)&&age>=-60000&&age<180000;
      document.getElementById(prefix+'State').textContent=fresh?(names[s.phase]||'狀態待更新'):'最後紀錄已過期，狀態待確認';
      document.getElementById(prefix+'Time').textContent=Number.isFinite(Date.parse(s?.updated_at))?`最後更新：${new Date(s.updated_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}`:'';
    }catch{document.getElementById(prefix+'State').textContent='暫時無法取得研究狀態';}
  }
  const run=()=>Promise.all([refresh('daytrade_learning_status','publicDaily'),refresh('history_training_status','publicHistory')]);
  run();setInterval(run,60000);
})();
