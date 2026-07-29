import asyncio
import json
import logging
import requests
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, LabeledPrice
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, PreCheckoutQueryHandler, JobQueue
from telegram.error import TelegramError

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8831108095:AAHggP-ctbO3G4iQ7G_ewecFPzBtZFG6yX0"  # Токен бота от @BotFather
OPENROUTER_API_KEY = "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"  # API ключ OpenRouter
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "inclusionai/ling-3.0-flash:free"

BOT_NAME = "Stalkow AI"
SUPPORT_USERNAME = "@stalkow"
CHANNEL_USERNAME = "@stalkowAiinfo"  # Ваш канал
CHANNEL_ID = "@stalkowAiinfo"  # ID канала для проверки

# Тарифы
FREE_REQUESTS_PER_DAY = 10
PREMIUM_REQUESTS_PER_DAY = 20

# Цены в Telegram Stars
PRICE_MONTH = 5  # 5 Stars за месяц
PRICE_YEAR = 40  # 40 Stars за год (скидка 33%)

# Скидки
DISCOUNT_MONTH = 3  # Цена со скидкой
DISCOUNT_YEAR = 25  # Цена со скидкой
DISCOUNT_ACTIVE = False  # Скидка активна

# Сообщения бота
MESSAGES = [
    "💭 *Stalkow ждёт тебя, пока ты ответишь!*\nНе заставляй меня скучать... 🥺",
    "🌟 *Stalkow скучно без тебя!*\nВозвращайся скорее, я тут один... 💫",
    "🎭 *Эй, ты где?*\nStalkow уже заждался твоего сообщения! ✨",
    "💎 *Тук-тук!*\nЭто Stalkow! Может поболтаем? 🚀",
    "🌙 *Даже звёзды спрашивают о тебе...*\nStalkow тоже хочет знать, как ты! 💫",
    "🎪 *Я тут приготовил кое-что интересное!*\nStalkow всегда рад тебе! 🌟",
    "💫 *Знаешь что?*\nStalkow ценит каждый момент с тобой! ✨",
    "🦋 *Тишина...*\nНарушь её! Stalkow ждёт твоего сообщения! 💭"
]

