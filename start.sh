#!/bin/bash

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║     🎵 SUPER RADIO BOT with Tunnel           ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Запускаем localhost.run туннель в фоне
echo "🔄 Запуск туннеля localhost.run..."
ssh -o StrictHostKeyChecking=no -R 80:localhost:8080 localhost.run > /tmp/tunnel.log 2>&1 &
TUNNEL_PID=$!

# Ждём получения URL
echo "⏳ Ожидание туннеля..."
sleep 5

# Пытаемся получить URL из логов
for i in {1..30}; do
    if [ -f /tmp/tunnel.log ]; then
        URL=$(cat /tmp/tunnel.log | grep -o 'https://[a-z0-9\-]*\.loca\.lt' | head -1)
        if [ ! -z "$URL" ]; then
            export PUBLIC_URL="$URL"
            echo "✅ ТУННЕЛЬ СОЗДАН: $PUBLIC_URL"
            break
        fi
    fi
    sleep 1
done

if [ -z "$PUBLIC_URL" ]; then
    echo "⚠️ Не удалось получить URL туннеля"
    export PUBLIC_URL="http://localhost:8080"
fi

# Запускаем бота
echo "🚀 Запуск бота..."
python bot.py

# Останавливаем туннель при завершении
kill $TUNNEL_PID
