#!/bin/bash

echo "========================================="
echo "🎵 RADIO BOT STARTING"
echo "========================================="

# Проверяем, запущен ли Icecast
if ! pgrep -x "icecast2" > /dev/null; then
    echo "🔄 Запуск Icecast..."
    sudo systemctl start icecast2
    sleep 3
fi

# Проверяем, работает ли Icecast
echo "🔍 Проверка Icecast..."
if curl -s http://localhost:8000/stream -o /dev/null; then
    echo "✅ Icecast работает"
else
    echo "❌ Icecast не отвечает"
fi

# Открываем порт в фаерволе (Ubuntu/Debian)
echo "🔓 Открываем порт 8000..."
if command -v ufw &> /dev/null; then
    sudo ufw allow 8000/tcp
    sudo ufw reload
    echo "✅ Порт 8000 открыт через ufw"
elif command -v firewall-cmd &> /dev/null; then
    sudo firewall-cmd --add-port=8000/tcp --permanent
    sudo firewall-cmd --reload
    echo "✅ Порт 8000 открыт через firewalld"
else
    echo "⚠️ Фаервол не найден, порт нужно открыть вручную"
fi

# Показываем информацию о сети
echo ""
echo "📡 ИНФОРМАЦИЯ О ДОСТУПЕ:"
echo "   Локальный IP: $(hostname -I | awk '{print $1}')"
echo "   Внешний IP: $(curl -s https://api.ipify.org)"
echo "   Порт: 8000"
echo ""
echo "🔗 ССЫЛКА ДЛЯ ДРУЗЕЙ: http://$(curl -s https://api.ipify.org):8000/stream"
echo ""

# Запускаем Telegram бота
echo "🚀 Запуск бота..."
python3 bot.py
