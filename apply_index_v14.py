#!/usr/bin/env python3
# Easystock index.html v1.4 patcher
#
# 用法：
#   把本檔放在 easystock repo 根目錄（旁邊有 index.html）
#   python apply_index_v14.py
#
# 會先備份：
#   index.html.before-shioaji-v14.bak

from pathlib import Path
import re
import shutil
import sys

INDEX = Path("index.html")
BACKUP = Path("index.html.before-shioaji-v14.bak")


def die(msg):
    print(f"[ERROR] {msg}")
    sys.exit(1)


def replace_once(text, old, new, label, required=True):
    if old not in text:
        if required:
            die(f"找不到要修改的區塊：{label}")
        print(f"[SKIP] {label}")
        return text
    text = text.replace(old, new, 1)
    print(f"[OK] {label}")
    return text


def find_js_function_span(text, name):
    pat = re.compile(
        rf"(?m)^[ \t]*(?:async[ \t]+)?function[ \t]+{re.escape(name)}[ \t]*\("
    )
    m = pat.search(text)
    if not m:
        return None

    start = m.start()
    brace = text.find("{", m.end())
    if brace < 0:
        return None

    i = brace
    depth = 0
    state = "code"
    quote = None

    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if state == "code":
            if ch == "/" and nxt == "/":
                state = "line_comment"
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block_comment"
                i += 2
                continue
            if ch in ("'", '"', "`"):
                state = "string"
                quote = ch
                i += 1
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    while end < len(text) and text[end] in " \t":
                        end += 1
                    if end < len(text) and text[end] == "\n":
                        end += 1
                    return start, end

        elif state == "string":
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                state = "code"
                quote = None

        elif state == "line_comment":
            if ch == "\n":
                state = "code"

        elif state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "code"
                i += 2
                continue

        i += 1

    return None


def replace_js_function(text, name, new_code, required=True):
    span = find_js_function_span(text, name)
    if not span:
        if required:
            die(f"找不到 JavaScript 函式：{name}")
        print(f"[SKIP] function {name}")
        return text

    start, end = span
    text = text[:start] + new_code.rstrip() + "\n\n" + text[end:]
    print(f"[OK] function {name}")
    return text


PREMARKET_SECTION = '''
  <!-- =====================================================
       AI PREMARKET BRIEF
       ===================================================== -->

  <section
    id="premarketBriefSection"
    class="panel rounded-2xl p-4">

    <div class="flex flex-wrap items-start justify-between gap-3">

      <div>
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-bold text-main">
            🤖 AI 開盤前市場通報
          </h2>

          <span
            id="premarketMarketLevel"
            class="text-[9px] rounded border muted-border px-2 py-0.5 text-sub">
            等待 AI
          </span>
        </div>

        <div
          id="premarketGeneratedAt"
          class="text-[9px] text-sub font-mono mt-1">
          每日開盤前更新
        </div>
      </div>

      <a
        href="https://jimmyeyes03160729.github.io/easystock/"
        target="_blank"
        rel="noopener noreferrer"
        class="btn px-3 py-1.5 rounded-lg text-[10px] font-bold">
        墨衡量化 ↗
      </a>
    </div>


    <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3">

      <div class="rounded-xl border muted-border p-2.5">
        <div class="text-[9px] text-sub">AI 風險分數</div>
        <div id="premarketRiskScore" class="text-xl font-bold text-main mt-1">--</div>
      </div>

      <div class="rounded-xl border muted-border p-2.5">
        <div class="text-[9px] text-sub">市場偏向</div>
        <div id="premarketBias" class="text-sm font-bold text-main mt-2">--</div>
      </div>

      <div class="rounded-xl border muted-border p-2.5">
        <div class="text-[9px] text-sub">預估波動</div>
        <div id="premarketVolatility" class="text-sm font-bold text-main mt-2">--</div>
      </div>

      <div class="rounded-xl border muted-border p-2.5">
        <div class="text-[9px] text-sub">當沖模式</div>
        <div class="text-[10px] font-bold text-amber-300 mt-1 leading-relaxed">
          09:30 開始<br>
          12:30 停新倉<br>
          12:55 全出
        </div>
      </div>

    </div>


    <div class="grid grid-cols-1 lg:grid-cols-3 gap-3 mt-3">

      <div class="lg:col-span-2 rounded-xl border muted-border p-3">
        <div class="text-[10px] font-bold text-cyan-300">🧠 AI 判讀</div>

        <div
          id="premarketSummary"
          class="text-[11px] text-sub leading-relaxed mt-2 whitespace-pre-line">
          尚未取得今日 AI 開盤前分析。
        </div>
      </div>

      <div class="rounded-xl border muted-border p-3">
        <div class="text-[10px] font-bold text-emerald-300">🎯 今日重點</div>

        <div
          id="premarketFocus"
          class="text-[10px] text-sub mt-2 space-y-1">
          <div>等待 AI 分析...</div>
        </div>
      </div>

    </div>


    <div
      id="premarketMarkets"
      class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 mt-3">
    </div>

  </section>

'''


