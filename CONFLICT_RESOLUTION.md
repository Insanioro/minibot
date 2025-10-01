# Быстрое решение конфликта polling

## Проблема
```
telegram.error.Conflict: Conflict: terminated by other getUpdates request
```

## Причина
Одновременно запущено несколько экземпляров бота с одним токеном.

## Решение

### 1. Остановите все экземпляры бота
```bash
# Остановите локальный бот (если запущен)
Ctrl+C

# Проверьте Render - остановите/перезапустите сервис если нужно
```

### 2. Убедитесь в правильной настройке

**Локальная разработка (.env файл):**
```env
TELEGRAM_BOT_TOKEN=your_real_token_here
# НЕ добавляйте PRODUCTION=true для локальной разработки
```

**Production на Render (переменные окружения):**
```
TELEGRAM_BOT_TOKEN=your_real_token_here
PRODUCTION=true
WEBHOOK_URL=https://your-app-name.onrender.com
PORT=8000
```

### 3. Режимы работы

- **Локально**: автоматически использует polling
- **Render**: автоматически использует webhook (если PRODUCTION=true)

### 4. Проверка webhook

```bash
# Проверить текущий webhook
python webhook_util.py info

# Удалить webhook (если нужно переключиться на polling)
python webhook_util.py delete
```

### 5. Важные правила

✅ Запускайте бота ТОЛЬКО в одном месте одновременно
✅ Для production используйте webhook (Render)
✅ Для разработки используйте polling (локально)
❌ Не запускайте бота локально, если он работает на Render
❌ Не используйте один токен для нескольких экземпляров
