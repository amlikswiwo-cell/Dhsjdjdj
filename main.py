import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
OFFER_SECONDS = 5 * 60 * 60 + 59 * 60


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health", "/healthz"):
            body = b"OK"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Keep routine health checks out of the logs.
        return


def start_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("Health server listening on 0.0.0.0:%s", port)


TEXT = {
    "ru": {
        "title": "🎁 Предложение по подарку",
        "gift": "Подарок",
        "price": "Цена",
        "expires": "Действует",
        "accept": "✅ Выбрать предложение",
        "decline": "✖️ Отклонить",
        "chosen": "Вы выбрали это предложение. Дальнейшие условия нужно согласовать с продавцом.",
        "declined": "Предложение отклонено.",
        "expired": "⌛ Срок действия предложения истёк.",
        "bad": "Формат: /offer CandyCane-3225 1000 ru stars",
        "denied": "Эта команда доступна только администратору.",
        "help": "Создать предложение: /offer CandyCane-3225 1000 ru stars\nЯзыки: ru, en, zh. Валюты: rub, gram, stars.",
    },
    "en": {
        "title": "🎁 Gift offer",
        "gift": "Gift",
        "price": "Price",
        "expires": "Valid for",
        "accept": "✅ Choose offer",
        "decline": "✖️ Decline",
        "chosen": "You selected this offer. Please confirm the final terms with the seller.",
        "declined": "Offer declined.",
        "expired": "⌛ This offer has expired.",
        "bad": "Format: /offer CandyCane-3225 1000 en stars",
        "denied": "This command is admin-only.",
        "help": "Create offer: /offer CandyCane-3225 1000 en stars\nLanguages: ru, en, zh. Currencies: rub, gram, stars.",
    },
    "zh": {
        "title": "🎁 礼物报价",
        "gift": "礼物",
        "price": "价格",
        "expires": "有效期",
        "accept": "✅ 选择报价",
        "decline": "✖️ 拒绝",
        "chosen": "你已选择此报价。请与卖家确认最终交易条件。",
        "declined": "报价已拒绝。",
        "expired": "⌛ 此报价已过期。",
        "bad": "格式：/offer CandyCane-3225 1000 zh stars",
        "denied": "此命令仅管理员可用。",
        "help": "创建报价：/offer CandyCane-3225 1000 zh stars\n语言：ru、en、zh。币种：rub、gram、stars。",
    },
}

CURRENCIES = {"rub": "RUB", "gram": "Gram", "stars": "⭐ Stars"}


def is_admin(update: Update) -> bool:
    return bool(update.effective_user and ADMIN_ID and update.effective_user.id == ADMIN_ID)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = "ru"
    if context.args and context.args[0].lower() in TEXT:
        lang = context.args[0].lower()
    await update.effective_message.reply_text(TEXT[lang]["help"])


async def offer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.effective_message.reply_text(TEXT["ru"]["denied"])
        return
    if len(context.args) != 4:
        await update.effective_message.reply_text(TEXT["ru"]["bad"])
        return

    gift, amount, lang, currency = context.args
    lang, currency = lang.lower(), currency.lower()
    if lang not in TEXT or currency not in CURRENCIES:
        await update.effective_message.reply_text(TEXT["ru"]["bad"])
        return
    try:
        if float(amount) <= 0:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text(TEXT[lang]["bad"])
        return

    t = TEXT[lang]
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t["accept"], callback_data=f"choose:{lang}"),
            InlineKeyboardButton(t["decline"], callback_data=f"decline:{lang}"),
        ]
    ])
    message = await update.effective_message.reply_text(
        f'{t["title"]}\n\n'
        f'{t["gift"]}: {gift}\n'
        f'{t["price"]}: {amount} {CURRENCIES[currency]}\n'
        f'{t["expires"]}: 5 ч. 59 м.\n\n'
        "ℹ️ Выбор предложения не подтверждает оплату или передачу подарка.",
        reply_markup=keyboard,
    )
    context.job_queue.run_once(
        expire_offer, OFFER_SECONDS,
        data={"chat_id": message.chat_id, "message_id": message.message_id, "lang": lang},
        name=f"offer-{message.chat_id}-{message.message_id}",
    )


async def expire_offer(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    lang = data["lang"]
    try:
        await context.bot.edit_message_text(
            chat_id=data["chat_id"],
            message_id=data["message_id"],
            text=TEXT[lang]["expired"],
        )
    except Exception:
        log.exception("Could not mark offer as expired")


async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    action, lang = query.data.split(":", 1)
    response = TEXT[lang]["chosen"] if action == "choose" else TEXT[lang]["declined"]
    try:
        await query.answer(response, show_alert=True)
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        log.exception("Could not process offer choice")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(TEXT["ru"]["help"])


def main() -> None:
    start_health_server()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("offer", offer))
    app.add_handler(CallbackQueryHandler(handle_choice, pattern=r"^(choose|decline):(ru|en|zh)$"))
    app.run_polling()


if __name__ == "__main__":
    main()