RENDER_PREMARKET = r'''  function renderPremarketBrief() {

    const brief =
      PREMARKET_BRIEF || {};

    const level =
      String(
        brief.market_level || ""
      ).toUpperCase();

    const levelMap = {
      GREEN: {
        label: "🟢 GREEN",
        cls: "text-emerald-300 border-emerald-500/40"
      },
      YELLOW: {
        label: "🟡 YELLOW",
        cls: "text-amber-300 border-amber-500/40"
      },
      RED: {
        label: "🔴 RED",
        cls: "text-rose-300 border-rose-500/40"
      }
    };

    const levelInfo =
      levelMap[level]
      || {
        label: "等待 AI",
        cls: "text-sub muted-border"
      };


    const levelEl =
      document.getElementById(
        "premarketMarketLevel"
      );

    if (levelEl) {
      levelEl.textContent =
        levelInfo.label;

      levelEl.className =
        `text-[9px] rounded border px-2 py-0.5 ${levelInfo.cls}`;
    }


    const generatedEl =
      document.getElementById(
        "premarketGeneratedAt"
      );

    if (generatedEl) {
      generatedEl.textContent =
        brief.generated_at
          ? `AI 更新 ${formatTaiwanDateTime(brief.generated_at)}`
          : "每日開盤前更新";
    }


    const riskEl =
      document.getElementById(
        "premarketRiskScore"
      );

    if (riskEl) {
      const risk =
        n(
          brief.risk_score
        );

      riskEl.textContent =
        risk === null
          ? "--"
          : `${fmt(risk, 0)} / 100`;

      riskEl.className =
        risk === null
          ? "text-xl font-bold text-main mt-1"
          : risk >= 70
            ? "text-xl font-bold text-rose-300 mt-1"
            : risk >= 40
              ? "text-xl font-bold text-amber-300 mt-1"
              : "text-xl font-bold text-emerald-300 mt-1";
    }


    const biasEl =
      document.getElementById(
        "premarketBias"
      );

    if (biasEl) {
      const biasLabels = {
        BULLISH: "偏多",
        CAUTIOUS_BULLISH: "謹慎偏多",
        NEUTRAL: "中性",
        CAUTIOUS_BEARISH: "謹慎偏空",
        BEARISH: "偏空"
      };

      biasEl.textContent =
        biasLabels[brief.market_bias]
        ||
        brief.market_bias
        ||
        "--";
    }


    const volEl =
      document.getElementById(
        "premarketVolatility"
      );

    if (volEl) {
      const volLabels = {
        LOW: "低",
        MEDIUM: "中等",
        HIGH: "高",
        EXTREME: "極高"
      };

      volEl.textContent =
        volLabels[brief.expected_volatility]
        ||
        brief.expected_volatility
        ||
        "--";
    }


    const summaryEl =
      document.getElementById(
        "premarketSummary"
      );

    if (summaryEl) {
      summaryEl.textContent =
        brief.summary
        ||
        "尚未取得今日 AI 開盤前分析。";
    }


    const focusEl =
      document.getElementById(
        "premarketFocus"
      );

    if (focusEl) {
      const focus =
        Array.isArray(
          brief.focus
        )
          ? brief.focus
          : [];

      focusEl.innerHTML =
        focus.length
          ? focus
              .slice(0, 8)
              .map(
                item => `
                  <div>
                    • ${escapeHtml(item)}
                  </div>
                `
              )
              .join("")
          : `
              <div>
                等待 AI 分析...
              </div>
            `;
    }


    const marketsEl =
      document.getElementById(
        "premarketMarkets"
      );

    if (marketsEl) {
      const markets =
        brief.markets
        ||
        brief.market_data
        ||
        {};

      const marketItems = [
        ["S&P 500", markets.sp500],
        ["Nasdaq", markets.nasdaq],
        ["SOX", markets.sox],
        ["台積電 ADR", markets.tsm_adr],
        ["台指夜盤", markets.taiwan_night],
        ["VIX", markets.vix]
      ];

      marketsEl.innerHTML =
        marketItems
        .map(
          ([label, value]) => {

            let text = "--";
            let cls = "text-main";

            if (
              value !== null
              &&
              value !== undefined
            ) {

              if (
                typeof value === "object"
              ) {

                const change =
                  n(
                    value.change_pct
                  );

                const price =
                  n(
                    value.price
                  );

                if (
                  change !== null
                ) {

                  text =
                    `${
                      change >= 0
                        ? "+"
                        : ""
                    }${fmt(change, 2)}%`;

                  cls =
                    change > 0
                      ? "text-emerald-300"
                      : change < 0
                        ? "text-rose-300"
                        : "text-main";

                } else if (
                  price !== null
                ) {

                  text =
                    fmt(
                      price,
                      2
                    );
                }

              } else {

                const numeric =
                  n(value);

                if (
                  numeric !== null
                ) {

                  text =
                    `${
                      numeric >= 0
                        ? "+"
                        : ""
                    }${fmt(numeric, 2)}%`;

                  cls =
                    numeric > 0
                      ? "text-emerald-300"
                      : numeric < 0
                        ? "text-rose-300"
                        : "text-main";
                }
              }
            }

            return `
              <div class="rounded-xl border muted-border p-2.5">
                <div class="text-[8px] text-sub">
                  ${escapeHtml(label)}
                </div>
                <div class="text-[11px] font-bold mt-1 ${cls}">
                  ${escapeHtml(text)}
                </div>
              </div>
            `;
          }
        )
        .join("");
    }
  }
'''


