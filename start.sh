#!/bin/bash

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║     🎵 SUPER RADIO + BORE TUNNEL 🎵          ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Запускаем радио сервер в фоне
python bot.py &
RADIO_PID=$!

# Ждём запуска радио
sleep 5

# Запускаем bore туннель
echo "🔄 Запуск bore туннеля..."
bore local 8080 --to bore.pub

# Останавливаем радио при завершении
kill $RADIO_PID
