# =============================================================================
# Showdesk PostgreSQL -- official postgres image + WAL-G for continuous
# archiving and point-in-time recovery (PITR) to any S3-compatible storage.
#
# Archiving is a no-op until WALG_S3_PREFIX is set, so the image behaves
# exactly like the upstream one by default. See deploy/postgres/README.md.
# =============================================================================
FROM postgres:17

ARG WALG_VERSION=v3.0.9
ARG TARGETARCH

RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
      amd64) asset=wal-g-pg-22.04-amd64 ;; \
      arm64) asset=wal-g-pg-22.04-aarch64 ;; \
      *) echo "unsupported arch ${TARGETARCH}"; exit 1 ;; \
    esac; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    base="https://github.com/wal-g/wal-g/releases/download/${WALG_VERSION}"; \
    cd /tmp; \
    curl -fsSLO "${base}/${asset}"; \
    curl -fsSLO "${base}/${asset}.sha256"; \
    sha256sum -c "${asset}.sha256"; \
    install -m 755 "${asset}" /usr/local/bin/wal-g; \
    rm -f /tmp/wal-g-*; \
    apt-get purge -y curl; apt-get autoremove -y; rm -rf /var/lib/apt/lists/*; \
    wal-g --version

COPY --chmod=755 walg-archive.sh /usr/local/bin/walg-archive
COPY --chmod=755 walg-backup-loop.sh /usr/local/bin/walg-backup-loop