LIVE_INTRADAY_FUNCTIONS = r'''  function renderLiveIntraday() {

    const container =
      document.getElementById(
        "intradayPickList"
      );

    const stamp =
      document.getElementById(
        "intradayStamp"
      );

    if (!container) {
      return;
    }

    const lastUpdate =
      INTRADAY_LIVE?.last_update_at
      ||
      INTRADAY_LIVE?.generated_at;

    const session =
      INTRADAY_LIVE?.session
      ||
      "unknown";

    const sessionLabels = {
      preopen: "開盤前",
      daytrade: "即時監控",
      no_new_entry: "停止新進場",
      force_exit: "強制出場",
      closed: "當沖已結束"
    };

    if (stamp) {
      stamp.textContent =
        lastUpdate
          ? `${
              sessionLabels[session]
              || session
            } · ${formatTaiwanDateTime(lastUpdate)}`
          : "等待 Shioaji";
    }


    const openRows =
      Object.values(
        INTRADAY_LIVE?.open_positions
        || {}
      )
      .filter(Boolean)
      .map(
        x => ({
          ...x,
          _liveStatus: "OPEN"
        })
      );

    const closedRows =
      Object.values(
        INTRADAY_LIVE?.closed_trades
        || {}
      )
      .filter(Boolean)
      .map(
        x => ({
          ...x,
          _liveStatus: "CLOSED"
        })
      )
      .sort(
        (a, b) => {
          const ta =
            Date.parse(
              a.exit_time || ""
            )
            || 0;

          const tb =
            Date.parse(
              b.exit_time || ""
            )
            || 0;

          return tb - ta;
        }
      );


    let rows = [
      ...openRows,
      ...closedRows
    ];


    rows =
      rows.filter(
        x => {

          const price =
            n(
              x.current_price
              ??
              x.exit_price
              ??
              x.entry_price
            );

          if (
            price === null
          ) {
            return false;
          }

          if (
            PRICE_MIN !== null
            &&
            price < PRICE_MIN
          ) {
            return false;
          }

          if (
            PRICE_MAX !== null
            &&
            price > PRICE_MAX
          ) {
            return false;
          }

          if (
            BUDGET_MAX !== null
            &&
            price * 1000 > BUDGET_MAX
          ) {
            return false;
          }

          return true;
        }
      );


    rows =
      rows.slice(
        0,
        6
      );


    if (!rows.length) {

      let message;

      if (
        session === "closed"
      ) {

        message =
          "今日當沖已結束。13:00 後不再產生新的當沖訊號。";

      } else if (
        session === "no_new_entry"
      ) {

        message =
          "12:30 後停止新進場；現有部位持續監控至出場。";

      } else if (
        session === "force_exit"
      ) {

        message =
          "12:55 強制出場階段。";

      } else {

        message =
          "目前沒有 OPEN 部位或今日完成交易。";
      }

      container.innerHTML = `
        <div class="text-[11px] text-sub text-center py-8">
          ${message}
        </div>
      `;

      return;
    }


    container.innerHTML =
      rows
      .map(
        x => {

          const isOpen =
            x._liveStatus
            === "OPEN";

          const entry =
            n(
              x.entry_price
            );

          const current =
            n(
              x.current_price
            );

          const exit =
            n(
              x.exit_price
            );

          const displayPrice =
            isOpen
              ? (
                  current
                  ??
                  entry
                )
              : (
                  exit
                  ??
                  entry
                );

          let pnl = null;

          if (
            isOpen
            &&
            entry !== null
            &&
            current !== null
            &&
            entry > 0
          ) {

            pnl =
              (
                current
                /
                entry
                -
                1
              )
              *
              100;

          } else if (
            !isOpen
          ) {

            pnl =
              n(
                x.pnl_pct
              );
          }

          const pnlClass =
            pnl === null
              ? "text-sub"
              : pnl > 0
                ? "text-emerald-300"
                : pnl < 0
                  ? "text-rose-300"
                  : "text-sub";

          const pnlText =
            pnl === null
              ? "--"
              : `${
                  pnl >= 0
                    ? "+"
                    : ""
                }${fmt(pnl, 2)}%`;

          const statusClass =
            isOpen
              ? "text-emerald-300 border-emerald-500/40"
              : "text-slate-300 border-slate-500/40";

          const reasons =
            Array.isArray(
              x.entry_reasons
            )
              ? x.entry_reasons
              : [];

          return `
            <div class="rounded-xl border muted-border p-3 bg-black/10">

              <div class="flex items-start justify-between gap-2">

                <div>
                  <div class="flex items-center gap-1.5">

                    <span class="font-bold text-sm text-main">
                      ${escapeHtml(
                        x.name
                        ||
                        x.symbol
                      )}
                    </span>

                    <span class="text-[9px] text-sub">
                      ${escapeHtml(
                        x.symbol
                      )}
                    </span>

                    <span class="text-[8px] border rounded px-1.5 py-0.5 ${statusClass}">
                      ${
                        isOpen
                          ? "OPEN"
                          : "CLOSED"
                      }
                    </span>

                  </div>

                  <div class="text-[9px] text-sub mt-1">
                    ${
                      isOpen
                        ? "Shioaji 即時監控中"
                        : escapeHtml(
                            x.exit_reason
                            ||
                            "已出場"
                          )
                    }
                  </div>
                </div>


                <div class="text-right">
                  <div class="text-sm font-bold text-main">
                    ${
                      displayPrice !== null
                        ? fmt(
                            displayPrice,
                            2
                          )
                        : "--"
                    }
                  </div>

                  <div class="text-[11px] font-bold ${pnlClass}">
                    ${pnlText}
                  </div>
                </div>

              </div>


              <div class="grid grid-cols-2 gap-2 mt-3 text-[9px]">

                <div class="rounded-lg border muted-border p-2">
                  <div class="text-sub">進場</div>

                  <div class="text-main font-mono mt-1">
                    ${
                      entry !== null
                        ? fmt(
                            entry,
                            2
                          )
                        : "--"
                    }
                  </div>

                  <div class="text-emerald-300 mt-0.5">
                    ${
                      x.entry_time
                        ? formatTaiwanDateTime(
                            x.entry_time
                          )
                        : "--"
                    }
                  </div>
                </div>


                <div class="rounded-lg border muted-border p-2">
                  <div class="text-sub">
                    ${
                      isOpen
                        ? "目前 / 最高"
                        : "出場"
                    }
                  </div>

                  <div class="text-main font-mono mt-1">
                    ${
                      isOpen
                        ? `${
                            current !== null
                              ? fmt(
                                  current,
                                  2
                                )
                              : "--"
                          } / ${
                            n(
                              x.highest_price
                            ) !== null
                              ? fmt(
                                  x.highest_price,
                                  2
                                )
                              : "--"
                          }`
                        : (
                            exit !== null
                              ? fmt(
                                  exit,
                                  2
                                )
                              : "--"
                          )
                    }
                  </div>

                  <div class="text-rose-300 mt-0.5">
                    ${
                      isOpen
                        ? (
                            x.stop_price != null
                              ? `停損 ${fmt(
                                  x.stop_price,
                                  2
                                )}`
                              : "--"
                          )
                        : (
                            x.exit_time
                              ? formatTaiwanDateTime(
                                  x.exit_time
                                )
                              : "--"
                          )
                    }
                  </div>
                </div>

              </div>


              ${
                isOpen
                &&
                x.entry_score != null
                  ? `
                    <div class="text-[9px] text-cyan-300 mt-2">
                      量化進場分數：
                      ${escapeHtml(
                        x.entry_score
                      )}
                    </div>
                  `
                  : ""
              }


              ${
                isOpen
                &&
                x.trailing_stop != null
                  ? `
                    <div class="text-[9px] text-amber-300 mt-1">
                      移動停利：
                      ${fmt(
                        x.trailing_stop,
                        2
                      )}
                    </div>
                  `
                  : ""
              }


              ${
                reasons.length
                  ? `
                    <div class="flex flex-wrap gap-1 mt-2">
                      ${
                        reasons
                        .slice(
                          0,
                          4
                        )
                        .map(
                          reason => `
                            <span class="text-[8px] rounded border muted-border px-1.5 py-0.5 text-emerald-300">
                              ✓ ${escapeHtml(reason)}
                            </span>
                          `
                        )
                        .join("")
                      }
                    </div>
                  `
                  : ""
              }


              ${
                !isOpen
                &&
                x.mfe_pct != null
                  ? `
                    <div class="grid grid-cols-2 gap-2 mt-2 text-[8px] text-sub">

                      <div>
                        最高浮盈
                        <span class="text-emerald-300">
                          ${Number(x.mfe_pct).toFixed(2)}%
                        </span>
                      </div>

                      <div>
                        最大浮虧
                        <span class="text-rose-300">
                          ${Number(x.mae_pct).toFixed(2)}%
                        </span>
                      </div>

                    </div>
                  `
                  : ""
              }

            </div>
          `;
        }
      )
      .join("");
  }


  function renderIntradayPicks() {

    // 新 Shioaji 當沖
    renderLiveIntraday();

    // 舊 Fugle 只保留 Overnight
    const s2 =
      document.getElementById(
        "overnightStamp"
      );

    if (s2) {
      s2.textContent =
        INTRADAY?.session === "close"
          ? "收盤版"
          : "尾盤預估";
    }

    renderLinePickList(
      "overnightPickList",
      INTRADAY?.overnight
      ||
      [],
      "OVERNIGHT"
    );
  }
'''


