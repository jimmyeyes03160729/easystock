#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EasyStock LINE Stock Bot Webhook V4

重點：
- 圖卡由 stock_command_service.py 即時產生
- 圖片目錄建議設為 /dev/shm/easystock_cards（RAM / tmpfs）
- 同一圖卡指令 60 秒內共用快取
- 圖片超過 10 分鐘自動刪除
- 最多保留 50 張 PNG
- 支援 Gunicorn 多 worker：使用 /dev/shm 檔案快取 + flock

Endpoints:
GET  /healthz
POST /callback
GET  /charts/<filename>
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from flask import Flask, abort, request, send_from_directory

from line_bot import reply_messages as line_reply
from line_group_manager import register_group
from paper_trade_game import handle_game_command

from stock_command_service import (
    CHART_DIR,
    handle_command,
    parse_command,
)


app = Flask(__name__)

from easystock_admin.web import register_admin
from easystock_admin.line import handle_admin_command
ADMIN_STORE = register_admin(app)


# ============================================================
# LINE 設定
# ============================================================

LINE_CHANNEL_SECRET = os.environ.get(
    "LINE_CHANNEL_SECRET",
    "",
).strip()

LINE_CHANNEL_ACCESS_TOKEN = (
    os.environ.get(
        "LINE_CHANNEL_ACCESS_TOKEN",
        "",
    ).strip()
    or os.environ.get(
        "LINE_ACCESS_TOKEN",
        "",
    ).strip()
)

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"


# ============================================================
# 圖卡 RAM / 快取設定
# ============================================================

CARD_TTL_SECONDS = int(
    os.environ.get(
        "LINE_CARD_TTL_SECONDS",
        "600",
    )
)

CARD_REUSE_SECONDS = int(
    os.environ.get(
        "LINE_CARD_REUSE_SECONDS",
        "60",
    )
)

CARD_MAX_FILES = int(
    os.environ.get(
        "LINE_CARD_MAX_FILES",
        "50",
    )
)

# stock_command_service.py 會依 LINE_CHART_DIR 建立 CHART_DIR。
# 建議 .env：LINE_CHART_DIR=/dev/shm/easystock_cards
CHART_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

CACHE_FILE = CHART_DIR / ".line_card_cache.json"
CACHE_LOCK_FILE = CHART_DIR / ".line_card_cache.lock"


# ============================================================
# LINE 簽章驗證
# ============================================================


def verify_signature(body: bytes, signature: str) -> bool:
    if not LINE_CHANNEL_SECRET:
        return False

    digest = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()

    expected = base64.b64encode(
        digest
    ).decode("ascii")

    return hmac.compare_digest(
        expected,
        signature or "",
    )


# ============================================================
# 圖卡快取工具
# ============================================================


def _cache_key(cmd) -> str:
    """同一種圖卡 + 同一查詢目標使用相同快取 key。"""
    kind = str(getattr(cmd, "kind", "") or "").upper().strip()
    query = str(getattr(cmd, "query", "") or "").strip().upper()
    return f"{kind}:{query}"


def _is_image_command(cmd) -> bool:
    """只有 P/K/T 圖卡使用 60 秒快取；文字查價永遠即時查。"""
    kind = str(getattr(cmd, "kind", "") or "").upper().strip()
    return kind in {"P", "K", "T"}


def _has_image_message(messages: list[dict]) -> bool:
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        if message.get("type") == "image":
            return True
        if message.get("type") == "flex":
            contents = message.get("contents") or {}
            hero = contents.get("hero") if isinstance(contents, dict) else None
            if isinstance(hero, dict) and hero.get("type") == "image":
                return True
    return False


def _image_filename_from_messages(messages: list[dict]) -> str | None:
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        url = ""
        if message.get("type") == "image":
            url = str(message.get("originalContentUrl") or message.get("previewImageUrl") or "").strip()
        elif message.get("type") == "flex":
            contents = message.get("contents") or {}
            hero = contents.get("hero") if isinstance(contents, dict) else None
            if isinstance(hero, dict) and hero.get("type") == "image":
                url = str(hero.get("url") or "").strip()
        if not url:
            continue
        try:
            parsed = urlparse(url); name = Path(unquote(parsed.path)).name
        except Exception:
            continue
        if name.lower().endswith(".png"):
            return name
    return None


def _cached_image_still_exists(messages: list[dict]) -> bool:
    filename = _image_filename_from_messages(messages)
    if not filename:
        return False

    path = CHART_DIR / Path(filename).name

    try:
        return (
            path.exists()
            and path.is_file()
            and path.stat().st_size > 0
        )
    except Exception:
        return False


