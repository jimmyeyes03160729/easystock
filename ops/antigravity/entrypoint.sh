#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export HOME=/home/agent
export PATH="$HOME/.local/bin:/opt/venv/bin:$PATH"
# No D-Bus/keyring service in this headless container; CLI falls back to files.
unset DBUS_SESSION_BUS_ADDRESS
mkdir -p "$HOME/.local/bin" "$HOME/.ssh" /workspace
if [[ ! -x "$HOME/.local/bin/agy" ]]; then
    cp /opt/antigravity/antigravity "$HOME/.local/bin/agy"
    chmod 700 "$HOME/.local/bin/agy"
fi

auth_mode=${GITHUB_AUTH_MODE:-ssh}
case "$auth_mode" in
    ssh)
        [[ -r /run/github/id_ed25519 && -r /run/github/known_hosts ]] || {
            echo 'Mount a dedicated GitHub key and verified known_hosts in /run/github.' >&2; exit 1;
        }
        # Copy to writable private home: read-only NAS mounts may have loose modes.
        install -m 600 /run/github/id_ed25519 "$HOME/.ssh/github_key"
        install -m 600 /run/github/known_hosts "$HOME/.ssh/github_known_hosts"
        export GIT_SSH_COMMAND="ssh -F /dev/null -i $HOME/.ssh/github_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$HOME/.ssh/github_known_hosts"
        git config --global core.sshCommand "$GIT_SSH_COMMAND"
        repo_url=git@github.com:jimmyeyes03160729/easystock.git
        ;;
    token)
        [[ -s /run/github/token ]] || { echo 'Mount GitHub token file in /run/github/token.' >&2; exit 1; }
        repo_url=https://github.com/jimmyeyes03160729/easystock.git
        git config --global --unset-all core.sshCommand || true
        rm -f "$HOME/.ssh/github_key" "$HOME/.ssh/github_known_hosts"
        ;;
    *) echo 'GITHUB_AUTH_MODE must be ssh or token.' >&2; exit 1 ;;
esac
export GIT_TERMINAL_PROMPT=0
# Reset persistent auth configuration when switching modes; never store a token.
git config --global --unset-all credential.helper || true
git config --global credential.helper /usr/local/bin/github-credential.sh
git config --global credential.useHttpPath true
git config --global user.name "${GIT_AUTHOR_NAME:?Set GIT_AUTHOR_NAME}"
git config --global user.email "${GIT_AUTHOR_EMAIL:?Set GIT_AUTHOR_EMAIL}"
git config --global init.defaultBranch main
repo=/workspace/easystock
if [[ ! -e "$repo" ]]; then
    git clone --branch main --single-branch "$repo_url" "$repo"
fi
[[ -d "$repo/.git" ]] || { echo 'Existing workspace is not a Git checkout; refusing to overwrite.' >&2; exit 1; }
[[ $(git -C "$repo" branch --show-current) == main ]] || {
    echo 'Workspace is not on main; refusing to switch or discard changes.' >&2; exit 1;
}
git -C "$repo" remote set-url origin "$repo_url"
# No automatic pull/reset/install on restart: preserve edits and running work.
cd "$repo"
mode=${1:-daemon}
case "$mode" in
    login)
        # Documented SSH OAuth URL/code flow (docker exec alone is not SSH).
        export SSH_CONNECTION='127.0.0.1 22 127.0.0.1 22'
        exec agy
        ;;
    shell) exec bash ;;
    daemon) ;;
    *) exec "$@" ;;
esac

cleanup() {
    trap - TERM INT EXIT
    timeout 15 agy remote-control stop || true
}
trap 'exit 0' TERM INT
trap cleanup EXIT
# Official 1.2.14+ non-systemd background mode. Do not invoke an undocumented
# serve command or mistake the short-lived start command for the daemon.
timeout 60 agy remote-control start --name "${AGY_INSTANCE_NAME:-EasyStock-NAS}"
pid=''
for ((attempt=0; attempt<10; attempt++)); do
    status=$(timeout 10 agy remote-control status)
    printf '%s\n' "$status"
    pid=$(printf '%s\n' "$status" | sed -nE 's/.*[Pp][Ii][Dd][[:space:]:=]+([0-9]+).*/\1/p' | head -n 1)
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then break; fi
    sleep 2
done
[[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null || {
    echo 'No live daemon PID reported by official status; exiting for Docker restart.' >&2; exit 1;
}
printf '%s\n' "$pid" > /tmp/antigravity-daemon.pid
echo "Supervising Antigravity daemon PID $pid."
while kill -0 "$pid" 2>/dev/null; do
    # A dead child may remain a zombie until tini reaps it.
    if [[ -r /proc/$pid/stat ]] && [[ $(awk '{print $3}' "/proc/$pid/stat") == Z ]]; then break; fi
    sleep 5 & wait $!
done
echo 'Antigravity daemon exited; Docker restart policy will recover it.' >&2
exit 1
