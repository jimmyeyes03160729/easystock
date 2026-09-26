#!/usr/bin/env python3

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import shutil
import subprocess
import sys


ROOT = Path("/home/ubuntu/easystock")
SOURCE = ROOT / "vm_runtime"

BACKUP_ROOT = Path(
    "/home/ubuntu/easystock-maintenance/intraday-runtime"
)

FILES = [
    "intraday_live.py",
    "market_risk.py",
    "firebase_store.py",
    "paper_account.py",
    # The root premarket_ai.py is a compatibility entry point that executes
    # vm_runtime/premarket_ai.py. Keep that entry point intact on the VM.
    "daytrade_learning/features.py",
    "daytrade_learning/core.py",
    "daytrade_learning/research.py",
    "position_manager.py",
    "daytrade_learning/runtime.py",
    "daytrade_learning/model_runtime.py",
    "learning_status.py",
    "learning_cycle.py",
    "learning_eod.py",
    "easystock_admin/store.py",
]

CORE_SERVICES = [
    "easystock-intraday.service",
    "easystock-learning.service",
    "easystock-learning-train.service",
    "easystock-research-cycle.service",
]


def run(*args, check=True, capture=False, env=None):
    kwargs = {
        "check": check,
        "text": True,
        "env": env,
    }

    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.STDOUT

    return subprocess.run(
        list(args),
        **kwargs,
    )


def active(unit: str) -> bool:
    r = run(
        "systemctl",
        "is-active",
        unit,
        check=False,
        capture=True,
    )

    return r.stdout.strip() in {
        "active",
        "activating",
    }


def source_is_committed() -> None:
    paths = [
        str(Path("vm_runtime") / p)
        for p in FILES
    ]

    run("git", "ls-files", "--error-unmatch", *paths, capture=True)
    r = run(
        "git",
        "diff",
        "--quiet",
        "HEAD",
        "--",
        *paths,
        check=False,
    )

    if r.returncode != 0:
        raise RuntimeError(
            "vm_runtime 尚有未提交修改，"
            "拒絕部署。請先 commit。"
        )


def check_sources() -> None:
    print("===== 檢查來源檔 =====")

    for rel in FILES:
        p = SOURCE / rel

        if not p.exists():
            raise FileNotFoundError(
                f"缺少部署來源：{p}"
            )

        print("OK", rel)


def compile_sources() -> None:
    print("\n===== Python 語法檢查 =====")

    py_files = [
        SOURCE / rel
        for rel in FILES
        if rel.endswith(".py")
    ]

    run(
        str(ROOT / ".venv/bin/python"),
        "-m",
        "py_compile",
        *[str(x) for x in py_files],
    )

    print("✅ py_compile 全部通過")


def check_services() -> None:
    print("\n===== 服務狀態 =====")

    busy = []

    for unit in CORE_SERVICES:
        is_busy = active(unit)

        print(
            unit,
            "ACTIVE" if is_busy else "not active",
        )

        if is_busy:
            busy.append(unit)

    if busy:
        raise RuntimeError(
            "核心服務仍在執行，為避免盤中覆蓋程式，"
            "停止部署："
            + ", ".join(busy)
        )


def backup_live() -> Path:
    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    backup = BACKUP_ROOT / f"backup_{stamp}"
    backup.mkdir(
        parents=True,
        exist_ok=False,
    )

    print(
        "\n===== 備份正式執行檔 ====="
    )

    for rel in FILES:
        src = ROOT / rel

        if not src.exists():
            continue

        dest = backup / rel
        dest.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.copy2(
            src,
            dest,
        )

        print("BACKUP", rel)

    return backup


def install_files() -> None:
    print("\n===== 安裝 Runtime =====")

    for rel in FILES:
        src = SOURCE / rel
        dest = ROOT / rel

        dest.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        tmp = dest.with_name(
            dest.name + ".deploy-tmp"
        )

        shutil.copy2(
            src,
            tmp,
        )

        tmp.replace(dest)

        print("INSTALL", rel)


def validate_live() -> None:
    print(
        "\n===== 正式 Runtime 驗證 ====="
    )

    py_files = [
        ROOT / rel
        for rel in FILES
        if rel.endswith(".py")
    ]

    run(
        str(ROOT / ".venv/bin/python"),
        "-m",
        "py_compile",
        *[str(x) for x in py_files],
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    code = r'''
from position_manager import (
    PaperWallet,
    PositionManager,
)

from easystock_admin.store import (
    get_paper_position,
)

from daytrade_learning.runtime import (
    Recorder,
)

from daytrade_learning.model_runtime import (
    DaytradeModel,
    live_features,
)

m = DaytradeModel(path="")
d = m.evaluate({})

assert d.get("reason") == "no_approved_model"
assert d.get("active") is False
assert d.get("approved") is False

print("PaperWallet OK")
print("PositionManager OK")
print("get_paper_position OK")
print("Recorder OK")
print("DaytradeModel fail-safe OK")
'''

    r = run(
        str(ROOT / ".venv/bin/python"),
        "-c",
        code,
        capture=True,
        env=env,
    )

    print(r.stdout.strip())
    print("✅ 正式 Runtime 驗證通過")


def restore(backup: Path) -> None:
    print(
        "\n⚠️ 部署失敗，開始還原"
    )

    for rel in FILES:
        src = backup / rel

        if not src.exists():
            (ROOT / rel).unlink(missing_ok=True)
            continue

        dest = ROOT / rel

        dest.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.copy2(
            src,
            dest,
        )

        print("RESTORE", rel)


def publish_status() -> None:
    print(
        "\n===== 更新 Learning Status ====="
    )

    run(
        "sudo",
        "systemctl",
        "start",
        "easystock-learning-status.service",
    )

    print("✅ learning status 已更新")


def main():
    os.umask(0o077)
    os.chdir(ROOT)

    print(
        "Easystock Intraday Runtime Installer"
    )

    print(
        "Git HEAD:",
        run(
            "git",
            "rev-parse",
            "--short",
            "HEAD",
            capture=True,
        ).stdout.strip(),
    )

    source_is_committed()
    check_sources()
    compile_sources()
    check_services()
    if '--check-only' in sys.argv:
        print('Checks completed; no runtime files installed.')
        return

    backup = backup_live()

    try:
        install_files()
        validate_live()
        publish_status()

    except BaseException:
        restore(backup)

        try:
            validate_live()
        except Exception as exc:
            print(
                "⚠️ 還原後驗證也失敗：",
                exc,
            )

        raise

    print()
    print("================================")
    print("✅ Intraday Runtime 部署完成")
    print("Backup:", backup)
    print("================================")
    print()
    print(
        "注意：此部署程式不會自動啟動 "
        "easystock-intraday.service"
    )
    print(
        "也不會自動把任何模型 HASH 加入認證清單。"
    )


if __name__ == "__main__":
    try:
        main()

    except Exception as exc:
        print()
        print(
            "❌ DEPLOY FAILED:",
            f"{type(exc).__name__}: {exc}",
        )
        sys.exit(1)