LOAD_SPLIT_SCHEMA = r'''  async function loadSplitSchema() {

    const summary =
      await fetchJson(
        `${FIREBASE_ROOT}/summary.json`
      );

    if (
      !summary
      ||
      typeof summary !== "object"
      ||
      Array.isArray(
        summary
      )
    ) {
      throw new Error(
        "新版 Firebase 缺少 summary"
      );
    }


    const [
      meta,
      backtests,
      intraday,
      intradayLive,
      premarketBrief
    ] =
      await Promise.all([

        fetchJson(
          `${FIREBASE_ROOT}/meta.json`
        )
        .catch(
          err => {
            console.warn(
              "meta 讀取失敗",
              err
            );
            return {};
          }
        ),

        fetchJson(
          `${FIREBASE_ROOT}/backtests.json`
        )
        .catch(
          err => {
            console.warn(
              "backtests 讀取失敗",
              err
            );
            return {};
          }
        ),

        fetchJson(
          `${FIREBASE_ROOT}/intraday_picks.json`
        )
        .catch(
          err => {
            console.warn(
              "intraday_picks 讀取失敗",
              err
            );
            return {};
          }
        ),

        fetchJson(
          `${FIREBASE_ROOT}/intraday_live.json`
        )
        .catch(
          err => {
            console.warn(
              "intraday_live 讀取失敗",
              err
            );
            return {};
          }
        ),

        fetchJson(
          `${FIREBASE_ROOT}/premarket_brief.json`
        )
        .catch(
          err => {
            console.warn(
              "premarket_brief 尚未建立",
              err
            );
            return {};
          }
        )

      ]);


    DATA_MODE =
      "split";

    META = {
      ...(meta || {}),
      backtests:
        backtests
        ||
        {}
    };

    INTRADAY =
      intraday
      ||
      {};

    INTRADAY_LIVE =
      intradayLive
      ||
      {};

    PREMARKET_BRIEF =
      premarketBrief
      ||
      {};

    return Object.values(
      summary
    ).filter(
      Boolean
    );
  }
'''


