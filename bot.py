import asyncio
import json
import logging
import requests
import traceback
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, LabeledPrice
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, PreCheckoutQueryHandler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_TOKEN = "8831108095:AAHggP-ctbO3G4iQ7G_ewecFPzBtZFG6yX0"
OPENROUTER_API_KEY = "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"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "inclusionai/ling-3.0-flash:free"
BOT_NAME = "Stalkow AI"
SUPPORT_USERNAME = "@stalkow"

# Тарифы
FREE_REQUESTS_PER_DAY = 10
PREMIUM_REQUESTS_PER_DAY = 20

# Цены в Telegram Stars (1 Star ≈ $0.01)
PRICE_MONTH = 5  # 5 Stars за месяц
PRICE_YEAR = 40  # 40 Stars за год (5×12=60, скидка 33% = 40)

# ID провайдера платежей (должен совпадать с настройками в BotFather)
PROVIDER_TOKEN = "YOUR_PROVIDER_TOKEN"  # Получить у платежного провайдера

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
            f"• Год: {PRICE_YEAR} ⭐ (экономия 20 ⭐)",
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
            f"📅 *Год:* {PRICE_YEAR} ⭐\n"
            f"• {PREMIUM_REQUESTS_PER_DAY} запросов/день\n"
            f"• Размышления\n"
            f"• Экономия 20 ⭐ (33%)\n\n"
            f"💡 *Расчет:* {PRICE_MONTH} ⭐ × 12 = {PRICE_MONTH * 12} ⭐\n"
            f"🔥 *Годовая цена:* {PRICE_YEAR} ⭐ (выгода {PRICE_MONTH * 12 - PRICE_YEAR} ⭐)",
            parse_mode='Markdown',
            reply_markup=get_premium_keyboard()
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if query.data == "buy_month":
        # Создаем реальный счет на оплату
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title="Stalkow AI Premium - Месяц",
            description=f"Премиум доступ на 1 месяц\n{PREMIUM_REQUESTS_PER_DAY} запросов/день\nРазмышления включены",
            payload="premium_month",
            provider_token=PROVIDER_TOKEN,
            currency="XTR",  # XTR - код для Telegram Stars
            prices=[LabeledPrice("Premium Месяц", PRICE_MONTH)],
            start_parameter="premium_month",
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            is_flexible=False
        )
        
    elif query.data == "buy_year":
        # Создаем реальный счет на оплату
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title="Stalkow AI Premium - Год",
            description=f"Премиум доступ на 12 месяцев\n{PREMIUM_REQUESTS_PER_DAY} запросов/день\nЭкономия 20 Stars!",
            payload="premium_year",
            provider_token=PROVIDER_TOKEN,
            currency="XTR",  # XTR - код для Telegram Stars
            prices=[LabeledPrice("Premium Год", PRICE_YEAR)],
            start_parameter="premium_year",
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            is_flexible=False
        )
        
    elif query.data == "info_discount":
        await query.answer(
            f"Годовая подписка: {PRICE_YEAR}⭐ вместо {PRICE_MONTH * 12}⭐\n"
            f"Экономия {PRICE_MONTH * 12 - PRICE_YEAR} Stars (33%)!",
            show_alert=True
        )
    
    elif query.data == "cancel_buy":
        await query.message.edit_text(
            "❌ Покупка отменена",
            reply_markup=None
        )

async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение перед оплатой"""
    query = update.pre_checkout_query
    
    # Проверяем payload
    if query.invoice_payload in ["premium_month", "premium_year"]:
        # Подтверждаем оплату
        await query.answer(ok=True)
    else:
        # Отклоняем
        await query.answer(ok=False, error_message="Неверный товар")

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик успешной оплаты"""
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    stalkow_bot = context.bot_data['stalkow_bot']
    
    if payment.invoice_payload == "premium_month":
        # Активируем премиум на месяц
        expiry = stalkow_bot.add_premium(user_id, months=1)
        
        await update.message.reply_text(
            "✅ *Оплата успешна!*\n\n"
            "💎 Premium активирован на 1 месяц\n"
            f"📅 Действует до: {expiry.strftime('%d.%m.%Y')}\n"
            f"📝 Лимит: {PREMIUM_REQUESTS_PER_DAY} запросов/день\n\n"
            "Спасибо за поддержку! 🎉",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )
    
    elif payment.invoice_payload == "premium_year":
        # Активируем премиум на год
        expiry = stalkow_bot.add_premium(user_id, months=12)
        
        await update.message.reply_text(
            "✅ *Оплата успешна!*\n\n"
            "💎 Premium активирован на 12 месяцев\n"
            f"📅 Действует до: {expiry.strftime('%d.%m.%Y')}\n"
            f"📝 Лимит: {PREMIUM_REQUESTS_PER_DAY} запросов/день\n"
            "🔥 Вы сэкономили 20 Stars!\n\n"
            "Спасибо за поддержку! 🎉",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(user_id, stalkow_bot)
        )

def main():
    print(f"🤖 Запуск {BOT_NAME}...")
    
    if TELEGRAM_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("❌ Укажите TELEGRAM_TOKEN!")
        return
    
    if PROVIDER_TOKEN == "YOUR_PROVIDER_TOKEN":
        print("❌ Укажите PROVIDER_TOKEN!")
        print("💡 Получить токен: @BotFather → Payments")
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
    
    # Обработчик callback-запросов (кнопки)
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Обработчик сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print(f"✅ {BOT_NAME} запущен!")
    print(f"📊 Тарифы:")
    print(f"   🆓 Бесплатный: {FREE_REQUESTS_PER_DAY} запросов/день")
    print(f"   💎 Премиум: {PREMIUM_REQUESTS_PER_DAY} запросов/день")
    print(f"   💳 Месяц: {PRICE_MONTH} ⭐")
    print(f"   💳 Год: {PRICE_YEAR} ⭐ (экономия {PRICE_MONTH * 12 - PRICE_YEAR} ⭐)")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
