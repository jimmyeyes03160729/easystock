FROM debian:bookworm-slim
ENV TZ=Asia/Taipei
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       bash cron openssh-client rsync python3 util-linux coreutils findutils \
       procps tzdata ca-certificates \
    && ln -snf /usr/share/zoneinfo/Asia/Taipei /etc/localtime \
    && echo Asia/Taipei > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/easystock/ops/nas
COPY sync_from_vm.sh sync_orderbook.sh healthcheck.sh docker-entrypoint.sh ./
RUN chmod 0755 sync_from_vm.sh sync_orderbook.sh healthcheck.sh docker-entrypoint.sh
COPY easystock-backup.cron /etc/cron.d/easystock-backup
RUN chmod 0644 /etc/cron.d/easystock-backup
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD /usr/bin/pgrep -x cron >/dev/null && test -d /data/backup/vm && test -r /data/backup/vm && test -w /data/backup/vm && test -x /data/backup/vm || exit 1
ENTRYPOINT ["/opt/easystock/ops/nas/docker-entrypoint.sh"]
CMD ["/usr/sbin/cron", "-f"]