REFRESH_LIVE = r'''  async function refreshLiveData() {

    try {

      const [
        live,
        brief
      ] =
        await Promise.all([

          fetchJson(
            `${FIREBASE_ROOT}/intraday_live.json`
          )
          .catch(
            () => ({})
          ),

          fetchJson(
            `${FIREBASE_ROOT}/premarket_brief.json`
          )
          .catch(
            () => ({})
          )

        ]);


      INTRADAY_LIVE =
        live
        ||
        {};

      if (
        brief
        &&
        Object.keys(
          brief
        ).length
      ) {
        PREMARKET_BRIEF =
          brief;
      }

      renderLiveIntraday();
      renderPremarketBrief();
      updateSystemStatus();

    } catch (err) {

      console.warn(
        "Live refresh failed",
        err
      );
    }
  }

'''


NEW_ONLOAD = r'''  window.onload = () => {

    setTheme(
      CURRENT_THEME
    );

    restorePriceRange();
    restoreBudget();

    fetchMarketData();

    // Shioaji / AI 即時節點：
    // 每 5 秒只抓 live 節點。
    setInterval(
      refreshLiveData,
      5000
    );
  };'''


NEW_DISCLAIMER = r'''  <section
    class="panel rounded-2xl p-4 text-[10px] text-sub leading-relaxed">

    本頁為量化資料整理與研究工具，不構成投資建議。
    首頁「今日首選」是規則式排序，不代表保證獲利；
    遇到紅燈市場可直接選擇觀望。

    資料核心為 TWSE / TPEx 官方公開資料；
    永豐 Shioaji 負責即時當沖行情，
    Fugle 暫時保留歷史研究與隔日衝資料。

    當沖訊號以 Oracle VM 即時策略為準：
    09:30 開始允許進場，
    12:30 停止新進場，
    12:55 強制結束當沖部位，
    13:00 後不再產生當沖進場訊號。

    AI 開盤前通報為模型依市場資料與新聞產生的風險評估，
    不代表保證預測未來行情。

  </section>'''


