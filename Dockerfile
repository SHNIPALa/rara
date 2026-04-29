FROM python:3.11-slim

# Установка ffmpeg и bore
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && curl -L https://github.com/ekzhang/bore/releases/download/v0.5.0/bore-v0.5.0-x86_64-unknown-linux-musl.tar.gz | tar xz \
    && mv bore /usr/local/bin/ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

RUN mkdir -p music

CMD ["python", "bot.py"]
