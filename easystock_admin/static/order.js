(() => {
  const openBtn = document.getElementById("openOrderModal");
  const closeBtn = document.getElementById("closeOrderModal");
  const modal = document.getElementById("orderModal");

  const verifyBtn = document.getElementById("btnOrderVerify");
  const verifyBadge = document.getElementById("orderVerifyBadge");

  const symbolInput = document.getElementById("orderSymbol");
  const queryBtn = document.getElementById("btnOrderQuery");
  const quotePanel = document.getElementById("orderQuotePanel");
  const stockTitle = document.getElementById("orderStockTitle");
  const stockPrice = document.getElementById("orderStockPrice");
  const bidTable = document.getElementById("orderBidTable");
  const askTable = document.getElementById("orderAskTable");

  const btnUnitShare = document.getElementById("btnUnitShare");
  const btnUnitSheet = document.getElementById("btnUnitSheet");
  const qtyLabel = document.getElementById("orderQtyLabel");
  const quickQtyContainer = document.getElementById("quickQtyBtns");

  const priceInput = document.getElementById("orderPrice");
  const qtyInput = document.getElementById("orderQty");
  const totalEst = document.getElementById("orderTotalEst");
  const caPasswdInput = document.getElementById("orderCaPasswd");
  const submitBtn = document.getElementById("btnOrderSubmit");
  const orderResult = document.getElementById("orderResult");

  let currentUnit = "share"; // "share" (股) 或 "sheet" (張)

  // admin.js 登入後保存的 CSRF token；寫入型操作都必須帶上。
  function headers() {
    return { "Content-Type": "application/json", "X-CSRF-Token": typeof csrf === "string" ? csrf : "" };
  }

  function closeModal() {
    modal.hidden = true;
    openBtn?.focus();
  }
  openBtn?.addEventListener("click", () => {
    modal.hidden = false;
    closeBtn?.focus();
  });
  closeBtn?.addEventListener("click", closeModal);
  modal?.addEventListener("click", event => {
    if (event.target === modal) closeModal();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && modal && !modal.hidden) closeModal();
  });

  // 1. 單位切換：股 vs 張
  function setUnit(unit) {
    currentUnit = unit;
    if (unit === "share") {
      btnUnitShare.classList.add("active");
      btnUnitSheet.classList.remove("active");
      qtyLabel.textContent = "委託數量 (股)";
      quickQtyContainer.innerHTML = `
        <button type="button" data-qty="1">1</button>
        <button type="button" data-qty="10">10</button>
        <button type="button" data-qty="100">100</button>
      `;
    } else {
      btnUnitSheet.classList.add("active");
      btnUnitShare.classList.remove("active");
      qtyLabel.textContent = "委託數量 (張)";
      quickQtyContainer.innerHTML = `
        <button type="button" data-qty="1">1</button>
        <button type="button" data-qty="2">2</button>
        <button type="button" data-qty="5">5</button>
      `;
    }
    calcTotal();
  }

  btnUnitShare?.addEventListener("click", () => setUnit("share"));
  btnUnitSheet?.addEventListener("click", () => setUnit("sheet"));

  // 快捷數量按鈕點擊
  quickQtyContainer?.addEventListener("click", (e) => {
    if (e.target.tagName === "BUTTON") {
      qtyInput.value = e.target.getAttribute("data-qty");
      calcTotal();
    }
  });

  // 計算預估交割金額 (張 = 1000 股)
  function calcTotal() {
    const p = parseFloat(priceInput.value) || 0;
    const q = parseInt(qtyInput.value) || 0;
    const multiplier = currentUnit === "sheet" ? 1000 : 1;
    const total = Math.round(p * q * multiplier);
    if (totalEst) {
      totalEst.textContent = `預估交割金額：約 ${total.toLocaleString()} 元`;
    }
  }
  priceInput?.addEventListener("input", calcTotal);
  qtyInput?.addEventListener("input", calcTotal);

  // 安全解析 JSON 回應
  async function parseResponse(res, defaultError) {
    let data;
    try {
      data = await res.json();
    } catch {
      throw new Error(`伺服器回應異常 (HTTP ${res.status})，請確認網路或登入狀態後重試`);
    }
    if (!res.ok || !data.ok) {
      throw new Error(data.message || data.error || defaultError);
    }
    return data;
  }

  // 2. 帳號連線驗證
  verifyBtn?.addEventListener("click", async () => {
    verifyBtn.disabled = true;
    verifyBadge.textContent = "正在連線永豐 API…";
    verifyBadge.className = "order-badge loading";
    try {
      const res = await fetch("/admin/api/order/verify", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({})
      });
      const data = await parseResponse(res, "連線驗證失敗");
      const acc = data.account;
      verifyBadge.textContent = `✅ 連線成功！戶名：${acc.person_name} (帳號: ${acc.account_id})`;
      verifyBadge.className = "order-badge success";
    } catch (err) {
      verifyBadge.textContent = `❌ ${err.message}`;
      verifyBadge.className = "order-badge error";
    } finally {
      verifyBtn.disabled = false;
    }
  });

  // 3. 股票報價與五檔
  queryBtn?.addEventListener("click", async () => {
    const sym = symbolInput.value.trim();
    if (!sym) return alert("請輸入股票代碼！");
    queryBtn.disabled = true;
    queryBtn.textContent = "查詢中…";
    try {
      const res = await fetch("/admin/api/order/quote", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ symbol: sym })
      });
      const data = await parseResponse(res, "報價查詢失敗");

      const q = data.quote;
      stockTitle.textContent = `${q.name} (${q.symbol})`;
      stockPrice.textContent = `${q.close.toFixed(2)} 元 (${q.change_pct > 0 ? "+" : ""}${q.change_pct}%)`;
      stockPrice.style.color = q.change_pct > 0 ? "#ef4444" : (q.change_pct < 0 ? "#22c55e" : "#888");

      priceInput.value = q.close;
      calcTotal();

      // 以 data-price 加事件委派帶入價格；CSP 不允許行內 onclick。
      const levels = (rows, color, empty) => rows.map(level => `
        <tr style="cursor:pointer;" data-price="${Number(level.price)}">
          <td style="color:${color};font-weight:bold;">${Number(level.price).toFixed(2)}</td>
          <td style="text-align:right;color:#888;">${Number(level.volume)}</td>
        </tr>
      `).join("") || `<tr><td colspan='2'>${empty}</td></tr>`;
      bidTable.innerHTML = levels(q.bids || [], "#ef4444", "無買盤");
      askTable.innerHTML = levels(q.asks || [], "#22c55e", "無賣盤");

      quotePanel.hidden = false;
    } catch (err) {
      alert(`報價查詢失敗：${err.message}`);
    } finally {
      queryBtn.disabled = false;
      queryBtn.textContent = "查詢報價";
    }
  });

  for (const table of [bidTable, askTable]) {
    table?.addEventListener("click", event => {
      const row = event.target.closest("tr[data-price]");
      if (!row) return;
      priceInput.value = row.dataset.price;
      calcTotal();
    });
  }

  // 4. 送單確認
  submitBtn?.addEventListener("click", async () => {
    const sym = symbolInput.value.trim();
    const p = parseFloat(priceInput.value);
    const q = parseInt(qtyInput.value);
    const caPw = caPasswdInput.value.trim();

    if (!sym || !p || !q) return alert("請填妥股票代碼、價格與委託數量！");
    if (!caPw) return alert("下單必須填寫憑證密碼（CA密碼）！");

    const isOdd = (currentUnit === "share");
    const unitText = isOdd ? "股" : "張";
    const multiplier = isOdd ? 1 : 1000;
    const total = Math.round(p * q * multiplier);

    const ok = confirm(`【正式送單確認】\n\n` +
      `標的：${sym}\n` +
      `動作：買進\n` +
      `價格：${p.toFixed(2)} 元\n` +
      `數量：${q} ${unitText}\n` +
      `預估金額：約 ${total.toLocaleString()} 元\n\n` +
      `確定要送出委託嗎？`);

    if (!ok) return;

    // 每次確認送單產生一個識別碼；伺服器拒絕重複的識別碼，避免重複委託。
    const clientOrderId = crypto.randomUUID();

    submitBtn.disabled = true;
    submitBtn.textContent = "送單中…";
    orderResult.textContent = "正在簽章送單…";

    try {
      const res = await fetch("/admin/api/order/place", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({
          client_order_id: clientOrderId,
          symbol: sym,
          action: "BUY",
          price: p,
          quantity: q,
          is_odd_lot: isOdd,
          ca_passwd: caPw
        })
      });
      const data = await parseResponse(res, "下單委託失敗");
      const t = data.trade;
      orderResult.style.color = "#4ade80";
      orderResult.textContent = `✅ 委託成功！書號：${t.order_id} ｜ 狀態：${t.status}`;
      alert(`🎉 委託成功送出！\n委託書號：${t.order_id}`);
    } catch (err) {
      orderResult.style.color = "#ef4444";
      orderResult.textContent = `❌ 下單失敗: ${err.message}`;
      alert(`下單失敗：${err.message}`);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "⚡ 確認送出委託";
    }
  });
})();
