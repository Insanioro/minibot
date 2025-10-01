import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Set
import json
import os

from telegram import Update, ChatMemberUpdated, ChatMember, Chat
from telegram.ext import Application, ChatJoinRequestHandler, ChatMemberHandler, ContextTypes, CommandHandler
from telegram.constants import ChatAction, ParseMode, ChatType
from telegram.error import BadRequest, Forbidden, TimedOut, NetworkError, Conflict
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
        
        # Статистика по каналам/группам
        self.channel_stats = {}  # chat_id -> статистика канала
        self.tracked_groups = set()  # множество отслеживаемых групп
        
        # Глобальная статистика (сумма по всем каналам)
        self.global_stats = {
            'hourly_requests': 0,
            'hourly_left': 0,
            'daily_requests': 0,
            'daily_left': 0,
            'total_requests': 0,
            'total_approved': 0,
            'total_left': 0
        }
        
        # Загружаем сохраненную статистику
        self.load_stats_from_file()
        
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
        
        chat_title = request.chat.title or f"Чат {chat_id}"
        logger.info(f"Получена заявка от пользователя {request.from_user.first_name} ({user_id}) в чат '{chat_title}' ({chat_id}, тип: {chat_type})")
        
        # Проверяем тип чата
        if chat_type not in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
            logger.warning(f"Неподдерживаемый тип чата: {chat_type}")
            return
        
        # Обновляем статистику для конкретного канала
        self.get_or_create_channel_stats(chat_id, chat_title)
        self.update_channel_stats(chat_id, 'hourly_requests')
        self.update_channel_stats(chat_id, 'daily_requests')
        self.update_channel_stats(chat_id, 'total_requests')
        
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
            
            # Обновляем статистику одобренных для конкретного канала
            self.update_channel_stats(chat_id, 'total_approved')
            

            
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
            
            # Обновляем статистику покинувших для конкретного канала
            chat_title = update.effective_chat.title or f"Чат {chat_id}"
            self.get_or_create_channel_stats(chat_id, chat_title)
            self.update_channel_stats(chat_id, 'hourly_left')
            self.update_channel_stats(chat_id, 'daily_left')
            self.update_channel_stats(chat_id, 'total_left')
            
            logger.info(f"Пользователь {chat_member_update.new_chat_member.user.first_name} ({user_id}) покинул чат '{chat_title}' ({chat_type})")
    
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
    
    def get_or_create_channel_stats(self, chat_id: str, chat_title: str):
        """Создает или возвращает статистику для канала"""
        if chat_id not in self.channel_stats:
            self.channel_stats[chat_id] = {
                'title': chat_title,
                'hourly_requests': 0,
                'hourly_left': 0,
                'daily_requests': 0,
                'daily_left': 0,
                'total_requests': 0,
                'total_approved': 0,
                'total_left': 0,
                'last_activity': datetime.now()
            }
            logger.info(f"Создана статистика для канала '{chat_title}' ({chat_id})")
        return self.channel_stats[chat_id]
    
    def update_channel_stats(self, chat_id: str, stat_type: str):
        """Обновляет статистику канала"""
        if chat_id in self.channel_stats:
            self.channel_stats[chat_id][stat_type] += 1
            self.channel_stats[chat_id]['last_activity'] = datetime.now()
            
            # Обновляем глобальную статистику
            if stat_type in self.global_stats:
                self.global_stats[stat_type] += 1



    async def send_hourly_stats(self, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет почасовую статистику администраторам"""
        # Проверяем есть ли активность
        total_requests = sum(stats['hourly_requests'] for stats in self.channel_stats.values())
        total_left = sum(stats['hourly_left'] for stats in self.channel_stats.values())
        
        if total_requests == 0 and total_left == 0:
            return  # Не отправляем пустую статистику
        
        current_time = datetime.now().strftime("%H:%M")
        
        # Глобальная статистика
        global_message = (
            f"📊 Общая статистика за час ({current_time}):\n"
            f"📈 Новых заявок: {total_requests}\n"
            f"📉 Покинули: {total_left}\n"
            f"🔄 Чистый прирост: {total_requests - total_left}\n\n"
        )
        
        # Статистика по каналам
        channel_details = []
        for chat_id, stats in self.channel_stats.items():
            if stats['hourly_requests'] > 0 or stats['hourly_left'] > 0:
                channel_growth = stats['hourly_requests'] - stats['hourly_left']
                growth_emoji = "📈" if channel_growth > 0 else "📉" if channel_growth < 0 else "➖"
                
                channel_details.append(
                    f"🏷️ {stats['title'][:30]}:\n"
                    f"  � Заявок: {stats['hourly_requests']}\n"
                    f"  👋 Покинули: {stats['hourly_left']}\n"
                    f"  {growth_emoji} Прирост: {channel_growth}"
                )
        
        if channel_details:
            stats_message = global_message + "📋 По каналам:\n" + "\n\n".join(channel_details)
        else:
            stats_message = global_message.rstrip()
        
        await self.send_stats_to_admins(context, stats_message)
        
        # Сбрасываем почасовую статистику
        for stats in self.channel_stats.values():
            stats['hourly_requests'] = 0
            stats['hourly_left'] = 0
        self.global_stats['hourly_requests'] = 0
        self.global_stats['hourly_left'] = 0
    
    async def send_daily_stats(self, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет статистику за 8 часов администраторам"""
        current_time = datetime.now().strftime("%d.%m.%Y %H:%M")
        
        # Глобальная статистика за 8 часов
        total_daily_requests = sum(stats['daily_requests'] for stats in self.channel_stats.values())
        total_daily_left = sum(stats['daily_left'] for stats in self.channel_stats.values())
        total_approved = sum(stats['total_approved'] for stats in self.channel_stats.values())
        total_requests = sum(stats['total_requests'] for stats in self.channel_stats.values())
        total_left = sum(stats['total_left'] for stats in self.channel_stats.values())
        
        global_message = (
            f"📈 Общий отчет за 8 часов ({current_time}):\n\n"
            f"📝 Новых заявок: {total_daily_requests}\n"
            f"✅ Одобрено: {total_approved}\n"
            f"👋 Покинули: {total_daily_left}\n"
            f"🔄 Чистый прирост: {total_daily_requests - total_daily_left}\n\n"
            f"📊 Общая статистика с запуска:\n"
            f"📋 Всего заявок: {total_requests}\n"
            f"✅ Всего одобрено: {total_approved}\n"
            f"👋 Всего покинуло: {total_left}\n\n"
        )
        
        # Детальная статистика по каналам
        channel_details = []
        for chat_id, stats in self.channel_stats.items():
            if stats['total_requests'] > 0 or stats['total_left'] > 0:
                daily_growth = stats['daily_requests'] - stats['daily_left']
                total_growth = stats['total_requests'] - stats['total_left']
                
                daily_emoji = "📈" if daily_growth > 0 else "📉" if daily_growth < 0 else "➖"
                total_emoji = "📈" if total_growth > 0 else "📉" if total_growth < 0 else "➖"
                
                channel_details.append(
                    f"🏷️ {stats['title'][:35]}:\n"
                    f"  � За 8 часов: {stats['daily_requests']} заявок, {stats['daily_left']} покинули\n"
                    f"  {daily_emoji} Прирост за 8ч: {daily_growth}\n"
                    f"  📊 Всего: {stats['total_requests']} заявок, {stats['total_approved']} одобрено\n"
                    f"  {total_emoji} Общий прирост: {total_growth}"
                )
        
        if channel_details:
            stats_message = global_message + "📋 Детализация по каналам:\n\n" + "\n\n".join(channel_details)
        else:
            stats_message = global_message.rstrip()
        
        await self.send_stats_to_admins(context, stats_message)
        
        # Сбрасываем дневную статистику
        for stats in self.channel_stats.values():
            stats['daily_requests'] = 0
            stats['daily_left'] = 0
        self.global_stats['daily_requests'] = 0
        self.global_stats['daily_left'] = 0
    
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
    
    def save_stats_to_file(self):
        """Сохраняет статистику в файл"""
        try:
            stats_data = {
                'channel_stats': {},
                'global_stats': self.global_stats,
                'tracked_groups': list(self.tracked_groups),
                'last_saved': datetime.now().isoformat()
            }
            
            # Конвертируем datetime в строки для JSON
            for chat_id, stats in self.channel_stats.items():
                stats_copy = stats.copy()
                if 'last_activity' in stats_copy:
                    stats_copy['last_activity'] = stats_copy['last_activity'].isoformat()
                stats_data['channel_stats'][chat_id] = stats_copy
            
            with open('bot_stats.json', 'w', encoding='utf-8') as f:
                json.dump(stats_data, f, ensure_ascii=False, indent=2)
            
            logger.info("Статистика сохранена в файл")
        except Exception as e:
            logger.error(f"Ошибка при сохранении статистики: {e}")
    
    def load_stats_from_file(self):
        """Загружает статистику из файла"""
        try:
            with open('bot_stats.json', 'r', encoding='utf-8') as f:
                stats_data = json.load(f)
            
            # Загружаем данные
            self.global_stats = stats_data.get('global_stats', self.global_stats)
            self.tracked_groups = set(stats_data.get('tracked_groups', []))
            
            # Загружаем статистику каналов
            for chat_id, stats in stats_data.get('channel_stats', {}).items():
                if 'last_activity' in stats and isinstance(stats['last_activity'], str):
                    try:
                        stats['last_activity'] = datetime.fromisoformat(stats['last_activity'])
                    except:
                        stats['last_activity'] = datetime.now()
                self.channel_stats[chat_id] = stats
            
            logger.info(f"Загружена статистика для {len(self.channel_stats)} каналов")
        except FileNotFoundError:
            logger.info("Файл статистики не найден, начинаем с пустой статистики")
        except Exception as e:
            logger.error(f"Ошибка при загрузке статистики: {e}")
    
    async def periodic_save_stats(self, context: ContextTypes.DEFAULT_TYPE):
        """Периодически сохраняет статистику"""
        self.save_stats_to_file()

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
            
            # Периодическое сохранение статистики
            context.job_queue.run_repeating(
                self.periodic_save_stats,
                interval=3600,  # каждые 60 минут
                first=3600,     # первое сохранение через 60 минут
                name="save_stats"
            )
            
            logger.info("Настроены периодические задачи для статистики")
        else:
            logger.error("JobQueue не настроен для периодических задач!")

    async def handle_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает команду /stats для получения текущей статистики"""
        if not update.message:
            return
            
        user_id = update.effective_user.id
        
        # Проверяем, является ли пользователь администратором хотя бы одного канала
        is_admin = False
        for chat_id in self.tracked_groups:
            try:
                chat_admins = await context.bot.get_chat_administrators(int(chat_id))
                if any(admin.user.id == user_id and not admin.user.is_bot for admin in chat_admins):
                    is_admin = True
                    break
            except Exception:
                continue
        
        if not is_admin:
            await update.message.reply_text("❌ У вас нет прав для просмотра статистики")
            return
        
        # Формируем сообщение со статистикой
        current_time = datetime.now().strftime("%d.%m.%Y %H:%M")
        
        if not self.channel_stats:
            await update.message.reply_text("📊 Статистика пуста - бот еще не обрабатывал заявки")
            return
        
        # Общая статистика
        total_requests = sum(stats['total_requests'] for stats in self.channel_stats.values())
        total_approved = sum(stats['total_approved'] for stats in self.channel_stats.values())
        total_left = sum(stats['total_left'] for stats in self.channel_stats.values())
        
        message = (
            f"📊 Текущая статистика ({current_time}):\n\n"
            f"🌐 ОБЩАЯ СТАТИСТИКА:\n"
            f"📋 Всего заявок: {total_requests}\n"
            f"✅ Одобрено: {total_approved}\n"
            f"👋 Покинули: {total_left}\n"
            f"🔄 Общий прирост: {total_requests - total_left}\n\n"
        )
        
        # Статистика по каналам
        active_channels = [(chat_id, stats) for chat_id, stats in self.channel_stats.items() 
                          if stats['total_requests'] > 0 or stats['total_left'] > 0]
        
        if active_channels:
            message += "📋 ПО КАНАЛАМ:\n"
            for i, (chat_id, stats) in enumerate(active_channels, 1):
                growth = stats['total_requests'] - stats['total_left']
                growth_emoji = "📈" if growth > 0 else "📉" if growth < 0 else "➖"
                
                message += (
                    f"\n{i}. 🏷️ {stats['title'][:30]}:\n"
                    f"   📥 Заявок: {stats['total_requests']}\n"
                    f"   ✅ Одобрено: {stats['total_approved']}\n"
                    f"   👋 Покинули: {stats['total_left']}\n"
                    f"   {growth_emoji} Прирост: {growth}\n"
                )
        
        try:
            await update.message.reply_text(message)
        except Exception as e:
            logger.error(f"Ошибка при отправке статистики: {e}")
            await update.message.reply_text("❌ Ошибка при получении статистики")

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
        application.add_handler(CommandHandler("stats", self.handle_stats_command))
        application.add_handler(ChatJoinRequestHandler(self.handle_chat_join_request))
        application.add_handler(ChatMemberHandler(self.handle_chat_member_update))
        
        # Настраиваем периодические задачи для статистики
        application.job_queue.run_once(
            self.setup_periodic_tasks,
            0  # Запускаем сразу
        )
        
        # Настраиваем graceful shutdown
        def signal_handler(signum, frame):
            logger.info("Получен сигнал завершения, сохраняем статистику...")
            self.save_stats_to_file()
            logger.info("Останавливаем бота...")
            application.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        logger.info("Бот запущен и готов к работе!")
        logger.info(f"Отслеживаемые типы обновлений: заявки на вступление, изменения участников")
        
        # Определяем режим работы
        is_production = os.getenv('RENDER') == 'true' or os.getenv('PRODUCTION') == 'true'
        
        if is_production:
            # В production используем webhook
            self.run_webhook(application)
        else:
            # В development используем polling
            self.run_polling(application)
    
    def run_webhook(self, application):
        """Запуск через webhook (для production)"""
        webhook_url = os.getenv('WEBHOOK_URL')
        port = int(os.getenv('PORT', 8000))
        
        if not webhook_url:
            logger.error("❌ WEBHOOK_URL не установлен для production режима!")
            logger.error("💡 Установите переменную WEBHOOK_URL в настройках Render")
            return
        
        # Формируем полный URL для webhook
        webhook_path = f"/{self.token}"
        full_webhook_url = f"{webhook_url.rstrip('/')}{webhook_path}"
        
        logger.info(f"🌐 Запуск бота в webhook режиме")
        logger.info(f"🔗 Webhook URL: {full_webhook_url}")
        logger.info(f"🔌 Port: {port}")
        
        try:
            application.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path=webhook_path,
                webhook_url=full_webhook_url,
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
        except Exception as e:
            logger.error(f"💥 Ошибка webhook: {e}")
            raise
    
    def run_polling(self, application):
        """Запуск через polling (для development)"""
        logger.info("🔄 Запуск бота в polling режиме (для разработки)")
        
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                application.run_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True  # Игнорируем старые обновления при перезапуске
                )
                break  # Если polling запустился успешно, выходим из цикла
                
            except Conflict as e:
                retry_count += 1
                logger.error(f"⚠️ Конфликт polling (попытка {retry_count}/{max_retries}): {e}")
                
                if retry_count < max_retries:
                    logger.info(f"⏳ Ожидание {retry_count * 5} секунд перед повторной попыткой...")
                    asyncio.run(asyncio.sleep(retry_count * 5))
                else:
                    logger.error("❌ Не удалось запустить polling после всех попыток!")
                    logger.error("💡 Возможные причины:")
                    logger.error("   - Бот уже запущен в другом месте (локально или на Render)")
                    logger.error("   - Используйте webhook для production или остановите другие экземпляры")
                    raise
                    
            except (TimedOut, NetworkError) as e:
                retry_count += 1
                logger.error(f"🌐 Сетевая ошибка (попытка {retry_count}/{max_retries}): {e}")
                
                if retry_count < max_retries:
                    logger.info(f"⏳ Ожидание {retry_count * 3} секунд перед повторной попыткой...")
                    asyncio.run(asyncio.sleep(retry_count * 3))
                else:
                    logger.error("❌ Не удалось подключиться после всех попыток!")
                    raise
                    
            except Exception as e:
                logger.error(f"💥 Критическая ошибка при запуске бота: {e}")
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
