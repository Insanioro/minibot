import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Set
import json
import os

from telegram import Update, ChatMemberUpdated, ChatMember, Chat
from telegram.ext import Application, ChatJoinRequestHandler, ChatMemberHandler, ContextTypes, CommandHandler
from telegram.constants import ChatAction, ParseMode, ChatType
from telegram.error import BadRequest, Forbidden
import signal
import sys

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.pending_requests: Dict[str, Dict] = {}  # user_id -> {chat_id, request_time, user_data}
        self.approved_users: Set[str] = set()  # множество одобренных пользователей
        self.config = self.load_config()
        
        # Статистика
        self.stats = {
            'hourly_requests': 0,  # заявки за текущий час
            'hourly_left': 0,      # отписавшиеся за текущий час
            'daily_requests': 0,   # заявки за 8 часов
            'daily_left': 0,       # отписавшиеся за 8 часов
            'total_requests': 0,   # всего заявок
            'total_approved': 0,   # всего одобрено
            'total_left': 0        # всего отписалось
        }
        self.tracked_groups = set()  # множество отслеживаемых групп
        
    def load_config(self) -> Dict:
        """Загружает конфигурацию из файла config.json"""
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning("Файл config.json не найден, используются настройки по умолчанию")
            return {
                "auto_approve_delay": 10,  # 10 минут в секундах
                "welcome_message": " Добро пожаловать в нашу группу! Для консультации/заказа: @apple_anastasiya",
                "admin_notification": True
            }
    
    async def handle_chat_join_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает заявки на вступление в группу"""
        if not update.chat_join_request:
            return
            
        request = update.chat_join_request
        user_id = str(request.from_user.id)
        chat_id = str(request.chat.id)
        chat_type = request.chat.type
        
        logger.info(f"Получена заявка от пользователя {request.from_user.first_name} ({user_id}) в чат {chat_id} (тип: {chat_type})")
        
        # Проверяем тип чата
        if chat_type not in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
            logger.warning(f"Неподдерживаемый тип чата: {chat_type}")
            return
        
        # Обновляем статистику
        self.stats['hourly_requests'] += 1
        self.stats['daily_requests'] += 1
        self.stats['total_requests'] += 1
        
        # Добавляем группу в отслеживаемые
        self.tracked_groups.add(chat_id)
        
        # Сохраняем информацию о заявке
        self.pending_requests[user_id] = {
            'chat_id': chat_id,
            'request_time': datetime.now(),
            'user_data': {
                'id': request.from_user.id,
                'first_name': request.from_user.first_name,
                'last_name': request.from_user.last_name,
                'username': request.from_user.username
            }
        }
        
        # Планируем автоматическое одобрение через 10 минут
        delay = self.config.get("auto_approve_delay", 600)
        
        if context.job_queue is not None:
            context.job_queue.run_once(
                self.auto_approve_request,
                delay,
                data={'user_id': user_id, 'chat_id': chat_id},
                name=f"approve_{user_id}_{chat_id}"
            )
            logger.info(f"Запланировано автоматическое одобрение через {delay} секунд")
        else:
            logger.error("JobQueue не настроен! Автоматическое одобрение не будет работать.")
        
        # Уведомляем администраторов (если включено в настройках)
        if self.config.get("admin_notification", True):
            await self.notify_admins(context, request)
    
    async def auto_approve_request(self, context: ContextTypes.DEFAULT_TYPE):
        """Автоматически одобряет заявку через указанный время"""
        job_data = context.job.data
        user_id = job_data['user_id']
        chat_id = job_data['chat_id']
        
        # Проверяем, что заявка все еще актуальна
        if user_id not in self.pending_requests:
            logger.info(f"Заявка пользователя {user_id} уже обработана")
            return
        
        try:
            # Одобряем заявку
            await context.bot.approve_chat_join_request(
                chat_id=int(chat_id),
                user_id=int(user_id)
            )
            
            # Добавляем пользователя в список одобренных
            self.approved_users.add(user_id)
            
            # Удаляем из ожидающих
            user_data = self.pending_requests.pop(user_id)
            
            logger.info(f"Автоматически одобрена заявка пользователя {user_data['user_data']['first_name']} ({user_id})")
            
            # Обновляем статистику одобренных
            self.stats['total_approved'] += 1
            

            
        except Exception as e:
            logger.error(f"Ошибка при автоматическом одобрении заявки: {e}")
            # Удаляем из ожидающих в случае ошибки
            self.pending_requests.pop(user_id, None)
    
    async def handle_chat_member_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отслеживает изменения участников чата для отправки приветственного сообщения и статистики"""
        if not update.chat_member:
            return
        
        chat_member_update = update.chat_member
        user_id = str(chat_member_update.new_chat_member.user.id)
        old_status = chat_member_update.old_chat_member.status
        new_status = chat_member_update.new_chat_member.status
        chat_type = update.effective_chat.type
        chat_id = str(update.effective_chat.id)
        
        # Добавляем чат в отслеживаемые если его еще нет
        self.tracked_groups.add(chat_id)
        
        # Проверяем, что пользователь стал участником группы
        if (old_status in [ChatMember.LEFT, ChatMember.KICKED] and 
            new_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]):
            
            # Проверяем, что это пользователь, которого мы одобрили
            if user_id in self.approved_users:
                await self.send_welcome_message(update, context, chat_member_update.new_chat_member.user)
                self.approved_users.remove(user_id)  # Удаляем из списка после отправки приветствия
        
        # Отслеживаем людей, покидающих группу
        elif (old_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR] and 
              new_status in [ChatMember.LEFT, ChatMember.KICKED]):
            
            self.stats['hourly_left'] += 1
            self.stats['daily_left'] += 1
            self.stats['total_left'] += 1
            logger.info(f"Пользователь {chat_member_update.new_chat_member.user.first_name} ({user_id}) покинул чат {chat_type}")
    
    async def send_welcome_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user):
        """Отправляет приветственное сообщение новому участнику"""
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        welcome_text = self.config.get("welcome_message", "🎉 Добро пожаловать в нашу группу!")
        
        # Проверяем права бота на отправку сообщений
        try:
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if not bot_member.can_send_messages:
                logger.warning(f"Бот не может отправлять сообщения в чат {chat_id}")
                return
        except (BadRequest, Forbidden) as e:
            logger.warning(f"Не удалось проверить права бота в чате {chat_id}: {e}")
            return
        
        # Персонализируем сообщение
        if chat_type == ChatType.CHANNEL:
            # Для каналов используем простое сообщение без упоминания
            personalized_message = f"🎉 Добро пожаловать, {user.first_name}! {welcome_text}"
        else:
            # Для групп используем упоминание
            user_mention = f"[{user.first_name}](tg://user?id={user.id})"
            personalized_message = f"{user_mention}, {welcome_text}"
        
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=personalized_message,
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Отправлено приветственное сообщение пользователю {user.first_name} ({user.id}) в {chat_type}")
        except (BadRequest, Forbidden) as e:
            logger.error(f"Ошибка при отправке приветственного сообщения: {e}")
            # Пробуем отправить без форматирования
            try:
                simple_message = f"Добро пожаловать, {user.first_name}! {welcome_text}"
                await context.bot.send_message(chat_id=chat_id, text=simple_message)
                logger.info(f"Отправлено упрощенное приветственное сообщение")
            except Exception as e2:
                logger.error(f"Не удалось отправить даже упрощенное сообщение: {e2}")
    
    async def notify_admins(self, context: ContextTypes.DEFAULT_TYPE, request):
        """Уведомляет администраторов о новой заявке"""
        try:
            # Безопасное форматирование без специальных символов
            username = request.from_user.username if request.from_user.username else 'не указан'
            last_name = ' ' + request.from_user.last_name if request.from_user.last_name else ''
            delay_minutes = self.config.get('auto_approve_delay', 600) // 60
            
            admin_message = (
                f"📝 Новая заявка на вступление:\n"
                f"👤 Пользователь: {request.from_user.first_name}{last_name}\n"
                f"🆔 ID: {request.from_user.id}\n"
                f"👤 Username: {username}\n"
                f"⏰ Автоматическое одобрение через {delay_minutes} минут"
            )
            
            # Получаем список администраторов
            chat_admins = await context.bot.get_chat_administrators(request.chat.id)
            
            for admin in chat_admins:
                if not admin.user.is_bot:  # Не отправляем ботам
                    try:
                        await context.bot.send_message(
                            chat_id=admin.user.id,
                            text=admin_message
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось отправить уведомление админу {admin.user.id}: {e}")
                        
        except Exception as e:
            logger.error(f"Ошибка при уведомлении администраторов: {e}")
    



    async def send_hourly_stats(self, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет почасовую статистику администраторам"""
        if self.stats['hourly_requests'] == 0 and self.stats['hourly_left'] == 0:
            return  # Не отправляем пустую статистику
        
        current_time = datetime.now().strftime("%H:%M")
        stats_message = (
            f"📊 Статистика за последний час ({current_time}):\n"
            f"📈 Новых заявок: {self.stats['hourly_requests']}\n"
            f"📉 Покинули группу: {self.stats['hourly_left']}\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"🔄 Прирост: {self.stats['hourly_requests'] - self.stats['hourly_left']}"
        )
        
        await self.send_stats_to_admins(context, stats_message)
        
        # Сбрасываем почасовую статистику
        self.stats['hourly_requests'] = 0
        self.stats['hourly_left'] = 0
    
    async def send_daily_stats(self, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет статистику за 8 часов администраторам"""
        current_time = datetime.now().strftime("%d.%m.%Y %H:%M")
        stats_message = (
            f"📈 Статистика за последние 8 часов ({current_time}):\n\n"
            f"📝 Новых заявок: {self.stats['daily_requests']}\n"
            f"✅ Одобрено: {self.stats['total_approved']}\n"
            f"👋 Покинули группу: {self.stats['daily_left']}\n"
            f"🔄 Чистый прирост: {self.stats['daily_requests'] - self.stats['daily_left']}\n\n"
            f"📊 Общая статистика:\n"
            f"📋 Всего заявок: {self.stats['total_requests']}\n"
            f"✅ Всего одобрено: {self.stats['total_approved']}\n"
            f"👋 Всего покинуло: {self.stats['total_left']}"
        )
        
        await self.send_stats_to_admins(context, stats_message)
        
        # Сбрасываем дневную статистику
        self.stats['daily_requests'] = 0
        self.stats['daily_left'] = 0
    
    async def send_stats_to_admins(self, context: ContextTypes.DEFAULT_TYPE, message: str):
        """Отправляет статистику всем администраторам всех отслеживаемых групп"""
        sent_to_admins = set()  # Чтобы не отправлять дубли одному админу
        
        # Используем отслеживаемые группы
        if not self.tracked_groups:
            logger.warning("Нет отслеживаемых групп для отправки статистики")
            return
        
        for chat_id in list(self.tracked_groups):  # Создаем копию для безопасной итерации
            try:
                # Получаем информацию о чате
                chat = await context.bot.get_chat(int(chat_id))
                chat_type = chat.type
                
                # Пропускаем каналы, если бот не админ
                if chat_type == ChatType.CHANNEL:
                    try:
                        bot_member = await context.bot.get_chat_member(int(chat_id), context.bot.id)
                        if bot_member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                            continue
                    except (BadRequest, Forbidden):
                        continue
                
                chat_admins = await context.bot.get_chat_administrators(int(chat_id))
                
                for admin in chat_admins:
                    if not admin.user.is_bot and admin.user.id not in sent_to_admins:
                        try:
                            await context.bot.send_message(
                                chat_id=admin.user.id,
                                text=message
                            )
                            sent_to_admins.add(admin.user.id)
                            logger.info(f"Отправлена статистика админу {admin.user.id} из {chat_type}")
                        except (BadRequest, Forbidden) as e:
                            logger.warning(f"Не удалось отправить статистику админу {admin.user.id}: {e}")
                        except Exception as e:
                            logger.error(f"Неожиданная ошибка при отправке статистики админу {admin.user.id}: {e}")
                            
            except (BadRequest, Forbidden) as e:
                logger.warning(f"Нет доступа к чату {chat_id}: {e}")
                # Удаляем недоступный чат из отслеживаемых
                self.tracked_groups.discard(chat_id)
            except Exception as e:
                logger.error(f"Ошибка при получении админов для чата {chat_id}: {e}")
    
    async def setup_periodic_tasks(self, context: ContextTypes.DEFAULT_TYPE):
        """Настраивает периодические задачи для статистики"""
        if context.job_queue is not None:
            # Почасовые отчеты
            context.job_queue.run_repeating(
                self.send_hourly_stats,
                interval=3600,  # каждый час (3600 секунд)
                first=3600,     # первый отчет через час
                name="hourly_stats"
            )
            
            # Отчеты каждые 8 часов
            context.job_queue.run_repeating(
                self.send_daily_stats,
                interval=28800,  # каждые 8 часов (8 * 3600 секунд)
                first=28800,     # первый отчет через 8 часов
                name="daily_stats"
            )
            
            logger.info("Настроены периодические задачи для статистики")
        else:
            logger.error("JobQueue не настроен для периодических задач!")

    def run(self):
        """Запускает бота"""
        # Создаем приложение с JobQueue
        from telegram.ext import JobQueue
        
        application = (
            Application.builder()
            .token(self.token)
            .job_queue(JobQueue())
            .build()
        )
        
        # Регистрируем обработчики
        application.add_handler(ChatJoinRequestHandler(self.handle_chat_join_request))
        application.add_handler(ChatMemberHandler(self.handle_chat_member_update))
        
        # Настраиваем периодические задачи для статистики
        application.job_queue.run_once(
            self.setup_periodic_tasks,
            0  # Запускаем сразу
        )
        
        # Настраиваем graceful shutdown
        def signal_handler(signum, frame):
            logger.info("Получен сигнал завершения, останавливаем бота...")
            application.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        logger.info("Бот запущен и готов к работе!")
        logger.info(f"Отслеживаемые типы обновлений: заявки на вступление, изменения участников")
        
        # Запускаем бота
        try:
            application.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True  # Игнорируем старые обновления при перезапуске
            )
        except Exception as e:
            logger.error(f"Критическая ошибка при запуске бота: {e}")
            raise

def main():
    # Получаем токен бота из переменной окружения или файла
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not token:
        try:
            # Пробуем загрузить из .env файла (для локальной разработки)
            with open('.env', 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('TELEGRAM_BOT_TOKEN=') and not line.startswith('#'):
                        token = line.split('=', 1)[1].strip()
                        # Убираем кавычки если они есть
                        if token.startswith('"') and token.endswith('"'):
                            token = token[1:-1]
                        if token.startswith("'") and token.endswith("'"):
                            token = token[1:-1]
                        break
        except FileNotFoundError:
            logger.warning("Файл .env не найден, используются только переменные окружения")
    
    if not token or token == 'your_bot_token_here':
        logger.error(
            "❌ TELEGRAM_BOT_TOKEN не найден!\n"
            "Для локальной разработки: создайте файл .env с токеном\n"
            "Для Render: добавьте переменную окружения TELEGRAM_BOT_TOKEN"
        )
        return
    
    # Проверяем, что токен выглядит правильно (должен содержать : и быть достаточно длинным)
    if ':' not in token or len(token) < 35:
        logger.error("❌ Токен бота имеет неправильный формат!")
        return
    
    logger.info(f"🚀 Запуск бота с токеном: {token[:10]}...")
    logger.info(f"🌍 Режим работы: {'PRODUCTION (Render)' if os.getenv('RENDER') else 'DEVELOPMENT (Local)'}")
    
    try:
        bot = TelegramBot(token)
        bot.run()
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        raise

if __name__ == '__main__':
    main()
