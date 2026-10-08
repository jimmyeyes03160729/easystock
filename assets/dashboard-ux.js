/* Presentation only: no orders, strategy changes, Firebase writes or private reads. */
(() => {
  'use strict';
  const get = id => document.getElementById(id);
  const setText = (id, value) => { const el = get(id); if (el) el.textContent = value; };
  function timeText(at) {
    const ms = Date.parse(at);
    return Number.isFinite(ms) ? new Date(ms).toLocaleString('zh-TW', {timeZone:'Asia/Taipei', hour12:false}) + '（台北）' : '尚未取得有效時間';
  }
  function emptyReason({live = {}, health = {}, filtered = false, now = Date.now()} = {}) {
    if (!health.current) return health.message || '尚無有效快照，無法確認訊號原因。';
    if (filtered) return '目前紀錄被股價 / 單張預算篩選隱藏；請清除篩選。篩選不會改變交易設定。';
    if (live.session === 'closed') return '當沖已結束；目前為收盤 / 歷史快照，不代表今日有新訊號。';
    if (live.session === 'preopen') return '開盤前待命；尚未進入盤中訊號時段。';
    if (live.session === 'no_new_entry') return '已停止新進場；現有模擬部位仍依原規則監控。';
    if (live.session === 'force_exit') return '強制出場階段，不產生新的進場訊號。';
    if (live.session !== 'daytrade') return '盤中階段待確認；不以缺少紀錄推測市場休市。';
    const gate = live.market_risk || {};
    const age = now - Date.parse(gate.checked_at || gate.received_at);
    const freshGate = Number.isFinite(age) && age >= -60000 && age <= 90000;
    if (freshGate && gate.gate_action === 'BLOCK') {
      if (gate.gate_reason === 'market_risk_red') return '市場風險紅燈：後端目前阻擋新進場，不調整風控門檻。';
      if (gate.gate_reason === 'market_data_unavailable') return '市場資料不可用：後端目前阻擋新進場，等待有效行情。';
      return '後端風控目前阻擋新進場；具體原因待確認。';
    }
    if (live.config?.entry_mode === 'model' && live.config.model_ready === false) return '模型未就緒，禁止新進場；不切換策略或放寬條件。';
    return '目前沒有 OPEN 部位或今日完成交易。尚無可顯示紀錄；是否未符合條件或被其他門檻阻擋，需等待後端證據，不能由空清單推定。';
  }
  function requestFinished(ms, success) {
    const label = Number.isFinite(ms) && ms >= 0
      ? `最近完成的資料請求${success ? '' : '（失敗）'} ${Math.round(ms)} ms`
      : '資料請求耗時未知';
    setText('requestTiming', label);
    setText('footerRequestTiming', label + ' · 含下載與解析，非行情延遲');
  }
  function update(data) {
    const live = data?.live || {}, health = data?.health || {}, meta = data?.meta || {};
    const labels = {preopen:'開盤前',daytrade:'盤中模擬監控',no_new_entry:'停止新進場',force_exit:'強制出場階段',closed:'收盤 / 歷史快照'};
    setText('overviewSession', health.current ? (labels[live.session] || '階段待確認') : (health.label || '待確認'));
    const dailyConnection = data?.dailyFetchState === 'failed' ? '最近讀取失敗，保留最後快照；' : data?.dailyFetchState === 'loading' ? '正在讀取；' : '';
    setText('overviewValidity', `日線：${dailyConnection}${data?.dailyValid ? '符合既有版本 / 日期檢查（非即時）' : '待確認或失效，不產生資格推薦'} · 盤中：${health.current ? live.session === 'closed' ? '收盤 / 歷史快照，非即時' : '快照通過時效檢查' : '待確認 / 失效'}`);
    setText('overviewUpdated', `日線 ${meta.updated_at || '未知'} · 盤中 ${timeText(live.last_update_at || live.generated_at)}`);
    setText('overviewNotice', health.message || '此處的「盤中」是模擬資料服務階段，不是交易所開市或實盤執行證明。');
  }
  window.DashboardUX = {update, emptyReason, requestFinished};
})();
