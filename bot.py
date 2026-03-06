import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

from config import TELEGRAM_BOT_TOKEN, OPERATOR_CHAT_ID
from scraper import scrape_product, ProductInfo
from calculator import calculate_order, OrderSummary

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation states
WAITING_FOR_LINK, ASK_MORE, CONFIRM_ORDER = range(3)

URL_REGEX = re.compile(r"https?://\S+")


def _format_order_summary(summary: OrderSummary) -> str:
    """Format order summary as a readable message."""
    lines = ["📦 *Расчет стоимости заказа:*\n"]

    for i, item in enumerate(summary.items, 1):
        price_str = f"{item.original_price_eur:.2f}" if item.original_price_eur > 0 else "не определена"
        lines.append(
            f"*{i}. {_escape_md(item.product.name)}*\n"
            f"   Цена: {price_str} EUR\n"
            f"   Наценка (25%): {item.markup:.2f} EUR\n"
            f"   Доставка до Португалии: {item.shipping_portugal:.2f} EUR\n"
            f"   Доставка до России (~{item.product.estimated_weight_kg} кг): {item.shipping_russia:.2f} EUR\n"
            f"   *Итого за позицию: {item.total_per_item:.2f} EUR*\n"
        )

    lines.append(f"\n⚖️ Общий вес: ~{summary.total_weight_kg} кг")
    lines.append(f"💰 *ИТОГО за весь заказ: {summary.total_cost_eur:.2f} EUR*")
    lines.append(
        "\n⚠️ _Расчет приблизительный. Точную стоимость подтвердит менеджер._"
    )

    return "\n".join(lines)


def _escape_md(text: str) -> str:
    """Escape special MarkdownV2 characters."""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    escaped = ""
    for ch in text:
        if ch in special_chars:
            escaped += "\\" + ch
        else:
            escaped += ch
    return escaped


def _format_order_for_operator(summary: OrderSummary, user) -> str:
    """Format order for the operator notification."""
    username = f"@{user.username}" if user.username else user.full_name
    user_id = user.id
    lines = [
        f"🆕 НОВЫЙ ЗАКАЗ от {username} (ID: {user_id})\n",
    ]

    for i, item in enumerate(summary.items, 1):
        lines.append(
            f"{i}. {item.product.name}\n"
            f"   Цена: {item.original_price_eur:.2f} EUR | "
            f"Итого: {item.total_per_item:.2f} EUR\n"
            f"   Ссылка: {item.product.url}\n"
        )

    lines.append(f"\nОбщий вес: ~{summary.total_weight_kg} кг")
    lines.append(f"ИТОГО: {summary.total_cost_eur:.2f} EUR")

    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation."""
    context.user_data["products"] = []
    await update.message.reply_text(
        "Привет! 👋 Я помогу рассчитать примерную стоимость доставки товаров в Россию.\n\n"
        "Отправь мне ссылку на товар, который хочешь заказать:"
    )
    return WAITING_FOR_LINK


async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process a product link."""
    text = update.message.text
    urls = URL_REGEX.findall(text)

    if not urls:
        await update.message.reply_text(
            "Я не нашел ссылку в твоем сообщении. "
            "Пожалуйста, отправь ссылку на товар (начинается с http:// или https://):"
        )
        return WAITING_FOR_LINK

    url = urls[0]
    await update.message.reply_text("⏳ Загружаю информацию о товаре...")

    product = scrape_product(url)

    if product is None:
        await update.message.reply_text(
            "❌ Не удалось загрузить страницу товара. "
            "Проверь ссылку и попробуй еще раз:"
        )
        return WAITING_FOR_LINK

    if product.price is None:
        await update.message.reply_text(
            f"⚠️ Нашел товар: *{_escape_md(product.name)}*\n"
            "Но не смог определить цену автоматически.\n"
            "Товар все равно добавлен в заказ — менеджер уточнит цену.",
            parse_mode="MarkdownV2",
        )
    else:
        await update.message.reply_text(
            f"✅ Товар найден:\n"
            f"*{_escape_md(product.name)}*\n"
            f"Цена: {product.price:.2f} {product.currency}\n"
            f"Примерный вес: {product.estimated_weight_kg} кг",
            parse_mode="MarkdownV2",
        )

    context.user_data["products"].append(product)

    keyboard = [
        [
            InlineKeyboardButton("✅ Добавить ещё товар", callback_data="add_more"),
            InlineKeyboardButton("📋 Рассчитать заказ", callback_data="calculate"),
        ]
    ]
    await update.message.reply_text(
        "Хочешь добавить ещё товар?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ASK_MORE


async def ask_more_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the 'add more?' choice."""
    query = update.callback_query
    await query.answer()

    if query.data == "add_more":
        await query.edit_message_text("Отправь ссылку на следующий товар:")
        return WAITING_FOR_LINK

    # calculate
    products = context.user_data.get("products", [])
    if not products:
        await query.edit_message_text("Заказ пуст. Отправь ссылку на товар:")
        return WAITING_FOR_LINK

    summary = calculate_order(products)
    context.user_data["summary"] = summary

    text = _format_order_summary(summary)

    keyboard = [
        [
            InlineKeyboardButton("✅ Подтвердить заказ", callback_data="confirm"),
            InlineKeyboardButton("❌ Отменить", callback_data="cancel"),
        ]
    ]

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CONFIRM_ORDER


async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle order confirmation."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        context.user_data.clear()
        await query.edit_message_text(
            "Заказ отменен. Чтобы начать заново, нажми /start"
        )
        return ConversationHandler.END

    # Confirm order — send to operator
    summary: OrderSummary = context.user_data["summary"]
    user = query.from_user
    operator_text = _format_order_for_operator(summary, user)

    if OPERATOR_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=OPERATOR_CHAT_ID,
                text=operator_text,
            )
        except Exception as e:
            logger.error(f"Failed to send order to operator: {e}")

    await query.edit_message_text(
        "✅ Заказ оформлен!\n\n"
        "С вами свяжется менеджер для подтверждения заказа и уточнения деталей.\n"
        "Спасибо! 🙏\n\n"
        "Чтобы создать новый заказ, нажмите /start"
    )

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    context.user_data.clear()
    await update.message.reply_text(
        "Заказ отменен. Чтобы начать заново, нажми /start"
    )
    return ConversationHandler.END


def main():
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN is not set. Check your .env file.")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_FOR_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link),
            ],
            ASK_MORE: [
                CallbackQueryHandler(ask_more_handler),
            ],
            CONFIRM_ORDER: [
                CallbackQueryHandler(confirm_order),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)

    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