def main():
    if not INDEX.exists():
        die("找不到 index.html。請把本檔放在 easystock repo 根目錄。")

    text = INDEX.read_text(encoding="utf-8")

    if "INTRADAY_LIVE" in text and "premarketBriefSection" in text:
        die("看起來 index.html 已經套用過新版，為避免重複插入已停止。")

    shutil.copy2(INDEX, BACKUP)
    print(f"[OK] 已備份：{BACKUP}")

    text = text.replace(
        "Mohren Quant Matrix v1.3",
        "Mohren Quant Matrix v1.4"
    )
    text = text.replace(
        "\n             v1.3\n",
        "\n             v1.4\n"
    )
    print("[OK] 網頁版本 v1.4")

    intraday_anchor = '''  <!-- =====================================================
       INTRADAY
       ===================================================== -->'''

    if intraday_anchor not in text:
        die("找不到 INTRADAY HTML 區塊。")

    text = text.replace(
        intraday_anchor,
        PREMARKET_SECTION + intraday_anchor,
        1
    )
    print("[OK] AI 開盤前通報 HTML")

    text = text.replace(
        "⚡ 當沖 TOP 3",
        "⚡ Shioaji 即時當沖",
        1
    )

    text = text.replace(
        "5分K主趨勢 × 15分K同向 × VWAP × 量能 × 突破 × 市場燈號；\n        有否決訊號就不推薦。",
        "永豐 Shioaji 即時行情 × 5分K × 15分K × VWAP × 量能 × AI市場燈號；\n        09:30 開始、12:30 停止新進場、12:55 強制出場、13:00 完全關閉。",
        1
    )

    text = text.replace(
        "等待 Intraday & Overnight Picks…",
        "等待 Shioaji 即時當沖資料…",
        1
    )
    print("[OK] Shioaji 當沖標題/說明")

    global_old = '''  let INTRADAY = {};

  let DATA_MODE = "split";'''

    global_new = '''  // 舊 Fugle：只保留隔日衝
  let INTRADAY = {};

  // Oracle VM + Shioaji 正式當沖
  let INTRADAY_LIVE = {};

  // AI 開盤前通報
  let PREMARKET_BRIEF = {};

  let DATA_MODE = "split";'''

    text = replace_once(
        text,
        global_old,
        global_new,
        "GLOBAL STATE"
    )

    anchors = [
        '''  /* ========================================================
     INTRADAY FILTER
     ======================================================== */''',
        '''  /* ========================================================
     INTRADAY CARD
     ======================================================== */'''
    ]

    inserted = False
    for anchor in anchors:
        if anchor in text:
            text = text.replace(
                anchor,
                RENDER_PREMARKET + "\n\n" + anchor,
                1
            )
            inserted = True
            print("[OK] function renderPremarketBrief")
            break

    if not inserted:
        die("找不到 INTRADAY FILTER / INTRADAY CARD 區塊。")

    text = replace_js_function(
        text,
        "renderIntradayPicks",
        LIVE_INTRADAY_FUNCTIONS
    )

    text = replace_js_function(
        text,
        "loadSplitSchema",
        LOAD_SPLIT_SCHEMA
    )

    span = find_js_function_span(
        text,
        "renderAllSections"
    )

    if not span:
        die("找不到 renderAllSections")

    start, end = span
    block = text[start:end]

    if "renderPremarketBrief();" not in block:
        old = "renderMarketSignal(pool);"
        if old not in block:
            die("renderAllSections 內找不到 renderMarketSignal(pool);")

        block = block.replace(
            old,
            old + "\n\n  renderPremarketBrief();",
            1
        )
        text = text[:start] + block + text[end:]
        print("[OK] renderAllSections 加入 AI")

    old_scan = '''const scanAt =
      INTRADAY?.last_scan_at
      ||
      INTRADAY?.generated_at;'''

    new_scan = '''const scanAt =
      INTRADAY_LIVE?.last_update_at
      ||
      INTRADAY_LIVE?.generated_at
      ||
      INTRADAY?.last_scan_at
      ||
      INTRADAY?.generated_at;'''

    if old_scan in text:
        text = text.replace(
            old_scan,
            new_scan,
            1
        )
        print("[OK] 盤中最後掃描優先讀 Shioaji")
    else:
        print("[WARN] 找不到舊 scanAt 區塊；其餘功能照常套用。")

    old_tracking = '''trackingEl.textContent =
        INTRADAY?.time_tracking?.enabled
          ? "已啟用"
          : "尚未建立";'''

    new_tracking = '''trackingEl.textContent =
        INTRADAY_LIVE?.source
          === "sinotrade_shioaji"
            ? "Shioaji Live"
            : "等待連線";'''

    if old_tracking in text:
        text = text.replace(
            old_tracking,
            new_tracking,
            1
        )
        print("[OK] 當沖追蹤顯示 Shioaji Live")

    if "async function refreshLiveData()" not in text:
        onload_pos = text.find(
            "window.onload = () =>"
        )
        if onload_pos < 0:
            die("找不到 window.onload")

        text = (
            text[:onload_pos]
            + REFRESH_LIVE
            + "\n"
            + text[onload_pos:]
        )
        print("[OK] 5 秒 Live refresh")

    onload_re = re.compile(
        r'(?ms)^[ \t]*window\.onload[ \t]*=[ \t]*\(\)[ \t]*=>[ \t]*\{.*?^[ \t]*\};'
    )

    m = onload_re.search(text)
    if not m:
        die("無法替換 window.onload")

    text = (
        text[:m.start()]
        + NEW_ONLOAD
        + text[m.end():]
    )
    print("[OK] window.onload")

    disclaimer_re = re.compile(
        r'''(?ms)  <section class="panel rounded-2xl p-4 text-\[10px\] text-sub leading-relaxed">\s*本頁為量化資料整理與研究工具，不構成投資建議。.*?</section>'''
    )

    m = disclaimer_re.search(text)
    if m:
        text = (
            text[:m.start()]
            + NEW_DISCLAIMER
            + text[m.end():]
        )
        print("[OK] Disclaimer")
    else:
        print("[WARN] 找不到原 Disclaimer，沒有修改。")

    required = [
        "INTRADAY_LIVE",
        "PREMARKET_BRIEF",
        "premarketBriefSection",
        "renderPremarketBrief",
        "renderLiveIntraday",
        "/intraday_live.json",
        "/premarket_brief.json",
        "refreshLiveData",
        "12:30",
        "12:55",
        "13:00",
    ]

    missing = [
        token
        for token in required
        if token not in text
    ]

    if missing:
        die(
            "套用後驗證失敗，缺少："
            + ", ".join(missing)
        )

    INDEX.write_text(
        text,
        encoding="utf-8"
    )

    print()
    print("======================================")
    print("✅ index.html v1.4 套用完成")
    print("======================================")
    print(f"新版：{INDEX}")
    print(f"備份：{BACKUP}")
    print()
    print("請接著執行：")
    print("  git diff -- index.html")
    print("  git status")


if __name__ == "__main__":
    main()
