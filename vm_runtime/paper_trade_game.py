#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import datetime, timezone, timedelta
import os
import re
import requests

from firebase_store import FirebaseStore


TPE = timezone(timedelta(hours=8))

ROOT = "paper_game"

START_CASH = 5_000_000
LOT_SIZE = 1000


def now():
    return datetime.now(TPE)


def week_key():
    x = now().isocalendar()
    return f"{x.year}-W{x.week:02d}"


def root():
    return FirebaseStore().root.child(ROOT)


def config():
    data = root().child("config").get() or {}

    if not isinstance(data, dict):
        data = {}

    return data


def ensure_config():

    ref = root().child("config")

    data = ref.get() or {}

    update = {}

    if "enabled" not in data:
        update["enabled"] = False

    if "starting_cash" not in data:
        update["starting_cash"] = START_CASH

    if update:
        ref.update(update)

    return ref.get() or {}


def enabled():

    return bool(
        config().get(
            "enabled",
            False
        )
    )


def set_enabled(value):

    root().child("config").update({
        "enabled": bool(value),
        "updated_at": now().isoformat(
            timespec="seconds"
        )
    })


def season():

    return (
        root()
        .child("seasons")
        .child(week_key())
    )


def user_ref(user_id):

    return (
        season()
        .child("users")
        .child(user_id)
    )


def member_ref(group_id, user_id):

    return (
        root()
        .child("members")
        .child(group_id)
        .child(user_id)
    )


def get_line_name(
    group_id,
    user_id
):

    cached = (
        member_ref(
            group_id,
            user_id
        )
        .get()
        or {}
    )

    name = str(
        cached.get(
            "display_name",
            ""
        )
    ).strip()


    token = (
        os.environ.get(
            "LINE_CHANNEL_ACCESS_TOKEN"
        )
        or ""
    ).strip()


    if token:

        try:

            url = (
                "https://api.line.me/v2/bot/group/"
                f"{group_id}/member/{user_id}"
            )

            r = requests.get(
                url,
                headers={
                    "Authorization":
                    f"Bearer {token}"
                },
                timeout=10
            )

            if r.status_code == 200:

                data = r.json()

                api_name = str(
                    data.get(
                        "displayName",
                        ""
                    )
                ).strip()

                if api_name:
                    name = api_name

        except Exception:

            pass


    if not name:

        name = (
            "玩家-"
            + user_id[-6:]
        )


    member_ref(
        group_id,
        user_id
    ).update({

        "display_name": name,

        "updated_at":
        now().isoformat(
            timespec="seconds"
        )
    })


    return name



def ensure_user(
    group_id,
    user_id
):

    name = get_line_name(
        group_id,
        user_id
    )


    ref = user_ref(
        user_id
    )


    data = ref.get()


    if isinstance(data, dict) and data:

        return data



    data = {

        "user_id":
        user_id,

        "group_id":
        group_id,

        "display_name":
        name,


        "starting_cash":
        START_CASH,


        "cash":
        START_CASH,


        "realized_pnl":
        0,


        "positions":
        {},


        "trades":
        {},


        "joined_at":
        now().isoformat(
            timespec="seconds"
        )
    }


    ref.set(data)


    return data



def register_signal(
    symbol,
    name,
    price,
    trade_id=""
):

    if not enabled():

        return False


    season().child(
        "signals"
    ).child(
        str(symbol)
    ).set({

        "symbol":
        str(symbol),

        "name":
        str(name),

        "entry_price":
        float(price),

        "trade_id":
        trade_id,

        "active":
        True,


        "created_at":
        now().isoformat(
            timespec="seconds"
        )

    })


    return True



