FROM python:3.11-slim

# Установка Node.js (для LocalTunnel) и других инструментов
RUN apt-get update && apt-get install -y \
    ffmpeg \
    openssh-client \
    curl \
    nodejs \
    npm \
    && npm install -g localtunnel \
    && rm -rf /var/lib/apt/lists/*

# Установка Bore
RUN curl -L https://github.com/ekzhang/bore/releases/download/v0.5.0/bore-v0.5.0-x86_64-unknown-linux-musl.tar.gz | tar xz \
    && mv bore /usr/local/bin/

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

RUN mkdir -p music

CMD ["python", "bot.py"]
