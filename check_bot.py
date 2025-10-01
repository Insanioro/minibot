#!/usr/bin/env python3
"""
Проверка статуса Telegram бота
"""

import os
import sys
import requests
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

def check_bot_status():
    """Проверить статус бота"""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not token or token == 'your_bot_token_here':
        print("❌ TELEGRAM_BOT_TOKEN не установлен или использует значение по умолчанию")
        return False
    
    # Проверяем, что бот доступен
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get('ok'):
            bot_info = data['result']
            print(f"✅ Бот активен: @{bot_info['username']} ({bot_info['first_name']})")
            return True
        else:
            print(f"❌ Ошибка бота: {data.get('description', 'Unknown error')}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка сети: {e}")
        return False

def check_webhook_status():
    """Проверить статус webhook"""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not token:
        return
    
    try:
        url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get('ok'):
            webhook_info = data['result']
            webhook_url = webhook_info.get('url', '')
            
            if webhook_url:
                print(f"🔗 Webhook активен: {webhook_url}")
                if webhook_info.get('has_custom_certificate'):
                    print("🔐 Используется пользовательский сертификат")
                if webhook_info.get('pending_update_count', 0) > 0:
                    print(f"⏳ Ожидающих обновлений: {webhook_info['pending_update_count']}")
                if webhook_info.get('last_error_message'):
                    print(f"⚠️ Последняя ошибка: {webhook_info['last_error_message']}")
            else:
                print("📱 Webhook не установлен (используется polling)")
                
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка при проверке webhook: {e}")

def main():
    print("🤖 Проверка статуса Telegram бота\n")
    
    # Проверяем переменные окружения
    is_production = os.getenv('PRODUCTION') == 'true' or os.getenv('RENDER') == 'true'
    webhook_url = os.getenv('WEBHOOK_URL')
    
    print(f"📋 Режим работы: {'Production' if is_production else 'Development'}")
    if is_production and webhook_url:
        print(f"🔗 Webhook URL: {webhook_url}")
    print("")
    
    # Проверяем статус бота
    if check_bot_status():
        print("")
        check_webhook_status()
        
        print("\n💡 Рекомендации:")
        if is_production:
            print("   - Для production используйте webhook")
            print("   - Убедитесь, что бот не запущен локально")
        else:
            print("   - Для разработки используйте polling")
            print("   - Убедитесь, что webhook не установлен")
            
        print("\n📊 Доступные команды для админов:")
        print("   /stats - получить статистику по всем каналам")

if __name__ == '__main__':
    main()
