# syntax=docker/dockerfile:1
# EasyStock Codex NAS 開發節點 Dockerfile
# 基礎映像檔採用官方 Debian/Node (支援 linux/arm64)
FROM node:22-bookworm-slim

ARG TARGETARCH=arm64
ARG PNPM_VERSION=10
ARG CODEX_RELEASE=latest

ENV TZ=Asia/Taipei \
    PYTHONUNBUFFERED=1

# 1. 驗證目標架構為 ARM64、安裝必要系統套件、建立 UID/GID 1000 非 root codex 使用者
RUN test "$TARGETARCH" = arm64 \
    && case "$(uname -m)" in aarch64|arm64) ;; *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;; esac \
    && apt-get update && apt-get install -y --no-install-recommends \
       bash ca-certificates curl git openssh-client python3 python3-pip \
       python3-venv python3-dev build-essential pkg-config procps tini \
       ripgrep jq tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupmod --new-name codex node \
    && usermod --login codex --home /home/codex --move-home --shell /bin/bash node \
    && getent passwd codex && id codex \
    && test "$(id -u codex)" = 1000 \
    && test "$(id -g codex)" = 1000 \
    && test -d /home/codex

ENV HOME=/home/codex \
    PATH=/home/codex/.local/bin:/opt/venv/bin:$PATH

# 2. 安裝 pnpm 10，建立 Python 獨立虛擬環境與 workspace 目錄
RUN npm install -g pnpm@${PNPM_VERSION} \
    && python3 -m venv /opt/venv \
    && chown -R codex:codex /opt/venv \
    && mkdir -p /workspace /opt/codex \
    && chown -R codex:codex /workspace

# 3. 使用 OpenAI 官方 Linux ARM64 Codex installer 進行安裝，並於 build 時驗證版本
RUN test "$TARGETARCH" = arm64 \
    && curl -fsSL https://chatgpt.com/codex/install.sh | \
       CODEX_RELEASE="${CODEX_RELEASE}" \
       CODEX_NON_INTERACTIVE=true \
       CODEX_INSTALL_DIR=/usr/local/bin \
       CODEX_HOME=/opt/codex \
       sh \
    && chmod -R 755 /opt/codex \
    && codex --version

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

USER codex
WORKDIR /workspace

ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["sleep", "infinity"]
