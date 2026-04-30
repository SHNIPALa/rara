FROM python:3.11-slim

# Установка ffmpeg и xTunnel
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    wget \
    unzip \
    && wget https://xtunnel.ru/download/linux/xtunnel -O /usr/local/bin/xtunnel \
    && chmod +x /usr/local/bin/xtunnel \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

RUN mkdir -p music data pending

CMD ["python", "bot.py"]
