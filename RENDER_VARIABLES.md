# 🔧 Переменные окружения для Render

## Обязательные переменные для Render:

```
TELEGRAM_BOT_TOKEN = ваш_токен_от_BotFather
PRODUCTION = true
WEBHOOK_URL = https://your-app-name.onrender.com
PORT = 8000
```

## Как получить токен:
1. Откройте [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot`
3. Следуйте инструкциям для создания бота
4. Скопируйте полученный токен (формат: `123456789:ABCdefGHIjklMNOpqrSTUvwxyz`)

## Как найти имя приложения Render:
1. После создания Web Service на Render
2. В URL вашего приложения: `https://your-app-name.onrender.com`
3. `your-app-name` - это имя, которое нужно использовать в `WEBHOOK_URL`

## Пример заполнения:

Если ваше приложение называется `my-telegram-bot`, то:
```
TELEGRAM_BOT_TOKEN = 6123456789:AAEhBOweik6ad6PsY_CphdD_nN-9Z9_rG2o
PRODUCTION = true
WEBHOOK_URL = https://my-telegram-bot.onrender.com
PORT = 8000
```

## ✅ Проверка корректности:
После настройки запустите: `python check_bot.py`
