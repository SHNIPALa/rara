#!/bin/bash

echo "========================================="
echo "🎵 RADIO BOT STARTING"
echo "========================================="

# Получаем внешний IP (если есть)
PUBLIC_IP=$(curl -s https://api.ipify.org 2>/dev/null || echo "localhost")

echo ""
echo "📡 ИНФОРМАЦИЯ О ДОСТУПЕ:"
echo "   Внешний IP: $PUBLIC_IP"
echo "   Порт: 8000"
echo ""
echo "🔗 ССЫЛКА ДЛЯ ДРУЗЕЙ: http://$PUBLIC_IP:8000/stream"
echo ""
echo "⚠️ ВАЖНО:"
echo "   1. Убедитесь, что порт 8000 открыт на вашем сервере"
echo "   2. Если вы дома - настройте проброс порта на роутере"
echo "   3. Проверьте доступ: curl http://$PUBLIC_IP:8000/stream"
echo ""

# Проверяем доступность Icecast
sleep 3
if curl -s http://localhost:8000/stream -o /dev/null; then
    echo "✅ Icecast работает"
else
    echo "❌ Icecast не отвечает, проверьте логи"
fi

# Запускаем Telegram бота
echo "🚀 Запуск бота..."
python bot.py
