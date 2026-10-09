(function (global) {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = value => typeof value === 'number' && Number.isFinite(value);
  const pct = value => num(value) ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%` : '—';
  const price = value => num(value) ? value.toFixed(2) : '—';
  const twd = value => num(value) ? `${value > 0 ? '+' : ''}${Math.round(value).toLocaleString('en-US')} 元` : '—';
  const tone = value => num(value) ? (value > 0 ? 'color:#EF4444' : value < 0 ? 'color:#10B981' : '') : '';
  const WEEK = ['日','一','二','三','四','五','六'];
  const day = value => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return '—';
    const [y, m, d] = value.split('-').map(Number);
    return `${m}/${d}（${WEEK[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]}）`;
  };
  const revMonth = month => month ? `${Number(month.slice(0,4))} 年 ${Number(month.slice(5,7))} 月營收` : '';

  function summary(feed) {
    const cur = feed?.current, next = feed?.next, last = feed?.last_closed;
    const hold = feed?.strategy?.hold_sessions ?? 10;
    if (cur && cur.status === 'waiting_entry')
      return `本批（${revMonth(cur.month)}）已在 ${day(cur.deadline_session)}晚上選出；${day(cur.entry_day)}開盤買進，持有 ${hold} 個交易日，${day(cur.exit_day)}收盤賣出。開盤漲停的不追。`;
    if (cur && cur.status === 'holding')
      return `持有中（${revMonth(cur.month)}）：${day(cur.entry_day)}進場，預計 ${day(cur.exit_day)}收盤出場。截至 ${day(cur.mark_day)}收盤，組合 ${pct(cur.net_pct)}（每 100 萬 ${twd(cur.twd_per_1m)}），同期全市場平均 ${pct(cur.universe_net_pct)}。`;
    const parts = [];
    if (last) parts.push(`上一批（${revMonth(last.month)}）${day(last.exit_day)}已出場：${pct(last.net_pct)}，每 100 萬 ${twd(last.twd_per_1m)}。`);
    if (next?.deadline_session) parts.push(`下一批：${day(next.deadline_session)}晚上選股，${day(next.entry_day)}開盤進場。`);
    return parts.join(' ') || '尚未有名單。';
  }

  function positions(feed) {
    const cur = feed?.current;
    const rows = cur?.positions || [];
    if (!rows.length) return '<p class="text-xs text-[#64748B] py-3">目前沒有持股；下一批名單在營收截止日晚上產生。</p>';
    const entered = cur.status !== 'waiting_entry';
    const head = ['排名','股票','營收年增','驚喜分數', entered ? '進場價' : '截止日收盤', entered ? '最新收盤' : '約買股數（10 萬）', entered ? '損益（扣成本）' : '狀態'];
    const body = rows.map(r => {
      const cells = entered
        ? [r.filled === false ? '開盤漲停未買' : price(r.entry), r.filled === false ? '—' : price(r.mark),
           r.filled === false ? '留現金' : `<span style="${tone(r.net_pct)}">${pct(r.net_pct)}</span>`]
        : [price(r.deadline_close), num(r.shares_est) ? `${r.shares_est.toLocaleString('en-US')} 股` : '—', '待開盤'];
      return `<tr style="border-top:1px solid var(--border,#232F42)"><td style="padding:6px 8px">${escape(r.rank)}</td>` +
        `<td style="padding:6px 8px;white-space:nowrap">${escape(r.symbol)} ${escape(r.name)}</td>` +
        `<td style="padding:6px 8px">${pct(r.rev_yoy_pct)}</td><td style="padding:6px 8px">${num(r.sur) ? r.sur.toFixed(2) : '—'}</td>` +
        cells.map(c => `<td style="padding:6px 8px">${c}</td>`).join('') + '</tr>';
    }).join('');
    return '<div style="overflow-x:auto"><table class="text-xs w-full" style="min-width:620px;text-align:left"><thead><tr>' +
      head.map(t => `<th style="padding:6px 8px">${t}</th>`).join('') + `</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function history(feed) {
    const rows = feed?.history || [];
    const rec = feed?.record || {};
    if (!rows.length) return '<p class="text-xs text-[#64748B]">前瞻紀錄：尚無已出場批次（第一批 2026 年 9 月營收，10/13 進場）。</p>';
    return `<p class="text-xs text-[#64748B]">前瞻紀錄：${rec.batches} 批，${rec.wins} 批賺錢，累計每 100 萬 ${twd(rec.twd_per_1m_total)}。</p>` +
      '<div style="overflow-x:auto"><table class="text-xs w-full" style="min-width:560px;text-align:left"><thead><tr>' +
      ['批次','進場','出場','買到檔數','組合','全市場','超額','每 100 萬'].map(t => `<th style="padding:6px 8px">${t}</th>`).join('') +
      '</tr></thead><tbody>' + rows.map(b => `<tr style="border-top:1px solid var(--border,#232F42)"><td style="padding:6px 8px">${escape(revMonth(b.month))}</td>` +
        `<td style="padding:6px 8px">${day(b.entry_day)}</td><td style="padding:6px 8px">${day(b.exit_day)}</td><td style="padding:6px 8px">${escape(b.n_filled)}</td>` +
        `<td style="padding:6px 8px;${tone(b.net_pct)}">${pct(b.net_pct)}</td><td style="padding:6px 8px">${pct(b.universe_net_pct)}</td>` +
        `<td style="padding:6px 8px">${pct(b.excess_pct)}</td><td style="padding:6px 8px">${twd(b.twd_per_1m)}</td></tr>`).join('') + '</tbody></table></div>';
  }

  function fullLine(feed) {
    const b = feed?.current || feed?.last_closed, f = b?.full_summary;
    if (!f || !num(f.n_companies)) return '';
    if (!f.all) return `全部上市櫃公司：已收錄 ${f.n_companies.toLocaleString('en-US')} 家（${f.n_scored} 家有驚喜分數），進場日開盤後開始追蹤。`;
    const g = (label, x) => `${label} ${pct(x?.net_pct)}`;
    return `全部上市櫃公司（不設成交額門檻，${f.n_companies.toLocaleString('en-US')} 家）：` +
      [g('全部平均', f.all), g('分數前 10 名', f.top10), g('分數前 10%', f.top_decile), g('分數後 10%', f.bottom_decile), g('無分數', f.no_score)].join('｜');
  }

  const FILL = {filled: '已計入', limit_up: '開盤漲停', no_trade: '當日無成交'};
  function fullTable(full, query) {
    const rows = (Array.isArray(full?.rows) ? full.rows : []).filter(r => !query || `${r.symbol} ${r.name}`.includes(query));
    if (!rows.length) return '<p class="text-xs text-[#64748B] py-2">沒有符合的公司。</p>';
    const entered = full.status !== 'waiting_entry';
    const head = ['排名','股票','市場','營收年增','驚喜分數', entered ? '進場價' : '截止日收盤', entered ? '最新收盤' : '', entered ? '損益（扣成本）' : ''].filter(Boolean);
    return '<div style="overflow:auto;max-height:480px"><table class="text-xs w-full" style="min-width:620px;text-align:left"><thead><tr>' +
      head.map(t => `<th style="padding:6px 8px;position:sticky;top:0;background:var(--panel,#131A26)">${t}</th>`).join('') + '</tr></thead><tbody>' +
      rows.map(r => {
        const tail = entered
          ? [r.fill === 'filled' ? price(r.entry) : escape(FILL[r.fill] || '—'), price(r.mark), `<span style="${tone(r.net_pct)}">${pct(r.net_pct)}</span>`]
          : [price(r.deadline_close)];
        return `<tr style="border-top:1px solid var(--border,#232F42)"><td style="padding:4px 8px">${r.rank ?? '—'}</td>` +
          `<td style="padding:4px 8px;white-space:nowrap">${escape(r.symbol)} ${escape(r.name)}</td><td style="padding:4px 8px">${escape(r.market)}</td>` +
          `<td style="padding:4px 8px">${pct(r.rev_yoy_pct)}</td><td style="padding:4px 8px">${num(r.sur) ? r.sur.toFixed(2) : '—'}</td>` +
          tail.map(c => `<td style="padding:4px 8px">${c}</td>`).join('') + '</tr>';
      }).join('') + '</tbody></table></div>';
  }

  function stale(feed, now) {
    const age = now - Date.parse(feed?.generated_at);
    return !Number.isFinite(age) || age > 36 * 3600000;
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = {summary, positions, history, stale, fullLine, fullTable, day, pct, twd};
  if (!global.document) return;
  let busy = false, FULL = null;
  async function loadFull() {
    const box = global.document.getElementById('shortTermFullRows');
    if (!box) return;
    try {
      if (!FULL) {
        const root = typeof FIREBASE_ROOT !== 'undefined' ? FIREBASE_ROOT : global.FIREBASE_ROOT;
        const response = await global.fetch(`${root}/public_feed/short_term_full.json`, {cache:'no-store'});
        FULL = response && response.ok ? await response.json() : null;
      }
      const query = (global.document.getElementById('shortTermFullSearch')?.value || '').trim();
      box.innerHTML = FULL ? fullTable(FULL, query) : '<p class="text-xs text-[#64748B] py-2">全部公司資料在第一批營收截止日晚上產生。</p>';
    } catch (_) {
      box.innerHTML = '<p class="text-xs text-[#64748B] py-2">全部公司資料暫時無法取得。</p>';
    }
  }
  global.document.getElementById('shortTermFull')?.addEventListener('toggle', e => { if (e.target.open) loadFull(); });
  global.document.getElementById('shortTermFullSearch')?.addEventListener('input', () => loadFull());
  async function refresh() {
    const get = id => global.document.getElementById(id);
    const status = get('shortTermStatus');
    if (!status || busy) return;
    busy = true;
    try {
      const root = typeof FIREBASE_ROOT !== 'undefined' ? FIREBASE_ROOT : global.FIREBASE_ROOT;
      if (!root) throw new Error('missing source');
      const response = await global.fetch(`${root}/public_feed/short_term.json`, {cache:'no-store'});
      const feed = response && response.ok ? await response.json() : null;
      if (!feed || feed.rules_version !== 'revenue-sur-short-v1') {
        status.textContent = '短期名單尚未發布；第一批在 10/12（一）晚上產生，10/13（二）開盤進場。';
        return;
      }
      status.textContent = summary(feed) + (stale(feed, Date.now()) ? '（資料更新已延遲）' : '');
      const line = get('shortTermFullLine');
      if (line) line.textContent = fullLine(feed);
      FULL = null;
      if (get('shortTermFull')?.open) loadFull();
      get('shortTermPicks').innerHTML = positions(feed);
      get('shortTermHistory').innerHTML = history(feed);
    } catch (_) {
      status.textContent = '短期名單暫時無法取得，請稍後重試。';
    } finally { busy = false; }
  }
  global.ShortTermUI = {refresh};
  refresh();
  global.setInterval(refresh, 30 * 60000);
})(typeof window !== 'undefined' ? window : globalThis);
