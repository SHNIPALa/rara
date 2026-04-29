#!/bin/bash

echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║     🎵 SUPER RADIO BOT + ICECAST 🎵           ║"
echo "╚═══════════════════════════════════════════════╝"
echo ""

# Ждем запуска Icecast
echo "🔄 Ожидание Icecast..."
sleep 10

# Запускаем бота
echo "🚀 Запуск бота..."
python bot.py
