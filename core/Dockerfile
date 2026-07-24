FROM python:3.11-slim

WORKDIR /app

# 安装 Docker CLI
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://get.docker.com | sh && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/

EXPOSE 9800

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "9800"]
