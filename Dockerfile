FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends openssh-client curl && \
    rm -rf /var/lib/apt/lists/*

# Установка ngrok (опционально, можно загружать через скрипт)
ARG NGROK_VERSION=3.19.1
RUN curl -sSL https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz \
    | tar -xz -C /usr/local/bin

# Установка cloudflared
RUN curl -sSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python", "bot.py"]
