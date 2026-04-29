#!/bin/bash

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     🎵 SUPER RADIO BOT 🎵                ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Запускаем ngrok в фоне
echo "🔄 Запуск ngrok туннеля..."
ngrok http 8080 --log=stdout > /tmp/ngrok.log 2>&1 &

sleep 5

# Получаем публичный URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | grep -o 'https://[a-zA-Z0-9.-]*\.ngrok-free.app' | head -1)

if [ -n "$NGROK_URL" ]; then
    export STREAM_URL="$NGROK_URL/stream.mp3"
    echo "✅ Туннель создан: $NGROK_URL"
else
    export STREAM_URL="http://localhost:8080/stream.mp3"
    echo "⚠️ Туннель не создан, используем localhost"
fi

echo ""
echo "🔗 ССЫЛКА ДЛЯ ДРУЗЕЙ: $STREAM_URL"
echo ""

# Запускаем бота
python bot.py
