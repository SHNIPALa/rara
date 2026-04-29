FROM python:3.11-slim

# Установка ffmpeg и SSH клиента
RUN apt-get update && apt-get install -y \
    ffmpeg \
    openssh-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

RUN mkdir -p music

# Установка клиента sshpass для автоматического ввода пароля (опционально)
RUN apt-get update && apt-get install -y sshpass && rm -rf /var/lib/apt/lists/*

CMD ["python", "bot.py"]
