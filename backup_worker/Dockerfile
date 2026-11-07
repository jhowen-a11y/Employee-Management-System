ARG POSTGRES_CLIENT_MAJOR=17
FROM postgres:${POSTGRES_CLIENT_MAJOR}-bookworm

ENV PYTHONUNBUFFERED=1 \
    PORT=10000 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && python3 -m venv "${VIRTUAL_ENV}" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app

EXPOSE 10000
ENTRYPOINT []
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 1 --threads 4 --timeout 1000 backup_worker.app:app"]