# ==================== КЛАСС БОТА ====================
class StalkowAI:
    def __init__(self):
        self.conversations = {}
        self.user_settings = {}
        self.user_requests = {}
        self.premium_users = {}
        self.last_message_time = {}  # Время последнего сообщения
        self.notifications_enabled = {}  # Уведомления вкл/выкл
        
    def get_conversation(self, user_id: int):
        if user_id not in self.conversations:
            self.conversations[user_id] = []
        return self.conversations[user_id]
    
    def clear_conversation(self, user_id: int):
        if user_id in self.conversations:
            self.conversations[user_id] = []
    
    def get_user_settings(self, user_id: int):
        if user_id not in self.user_settings:
            self.user_settings[user_id] = {
                "reasoning_enabled": False,
                "notifications_enabled": True  # По умолчанию включены
            }
        return self.user_settings[user_id]
    
    def toggle_reasoning(self, user_id: int):
        settings = self.get_user_settings(user_id)
        settings["reasoning_enabled"] = not settings["reasoning_enabled"]
        return settings["reasoning_enabled"]
    
    def toggle_notifications(self, user_id: int):
        settings = self.get_user_settings(user_id)
        settings["notifications_enabled"] = not settings["notifications_enabled"]
        return settings["notifications_enabled"]
    
    def is_premium(self, user_id: int):
        if user_id in self.premium_users:
            expiry = self.premium_users[user_id]
            if datetime.now() < expiry:
                return True
            else:
                del self.premium_users[user_id]
        return False
    
    def add_premium(self, user_id: int, months: int = 1):
        if self.is_premium(user_id):
            current_expiry = self.premium_users[user_id]
            new_expiry = current_expiry + timedelta(days=30 * months)
        else:
            new_expiry = datetime.now() + timedelta(days=30 * months)
        self.premium_users[user_id] = new_expiry
        return new_expiry
    
    def get_remaining_requests(self, user_id: int):
        today = datetime.now().date()
        if user_id not in self.user_requests:
            self.user_requests[user_id] = {"date": today, "count": 0}
        user_data = self.user_requests[user_id]
        if user_data["date"] != today:
            user_data["date"] = today
            user_data["count"] = 0
        max_requests = PREMIUM_REQUESTS_PER_DAY if self.is_premium(user_id) else FREE_REQUESTS_PER_DAY
        remaining = max_requests - user_data["count"]
        return max(0, remaining)
    
    def increment_request(self, user_id: int):
        today = datetime.now().date()
        if user_id not in self.user_requests:
            self.user_requests[user_id] = {"date": today, "count": 0}
        user_data = self.user_requests[user_id]
        if user_data["date"] != today:
            user_data["date"] = today
            user_data["count"] = 0
        user_data["count"] += 1
    
    def update_last_message(self, user_id: int):
        self.last_message_time[user_id] = datetime.now()
    
    async def call_openrouter(self, messages, reasoning_enabled=False):
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {"model": MODEL, "messages": messages}
        if reasoning_enabled:
            payload["reasoning"] = {"enabled": True}
        try:
            response = await asyncio.to_thread(
                requests.post, url=OPENROUTER_URL, headers=headers,
                data=json.dumps(payload), timeout=30
            )
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"API Error: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Request error: {e}")
            return None

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard(user_id: int, stalkow_bot: StalkowAI):
    settings = stalkow_bot.get_user_settings(user_id)
    is_premium = stalkow_bot.is_premium(user_id)
    remaining = stalkow_bot.get_remaining_requests(user_id)
    
    premium_status = "💎 Премиум" if is_premium else "⭐ Купить Premium"
    reasoning_status = "🧠 Размышления: ВКЛ" if settings["reasoning_enabled"] else "🧠 Размышления: ВЫКЛ"
    notif_status = "🔔 Уведомления: ВКЛ" if settings["notifications_enabled"] else "🔕 Уведомления: ВЫКЛ"
    
    keyboard = [
        [KeyboardButton(reasoning_status)],
        [KeyboardButton(f"📊 Лимиты: {remaining}"), KeyboardButton(premium_status)],
        [KeyboardButton(notif_status)],
        [KeyboardButton("👤 Поддержка"), KeyboardButton("ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_premium_keyboard():
    if DISCOUNT_ACTIVE:
        keyboard = [
            [InlineKeyboardButton(f"🔥 Месяц - {DISCOUNT_MONTH} ⭐ (СКИДКА!)", callback_data="buy_month")],
            [InlineKeyboardButton(f"🔥 Год - {DISCOUNT_YEAR} ⭐ (СКИДКА!)", callback_data="buy_year")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_buy")]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton(f"💎 Месяц - {PRICE_MONTH} ⭐", callback_data="buy_month"),
             InlineKeyboardButton(f"💎 Год - {PRICE_YEAR} ⭐", callback_data="buy_year")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_buy")]
        ]
    return InlineKeyboardMarkup(keyboard)

def get_notification_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔕 Выключить уведомления (1 ⭐)", callback_data="disable_notifications")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_notifications")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверка подписки на канал"""
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except TelegramError:
        return False

async def require_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка подписки и показ сообщения"""
    user_id = update.effective_user.id
    
    if await check_subscription(user_id, context):
        return True
    
    # Сообщение о необходимости подписки
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
        [InlineKeyboardButton("✅ Я подписался", callback_data="check_subscription")]
    ])
    
    await update.message.reply_text(
        f"🔒 *Доступ ограничен*\n\n"
        f"Для использования {BOT_NAME} необходимо подписаться на канал:\n"
        f"{CHANNEL_USERNAME}\n\n"
        f"После подписки нажмите кнопку ниже 👇",
        parse_mode='Markdown',
        reply_markup=keyboard
    )
    return False

# ==================== СИСТЕМА УВЕДОМЛЕНИЙ ====================
async def send_random_message(context: ContextTypes.DEFAULT_TYPE):
    """Отправка случайных сообщений пользователям"""
    stalkow_bot = context.bot_data['stalkow_bot']
    
    for user_id in stalkow_bot.last_message_time:
        settings = stalkow_bot.get_user_settings(user_id)
        
        # Проверяем, включены ли уведомления
        if not settings["notifications_enabled"]:
            continue
        
        # Проверяем, когда было последнее сообщение
        last_time = stalkow_bot.last_message_time.get(user_id)
        if last_time:
            time_diff = datetime.now() - last_time
            # Отправляем если прошло больше 1 часа
            if time_diff > timedelta(hours=1) and time_diff < timedelta(hours=3):
                try:
                    message = random.choice(MESSAGES)
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode='Markdown'
                    )
                except:
                    pass

