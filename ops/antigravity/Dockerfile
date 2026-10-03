# syntax=docker/dockerfile:1
# Debian/glibc and Node official multi-arch image (includes linux/arm64).
FROM node:22-bookworm-slim
ARG TARGETARCH
ARG PNPM_VERSION=10.18.3
ENV HOME=/home/agent PATH=/home/agent/.local/bin:/opt/venv/bin:$PATH \
    TZ=Asia/Taipei PYTHONUNBUFFERED=1
RUN test "$TARGETARCH" = arm64 \
    && apt-get update && apt-get install -y --no-install-recommends \
       bash ca-certificates curl git openssh-client python3 python3-venv \
       python3-dev build-essential pkg-config libffi-dev libssl-dev \
       procps tini ripgrep tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g pnpm@${PNPM_VERSION} \
    && usermod --login agent --home /home/agent --move-home --shell /bin/bash node \
    && groupmod --new-name agent node \
    && python3 -m venv /opt/venv && chown -R agent:agent /opt/venv \
    && mkdir -p /workspace /opt/antigravity \
    && chown agent:agent /workspace
# Pinned official linux_arm64 manifest, checked 2026-10-03. Rebuild explicitly
# when upgrading; the official install.sh otherwise selects a moving latest.
RUN curl -fsSL https://storage.googleapis.com/antigravity-public/antigravity-cli/1.2.16-5594158052802560/linux-arm/cli_linux_arm64.tar.gz -o /tmp/agy.tar.gz \
    && echo 'd17d8044736d31e24ce7c4cb3b75faef3ce5102ecaad31aef95785c0f3c13fa0615d7b11fa411eb73b848489adf9d411178446f3148e30353a2048cd3e731971  /tmp/agy.tar.gz' | sha512sum -c - \
    && tar -xzf /tmp/agy.tar.gz -C /opt/antigravity \
    && chmod 0755 /opt/antigravity/antigravity \
    && rm /tmp/agy.tar.gz
COPY entrypoint.sh github-credential.sh /usr/local/bin/
RUN chmod 0755 /usr/local/bin/entrypoint.sh /usr/local/bin/github-credential.sh
USER agent
WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["daemon"]
