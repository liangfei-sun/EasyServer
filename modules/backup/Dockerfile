FROM alpine:latest

RUN apk add --no-cache \
    restic \
    dcron \
    bash \
    curl \
    && mkdir -p /data/backups /scripts

COPY scripts/backup.sh /scripts/backup.sh
COPY scripts/entrypoint.sh /scripts/entrypoint.sh
RUN chmod +x /scripts/*.sh

ENTRYPOINT ["/scripts/entrypoint.sh"]