async def send_discount_notification(context: ContextTypes.DEFAULT_TYPE):
    """Отправка уведомлений о скидках"""
    global DISCOUNT_ACTIVE
    
    # Случайно включаем/выключаем скидки
    if random.random() < 0.3:  # 30% шанс
        DISCOUNT_ACTIVE = not DISCOUNT_ACTIVE
        
        stalkow_bot = context.bot_data['stalkow_bot']
        
        if DISCOUNT_ACTIVE:
            message = (
                "🎉 *ГОРЯЧАЯ СКИДКА!*\n\n"
                f"Только сейчас:\n"
                f"🔥 Premium месяц: {DISCOUNT_MONTH} ⭐ (вместо {PRICE_MONTH})\n"
                f"🔥 Premium год: {DISCOUNT_YEAR} ⭐ (вместо {PRICE_YEAR})\n\n"
                f"Экономия до 40%! Успей купить! 💫"
            )
        else:
            message = "💫 Скидки закончились, но не расстраивайся! Скоро будут новые!"
        
        # Отправляем всем пользователям
        for user_id in stalkow_bot.last_message_time:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode='Markdown'
                )
            except:
                pass

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    
    # Проверяем подписку
    if not await check_subscription(user_id, context):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
            [InlineKeyboardButton("✅ Я подписался", callback_data="check_subscription")]
        ])
        
        await update.message.reply_text(
            f"🌟 *Добро пожаловать в {BOT_NAME}!*\n\n"
            f"🔒 Для начала работы подпишитесь на наш канал:\n"
            f"{CHANNEL_USERNAME}\n\n"
            f"После подписки нажмите кнопку ниже 👇",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return
    
    stalkow_bot = context.bot_data['stalkow_bot']
    stalkow_bot.update_last_message(user_id)
    
    is_premium = stalkow_bot.is_premium(user_id)
    remaining = stalkow_bot.get_remaining_requests(user_id)
    settings = stalkow_bot.get_user_settings(user_id)
    
    welcome_message = (
        f"✨ *Добро пожаловать в {BOT_NAME}!*\n\n"
        f"🎭 *Тариф:* {'💎 Премиум' if is_premium else '🆓 Бесплатный'}\n"
        f"📝 *Запросов:* {remaining}\n"
        f"🧠 *Размышления:* {'ВКЛ' if settings['reasoning_enabled'] else 'ВЫКЛ'}\n"
        f"🔔 *Уведомления:* {'ВКЛ' if settings['notifications_enabled'] else 'ВЫКЛ'}\n\n"
        f"💫 Бесплатно: {FREE_REQUESTS_PER_DAY} запросов/день\n"
        f"💎 Premium: {PREMIUM_REQUESTS_PER_DAY} запросов/день"
    )
    
    if DISCOUNT_ACTIVE:
        welcome_message += f"\n\n🔥 *СКИДКИ АКТИВНЫ!*\nМесяц: {DISCOUNT_MONTH}⭐ | Год: {DISCOUNT_YEAR}⭐"
    
    await update.message.reply_text(
        welcome_message,
        parse_mode='Markdown',
        reply_markup=get_main_keyboard(user_id, stalkow_bot)
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback-запросов"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    stalkow_bot = context.bot_data['stalkow_bot']
    
    if query.data == "check_subscription":
        if await check_subscription(user_id, context):
            await query.message.delete()
            await start(update, context)
        else:
            await query.answer("❌ Вы ещё не подписались на канал!", show_alert=True)
    
    elif query.data == "buy_month":
        price = DISCOUNT_MONTH if DISCOUNT_ACTIVE else PRICE_MONTH
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=f"Stalkow AI Premium - Месяц",
            description=f"Премиум на 1 месяц\n{PREMIUM_REQUESTS_PER_DAY} запросов/день\nРазмышления безлимитно",
            payload="premium_month",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(f"Premium Месяц{' (СКИДКА)' if DISCOUNT_ACTIVE else ''}", price)]
        )
    
    elif query.data == "buy_year":
        price = DISCOUNT_YEAR if DISCOUNT_ACTIVE else PRICE_YEAR
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=f"Stalkow AI Premium - Год",
            description=f"Премиум на 12 месяцев\n{PREMIUM_REQUESTS_PER_DAY} запросов/день\nЭкономия 20 ⭐",
            payload="premium_year",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(f"Premium Год{' (СКИДКА)' if DISCOUNT_ACTIVE else ''}", price)]
        )
    
    elif query.data == "cancel_buy":
        await query.message.edit_text("💫 Будем ждать тебя снова!")
    
    elif query.data == "disable_notifications":
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title="Stalkow AI - Отключение уведомлений",
            description="Отключение случайных сообщений от бота",
            payload="disable_notifications",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice("Отключить уведомления", 1)]
        )
    
    elif query.data == "cancel_notifications":
        await query.message.edit_text("👌 Уведомления остаются включенными!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    user_message = update.message.text
    
    # Проверка подписки
    if not await check_subscription(user_id, context):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
            [InlineKeyboardButton("✅ Я подписался", callback_data="check_subscription")]
        ])
        
        await update.message.reply_text(
            f"🔒 *Доступ ограничен*\n\n"
            f"Подпишитесь на {CHANNEL_USERNAME} чтобы использовать бота!\n"
            f"После подписки нажмите кнопку ниже 👇",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return
    
    stalkow_bot = context.bot_data['stalkow_bot']
    stalkow_bot.update_last_message(user_id)
    settings = stalkow_bot.get_user_settings(user_id)
    
    # Обработка кнопок клавиатуры
    if user_message.startswith("🧠 Размышления:"):
        is_enabled = stalkow_bot.toggle_reasoning(user_id)
        status = "ВКЛ" if is_enabled else "ВЫКЛ"
        await update.message.reply_text(
            f"🧠 *Размышления {status}!*\n\n"
            f"{'🌟 Бот будет показывать процесс размышлений.' if is_enabled else '💫 Бот отвечает без размышлений.'}",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
        return
    
    elif user_message.startswith("📊 Лимиты:"):
        remaining = stalkow_bot.get_remaining_requests(user_id)
        is_premium = stalkow_bot.is_premium(user_id)
        max_requests = PREMIUM_REQUESTS_PER_DAY if is_premium else FREE_REQUESTS_PER_DAY
        
        await update.message.reply_text(
            f"📊 *Статистика запросов*\n\n"
            f"💎 *Тариф:* {'Премиум' if is_premium else 'Бесплатный'}\n"
            f"📝 *Использовано:* {max_requests - remaining}/{max_requests}\n"
            f"✅ *Осталось:* {remaining}\n\n"
            f"_Сброс каждый день в 00:00_",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
        return
    
    elif "Купить Premium" in user_message:
        await update.message.reply_text(
            f"💎 *Premium доступ*\n\n"
            f"Выберите тариф:\n\n"
            f"{'🔥 СКИДКИ АКТИВНЫ! 🔥' if DISCOUNT_ACTIVE else '💫 Стандартные цены'}\n\n"
            f"📅 Месяц: {DISCOUNT_MONTH if DISCOUNT_ACTIVE else PRICE_MONTH} ⭐\n"
            f"📅 Год: {DISCOUNT_YEAR if DISCOUNT_ACTIVE else PRICE_YEAR} ⭐\n\n"
            f"✨ *Преимущества Premium:*\n"
            f"• {PREMIUM_REQUESTS_PER_DAY} запросов/день\n"
            f"• Размышления без ограничений\n"
            f"• Приоритетная поддержка",
            parse_mode='Markdown',
            reply_markup=get_premium_keyboard()
        )
        return
    
    elif user_message == "💎 Премиум":
        is_premium = stalkow_bot.is_premium(user_id)
        if is_premium:
            expiry = stalkow_bot.premium_users[user_id]
            days_left = (expiry - datetime.now()).days
            await update.message.reply_text(
                f"💎 *Премиум активен!*\n\n"
                f"📅 *Дней осталось:* {days_left}\n"
                f"📝 *Лимит:* {PREMIUM_REQUESTS_PER_DAY} запросов/день\n"
                f"🧠 *Размышления:* Доступны\n\n"
                f"🌟 Спасибо за поддержку! Ты лучший! 🎉",
                parse_mode='Markdown',
                reply_markup=get_main_keyboard(user_id, stalkow_bot)
            )
        else:
            await update.message.reply_text(
                f"💎 *Premium доступ*\n\n"
                f"Выберите тариф:",
                parse_mode='Markdown',
                reply_markup=get_premium_keyboard()
            )
        return
    
    elif user_message.startswith("🔔 Уведомления:") or user_message.startswith("🔕 Уведомления:"):
        if settings["notifications_enabled"]:
            await update.message.reply_text(
                f"🔕 *Отключить уведомления?*\n\n"
                f"Стоимость: 1 ⭐\n"
                f"После отключения бот не будет присылать случайные сообщения.",
                parse_mode='Markdown',
                reply_markup=get_notification_keyboard()
            )
        else:
            await update.message.reply_text(
                f"🔔 *Уведомления уже выключены*\n\n"
                f"Хотите включить обратно? Напишите в поддержку: {SUPPORT_USERNAME}",
                parse_mode='Markdown',
                reply_markup=get_main_keyboard(user_id, stalkow_bot)
            )
        return
    
    elif user_message == "👤 Поддержка":
        await update.message.reply_text(
            f"👤 *Поддержка {BOT_NAME}*\n\n"
            f"📢 Канал: {CHANNEL_USERNAME}\n"
            f"💬 Поддержка: {SUPPORT_USERNAME}\n\n"
            f"💡 *Частые вопросы:*\n"
            f"• Как купить Premium?\n"
            f"• Как работают размышления?\n"
            f"• Как отключить уведомления?\n\n"
            f"⏰ Время ответа: до 24 часов",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
        return
    
    elif user_message == "ℹ️ Помощь":
        await update.message.reply_text(
            f"ℹ️ *Помощь {BOT_NAME}*\n\n"
            f"🆓 *Бесплатный тариф:*\n"
            f"• {FREE_REQUESTS_PER_DAY} запросов/день\n"
            f"• Базовые ответы\n"
            f"• Размышления\n\n"
            f"💎 *Премиум тариф:*\n"
            f"• {PREMIUM_REQUESTS_PER_DAY} запросов/день\n"
            f"• Расширенные возможности\n"
            f"• Приоритет\n\n"
            f"💳 *Цены:*\n"
            f"• Месяц: {PRICE_MONTH} ⭐\n"
            f"• Год: {PRICE_YEAR} ⭐\n\n"
            f"🔥 *Скидки появляются случайно!*",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
        return
    
    # Проверка лимита запросов
    remaining = stalkow_bot.get_remaining_requests(user_id)
    if remaining <= 0:
        await update.message.reply_text(
            f"⚠️ *Лимит исчерпан!*\n\n"
            f"Вы использовали все запросы на сегодня.\n\n"
            f"💎 *Premium:* {PREMIUM_REQUESTS_PER_DAY} запросов/день\n"
            f"💳 Купите Premium для продолжения!\n\n"
            f"🔄 Лимит обновится завтра в 00:00",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
        return
    
    # Обработка запроса
    conversation = stalkow_bot.get_conversation(user_id)
    conversation.append({"role": "user", "content": user_message})
    stalkow_bot.increment_request(user_id)
    
    await update.message.chat.send_action(action="typing")
    
    try:
        response_data = await stalkow_bot.call_openrouter(conversation, settings['reasoning_enabled'])
        if response_data and 'choices' in response_data:
            content = response_data['choices'][0]['message'].get('content', '')
            reasoning_details = response_data['choices'][0]['message'].get('reasoning_details', None)
            conversation.append({"role": "assistant", "content": content})
            
            if settings['reasoning_enabled'] and reasoning_details:
                reasoning_text = reasoning_details[:800] if len(reasoning_details) > 800 else reasoning_details
                response_text = f"💭 *Размышления Stalkow:*\n||{reasoning_text}||\n\n📝 *Ответ:*\n{content}"
            else:
                response_text = f"✨ *{BOT_NAME}:*\n{content}"
            
            new_remaining = stalkow_bot.get_remaining_requests(user_id)
            response_text += f"\n\n📝 _Осталось запросов: {new_remaining}_"
            
            if DISCOUNT_ACTIVE:
                response_text += f"\n🔥 _Действуют скидки на Premium!_"
            
            keyboard = get_main_keyboard(user_id, stalkow_bot)
            
            if len(response_text) > 4000:
                parts = [response_text[i:i+4000] for i in range(0, len(response_text), 4000)]
                for i, part in enumerate(parts):
                    if i == len(parts) - 1:
                        await update.message.reply_text(part, parse_mode='Markdown', reply_markup=keyboard)
                    else:
                        await update.message.reply_text(part, parse_mode='Markdown')
            else:
                await update.message.reply_text(response_text, parse_mode='Markdown', reply_markup=keyboard)
        else:
            await update.message.reply_text(
                "❌ *Ошибка получения ответа*\nПопробуйте еще раз.",
                parse_mode='Markdown',
                reply_markup=get_main_keyboard(user_id, stalkow_bot)
            )
            conversation.pop()
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(
            "❌ *Произошла ошибка*\nПопробуйте позже.",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
        conversation.pop()

async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик предварительной проверки платежа"""
    query = update.pre_checkout_query
    if query.invoice_payload in ["premium_month", "premium_year", "disable_notifications"]:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Ошибка платежа")

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик успешной оплаты"""
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    stalkow_bot = context.bot_data['stalkow_bot']
    
    if payment.invoice_payload == "premium_month":
        expiry = stalkow_bot.add_premium(user_id, months=1)
        await update.message.reply_text(
            f"🎉 *Оплата успешна!*\n\n"
            f"💎 Premium активирован на 1 месяц\n"
            f"📅 Действует до: {expiry.strftime('%d.%m.%Y')}\n"
            f"📝 Лимит: {PREMIUM_REQUESTS_PER_DAY} запросов/день\n\n"
            f"🌟 Добро пожаловать в Premium! Наслаждайся!",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
    
    elif payment.invoice_payload == "premium_year":
        expiry = stalkow_bot.add_premium(user_id, months=12)
        await update.message.reply_text(
            f"🎉 *Оплата успешна!*\n\n"
            f"💎 Premium активирован на 12 месяцев\n"
            f"📅 Действует до: {expiry.strftime('%d.%m.%Y')}\n"
            f"📝 Лимит: {PREMIUM_REQUESTS_PER_DAY} запросов/день\n"
            f"🔥 Экономия 20 ⭐!\n\n"
            f"🌟 Ты просто легенда! Спасибо за доверие!",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
    
    elif payment.invoice_payload == "disable_notifications":
        stalkow_bot.toggle_notifications(user_id)
        await update.message.reply_text(
            f"🔕 *Уведомления отключены!*\n\n"
            f"Бот больше не будет присылать случайные сообщения.\n"
            f"Но скидки всё ещё будут приходить! 💫",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )

# ==================== ЗАПУСК БОТА ====================
def main():
    print(f"""
╔══════════════════════════════════════╗
║       🤖 {BOT_NAME} Premium        ║
║       Telegram Stars Payments        ║
╚══════════════════════════════════════╝
    """)
    
    if TELEGRAM_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("❌ Укажите TELEGRAM_TOKEN!")
        return
    if OPENROUTER_API_KEY == "YOUR_OPENROUTER_API_KEY":
        print("❌ Укажите OPENROUTER_API_KEY!")
        return
    
    stalkow_bot = StalkowAI()
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.bot_data['stalkow_bot'] = stalkow_bot
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    
    # Обработчики платежей
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    
    # Обработчик callback-запросов
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Обработчик сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем JobQueue для уведомлений
    job_queue = application.job_queue
    
    # Случайные сообщения каждые 30 минут
    job_queue.run_repeating(send_random_message, interval=1800, first=10)
    
    # Проверка скидок каждый час
    job_queue.run_repeating(send_discount_notification, interval=3600, first=60)
    
    print(f"""
✅ {BOT_NAME} успешно запущен!
📊 Бесплатный лимит: {FREE_REQUESTS_PER_DAY} запросов/день
💎 Premium лимит: {PREMIUM_REQUESTS_PER_DAY} запросов/день
💳 Цены: Месяц={PRICE_MONTH}⭐ | Год={PRICE_YEAR}⭐
🔥 Скидки: Месяц={DISCOUNT_MONTH}⭐ | Год={DISCOUNT_YEAR}⭐
📢 Канал: {CHANNEL_USERNAME}
🔔 Уведомления: включены
🎭 Случайные сообщения: активны
    """)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
