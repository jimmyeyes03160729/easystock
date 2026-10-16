/* Approved homepage presentation. Reuses public renderers and never writes data. */
(() => {
  'use strict';
  const get = id => document.getElementById(id);
  const module = get('daytradeModule');
  if (!module || get('homeStrategyTabs')) return;
  const lists = {A:'intradayPickList', B1:'runwayV2PickList', B2:'runwayB2PickList', B3:'runwayB3PickList'};
  const titles = {A:'轉強突破', B1:'五檔拉回', B2:'布林轉折', B3:'五分突破'};
  const listNodes = Object.fromEntries(Object.entries(lists).map(([lane,id]) => [lane,get(id)]));
  const panes = {};
  const expanded = {A:false, B1:false, B2:false, B3:false};
  let selected = 'A', context = {};
  const setText = (id, value) => {
    const el = get(id), text = String(value ?? '—');
    if (el && el.textContent !== text) el.textContent = text;
  };
  const field = id => {
    const text = get(id)?.textContent || '';
    if (!text || /待資料|待提供|等待|—/.test(text)) return '—';
    return text.includes('：') ? text.slice(text.indexOf('：') + 1).trim() : text.trim();
  };
  const sourceDetails = document.querySelector('.dashboard-data-details');
  const overview = get('dashboardOverview');
  if (overview && sourceDetails) sourceDetails.querySelector('summary').after(overview);
  const health = get('providerHealthCard');
  if (health && sourceDetails) sourceDetails.append(health);
  if (get('dataStatusText') && sourceDetails) sourceDetails.append(get('dataStatusText'));
  const summary = document.createElement('details');
  summary.className = 'home-common-details';
  summary.innerHTML = '<summary>策略條件、通知時間與資料品質</summary>';
  const a = get(lists.A).parentElement;
  const b = get(lists.B1).parentElement;
  const grid = a.parentElement;
  const b2 = get(lists.B2).closest('section');
  const b3 = get(lists.B3).closest('section');
  const b1 = document.createElement('section');
  b1.append(b.firstElementChild, get(lists.B1));
  while (b.firstChild) {
    const child = b.firstChild;
    if (child === b2 || child === b3) b.removeChild(child);
    else summary.appendChild(child);
  }
  const policy = document.createElement('details');
  policy.className = 'home-policy';
  policy.innerHTML = '<summary>A 候選觀察與進場模式</summary>';
  const disclosure = get('aPolicyDisclosure');
  if (disclosure) {
    const heading = a.firstElementChild;
    disclosure.before(policy); policy.append(heading, disclosure);
    if (get('aCandidateList')) policy.append(get('aCandidateList'));
  }
  let hadCandidates = false;
  const revealCandidates = () => {
    const hasCandidates = !!get('aCandidateList')?.querySelector('article');
    if (hasCandidates && !hadCandidates) policy.open = true;
    hadCandidates = hasCandidates;
  };
  if (get('aCandidateList')) new MutationObserver(revealCandidates).observe(get('aCandidateList'), {childList:true});
  const rhythm = grid.previousElementSibling;
  if (rhythm && !rhythm.contains(get('intradayStamp'))) summary.prepend(rhythm);
  const tabs = document.createElement('div');
  tabs.id = 'homeStrategyTabs'; tabs.className = 'home-strategy-tabs';
  tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', '策略切換');
  const body = document.createElement('div'); body.className = 'home-strategy-body';
  Object.entries({A:a, B1:b1, B2:b2, B3:b3}).forEach(([lane, pane], i) => {
    panes[lane] = pane;
    pane.id = `homePane${lane}`; pane.classList.add('home-strategy-pane');
    pane.setAttribute('role', 'tabpanel'); pane.setAttribute('aria-labelledby', `homeTab${lane}`);
    const tab = document.createElement('button');
    tab.type = 'button'; tab.id = `homeTab${lane}`; tab.dataset.lane = lane;
    tab.setAttribute('role', 'tab'); tab.setAttribute('aria-controls', pane.id);
    tab.innerHTML = `<span class="home-lane-icon" aria-hidden="true">${lane}</span><span><b>${titles[lane]}</b><small id="homeCount${lane}">${lane === 'A' ? '研究' : '模擬'} · 等待資料</small></span>`;
    tab.addEventListener('click', () => select(lane));
    tab.addEventListener('keydown', event => {
      const keys = Object.keys(lists);
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? 3 : (i + (event.key === 'ArrowRight' ? 1 : 3)) % 4;
      select(keys[next]); get(`homeTab${keys[next]}`).focus();
    });
    tabs.append(tab); body.append(pane);
    const more = document.createElement('button');
    more.type = 'button'; more.className = 'home-more'; more.id = `homeMore${lane}`;
    more.addEventListener('click', () => { expanded[lane] = !expanded[lane]; refreshLists(); });
    listNodes[lane].after(more);
    const empty = document.createElement('p'); empty.id = `homeEmpty${lane}`; empty.hidden = true;
    empty.className = 'home-filter-empty'; empty.setAttribute('role', 'status');
    empty.textContent = '目前紀錄被價格／預算篩選隱藏，可清除篩選查看。';
    more.after(empty);
    new MutationObserver(refreshLists).observe(listNodes[lane], {childList:true});
  });
  grid.replaceWith(tabs, body, summary);
  const filter = document.querySelector('.filter-panel');
  if (filter) {
    const details = document.createElement('details'); details.className = 'home-filter-details';
    details.innerHTML = '<summary>價格／單張預算篩選 <span>只影響紀錄顯示</span></summary>';
    details.append(filter, get('priceFilterStatus'));
    tabs.after(details);
    filter.addEventListener('input', refreshLists);
    filter.addEventListener('change', refreshLists);
    filter.addEventListener('click', () => queueMicrotask(refreshLists));
  }
  const primary = get('intraday-strategies')?.parentElement;
  const heading = get('intraday-strategies');
  const section = module.closest('.recommendation-section');
  if (primary && heading && section) {
    const work = document.createElement('div'); work.className = 'home-workspace';
    const main = document.createElement('div'); main.className = 'home-main-column';
    const aside = document.createElement('aside'); aside.className = 'home-aside';
    aside.innerHTML = `<article class="home-note glass"><div class="home-eyebrow">AFTER THE BELL</div><h3>自己的節奏，<br><span>慢慢看清楚。</span></h3><p id="homeSessionNote">先確認資料日期與模式，再閱讀研究訊號與模擬紀錄。</p><div class="home-note-bottom">Research 研究 · Paper 模擬</div></article><article class="home-eight glass"><h3>開盤八法・尾盤八法</h3><p>盤勢分類與觀察選股。資料不足時保持等待，不把型態當成已驗證的買入訊號。</p><a href="#eight-methods">查看八法觀察 <span aria-hidden="true">→</span></a></article>`;
    heading.before(work); main.append(heading, section); work.append(main, aside);
  }
  function select(lane) {
    selected = lane;
    Object.keys(lists).forEach(key => {
      const active = key === lane, tab = get(`homeTab${key}`);
      panes[key].hidden = !active; tab.tabIndex = active ? 0 : -1;
      tab.setAttribute('aria-selected', String(active));
    });
    refreshLists();
  }
  function refreshLists() {
    const low = get('priceMin')?.value, high = get('priceMax')?.value, budget = get('budgetInput')?.value;
    const min = low === '' || low == null ? 0 : Number(low);
    const max = Math.min(high === '' || high == null ? Infinity : Number(high), budget === '' || budget == null ? Infinity : Number(budget) / 1000);
    Object.entries(lists).forEach(([lane, id]) => {
      const cards = [...get(id).querySelectorAll('.trade-detail-card')];
      let shown = 0, matched = 0;
      cards.forEach(card => {
        const price = Number(card.dataset.homePrice);
        const valid = Number.isFinite(price) && price >= min && price <= max;
        const open = card.dataset.homeStatus === 'OPEN';
        const visible = valid && (open || expanded[lane] || shown < 5);
        if (valid) matched++;
        card.hidden = !visible;
        if (visible) shown++;
      });
      setText(`homeCount${lane}`, `${lane === 'A' ? '研究' : '模擬'} · ${cards.length ? `${matched} 筆` : '等待資料'}`);
      const more = get(`homeMore${lane}`);
      more.hidden = matched <= 5;
      more.textContent = expanded[lane] ? '收合為前 5 筆 ↑' : `查看全部 ${matched} 筆 →`;
      get(`homeEmpty${lane}`).hidden = !cards.length || matched !== 0;
    });
  }
  function refreshSummary() {
    setText('homeResearchCount', field('researchTrades'));
    setText('homeResearchCaption', `研究完成 ${field('researchClosed')} 筆`);
    setText('homePaperFilled', field('researchPaperFilled'));
    setText('homePaperSkipped', field('researchPaperSkipped'));
    const pnl = field('researchPnl'); setText('homeResearchPnl', pnl);
    get('homeResearchPnl')?.classList.toggle('home-negative', /^[-−]/.test(pnl));
    get('homeResearchPnl')?.classList.toggle('home-positive', /^\+/.test(pnl));
    const coverage = field('learnCoverage'); setText('homeCoverage', coverage);
    const values = coverage.match(/^([\d,]+)\s*\/\s*([\d,]+)$/);
    const total = values ? Number(values[2].replaceAll(',', '')) : 0;
    const count = values ? Number(values[1].replaceAll(',', '')) : 0;
    const ratio = total > 0 && count >= 0 && count <= total ? 100 * count / total : null;
    setText('homeCoveragePercent', ratio == null ? '—' : `${ratio.toFixed(1)}%`);
    get('homeCoverageRing')?.style.setProperty('--home-coverage', `${ratio ?? 0}%`);
    setText('homeModelStatus', field('learnModel'));
    setText('homeLearningDays', field('learnDays'));
    setText('homeHistorySamples', field('historySamples'));
    const reportDate = get('researchSummaryDate')?.textContent.match(/\d{4}-\d{2}-\d{2}/)?.[0];
    setText('homeResearchDate', reportDate ? `研究資料日 ${reportDate}` : '研究日期待資料');
  }
  function update(next = {}) {
    context = next;
    setText('homeSnapshotState', get('overviewSession')?.textContent || '等待有效快照');
    const live = context.live || {};
    setText('homeOpenCount', context.health?.current ? Object.keys(live.open_positions || {}).length : '—');
    setText('homeSessionNote', !context.health?.current ? '資料尚待確認。保留最後紀錄，請先查看資料與模式。' : live.session === 'closed' ? '當沖時段已結束。先把進出場理由看清楚，比多追一個訊號更重要。' : '盤中資料持續更新。研究訊號與 Paper 成交分開呈現，依有效快照判讀。');
    refreshSummary(); refreshLists();
  }
  const learning = get('learningSection');
  if (learning) new MutationObserver(refreshSummary).observe(learning, {subtree:true, childList:true, characterData:true});
  const now = new Date();
  setText('homeDateDay', new Intl.DateTimeFormat('en-US', {timeZone:'Asia/Taipei',day:'2-digit'}).format(now));
  setText('homeDateMonth', new Intl.DateTimeFormat('en-US', {timeZone:'Asia/Taipei',month:'long'}).format(now).toUpperCase());
  setText('homeDateWeek', new Intl.DateTimeFormat('zh-TW', {timeZone:'Asia/Taipei',weekday:'long'}).format(now) + ` · ${new Intl.DateTimeFormat('en-US', {timeZone:'Asia/Taipei',year:'numeric'}).format(now)}`);
  get('homeDataDetails')?.addEventListener('click', () => {
    if (sourceDetails) sourceDetails.open = !sourceDetails.open;
    get('homeDataDetails').setAttribute('aria-expanded', String(!!sourceDetails?.open));
  });
  if (sourceDetails) sourceDetails.addEventListener('toggle', () => get('homeDataDetails')?.setAttribute('aria-expanded', String(sourceDetails.open)));
  window.HomePresentation = {update, refreshSummary, refreshLists, select};
  select(selected); refreshSummary();
})();
