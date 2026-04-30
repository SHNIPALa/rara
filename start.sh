#!/bin/bash

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║     🎵 SUPER RADIO BOT with NGROK 🎵         ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Настройка ngrok
echo "🔧 Configuring ngrok..."
ngrok config add-authtoken $NGROK_AUTH_TOKEN

# Запуск ngrok в фоне
echo "🔄 Starting ngrok tunnel..."
ngrok http 8080 --log=stdout > /tmp/ngrok.log 2>&1 &

# Ждём ngrok
sleep 5

# Получаем публичный URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "import sys, json; print(json.load(sys.stdin)['tunnels'][0]['public_url'] if json.load(sys.stdin)['tunnels'] else '')" 2>/dev/null)

if [ -n "$NGROK_URL" ]; then
    export PUBLIC_URL="$NGROK_URL"
    echo "✅ NGROK TUNNEL: $PUBLIC_URL"
else
    export PUBLIC_URL="http://localhost:8080"
    echo "⚠️ Ngrok not ready, using localhost"
fi

export STREAM_URL="$PUBLIC_URL/radio.mp3"

echo ""
echo "🔗 LINK FOR FRIENDS: $PUBLIC_URL"
echo "📡 STREAM URL: $STREAM_URL"
echo ""

# Запускаем бота
python bot.py
