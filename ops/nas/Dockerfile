FROM debian:bookworm-slim
ENV TZ=Asia/Taipei
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       bash cron openssh-client rsync python3 tzdata util-linux procps \
    && ln -snf /usr/share/zoneinfo/Asia/Taipei /etc/localtime \
    && echo Asia/Taipei > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/easystock/ops/nas
COPY sync_from_vm.sh healthcheck.sh ./
RUN chmod 0755 sync_from_vm.sh healthcheck.sh
COPY easystock-backup.cron /etc/cron.d/easystock-backup
RUN chmod 0644 /etc/cron.d/easystock-backup
ENTRYPOINT ["/bin/bash"]
