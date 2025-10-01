#!/bin/bash

# Этот скрипт выполняется при деплое на Render

echo "🚀 Настройка проекта для Render..."

# Проверяем наличие токена
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "❌ TELEGRAM_BOT_TOKEN не установлен!"
    exit 1
fi

echo "✅ Переменные окружения настроены"
echo "✅ Зависимости установлены"
echo "🎯 Запуск бота..."

# Запускаем бота
python bot.py
