#!/bin/bash

echo "========================================="
echo "🎵 RADIO BOT STARTING"
echo "========================================="

# Ждем запуска Icecast
sleep 5

# Запускаем FFmpeg для стриминга плейлиста
play_playlist() {
    while true; do
        for song in /app/music/*.mp3; do
            if [ -f "$song" ]; then
                echo "🎵 Playing: $(basename "$song")"
                ffmpeg -re -i "$song" -c copy -f mp3 icecast://source:hackme@localhost:8000/stream 2>/dev/null
                sleep 0.5
            fi
        done
    done
}

# Запускаем поток в фоне
play_playlist &
FFMPEG_PID=$!

# Запускаем бота
echo "🚀 Starting Telegram bot..."
python bot.py

# Останавливаем FFmpeg при завершении
kill $FFMPEG_PID