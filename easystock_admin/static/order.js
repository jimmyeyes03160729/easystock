(() => {
  const get = id => document.getElementById(id);
  const panel = get('manualOrderPanel');
  if (!panel) return;
  let state = null, action = 'BUY', unit = 'share', verification = null;
  let busy = false, uncertain = false, refreshGeneration = 0, verificationTimer = 0;
  const authenticated = () => !get('workspace').hidden;
  const say = (id, message, error = false) => {
    get(id).textContent = message;
    get(id).classList.toggle('error', error);
  };
  const text = value => value === null || value === undefined ? '未知' : String(value);
  const statusLabels = {
    PendingSubmit: '送出處理中', PreSubmitted: '券商處理中', Submitted: '已受理，等待成交',
    PartFilled: '部分成交', Filled: '全部成交', Cancelled: '已取消', Failed: '委託失敗／拒絕', Inactive: '尚未生效'
  };
  const statusName = value => statusLabels[String(value).split('.').pop()] || text(value);
  function resetPrivateState() {
    state = null; refreshGeneration++; invalidate(); get('orderCaPasswd').value = '';
    for (const id of ['orderPositions', 'orderOrders', 'orderDeals']) get(id).replaceChildren();
    get('orderQuotePanel').hidden = true;
    say('orderVerifyBadge', '尚未驗證'); say('orderPortfolioStatus', '請先使用 Google 登入。');
    say('orderResult', ''); updateControls();
  }
  async function request(path, body) {
    const response = await fetch('/admin/' + path, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      headers: body === undefined ? {} : {'Content-Type': 'application/json', 'X-CSRF-Token': typeof csrf === 'string' ? csrf : ''},
      ...(body === undefined ? {} : {body: JSON.stringify(body)})
    });
    if (response.status === 401) {
      get('workspace').hidden = true; get('login').hidden = false; resetPrivateState();
      say('loginStatus', '登入已失效，請重新登入。'); get('retryLogin').hidden = false;
    }
    let data;
    try { data = await response.json(); }
    catch { throw Object.assign(new Error('伺服器回應無法確認，請同步券商檢查。'), {status: response.status}); }
    if (!response.ok || data.ok === false) throw Object.assign(new Error(data.message || data.error || '券商操作失敗。'), {status: response.status});
    return data;
  }
  function table(id, rows, columns, sell = false) {
    const root = get(id); root.replaceChildren();
    if (!state?.broker?.complete || !state.broker_fresh) {
      root.textContent = '券商資料尚未完整同步，不代表沒有持股或委託。'; return;
    }
    if (!rows?.length) { root.textContent = sell ? '券商目前沒有持股。' : '券商目前沒有紀錄。'; return; }
    const table = document.createElement('table'), head = document.createElement('thead'), title = document.createElement('tr'), body = document.createElement('tbody');
    for (const [, label] of columns) { const th = document.createElement('th'); th.textContent = label; title.append(th); }
    if (sell) { const th = document.createElement('th'); th.textContent = '操作'; title.append(th); }
    head.append(title); table.append(head, body);
    for (const row of rows) {
      const tr = document.createElement('tr');
      for (const [key] of columns) {
        const td = document.createElement('td');
        td.textContent = key === 'status' ? statusName(row[key]) : key === 'side' ? ({BUY: '買進', SELL: '賣出'}[row[key]] || text(row[key])) : text(row[key]);
        tr.append(td);
      }
      if (sell) {
        const td = document.createElement('td'), button = document.createElement('button');
        button.type = 'button'; button.textContent = '帶入賣出';
        button.disabled = busy || !state.ordering_guard || !(row.available_to_sell > 0);
        button.addEventListener('click', () => {
          if (busy) return;
          get('orderSymbol').value = row.symbol; get('orderPrice').value = row.current_price ?? '';
          setUnit('share'); get('orderQty').value = Math.min(row.available_to_sell, 999); setAction('SELL');
          say('orderSellEvidence', `${row.symbol} ${row.name} · 可賣 ${row.available_to_sell} 股；請驗證本次賣出。`);
          calcTotal(); get('orderSymbol').focus();
        });
        td.append(button); tr.append(td);
      }
      body.append(tr);
    }
    root.append(table);
  }
  async function refresh() {
    if (!authenticated()) return;
    const generation = ++refreshGeneration;
    get('btnOrderRefresh').disabled = true;
    try {
      const data = await request('api/live-console');
      if (generation !== refreshGeneration || !authenticated()) return;
      state = data;
      const broker = data.broker || {};
      say('orderPortfolioStatus', broker.complete && data.broker_fresh
        ? `帳戶 ${text(broker.account?.account_id)} · 同步時間 ${text(broker.updated_at)}${data.ordering_guard ? '' : ' · 實單送出尚未啟用'}`
        : '券商持股尚未確認，請先連線驗證，再同步券商。', !broker.complete || !data.broker_fresh);
      table('orderPositions', broker.positions, [['symbol', '股票代碼'], ['name', '名稱'], ['quantity', '持股（股）'], ['available_to_sell', '可賣（股）'], ['average_price', '均價'], ['current_price', '現價'], ['unrealized_pnl', '未實現損益']], true);
      table('orderOrders', broker.orders, [['symbol', '股票'], ['side', '方向'], ['qty', '委託股數'], ['price', '限價'], ['status', '結果'], ['filled_qty', '已成交股數'], ['order_id', '委託識別']]);
      table('orderDeals', broker.deals, [['symbol', '股票'], ['side', '方向'], ['qty', '成交股數'], ['price', '成交價'], ['deal_time', '成交時間']]);
    } catch (error) {
      if (generation !== refreshGeneration) return;
      state = null; invalidate();
      say('orderPortfolioStatus', error.message, true);
      for (const id of ['orderPositions', 'orderOrders', 'orderDeals']) get(id).replaceChildren();
    } finally { if (generation === refreshGeneration) get('btnOrderRefresh').disabled = false; updateControls(); }
  }
  function invalidate() {
    clearTimeout(verificationTimer); verification = null;
    get('orderCaPasswd').value = ''; get('orderSellConfirm').value = ''; get('orderSellAccount').value = '';
    say('orderSellEvidence', '賣出前請先驗證；更改代碼、數量或價格後需重新驗證。');
    updateControls();
  }
  function updateControls() {
    const confirmed = verification && Date.now() < verification.deadline &&
      get('orderSellConfirm').value === 'SELL' && get('orderSellAccount').value === verification.account.account_id;
    get('btnOrderSubmit').disabled = busy || uncertain || !authenticated() || !state?.ordering_guard || !state?.broker?.authenticated || (action === 'SELL' && !confirmed);
    for (const id of ['btnOrderBuy', 'btnOrderSell', 'btnUnitShare', 'btnUnitSheet', 'orderSymbol', 'orderPrice', 'orderQty', 'btnOrderQuery', 'btnOrderVerify', 'btnOrderSellVerify']) get(id).disabled = busy || !authenticated();
  }
  function setAction(value) {
    if (busy) return;
    action = value; invalidate();
    for (const [id, selected] of [['btnOrderBuy', value === 'BUY'], ['btnOrderSell', value === 'SELL']]) {
      get(id).classList.toggle('active', selected); get(id).setAttribute('aria-pressed', String(selected));
    }
    get('orderSellVerification').hidden = value !== 'SELL';
    get('btnOrderSubmit').textContent = value === 'BUY' ? '確認送出買進委託' : '確認送出賣出委託';
  }
  function setUnit(value) {
    if (busy) return;
    unit = value; invalidate();
    get('btnUnitShare').classList.toggle('active', value === 'share'); get('btnUnitSheet').classList.toggle('active', value === 'sheet');
    get('orderQtyLabel').textContent = value === 'share' ? '委託數量（股）' : '委託數量（張）';
    get('orderQty').max = value === 'share' ? 999 : 499;
    const root = get('quickQtyBtns'); root.replaceChildren();
    for (const qty of value === 'share' ? [1, 10, 100] : [1, 2, 5]) {
      const button = document.createElement('button'); button.type = 'button'; button.dataset.qty = qty; button.textContent = qty; root.append(button);
    }
    calcTotal();
  }
  function calcTotal() {
    const amount = Number(get('orderPrice').value) * Number(get('orderQty').value) * (unit === 'share' ? 1 : 1000);
    say('orderTotalEst', `預估交割金額：約 ${Number.isFinite(amount) ? Math.round(amount).toLocaleString('zh-TW') : '未知'} 元（未含手續費及稅）`);
  }
  function order(clientId) {
    const result = {client_order_id: clientId, symbol: get('orderSymbol').value.trim(), action,
      price: Number(get('orderPrice').value), quantity: Number(get('orderQty').value), is_odd_lot: unit === 'share'};
    if (!/^[0-9]{4,6}[A-Z]?$/.test(result.symbol) || !Number.isFinite(result.price) || result.price <= 0 || !Number.isInteger(result.quantity) || result.quantity < 1 || result.quantity > (result.is_odd_lot ? 999 : 499)) throw Error('請填妥股票代碼、正數價格與合法整數數量。');
    return result;
  }
  get('btnOrderBuy').addEventListener('click', () => setAction('BUY'));
  get('btnOrderSell').addEventListener('click', () => setAction('SELL'));
  get('btnUnitShare').addEventListener('click', () => setUnit('share'));
  get('btnUnitSheet').addEventListener('click', () => setUnit('sheet'));
  get('quickQtyBtns').addEventListener('click', event => {
    const button = event.target.closest('button[data-qty]'); if (!button || busy) return;
    get('orderQty').value = button.dataset.qty; invalidate(); calcTotal();
  });
  for (const id of ['orderSymbol', 'orderPrice', 'orderQty']) get(id).addEventListener('input', () => {
    if (id === 'orderSymbol') get('orderQuotePanel').hidden = true;
    invalidate(); calcTotal();
  });
  for (const id of ['orderSellConfirm', 'orderSellAccount', 'orderCaPasswd']) get(id).addEventListener('input', updateControls);
  get('btnOrderRefresh').addEventListener('click', refresh);
  get('btnOrderVerify').addEventListener('click', async () => {
    if (busy || !authenticated()) return;
    busy = true; invalidate(); say('orderVerifyBadge', '正在連線永豐 API…');
    try {
      const data = await request('api/order/verify', {});
      say('orderVerifyBadge', `連線成功 · ${data.account.person_name} · 帳戶 ${data.account.account_id}`);
      await refresh();
    } catch (error) { say('orderVerifyBadge', error.message, true); }
    finally { busy = false; updateControls(); }
  });
  get('btnOrderQuery').addEventListener('click', async () => {
    if (busy || !authenticated()) return;
    const symbol = get('orderSymbol').value.trim();
    if (!symbol) { say('orderResult', '請輸入股票代碼。', true); return; }
    busy = true; invalidate();
    try {
      const {quote} = await request('api/order/quote', {symbol});
      get('orderStockTitle').textContent = `${quote.name} (${quote.symbol})`;
      get('orderStockPrice').textContent = `${Number(quote.close).toFixed(2)} 元（${text(quote.change_pct)}%）`;
      get('orderPrice').value = quote.close; calcTotal();
      for (const [id, rows] of [['orderBidTable', quote.bids], ['orderAskTable', quote.asks]]) {
        const table = get(id); table.replaceChildren();
        for (const level of rows || []) {
          const tr = document.createElement('tr'), price = document.createElement('td'), volume = document.createElement('td'), button = document.createElement('button');
          button.type = 'button'; button.textContent = Number(level.price).toFixed(2);
          button.addEventListener('click', () => { if (busy) return; get('orderPrice').value = level.price; invalidate(); calcTotal(); });
          price.append(button); volume.textContent = text(level.volume); tr.append(price, volume); table.append(tr);
        }
      }
      get('orderQuotePanel').hidden = false;
    } catch (error) { say('orderResult', `報價查詢失敗：${error.message}`, true); }
    finally { busy = false; updateControls(); }
  });
  get('btnOrderSellVerify').addEventListener('click', async () => {
    if (busy || !authenticated() || action !== 'SELL') return;
    busy = true; invalidate();
    try {
      const value = order(crypto.randomUUID());
      const result = await request('api/live-console/sell-verify', value);
      verification = {...result, order: value, deadline: Date.now() + result.expires_in * 1000};
      say('orderSellEvidence', `可賣 ${result.available_to_sell} 股 · 帳戶 ${result.account.account_id} · 驗證 ${result.expires_in} 秒有效；請輸入 SELL 與此遮罩帳戶。`);
      verificationTimer = setTimeout(() => { invalidate(); say('orderSellEvidence', '驗證已過期，請重新驗證。'); }, result.expires_in * 1000);
    } catch (error) { say('orderSellEvidence', error.message, true); }
    finally { busy = false; updateControls(); }
  });
  get('btnOrderSubmit').addEventListener('click', async () => {
    updateControls(); if (get('btnOrderSubmit').disabled) return;
    let value;
    try {
      value = order(verification?.order.client_order_id || crypto.randomUUID());
      const password = get('orderCaPasswd').value;
      if (!password) throw Error('請輸入憑證密碼。');
      const direction = action === 'BUY' ? '買進' : '賣出';
      if (!confirm(`【正式${direction}委託確認】\n股票：${value.symbol}\n限價：${value.price} 元\n數量：${value.quantity} ${unit === 'share' ? '股' : '張'}\n確認送出${direction}委託？`)) return;
      value.ca_passwd = password;
      if (action === 'SELL') Object.assign(value, {sell_verification_id: verification.verification_id, confirm_sell: 'SELL', confirm_account: get('orderSellAccount').value});
    } catch (error) { say('orderResult', error.message, true); return; }
    busy = true; invalidate(); say('orderResult', '正在送出委託，請勿重複操作…');
    try {
      const result = await request('api/order/place', value), trade = result.trade;
      const failed = String(trade.status).split('.').pop() === 'Failed';
      say('orderResult', `${value.action === 'BUY' ? '買進' : '賣出'}委託：${statusName(trade.status)} · 委託書號 ${text(trade.order_id)}。成交結果請查看「今日委託與成交結果」。`, failed);
      await refresh();
    } catch (error) {
      uncertain = !error.status || error.status >= 500 || /尚未確認|無法確認/.test(error.message);
      say('orderResult', uncertain ? `委託結果尚未確認：${error.message} 請同步券商／對帳，勿重送。` : `委託未送出：${error.message}`, true);
    } finally { value.ca_passwd = ''; busy = false; invalidate(); }
  });
  window.loadManualOrders = refresh;
  document.addEventListener('easystock:owner-ready', refresh);
  document.addEventListener('easystock:owner-ended', resetPrivateState);
  get('logout').addEventListener('click', resetPrivateState);
  updateControls();
})();
