FROM debian:bookworm-slim

RUN printf 'deb http://mirrors.aliyun.com/debian bookworm main\ndeb http://mirrors.aliyun.com/debian bookworm-updates main\ndeb http://mirrors.aliyun.com/debian-security bookworm-security main\n' > /etc/apt/sources.list \
    && rm -f /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=2 update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && python3 -m venv /venv \
    && rm -rf /var/lib/apt/lists/*

ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 \
    PERSONAL_ARCHIVE_HOME=/state HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin memory
COPY vendor/ /app/
COPY smoke_mcp.py /app/smoke_mcp.py
COPY smoke_planner_mcp.py /app/smoke_planner_mcp.py
USER 10001:10001
ENTRYPOINT ["python", "/app/mcp_pipe.py", "/app/mcp_server.py"]