def _load_cache_unlocked() -> dict:
    if not CACHE_FILE.exists():
        return {}

    try:
        data = json.loads(
            CACHE_FILE.read_text(encoding="utf-8")
        )
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache_unlocked(cache: dict) -> None:
    tmp = CACHE_FILE.with_suffix(".tmp")

    tmp.write_text(
        json.dumps(
            cache,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    tmp.replace(CACHE_FILE)


def _cleanup_png_files_unlocked() -> None:
    """
    1. 刪除超過 LINE_CARD_TTL_SECONDS 的 PNG
    2. 超過 LINE_CARD_MAX_FILES 時，從最舊開始刪
    """
    now = time.time()

    try:
        files = [
            path
            for path in CHART_DIR.glob("*.png")
            if path.is_file()
        ]
    except Exception:
        return

    # 先刪超過 TTL 的舊圖
    for path in files:
        try:
            age = now - path.stat().st_mtime
            if age > CARD_TTL_SECONDS:
                path.unlink(missing_ok=True)
        except Exception:
            pass

    # 再做最大張數限制
    try:
        files = sorted(
            [
                path
                for path in CHART_DIR.glob("*.png")
                if path.is_file()
            ],
            key=lambda path: path.stat().st_mtime,
        )
    except Exception:
        return

    overflow = len(files) - CARD_MAX_FILES

    if overflow > 0:
        for path in files[:overflow]:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass


def _cleanup_cache_unlocked(cache: dict) -> dict:
    """移除過期、格式錯誤、或圖片已不存在的 cache entry。"""
    now = time.time()
    cleaned: dict = {}

    for key, entry in cache.items():
        if not isinstance(entry, dict):
            continue

        try:
            created_at = float(entry.get("created_at", 0))
        except Exception:
            continue

        messages = entry.get("messages")

        if not isinstance(messages, list):
            continue

        # 快取本來就只重用 60 秒；過期就不用留 metadata。
        if now - created_at > CARD_REUSE_SECONDS:
            continue

        if not _cached_image_still_exists(messages):
            continue

        cleaned[key] = entry

    return cleaned


def cleanup_cards() -> None:
    """可從每個 webhook 請求尾端安全呼叫。"""
    CHART_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with CACHE_LOCK_FILE.open("a+") as lock_fp:
        fcntl.flock(
            lock_fp.fileno(),
            fcntl.LOCK_EX,
        )

        try:
            _cleanup_png_files_unlocked()

            cache = _load_cache_unlocked()
            cache = _cleanup_cache_unlocked(cache)
            _save_cache_unlocked(cache)
        finally:
            fcntl.flock(
                lock_fp.fileno(),
                fcntl.LOCK_UN,
            )


def handle_command_with_cache(cmd) -> list[dict]:
    """
    P / K / T：
      - 60 秒內相同指令直接使用上一張圖
      - Gunicorn 多 worker 共用 /dev/shm JSON cache
      - 使用 flock 避免兩個 worker 同時重畫相同圖卡

    其他指令：
      - #股票、#大盤、D、HELP 不做圖片快取
    """
    if not _is_image_command(cmd):
        return handle_command(cmd)

    key = _cache_key(cmd)
    now = time.time()

    CHART_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with CACHE_LOCK_FILE.open("a+") as lock_fp:
        fcntl.flock(
            lock_fp.fileno(),
            fcntl.LOCK_EX,
        )

        try:
            _cleanup_png_files_unlocked()

            cache = _load_cache_unlocked()
            cache = _cleanup_cache_unlocked(cache)

            entry = cache.get(key)

            if isinstance(entry, dict):
                try:
                    age = now - float(
                        entry.get("created_at", 0)
                    )
                except Exception:
                    age = CARD_REUSE_SECONDS + 1

                messages = entry.get("messages")

                if (
                    age <= CARD_REUSE_SECONDS
                    and isinstance(messages, list)
                    and _cached_image_still_exists(messages)
                ):
                    _save_cache_unlocked(cache)
                    return messages

            # 沒有可重用圖卡：真的向資料來源查詢並產圖。
            messages = handle_command(cmd)

            # 只有成功得到 image message 才快取；錯誤文字不快取。
            if _has_image_message(messages):
                cache[key] = {
                    "created_at": now,
                    "messages": messages,
                }

            cache = _cleanup_cache_unlocked(cache)
            _save_cache_unlocked(cache)

            _cleanup_png_files_unlocked()

            return messages

        finally:
            fcntl.flock(
                lock_fp.fileno(),
                fcntl.LOCK_UN,
            )


# ============================================================
# Flask endpoints
# ============================================================


@app.get("/healthz")
def healthz():
    try:
        png_count = len(
            list(CHART_DIR.glob("*.png"))
        )
    except Exception:
        png_count = -1

    return {
        "ok": True,
        "service": "easystock-line-stock-bot",
        "version": "v5-unified-line-hub",
        "chart_dir": str(CHART_DIR),
        "card_ttl_seconds": CARD_TTL_SECONDS,
        "card_reuse_seconds": CARD_REUSE_SECONDS,
        "card_max_files": CARD_MAX_FILES,
        "png_count": png_count,
    }


def _should_silence_reply(messages) -> bool:
    """查不到、格式錯誤、無效查詢時，LINE 群組保持安靜。"""
    if not isinstance(messages, list) or not messages:
        return True

    silent_words = (
        "查不到",
        "找不到",
        "無法查詢",
        "暫時無法查詢",
        "不存在",
        "不支援",
        "無效指令",
        "指令錯誤",
        "格式錯誤",
        "請輸入正確",
        "股票代碼錯誤",
        "無法辨識",
    )

    for message in messages:
        if not isinstance(message, dict):
            continue

        if message.get("type") != "text":
            return False

        text = str(message.get("text") or "")

        if any(word in text for word in silent_words):
            continue

        # 有正常文字就不靜默
        return False

    return True


@app.post("/callback")
def callback():
    body = request.get_data(
        cache=False
    )

    signature = request.headers.get(
        "X-Line-Signature",
        "",
    )

    if not verify_signature(
        body,
        signature,
    ):
        abort(400)

    try:
        payload = json.loads(
            body.decode("utf-8")
        )
    except Exception:
        abort(400)

    for event in payload.get("events", []):

        source = event.get("source") or {}
        from easystock_admin.conversations import observe, allowed
        observe(ADMIN_STORE, source)

        if source.get("type") == "group":
            group_id = source.get("groupId")
            if group_id:
                register_group(group_id)

        if event.get("type") != "message":
            continue

        message = event.get("message") or {}

        if message.get("type") != "text":
            continue

        text = str(
            message.get("text")
            or ""
        ).strip()

        # Signature was verified above. Bind/update commands only accept a private user source.
        try:
            admin_reply = handle_admin_command(
                text, source,
                str(event.get("webhookEventId") or message.get("id") or ""),
                store=ADMIN_STORE,
            )
            if admin_reply is not None:
                reply_token = event.get("replyToken")
                if reply_token:
                    line_reply(reply_token, [{"type": "text", "text": admin_reply[:5000]}])
                continue
        except Exception as exc:
            if text == "當沖設定" or text.startswith(("當沖設定 ", "綁定管理員 ")):
                print("[ADMIN COMMAND ERROR]", type(exc).__name__)
                continue
            raise

        if not allowed(ADMIN_STORE, source):
            continue

        # 模擬當沖遊戲指令先處理。
        game_reply = handle_game_command(
            text,
            source,
        )

        if game_reply is not None:
            reply_token = event.get("replyToken")

            if reply_token and game_reply:
                line_reply(
                    reply_token,
                    [{
                        "type": "text",
                        "text": str(game_reply)[:5000],
                    }],
                )

            continue

        cmd = parse_command(text)

        # 不認得的文字 = 群組一般聊天，不回覆。
        if cmd is None:
            continue

        reply_token = event.get(
            "replyToken"
        )

        if not reply_token:
            continue

        try:
            messages = handle_command_with_cache(
                cmd
            )

            if _should_silence_reply(messages):
                continue

            line_reply(
                reply_token,
                messages,
            )

        except Exception as exc:
            print(
                f"[LINE SILENT ERROR] {type(exc).__name__}: {exc}"
            )
            continue

    # 每次 webhook 後順手清理舊 RAM 圖卡。
    try:
        pass
        # cleanup_cards()  # CARD_FIX: 暫停立即刪除，避免 LINE 抓不到圖片
    except Exception:
        pass

    return "OK", 200


@app.get("/charts/<path:filename>")
def chart(filename: str):
    """
    LINE Messaging API 會透過公開 HTTPS URL 來抓這張圖片。

    實際 PNG 可放在 /dev/shm/easystock_cards，
    因此這個 URL 雖然存在，但不代表圖片永久寫入 VM 磁碟。
    """
    safe = Path(filename).name

    if not safe.lower().endswith(".png"):
        abort(404)

    path = CHART_DIR / safe

    if not path.exists():
        abort(404)

    return send_from_directory(
        CHART_DIR,
        safe,
        mimetype="image/png",
        max_age=30,
    )


# ============================================================
# Local debug server
# ============================================================


if __name__ == "__main__":
    host = os.environ.get(
        "LINE_BOT_HOST",
        "127.0.0.1",
    )

    port = int(
        os.environ.get(
            "LINE_BOT_PORT",
            "8088",
        )
    )

    app.run(
        host=host,
        port=port,
        threaded=True,
    )
