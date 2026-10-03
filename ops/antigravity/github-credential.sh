#!/usr/bin/env bash
set -euo pipefail
# Git credential protocol: answer only get requests for this exact repository.
[[ ${1:-} == get && ${GITHUB_AUTH_MODE:-ssh} == token ]] || exit 0
protocol='' host='' path=''
while IFS='=' read -r key value; do
    case "$key" in
        protocol) protocol=$value ;;
        host) host=$value ;;
        path) path=$value ;;
    esac
done
[[ "$protocol" == https && "$host" == github.com ]] || exit 0
[[ "$path" == jimmyeyes03160729/easystock.git || "$path" == jimmyeyes03160729/easystock ]] || exit 0
[[ -r /run/github/token ]] || exit 1
IFS= read -r token < /run/github/token || [[ -n ${token:-} ]]
[[ -n "$token" && "$token" != *$'\r'* ]] || exit 1
printf 'username=x-access-token\npassword=%s\n' "$token"
