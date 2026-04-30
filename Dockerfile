FROM python:3.11-slim

# Установка cloudflared (официальный бинарник)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && \
    chmod +x /usr/local/bin/cloudflared && \
    rm -rf /var/lib/apt/lists/*

RUN pip install aiogram
WORKDIR /app
COPY bot.py .
CMD ["python", "bot.py"]
