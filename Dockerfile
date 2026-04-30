FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends mpd client && \
    pip install aiogram python-mpd2 mutagen && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY bot.py .
CMD ["python", "bot.py"]