def close_signal(
    symbol,
    exit_price,
    reason=""
):

    users = (
        season()
        .child("users")
        .get()
        or {}
    )


    if not isinstance(
        users,
        dict
    ):
        return 0


    count = 0


    for uid, account in users.items():

        if not isinstance(
            account,
            dict
        ):
            continue


        positions = (
            account.get(
                "positions"
            )
            or {}
        )


        pos = positions.get(
            str(symbol)
        )


        if not pos:
            continue


        lots = int(
            pos.get(
                "lots",
                0
            )
        )


        buy_price = float(
            pos.get(
                "avg_price",
                0
            )
        )


        pnl = (
            float(exit_price)
            -
            buy_price
        ) * lots * LOT_SIZE


        account["cash"] = (
            float(
                account.get(
                    "cash",
                    0
                )
            )
            +
            float(exit_price)
            *
            lots
            *
            LOT_SIZE
        )


        account["realized_pnl"] = (
            float(
                account.get(
                    "realized_pnl",
                    0
                )
            )
            +
            pnl
        )


        positions.pop(
            str(symbol),
            None
        )


        account["positions"] = positions


        account.setdefault(
            "trades",
            {}
        )[

            now().strftime(
                "%Y%m%d%H%M%S"
            )

        ] = {

            "symbol":
            symbol,

            "exit_price":
            exit_price,

            "pnl":
            pnl,

            "reason":
            reason

        }


        user_ref(uid).set(
            account
        )


        count += 1


    return count
def active_signals():

    data = (
        season()
        .child("signals")
        .get()
        or {}
    )


    result = []


    if isinstance(
        data,
        dict
    ):

        for symbol, item in data.items():

            if (
                isinstance(item, dict)
                and item.get("active")
            ):

                result.append(item)


    return result



def find_signal(target=None):

    signals = active_signals()


    if not signals:

        return None



    if not target:

        return signals[0]



    target = str(
        target
    ).lower()



    for s in signals:

        symbol = str(
            s.get(
                "symbol",
                ""
            )
        ).lower()


        name = str(
            s.get(
                "name",
                ""
            )
        ).lower()



        if (
            target == symbol
            or target in name
        ):

            return s



    return None




def buy(
    group_id,
    user_id,
    lots,
    target=None
):

    if not enabled():

        return ""



    signal = find_signal(
        target
    )



    if not signal:

        return (
            "目前沒有可購買的"
            " EasyStock 當沖訊號。"
        )



    # 第一次買入，自動參賽

    old_user = user_ref(
        user_id
    ).get()


    is_new = not isinstance(
        old_user,
        dict
    )



    account = ensure_user(
        group_id,
        user_id
    )



    name = account.get(
        "display_name",
        "玩家"
    )



    symbol = str(
        signal.get(
            "symbol"
        )
    )


    stock_name = str(
        signal.get(
            "name",
            symbol
        )
    )


    price = float(
        signal.get(
            "entry_price",
            0
        )
    )



    if price <= 0:

        return "價格資料錯誤"



    cash = float(
        account.get(
            "cash",
            START_CASH
        )
    )



    cost_one = (
        price
        *
        LOT_SIZE
    )



    max_lots = int(
        cash
        //
        cost_one
    )


    real_lots = min(
        int(lots),
        max_lots
    )



    if real_lots <= 0:

        return (
            f"{name}\n"
            "虛擬資金不足"
        )



    cost = (
        price
        *
        LOT_SIZE
        *
        real_lots
    )



    positions = (
        account.get(
            "positions"
        )
        or {}
    )



    positions[symbol] = {

        "symbol":
        symbol,

        "name":
        stock_name,

        "lots":
        real_lots,

        "avg_price":
        price
    }



    account["positions"] = positions


    account["cash"] = (
        cash
        -
        cost
    )


    account["updated_at"] = (
        now().isoformat(
            timespec="seconds"
        )
    )


    user_ref(
        user_id
    ).set(
        account
    )



    first = ""

    if is_new:

        first = (
            f"🎮 {name} 已加入本週模擬賽\n"
            "初始資金 $5,000,000\n"
            "週五收盤後結算\n\n"
        )



    return (

        first +

        f"✅ {name}｜模擬成交\n"

        f"{stock_name} {symbol}\n"

        f"買入 {real_lots} 張\n"

        f"成交價 {price:.2f}\n"

        f"使用資金 ${cost:,.0f}\n"

        f"剩餘 ${account['cash']:,.0f}"

    )




