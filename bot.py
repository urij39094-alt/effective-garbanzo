import asyncio
import json
import logging
import requests
import traceback
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_TOKEN = ""8831108095:AAHggP-ctbO3G4iQ7G_ewecFPzBtZFG6yX0
OPENROUTER_API_KEY = "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"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "inclusionai/ling-3.0-flash:free"
BOT_NAME = "Stalkow AI"
SUPPORT_USERNAME = "@stalkow"

# Тарифы
FREE_REQUESTS_PER_DAY = 10
PREMIUM_REQUESTS_PER_DAY = 20

# Цены в Telegram Stars
PRICE_MONTH = 5  # 5 Stars за месяц
PRICE_YEAR = PRICE_MONTH * 12  # 60 Stars за год (без скидки)
PRICE_YEAR_WITH_DISCOUNT = int(PRICE_YEAR * 0.67)  # 40 Stars за год (скидка 33%)

class StalkowAI:
    def __init__(self):
        self.conversations = {}
        self.user_settings = {}
        self.user_requests = {}
        self.premium_users = {}
        
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
                "reasoning_enabled": False
            }
        return self.user_settings[user_id]
    
    def toggle_reasoning(self, user_id: int):
        settings = self.get_user_settings(user_id)
        settings["reasoning_enabled"] = not settings["reasoning_enabled"]
        return settings["reasoning_enabled"]
    
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
    
    async def call_openrouter(self, messages, reasoning_enabled=False):
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": MODEL,
            "messages": messages
        }
        
        if reasoning_enabled:
            payload["reasoning"] = {"enabled": True}
        
        try:
            response = await asyncio.to_thread(
                requests.post,
                url=OPENROUTER_URL,
                headers=headers,
                data=json.dumps(payload),
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"API Error: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Request error: {e}")
            return None

