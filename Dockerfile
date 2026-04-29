FROM python:3.11-slim

# Установка ffmpeg и зависимостей
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY bot.py .

# Создаём папку для музыки
RUN mkdir -p music

# Запуск
CMD ["python", "bot.py"]
