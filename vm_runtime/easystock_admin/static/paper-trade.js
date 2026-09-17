(() => {
  'use strict';

  async function getCsrfToken() {
    try {
      const res = await fetch('/admin/session');
      if (res.ok) {
        const data = await res.json();
        return data.csrf || '';
      }
    } catch (_) {}
    return '';
  }

  function render(data) {
    if (!data || !data.settings) return;
    const s = data.settings;
    const cur = Number(s.current_capital || s.initial_capital);
    const init = Number(s.initial_capital || 100000);
    const pnl = cur - init;
    const ret = init > 0 ? ((pnl / init) * 100).toFixed(2) : '0.00';

    const curEl = document.getElementById('simCurrentCapital');
    if (curEl) curEl.textContent = `${cur.toLocaleString()} 元`;

    const retEl = document.getElementById('simReturnRate');
    if (retEl) {
      retEl.textContent = `累計損益: ${pnl >= 0 ? '+' : ''}${pnl.toLocaleString()} 元 (${ret}%)`;
      retEl.style.color = pnl > 0 ? '#f87171' : pnl < 0 ? '#4ade80' : 'var(--muted,#888)';
    }

    const badge = document.getElementById('simStatusBadge');
    if (badge) {
      const isRun = s.status === 'running';
      badge.textContent = isRun ? '● 正在執行模擬' : '○ 模擬已暫停';
      badge.style.color = isRun ? '#4ade80' : 'var(--muted,#888)';
    }

    const startEl = document.getElementById('simStartDate');
    if (startEl) startEl.textContent = `起始日期: ${s.start_date || '--'} (本金 ${init.toLocaleString()})`;

    const tbody = document.getElementById('simLogsTableBody');
    if (tbody) {
      if (!data.logs || data.logs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:12px;color:var(--muted,#888);">尚無結算紀錄</td></tr>';
      } else {
        tbody.innerHTML = data.logs.map(log => {
          const color = log.net_pnl > 0 ? '#f87171' : log.net_pnl < 0 ? '#4ade80' : 'inherit';
          return `<tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
            <td style="padding:6px 4px;font-family:monospace;">${log.date}</td>
            <td style="padding:6px 4px;">${Number(log.start_balance).toLocaleString()}</td>
            <td style="padding:6px 4px;">${log.symbols || '--'}</td>
            <td style="padding:6px 4px;font-weight:bold;color:${color};">${log.net_pnl >= 0 ? '+' : ''}${Number(log.net_pnl).toLocaleString()}</td>
            <td style="padding:6px 4px;font-weight:bold;">${Number(log.end_balance).toLocaleString()}</td>
          </tr>`;
        }).join('');
      }
    }
  }

  async function load() {
    const ws = document.getElementById('workspace');
    if (ws && ws.hidden) return;
    try {
      const res = await fetch('/admin/paper-trade');
      if (res.ok) {
        const data = await res.json();
        render(data);
      }
    } catch (_) {}
  }

  function bindEvents() {
    const form = document.getElementById('paperTradeForm');
    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const cap = Number(document.getElementById('simInitialInput').value);
        const statusEl = document.getElementById('simActionStatus');
        statusEl.textContent = '設定中...';
        try {
          const csrf = await getCsrfToken();
          const res = await fetch('/admin/paper-trade/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
            body: JSON.stringify({ initial_capital: cap })
          });
          const data = await res.json();
          if (res.ok) {
            statusEl.textContent = `已成功啟動！起始本金設為 ${cap.toLocaleString()} 元。`;
            render(data);
          } else {
            statusEl.textContent = data.error || '設定失敗';
          }
        } catch (_) {
          statusEl.textContent = '連線失敗，請稍後重試。';
        }
      });
    }

    const btnToggle = document.getElementById('btnSimToggle');
    if (btnToggle) {
      btnToggle.addEventListener('click', async () => {
        const statusEl = document.getElementById('simActionStatus');
        statusEl.textContent = '狀態切換中...';
        try {
          const csrf = await getCsrfToken();
          const res = await fetch('/admin/paper-trade/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
            body: JSON.stringify({})
          });
          const data = await res.json();
          if (res.ok) {
            statusEl.textContent = '模擬狀態已更新。';
            render(data);
          } else {
            statusEl.textContent = data.error || '切換失敗';
          }
        } catch (_) {
          statusEl.textContent = '連線失敗。';
        }
      });
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    bindEvents();
    load();
    setInterval(load, 15000);
  });
})();