def get_main_keyboard(user_id: int, stalkow_bot: StalkowAI):
    settings = stalkow_bot.get_user_settings(user_id)
    is_premium = stalkow_bot.is_premium(user_id)
    remaining = stalkow_bot.get_remaining_requests(user_id)
    
    premium_status = "💎 Премиум" if is_premium else "⭐ Купить Premium"
    reasoning_status = "🧠 Размышления: ВКЛ" if settings["reasoning_enabled"] else "🧠 Размышления: ВЫКЛ"
    
    keyboard = [
        [KeyboardButton(reasoning_status)],
        [KeyboardButton(f"📊 Лимиты: {remaining}"), KeyboardButton(premium_status)],
        [KeyboardButton("👤 Поддержка"), KeyboardButton("ℹ️ Помощь")]
    ]
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_premium_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("💎 Месяц - 5 ⭐", callback_data="buy_month"),
            InlineKeyboardButton("💎 Год - 40 ⭐", callback_data="buy_year")
        ],
        [
            InlineKeyboardButton("💰 Экономия 20 ⭐ (33%)", callback_data="info_discount")
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_buy")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stalkow_bot = context.bot_data['stalkow_bot']
    is_premium = stalkow_bot.is_premium(user_id)
    remaining = stalkow_bot.get_remaining_requests(user_id)
    settings = stalkow_bot.get_user_settings(user_id)
    
    welcome_message = (
        f"👋 Добро пожаловать в {BOT_NAME}!\n\n"
        f"📊 *Ваш тариф:* {'💎 Премиум' if is_premium else '🆓 Бесплатный'}\n"
        f"📝 *Осталось запросов:* {remaining}\n"
        f"🧠 *Размышления:* {'ВКЛ' if settings['reasoning_enabled'] else 'ВЫКЛ'}\n\n"
        f"💡 *Бесплатный тариф:* {FREE_REQUESTS_PER_DAY} запросов/день\n"
        f"💎 *Премиум тариф:* {PREMIUM_REQUESTS_PER_DAY} запросов/день\n\n"
        "Используйте кнопки для управления:"
    )
    
    keyboard = get_main_keyboard(user_id, stalkow_bot)
    
    await update.message.reply_text(
        welcome_message,
        parse_mode='Markdown',
        reply_markup=keyboard
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    
    stalkow_bot = context.bot_data['stalkow_bot']
    settings = stalkow_bot.get_user_settings(user_id)
    
    # Обработка кнопок клавиатуры
    if user_message.startswith("🧠 Размышления:"):
        is_enabled = stalkow_bot.toggle_reasoning(user_id)
        status = "ВКЛ" if is_enabled else "ВЫКЛ"
        await update.message.reply_text(
            f"🧠 Размышления {status}!\n\n"
            f"{'Бот будет показывать процесс размышлений.' if is_enabled else 'Бот будет отвечать без размышлений.'}",
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
        return
    
    elif user_message.startswith("📊 Лимиты:"):
        remaining = stalkow_bot.get_remaining_requests(user_id)
        is_premium = stalkow_bot.is_premium(user_id)
        max_requests = PREMIUM_REQUESTS_PER_DAY if is_premium else FREE_REQUESTS_PER_DAY
        
        await update.message.reply_text(
            f"📊 *Лимиты запросов*\n\n"
            f"💎 *Тариф:* {'Премиум' if is_premium else 'Бесплатный'}\n"
            f"📝 *Использовано:* {max_requests - remaining}/{max_requests}\n"
            f"✅ *Осталось:* {remaining}\n\n"
            f"_Лимит обновляется каждый день в 00:00_",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
        return
    
    elif user_message.startswith("⭐ Купить Premium"):
        await show_premium_options(update, stalkow_bot, user_id)
        return
    
    elif user_message == "💎 Премиум":
        is_premium = stalkow_bot.is_premium(user_id)
        if is_premium:
            expiry = stalkow_bot.premium_users[user_id]
            days_left = (expiry - datetime.now()).days
            await update.message.reply_text(
                f"💎 *Премиум активен!*\n\n"
                f"📅 *Дней осталось:* {days_left}\n"
                f"📝 *Лимит:* {PREMIUM_REQUESTS_PER_DAY} запросов/день\n\n"
                f"Спасибо за поддержку! 🎉",
                parse_mode='Markdown',
                reply_markup=get_main_keyboard(user_id, stalkow_bot)
            )
        else:
            await show_premium_options(update, stalkow_bot, user_id)
        return
    
    elif user_message == "👤 Поддержка":
        await update.message.reply_text(
            f"👤 *Поддержка {BOT_NAME}*\n\n"
            f"По всем вопросам обращайтесь:\n"
            f"{SUPPORT_USERNAME}\n\n"
            f"💡 *Частые вопросы:*\n"
            f"• Как купить Premium?\n"
            f"• Как работают размышления?\n"
            f"• Что делать при ошибках?",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
        return
    
    elif user_message == "ℹ️ Помощь":
        await update.message.reply_text(
            f"ℹ️ *Помощь {BOT_NAME}*\n\n"
            f"🆓 *Бесплатный тариф:*\n"
            f"• {FREE_REQUESTS_PER_DAY} запросов в день\n"
            f"• Базовые ответы\n"
            f"• Размышления\n\n"
            f"💎 *Премиум тариф:*\n"
            f"• {PREMIUM_REQUESTS_PER_DAY} запросов в день\n"
            f"• Все функции\n"
            f"• Приоритетная поддержка\n\n"
            f"💳 *Цены в Stars:*\n"
            f"• Месяц: {PRICE_MONTH} ⭐\n"
            f"• Год: {PRICE_YEAR_WITH_DISCOUNT} ⭐ (экономия {PRICE_YEAR - PRICE_YEAR_WITH_DISCOUNT} ⭐)",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
        return
    
    # Проверка лимита запросов
    remaining = stalkow_bot.get_remaining_requests(user_id)
    
    if remaining <= 0:
        await update.message.reply_text(
            "⚠️ *Лимит запросов исчерпан!*\n\n"
            f"Вы использовали все запросы на сегодня.\n"
            f"🆓 Бесплатный лимит: {FREE_REQUESTS_PER_DAY} запросов/день\n\n"
            f"💎 *Premium:* {PREMIUM_REQUESTS_PER_DAY} запросов/день\n"
            f"💳 Купите Premium для продолжения!\n\n"
            f"🔄 Лимит обновится завтра в 00:00",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
        return
    
    # Обработка обычного сообщения
    conversation = stalkow_bot.get_conversation(user_id)
    
    conversation.append({
        "role": "user",
        "content": user_message
    })
    
    stalkow_bot.increment_request(user_id)
    
    await update.message.chat.send_action(action="typing")
    
    try:
        response_data = await stalkow_bot.call_openrouter(
            conversation,
            reasoning_enabled=settings['reasoning_enabled']
        )
        
        if response_data and 'choices' in response_data:
            assistant_message = response_data['choices'][0]['message']
            content = assistant_message.get('content', '')
            reasoning_details = assistant_message.get('reasoning_details', None)
            
            conversation.append({
                "role": "assistant",
                "content": content
            })
            
            if settings['reasoning_enabled'] and reasoning_details:
                reasoning_text = reasoning_details[:800] if len(reasoning_details) > 800 else reasoning_details
                response_text = (
                    f"💭 *Размышления:*\n||{reasoning_text}||\n\n"
                    f"📝 *Ответ:*\n{content}"
                )
            else:
                response_text = content
            
            new_remaining = stalkow_bot.get_remaining_requests(user_id)
            response_text += f"\n\n📝 _Осталось запросов: {new_remaining}_"
            
            keyboard = get_main_keyboard(user_id, stalkow_bot)
            
            if len(response_text) > 4000:
                parts = [response_text[i:i+4000] for i in range(0, len(response_text), 4000)]
                for i, part in enumerate(parts):
                    if i == len(parts) - 1:
                        await update.message.reply_text(
                            part,
                            parse_mode='Markdown',
                            reply_markup=keyboard
                        )
                    else:
                        await update.message.reply_text(part, parse_mode='Markdown')
            else:
                await update.message.reply_text(
                    response_text,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
        
        else:
            await update.message.reply_text(
                "❌ Ошибка получения ответа. Попробуйте еще раз.",
                reply_markup=get_main_keyboard(user_id, stalkow_bot)
            )
            conversation.pop()
            
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Попробуйте еще раз.",
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
        conversation.pop()

async def show_premium_options(update: Update, stalkow_bot: StalkowAI, user_id: int):
    is_premium = stalkow_bot.is_premium(user_id)
    
    if is_premium:
        expiry = stalkow_bot.premium_users[user_id]
        days_left = (expiry - datetime.now()).days
        await update.message.reply_text(
            f"💎 *У вас уже есть Premium!*\n\n"
            f"📅 Осталось дней: {days_left}\n"
            f"📝 Лимит: {PREMIUM_REQUESTS_PER_DAY} запросов/день\n\n"
            f"Хотите продлить?",
            parse_mode='Markdown',
            reply_markup=get_premium_keyboard()
        )
    else:
        await update.message.reply_text(
            f"💎 *Premium доступ*\n\n"
            f"Выберите тариф:\n\n"
            f"📅 *Месяц:* {PRICE_MONTH} ⭐\n"
            f"• {PREMIUM_REQUESTS_PER_DAY} запросов/день\n"
            f"• Размышления\n\n"
            f"📅 *Год:* {PRICE_YEAR_WITH_DISCOUNT} ⭐\n"
            f"• {PREMIUM_REQUESTS_PER_DAY} запросов/день\n"
            f"• Размышления\n"
            f"• Экономия {PRICE_YEAR - PRICE_YEAR_WITH_DISCOUNT} ⭐ (33%)\n\n"
            f"💡 *Расчет:* {PRICE_MONTH} ⭐ × 12 = {PRICE_YEAR} ⭐\n"
            f"🔥 *Годовая цена:* {PRICE_YEAR_WITH_DISCOUNT} ⭐ (выгода {PRICE_YEAR - PRICE_YEAR_WITH_DISCOUNT} ⭐)",
            parse_mode='Markdown',
            reply_markup=get_premium_keyboard()
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    stalkow_bot = context.bot_data['stalkow_bot']
    
    if query.data == "buy_month":
        await query.message.reply_text(
            f"💎 *Покупка Premium на месяц*\n\n"
            f"📝 *Тариф:* Premium\n"
            f"📅 *Срок:* 1 месяц\n"
            f"💳 *Цена:* {PRICE_MONTH} ⭐\n\n"
            f"Для оплаты используйте команду:\n"
            f"`/pay {PRICE_MONTH}`",
            parse_mode='Markdown'
        )
        
    elif query.data == "buy_year":
        await query.message.reply_text(
            f"💎 *Покупка Premium на год*\n\n"
            f"📝 *Тариф:* Premium\n"
            f"📅 *Срок:* 12 месяцев\n"
            f"💳 *Цена:* {PRICE_YEAR_WITH_DISCOUNT} ⭐\n"
            f"🔥 *Экономия:* {PRICE_YEAR - PRICE_YEAR_WITH_DISCOUNT} ⭐ (33%)\n\n"
            f"Для оплаты используйте команду:\n"
            f"`/pay {PRICE_YEAR_WITH_DISCOUNT}`",
            parse_mode='Markdown'
        )
        
    elif query.data == "info_discount":
        await query.answer(
            f"Годовая подписка: {PRICE_YEAR_WITH_DISCOUNT}⭐ вместо {PRICE_YEAR}⭐\n"
            f"Экономия {PRICE_YEAR - PRICE_YEAR_WITH_DISCOUNT} Stars (33%)!",
            show_alert=True
        )
    
    elif query.data == "cancel_buy":
        await query.message.edit_text(
            "❌ Покупка отменена",
            reply_markup=None
        )

async def pay_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        amount = int(context.args[0]) if context.args else 0
        
        if amount == PRICE_MONTH:
            stalkow_bot = context.bot_data['stalkow_bot']
            expiry = stalkow_bot.add_premium(user_id, months=1)
            
            await update.message.reply_text(
                "✅ *Оплата успешна!*\n\n"
                "💎 Premium активирован на 1 месяц\n"
                f"📅 Действует до: {expiry.strftime('%d.%m.%Y')}\n"
                f"📝 Лимит: {PREMIUM_REQUESTS_PER_DAY} запросов/день\n\n"
                "Спасибо за поддержку! 🎉",
                parse_mode='Markdown',
                reply_markup=get_main_keyboard(user_id, context.bot_data['stalkow_bot'])
            )
            
        elif amount == PRICE_YEAR_WITH_DISCOUNT:
            stalkow_bot = context.bot_data['stalkow_bot']
            expiry = stalkow_bot.add_premium(user_id, months=12)
            
            await update.message.reply_text(
                "✅ *Оплата успешна!*\n\n"
                "💎 Premium активирован на 12 месяцев\n"
                f"📅 Действует до: {expiry.strftime('%d.%m.%Y')}\n"
                f"📝 Лимит: {PREMIUM_REQUESTS_PER_DAY} запросов/день\n"
                f"🔥 Вы сэкономили {PRICE_YEAR - PRICE_YEAR_WITH_DISCOUNT} Stars!\n\n"
                "Спасибо за поддержку! 🎉",
                parse_mode='Markdown',
                reply_markup=get_main_keyboard(user_id, context.bot_data['stalkow_bot'])
            )
            
        else:
            await update.message.reply_text(
                "❌ Неверная сумма\n\n"
                "Доступные варианты:\n"
                f"• `/pay {PRICE_MONTH}` - месяц ({PRICE_MONTH} ⭐)\n"
                f"• `/pay {PRICE_YEAR_WITH_DISCOUNT}` - год ({PRICE_YEAR_WITH_DISCOUNT} ⭐)",
                parse_mode='Markdown'
            )
            
    except (IndexError, ValueError):
        await update.message.reply_text(
            f"💳 *Оплата Premium*\n\n"
            f"Используйте:\n"
            f"• `/pay {PRICE_MONTH}` - месяц\n"
            f"• `/pay {PRICE_YEAR_WITH_DISCOUNT}` - год\n\n"
            f"💡 Цены в Telegram Stars",
            parse_mode='Markdown'
        )

def main():
    print(f"🤖 Запуск {BOT_NAME}...")
    
    if TELEGRAM_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("❌ Укажите TELEGRAM_TOKEN!")
        return
    
    if OPENROUTER_API_KEY == "YOUR_OPENROUTER_API_KEY":
        print("❌ Укажите OPENROUTER_API_KEY!")
        return
    
    stalkow_bot = StalkowAI()
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.bot_data['stalkow_bot'] = stalkow_bot
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("pay", pay_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print(f"✅ {BOT_NAME} запущен!")
    print(f"📊 Тарифы:")
    print(f"   🆓 Бесплатный: {FREE_REQUESTS_PER_DAY} запросов/день")
    print(f"   💎 Премиум: {PREMIUM_REQUESTS_PER_DAY} запросов/день")
    print(f"   💳 Месяц: {PRICE_MONTH}⭐")
    print(f"   💳 Год: {PRICE_YEAR_WITH_DISCOUNT}⭐ (экономия {PRICE_YEAR - PRICE_YEAR_WITH_DISCOUNT}⭐)")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()