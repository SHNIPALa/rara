FROM python:3.11-slim
RUN pip install aiogram
WORKDIR /app
COPY bot.py .
CMD ["python", "bot.py"]
