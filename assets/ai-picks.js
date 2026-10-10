(function (global) {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = value => typeof value === 'number' && Number.isFinite(value);
  const pct = value => num(value) ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%` : '—';
  const twd = value => num(value) ? `${value > 0 ? '+' : ''}${Math.round(value).toLocaleString('en-US')} 元` : '—';
  const tone = value => num(value) ? (value > 0 ? 'color:#EF4444' : value < 0 ? 'color:#10B981' : '') : '';
  const WEEK = ['日','一','二','三','四','五','六'];
  const day = value => {
    if (!/^\d{4}-\d{2}-\d{2}/.test(value || '')) return '—';
    const [y, m, d] = value.slice(0, 10).split('-').map(Number);
    return `${m}/${d}（${WEEK[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]}）`;
  };
  const clock = value => /T(\d{2}:\d{2})/.exec(value || '')?.[1] || '';
  const MODEL = {openai: 'ChatGPT', claude: 'Claude', gemini: 'Gemini'};
  const GROUP = {consensus: '兩家都選', majority2: '兩家以上都選', hot10: '熱門股（對照）', random5: '隨機股（對照）'};
  const label = g => MODEL[g] || GROUP[g] || g;
  const RULES = 'llm-consensus-paper-v1';

  function summary(feed) {
    const b = feed?.recent?.[0];
    if (!b) return '尚未有 AI 選股；開盤日 08:00 自動選股，第一批 10/12（一）。';
    const models = Object.entries(b.models || {});
    const counts = models.map(([m, x]) => x.ok ? `${MODEL[m] || m} ${x.picks.length} 檔` : `${MODEL[m] || m} 回覆失敗`).join('、');
    const shared = (b.consensus || []).length;
    const head = `${day(b.day)} ${clock(b.frozen_at)} 選出：${counts}，兩家共同選 ${shared} 檔。`;
    if (b.status === 'waiting_entry') return `${head}當天開盤買進，${day(b.exit_day)}收盤賣出。`;
    const parts = ['openai', 'claude', 'consensus', 'hot10', 'random5']
      .filter(g => b.groups?.[g]).map(g => `${label(g)} ${pct(b.groups[g].net_pct)}`);
    const verb = b.status === 'closed' ? `${day(b.exit_day)}已出場` : `持有中，預計 ${day(b.exit_day)}收盤出場；截至 ${day(b.mark_day)}收盤`;
    return `${head}${verb}：${parts.join('｜')}。`;
  }

  function picks(feed) {
    const b = feed?.recent?.[0];
    if (!b) return '';
    const shared = new Set((b.consensus || []).map(x => x.symbol));
    const entered = b.status !== 'waiting_entry';
    return '<div class="grid gap-3 md:grid-cols-2">' + Object.entries(b.models || {}).map(([m, x]) => {
      const title = `<div class="text-sm font-bold text-[#F1F5F9]">${escape(MODEL[m] || m)}` +
        `<span class="text-xs font-normal text-[#64748B]"> · ${escape(x.model || '')}</span></div>`;
      let body;
      if (!x.ok) body = `<p class="text-xs text-[#F59E0B] mt-2">今天回覆失敗：${escape(x.error || '未知錯誤')}</p>`;
      else if (!x.picks.length) body = '<p class="text-xs text-[#64748B] mt-2">今天沒有選股（認為沒有合適標的）。</p>';
      else body = x.picks.map((p, i) => {
        const result = !entered ? '待開盤' : p.filled === false ? '開盤漲停未買' : `<span style="${tone(p.net_pct)}">${pct(p.net_pct)}</span>`;
        return `<div style="border-top:1px solid var(--border,#232F42)" class="py-2">` +
          `<div class="flex justify-between gap-2 text-xs"><span class="text-[#F1F5F9] font-semibold">${i + 1}. ${escape(p.symbol)} ${escape(p.name)}` +
          `${shared.has(p.symbol) ? ' <span class="text-[#F59E0B]">★兩家都選</span>' : ''}</span><span>${result}</span></div>` +
          `<p class="text-xs text-[#64748B] mt-1 leading-relaxed">${escape(p.reason)}</p></div>`;
      }).join('');
      const bad = x.invalid?.length ? `<p class="text-xs text-[#64748B] mt-1">名單外、不計分：${x.invalid.map(escape).join('、')}</p>` : '';
      return `<div class="p-3 rounded-xl bg-[#0D1C2D] border border-[#232F42]/60">${title}${body}${bad}</div>`;
    }).join('') + '</div>';
  }

  function record(feed) {
    const s = feed?.summary;
    const groups = s?.groups || {};
    if (!s?.closed_batches) return '<p class="text-xs text-[#64748B]">累計紀錄：尚無已出場批次（每批持有 5 個交易日）。至少 40 批後再判斷 AI 有沒有贏過對照組。</p>';
    const rows = Object.entries(groups).map(([g, v]) => [g.replace(/^p200_/, ''), v]);
    return `<p class="text-xs text-[#64748B]">累計紀錄：${s.closed_batches} 批已出場。AI 要同時贏過「熱門股」與「隨機股」才算有用。</p>` +
      '<div style="overflow-x:auto"><table class="text-xs w-full" style="min-width:520px;text-align:left"><thead><tr>' +
      ['組別','批次','賺錢','平均每批','每 100 萬平均','每 100 萬累計'].map(t => `<th style="padding:6px 8px">${t}</th>`).join('') +
      '</tr></thead><tbody>' + rows.map(([g, v]) => `<tr style="border-top:1px solid var(--border,#232F42)">` +
        `<td style="padding:6px 8px">${escape(label(g))}</td><td style="padding:6px 8px">${escape(v.batches)}</td>` +
        `<td style="padding:6px 8px">${escape(v.wins)}</td><td style="padding:6px 8px;${tone(v.mean_net_pct)}">${pct(v.mean_net_pct)}</td>` +
        `<td style="padding:6px 8px">${twd(v.twd_per_1m_mean)}</td><td style="padding:6px 8px">${twd(v.twd_per_1m_total)}</td></tr>`).join('') +
      '</tbody></table></div>';
  }

  function stale(feed, now) {
    const age = now - Date.parse(feed?.generated_at);
    return !Number.isFinite(age) || age > 36 * 3600000;
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = {summary, picks, record, stale, RULES};
  if (!global.document) return;
  let busy = false;
  async function refresh() {
    const get = id => global.document.getElementById(id);
    const status = get('aiPicksStatus');
    if (!status || busy) return;
    busy = true;
    try {
      const root = typeof FIREBASE_ROOT !== 'undefined' ? FIREBASE_ROOT : global.FIREBASE_ROOT;
      if (!root) throw new Error('missing source');
      const response = await global.fetch(`${root}/public_feed/llm_paper.json`, {cache:'no-store'});
      const feed = response && response.ok ? await response.json() : null;
      if (!feed || feed.rules_version !== RULES) {
        status.textContent = 'AI 選股尚未發布；第一批 10/12（一）08:00 自動選股。';
        return;
      }
      status.textContent = summary(feed) + (stale(feed, Date.now()) ? '（資料更新已延遲）' : '');
      get('aiPicksCards').innerHTML = picks(feed);
      get('aiPicksRecord').innerHTML = record(feed);
    } catch (_) {
      status.textContent = 'AI 選股暫時無法取得，請稍後重試。';
    } finally { busy = false; }
  }
  global.AiPicksUI = {refresh};
  refresh();
  global.setInterval(refresh, 10 * 60000);
})(typeof window !== 'undefined' ? window : globalThis);
