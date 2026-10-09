(function (global) {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pct = value => typeof value === 'number' && Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%` : '—';
  const price = value => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '—';
  function table(payload) {
    const rows = Array.isArray(payload?.rows) ? payload.rows : Object.values(payload?.rows || {});
    if (!rows.length) return '<p class="text-sub text-sm py-4">目前尚無符合條件的觀察紀錄；不代表沒有利多，可能尚缺公告文字或月增資料。</p>';
    return '<div style="overflow-x:auto"><table class="text-xs w-full" style="min-width:950px;text-align:left"><thead><tr>' +
      ['個股／訊號日','營收年增／月增','正向文字依據','觀察日／狀態','基準收盤','開盤','最高','最低','收盤','開盤→收盤'].map(t=>`<th style="padding:8px">${t}</th>`).join('') + '</tr></thead><tbody>' +
      rows.map(r=>{
        const o = r.status === 'complete' ? r.outcome : null;
        const status = r.status === 'complete' ? '已完成' : r.status === 'missing_data' ? '缺行情待補' : '等待收盤';
        const cell = key => o ? `${price(o[key])}<br>${pct(o[key+'_pct'])}` : '—';
        return `<tr style="border-top:1px solid var(--border,#334155)"><td style="padding:8px">${escape(r.symbol)} ${escape(r.name)}<br>${escape(String(r.signal_at || '').slice(0,10))}</td><td>${pct(r.rev_yoy)}<br>${pct(r.rev_mom)}<br>${escape(r.revenue_period)}</td><td style="max-width:280px;padding:8px"><details><summary>${escape(r.subject)}</summary><p>${escape(r.evidence)}</p><p>首次取得：${escape(r.event_first_seen_at)}<br>來源：${escape(r.source)}</p><a href="https://mops.twse.com.tw/mops/#/web/t05st01" target="_blank" rel="noopener">公開資訊觀測站（依代號／公告日查詢）</a><p>公告日：${escape(r.announcement_day)}</p></details></td><td>${escape(r.target_day)}<br>${status}</td><td>${price(r.reference_close)}<br>${escape(r.reference_day)}</td><td>${cell('open')}</td><td>${cell('high')}</td><td>${cell('low')}</td><td>${cell('close')}</td><td>${o ? pct(o.open_to_close_pct) : '—'}</td></tr>`;
      }).join('') + '</tbody></table></div>';
  }
  function summary(payload) {
    const s=payload?.summary || {};
    return `累計 ${s.total ?? 0} 筆觀察，完成 ${s.complete ?? 0} 筆；隔日收盤高於基準 ${pct(s.up_rate)}，平均漲跌 ${pct(s.mean_close_pct)}。${(payload?.errors || []).length ? '部分資料來源取得失敗。' : ''}`;
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {table, summary, pct};
  if (!global.document) return;
  let busy = false;
  async function refresh() {
    const box = global.document.getElementById('revenueObservationRows');
    const stamp = global.document.getElementById('revenueObservationStatus');
    if (!box || !stamp || busy) return;
    busy = true;
    try {
      const root = typeof FIREBASE_ROOT !== 'undefined' ? FIREBASE_ROOT : null;
      if (!root) throw new Error('missing source');
      const response = await fetch(`${root}/public_feed/revenue_observation.json`, {cache:'no-store'});
      if (!response.ok) throw new Error('unavailable');
      const data = await response.json();
      if (!data?.generated_at || data.rules_version !== 'revenue-positive-v1') throw new Error('missing data');
      const age = Date.now() - Date.parse(data.generated_at);
      stamp.textContent = `${summary(data)} 更新：${data.generated_at.replace('T',' ')}${!Number.isFinite(age) || age > 90*60000 ? '（資料更新已延遲）' : ''}`;
      box.innerHTML = table(data);
    } catch (_) {
      stamp.textContent = '觀察資料暫時無法取得，請稍後重試。';
    } finally { busy = false; }
  }
  refresh();
  global.setInterval(refresh, 10*60000);
})(typeof window !== 'undefined' ? window : globalThis);
