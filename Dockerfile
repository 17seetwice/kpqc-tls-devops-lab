FROM dmfive/kpqc-ossl3@sha256:3a833a303e49a4edb1faa4c8f2b55d224786568600c6b001ed1e6f8ab4a30d3d
# Refresh stale mirror indexes on a bounded retry; never mask an incomplete install.
RUN set -eu; \
    find /etc/apt -type f \( -name '*.sources' -o -name '*.list' \) -exec sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g; s|http://security.ubuntu.com|https://security.ubuntu.com|g' {} +; \
    for attempt in 1 2 3; do \
      if apt-get -o Acquire::http::No-Cache=true -o Acquire::https::No-Cache=true -o Acquire::Retries=3 update --error-on=any \
         && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::http::No-Cache=true -o Acquire::Retries=3 install -y --no-install-recommends python3 libxml2-utils time; then break; fi; \
      if [ "$attempt" = 3 ]; then exit 1; fi; \
      rm -rf /var/lib/apt/lists/*; sleep 3; \
    done; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY scripts /app/scripts
COPY schemas /app/schemas
ENTRYPOINT ["python3", "/app/scripts/lab.py"]
