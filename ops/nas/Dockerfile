FROM alpine:3.21
RUN apk add --no-cache bash openssh-client rsync python3 tzdata util-linux
WORKDIR /opt/easystock/ops/nas
COPY sync_from_vm.sh healthcheck.sh ./
RUN chmod 0755 sync_from_vm.sh healthcheck.sh
ENTRYPOINT ["/bin/bash"]