def account_text(
    group_id,
    user_id
):

    if not enabled():

        return ""



    account = ensure_user(
        group_id,
        user_id
    )


    name = account.get(
        "display_name",
        "玩家"
    )



    cash = float(
        account.get(
            "cash",
            0
        )
    )


    pnl = float(
        account.get(
            "realized_pnl",
            0
        )
    )



    lines = [

        f"🎮 {name}｜本週模擬帳戶",

        f"可用現金 ${cash:,.0f}",

        f"已實現損益 {pnl:+,.0f}",

    ]



    positions = (
        account.get(
            "positions"
        )
        or {}
    )


    if positions:

        lines.append("")

        lines.append("持股:")


        for s,p in positions.items():

            lines.append(

                f"{p.get('name')} "
                f"{p.get('lots')}張 "
                f"成本 {p.get('avg_price')}"

            )


    return "\n".join(lines)




def leaderboard():

    if not enabled():

        return ""



    users = (
        season()
        .child("users")
        .get()
        or {}
    )


    rows = []


    if isinstance(
        users,
        dict
    ):

        for uid, account in users.items():

            if not isinstance(
                account,
                dict
            ):
                continue


            total = (
                float(
                    account.get(
                        "cash",
                        0
                    )
                )
                +
                float(
                    account.get(
                        "realized_pnl",
                        0
                    )
                )
            )


            rows.append({

                "name":
                account.get(
                    "display_name",
                    uid[-6:]
                ),

                "pnl":
                total - START_CASH

            })



    rows.sort(
        key=lambda x:x["pnl"],
        reverse=True
    )


    if not rows:

        return "🎮 本週尚無參賽者"



    text = [
        "🏆 當沖吧！牛馬仔｜本週模擬排行"
    ]



    for i,r in enumerate(rows[:10],1):

        text.append(

            f"{i}. {r['name']} "
            f"{r['pnl']:+,.0f}"

        )


    return "\n".join(text)
def handle_game_command(
    text,
    source
):

    text = str(
        text or ""
    ).strip()


    if (
        not source
        or source.get("type")
        != "group"
    ):

        return None



    group_id = str(
        source.get(
            "groupId",
            ""
        )
    )


    user_id = str(
        source.get(
            "userId",
            ""
        )
    )


    if not group_id or not user_id:

        return ""



    ensure_config()



    if text == "遊戲開":

        set_enabled(True)

        return (
            "🎮 模擬當沖賽已開啟\n"
            "每週本金 $5,000,000\n"
            "週五結算"
        )



    if text == "遊戲關":

        set_enabled(False)

        return (
            "🎮 模擬當沖賽已關閉"
        )



    if text == "遊戲狀態":

        return (

            "🎮 模擬當沖賽："

            +
            (
                "開啟"
                if enabled()
                else
                "關閉"
            )

        )



    if not enabled():

        return None



    if text == "參賽":

        account = ensure_user(
            group_id,
            user_id
        )

        return (

            f"🎮 {account['display_name']} "
            "已加入本週模擬賽\n"

            "初始資金 $5,000,000\n"

            "週五收盤後結算"

        )



    if text == "資產":

        return account_text(
            group_id,
            user_id
        )



    if text == "排行":

        return leaderboard()



    m = re.match(
        r"^買\s*(\d+)\s*張$",
        text
    )


    if m:

        return buy(

            group_id,

            user_id,

            int(
                m.group(1)
            )

        )



    m = re.match(
        r"^買\s*([0-9A-Za-z\u4e00-\u9fff]+)\s*(\d+)\s*張$",
        text
    )


    if m:

        return buy(

            group_id,

            user_id,

            int(
                m.group(2)
            ),

            m.group(1)

        )



    return None
