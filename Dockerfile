FROM python:3.11-slim
RUN pip install aiogram python-mpd2 mutagen
WORKDIR /app
COPY bot.py .
CMD ["python", "bot.py"]
