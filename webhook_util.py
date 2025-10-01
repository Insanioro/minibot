#!/usr/bin/env python3
"""
Утилита для управления webhook Telegram бота
"""

import os
import sys
import requests
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

def get_webhook_info(token):
    """Получить информацию о текущем webhook"""
    url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
    response = requests.get(url)
    return response.json()

def set_webhook(token, webhook_url):
    """Установить webhook"""
    url = f"https://api.telegram.org/bot{token}/setWebhook"
    data = {
        'url': webhook_url,
        'allowed_updates': ['message', 'chat_join_request', 'chat_member']
    }
    response = requests.post(url, data=data)
    return response.json()

def delete_webhook(token):
    """Удалить webhook"""
    url = f"https://api.telegram.org/bot{token}/deleteWebhook"
    response = requests.post(url)
    return response.json()

def main():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN не найден в переменных окружения")
        return
    
    if len(sys.argv) < 2:
        print("Использование:")
        print(f"  python {sys.argv[0]} info           # Показать текущий webhook")
        print(f"  python {sys.argv[0]} set <URL>      # Установить webhook")
        print(f"  python {sys.argv[0]} delete         # Удалить webhook")
        return
    
    command = sys.argv[1].lower()
    
    if command == 'info':
        print("🔍 Получение информации о webhook...")
        result = get_webhook_info(token)
        print(f"Результат: {result}")
        
    elif command == 'set':
        if len(sys.argv) < 3:
            print("❌ Укажите URL для webhook")
            return
        webhook_url = sys.argv[2]
        print(f"🔗 Установка webhook: {webhook_url}")
        result = set_webhook(token, webhook_url)
        print(f"Результат: {result}")
        
    elif command == 'delete':
        print("🗑️ Удаление webhook...")
        result = delete_webhook(token)
        print(f"Результат: {result}")
        
    else:
        print(f"❌ Неизвестная команда: {command}")

if __name__ == '__main__':
    main()
