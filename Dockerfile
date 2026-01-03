FROM python:3.14-slim-bookworm AS exporter

WORKDIR /opt/app/

COPY mise.toml pyproject.toml uv.lock* ./

RUN UV_VERSION=$(sed -n 's/^uv = "\(.*\)"/\1/p' mise.toml) && \
    pip install --no-cache-dir uv==${UV_VERSION} && \
    uv export -o requirements.txt --no-default-groups --no-hashes --no-annotate --frozen --no-emit-project

#########################################################################
FROM python:3.14-slim-bookworm

WORKDIR /opt/app/

COPY --from=exporter /opt/app/requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt && \
    (find /usr/local -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true) && \
    rm -rf /root/.cache /tmp/*

COPY tg_trnsm_bot/ /opt/app/tg_trnsm_bot/

CMD ["python", "-m", "tg_trnsm_bot"]
