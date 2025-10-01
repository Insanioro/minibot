# Render Deployment Guide

## Подготовка к деплою на Render

### 1. Создание веб-сервиса на Render

1. Зайдите на [render.com](https://render.com) и создайте аккаунт
2. Подключите ваш GitHub репозиторий
3. Создайте новый **Web Service**
4. Выберите ваш репозиторий с ботом

### 2. Настройки деплоя

**Build Command:** (оставьте пустым)
```
pip install -r requirements.txt
```

**Start Command:**
```
python bot.py
```

### 3. Переменные окружения

В разделе **Environment Variables** добавьте:

- `TELEGRAM_BOT_TOKEN` = ваш токен от @BotFather
- `PRODUCTION` = `true`
- `WEBHOOK_URL` = `https://your-app-name.onrender.com` (замените your-app-name на имя вашего сервиса)
- `PORT` = `8000`
- `PYTHON_VERSION` = `3.11`

⚠️ **ВАЖНО**: Замените `your-app-name` в `WEBHOOK_URL` на реальное имя вашего сервиса Render!

### 4. Настройки

- **Region**: выберите ближайший к вашим пользователям
- **Plan**: Free (для начала)
- **Auto-Deploy**: включите для автоматического деплоя при изменениях

### 5. Деплой

1. Нажмите **Create Web Service**
2. Дождитесь завершения сборки и запуска
3. Проверьте логи на наличие ошибок

## Локальная разработка

```bash
# Установка зависимостей
pip install -r requirements.txt

# Создайте файл .env с токеном
echo "TELEGRAM_BOT_TOKEN=your_token_here" > .env

# Запуск
python bot.py
```

## Мониторинг

- Логи доступны в панели Render
- Бот автоматически перезапустится при ошибках
- Статистика работы доступна в дашборде

## Поддерживаемые каналы

✅ Приватные группы с заявками на вступление
✅ Публичные группы  
✅ Супергруппы
✅ Каналы (только для статистики)

## Решение проблем

### Ошибка "Conflict: terminated by other getUpdates request"

Эта ошибка возникает, когда одновременно запущено несколько экземпляров бота:

**Решение:**
1. **Остановите локальный бот** если он запущен
2. **Проверьте Render** - только один сервис должен работать
3. **Используйте разные режимы**:
   - Локально: polling (автоматически)
   - Render: webhook (через переменные окружения)

### Режимы работы

**Development (локально):**
- Использует polling
- Не требует webhook
- `.env` файл без `PRODUCTION=true`

**Production (Render):**
- Использует webhook  
- Требует `WEBHOOK_URL`
- Переменная `PRODUCTION=true`

### Проверка статуса

```bash
# Проверить работает ли бот
curl https://api.telegram.org/bot<YOUR_TOKEN>/getMe

# Проверить webhook
curl https://api.telegram.org/bot<YOUR_TOKEN>/getWebhookInfo
```

### Очистка webhook (если нужно)

```bash
curl -X POST https://api.telegram.org/bot<YOUR_TOKEN>/deleteWebhook
```
