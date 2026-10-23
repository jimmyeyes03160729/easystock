(function (global) {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pct = value => typeof value === 'number' && Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%` : '—';
  const price = value => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '—';
  const tone = value => typeof value === 'number' && Number.isFinite(value) ? (value > 0 ? 'color:#EF4444' : value < 0 ? 'color:#10B981' : '') : '';
  const sub = text => `<div style="color:var(--sub,#64748B);font-size:11px;margin-top:2px">${text}</div>`;
  const TD = 'padding:6px 8px;vertical-align:top';
  const NUM = TD + ';text-align:right;white-space:nowrap';
  function table(payload) {
    const rows = Array.isArray(payload?.rows) ? payload.rows : Object.values(payload?.rows || {});
    if (!rows.length) return '<p class="text-sub text-sm py-4">目前尚無符合條件的觀察紀錄；不代表沒有利多，可能尚缺公告文字或月增資料。</p>';
    const head = [['股票',0],['營收年增／月增',0],['正向消息',0],['觀察日',0],['基準收盤',1],['開盤',1],['最高',1],['最低',1],['收盤',1],['開→收',1]];
    return '<div style="overflow-x:auto"><table class="text-xs w-full" style="min-width:900px;text-align:left;border-collapse:collapse"><thead><tr>' +
      head.map(([t, n]) => `<th style="padding:6px 8px;white-space:nowrap;${n ? 'text-align:right' : ''}">${t}</th>`).join('') + '</tr></thead><tbody>' +
      rows.map(r=>{
        const o = r.status === 'complete' ? r.outcome : null;
        const status = r.status === 'complete' ? '已完成' : r.status === 'missing_data' ? '缺行情待補' : '等待收盤';
        const cell = key => o ? `${price(o[key])}${sub(`<span style="${tone(o[key+'_pct'])}">${pct(o[key+'_pct'])}</span>`)}` : '—';
        return `<tr style="border-top:1px solid var(--border,#334155)">` +
          `<td style="${TD};white-space:nowrap"><strong>${escape(r.symbol)} ${escape(r.name)}</strong>${sub(`訊號 ${escape(String(r.signal_at || '').slice(0,10))}`)}</td>` +
          `<td style="${TD};white-space:nowrap"><span style="${tone(r.rev_yoy)}">${pct(r.rev_yoy)}</span> ／ <span style="${tone(r.rev_mom)}">${pct(r.rev_mom)}</span>${sub(escape(r.revenue_period))}</td>` +
          `<td style="${TD};max-width:320px"><details><summary style="cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escape(r.subject)}</summary>` +
          `<p>${escape(r.evidence)}</p><p>首次取得：${escape(r.event_first_seen_at)}<br>來源：${escape(r.source)}</p>` +
          `<a href="https://mops.twse.com.tw/mops/#/web/t05st01" target="_blank" rel="noopener">公開資訊觀測站（依代號／公告日查詢）</a><p>公告日：${escape(r.announcement_day)}</p></details></td>` +
          `<td style="${TD};white-space:nowrap">${escape(r.target_day)}${sub(status)}</td>` +
          `<td style="${NUM}">${price(r.reference_close)}${sub(escape(r.reference_day))}</td>` +
          ['open','high','low','close'].map(k => `<td style="${NUM}">${cell(k)}</td>`).join('') +
          `<td style="${NUM};${tone(o?.open_to_close_pct)}">${o ? pct(o.open_to_close_pct) : '—'}</td></tr>`;
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
