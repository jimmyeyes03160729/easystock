#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

export HOME=/home/codex
export PATH="$HOME/.local/bin:/opt/venv/bin:$PATH"

mkdir -p "$HOME/.local/bin" "$HOME/.ssh" "$HOME/.codex" /workspace

# 驗證並安裝獨立的 GitHub SSH 金鑰與 known_hosts
if [[ -r /run/github/id_ed25519 && -r /run/github/known_hosts ]]; then
    install -m 600 /run/github/id_ed25519 "$HOME/.ssh/github_key"
    install -m 600 /run/github/known_hosts "$HOME/.ssh/github_known_hosts"
    export GIT_SSH_COMMAND="ssh -F /dev/null -i $HOME/.ssh/github_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$HOME/.ssh/github_known_hosts"
    git config --global core.sshCommand "$GIT_SSH_COMMAND"
else
    echo 'Error: Mount a dedicated GitHub SSH key (id_ed25519) and verified known_hosts in /run/github.' >&2
    exit 1
fi

export GIT_TERMINAL_PROMPT=0

# 設定 Git Author 資訊
git config --global user.name "${GIT_AUTHOR_NAME:?Set GIT_AUTHOR_NAME in .env}"
git config --global user.email "${GIT_AUTHOR_EMAIL:?Set GIT_AUTHOR_EMAIL in .env}"
git config --global init.defaultBranch main

repo="/workspace/easystock"
repo_url="git@github.com:jimmyeyes03160729/easystock.git"

# 若 workspace 尚未 checkout 則進行 clone；若已存在則嚴格保護未提交修改與分支
if [[ ! -e "$repo" ]]; then
    echo "Initial setup: cloning EasyStock repository into $repo..."
    git clone --branch main --single-branch "$repo_url" "$repo"
fi

[[ -d "$repo/.git" ]] || {
    echo "Error: Workspace path $repo exists but is not a Git repository; refusing to proceed." >&2
    exit 1
}

current_branch=$(git -C "$repo" branch --show-current)
if [[ "$current_branch" != "main" ]]; then
    echo "Error: Repository at $repo is on branch '$current_branch' (expected 'main')." >&2
    echo "Refusing to switch branch, reset, or discard changes to preserve uncommitted work." >&2
    exit 1
fi

git -C "$repo" remote set-url origin "$repo_url"

cd "$repo"

# 若有傳入指令則執行傳入指令，否則以安全 idle mode 常駐保留環境與登入狀態
if [[ $# -gt 0 ]]; then
    exec "$@"
fi

exec sleep infinity
