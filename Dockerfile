FROM dmfive/kpqc-ossl3@sha256:3a833a303e49a4edb1faa4c8f2b55d224786568600c6b001ed1e6f8ab4a30d3d
RUN apt-get update && apt-get install -y --no-install-recommends python3 libxml2-utils time && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY scripts /app/scripts
COPY schemas /app/schemas
ENTRYPOINT ["python3", "/app/scripts/lab.py"]
