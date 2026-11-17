import os
import logging
import threading
import secrets
import sqlite3
import re
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
OFFER_SECONDS = 5 * 60 * 60 + 59 * 60
MANAGER_LINK = "tg://send_gift?to=Autooffersgift"
DB_PATH = os.environ.get("OFFERS_DB", "offers.sqlite3")
CODE_RE = re.compile(r"^[A-F0-9]{20}$")


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pending_offers (
            code TEXT PRIMARY KEY, creator_id INTEGER NOT NULL, gift TEXT NOT NULL,
            amount TEXT NOT NULL, lang TEXT NOT NULL, currency TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            buyer_username TEXT
        )""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(pending_offers)")}
        if "buyer_username" not in columns:
            db.execute("ALTER TABLE pending_offers ADD COLUMN buyer_username TEXT")


def save_offer(code, creator_id, gift, amount, lang, currency, buyer_username=None):
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            "INSERT INTO pending_offers(code, creator_id, gift, amount, lang, currency, buyer_username) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (code, creator_id, gift, amount, lang, currency, buyer_username),
        )


def get_offer(code, creator_id=None):
    # Codes are deliberately transferable: they are created in the bot DM
    # and redeemed in the seller's Telegram Business chat by a different user.
    with sqlite3.connect(DB_PATH) as db:
        return db.execute(
            "SELECT gift, amount, lang, currency, buyer_username FROM pending_offers WHERE code=?",
            (code,),
        ).fetchone()


def consume_offer(code, creator_id=None):
    with sqlite3.connect(DB_PATH) as db:
        db.execute("DELETE FROM pending_offers WHERE code=?", (code,))


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
        return


def start_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Health server listening on 0.0.0.0:%s", port)


TEXT = {
    "ru": {
        "title": "🎁 Предложение по подарку",
        "gift": "Подарок",
        "price": "Предложение",
        "expires": "Оффер действует",
        "accept": "✅ Принять",
        "decline": "❌ Отклонить",
        "prompt": "Выберите действие ниже.",
        "accepted": "✅ Предложение принято",
        "amount": "Сумма",
        "order": "Заказ",
        "instructions": "✨ Для завершения сделки:\nОткройте профиль менеджера, нажмите Transfer Gift, выберите NFT из предложения и подтвердите передачу.",
        "transfer": "🎁 Передать подарок",
        "confirm": "✅ Подтвердить передачу",
        "reported": "Отметка сохранена: вы сообщили о передаче. Фактическая передача подарка автоматически не проверена.",
        "declined": "❌ Предложение отклонено.",
        "expired": "⌛ Срок действия предложения истёк.",
        "bad": "Формат: /offer CandyCane-3225 1000 ru stars",
        "help": "Создать оффер: /offer CandyCane-3225 1000 ru stars\nЯзыки: ru, en, zh. Валюты: rub, gram, stars.",
        "currency_note": "Валюта",
    },
    "en": {
        "title": "🎁 Gift offer",
        "gift": "Gift",
        "price": "Offer",
        "expires": "Offer valid for",
        "accept": "✅ Accept",
        "decline": "❌ Decline",
        "prompt": "Choose an action below.",
        "accepted": "✅ Offer accepted",
        "amount": "Amount",
        "order": "Order",
        "instructions": "✨ To complete the deal:\nOpen the manager's profile, tap Transfer Gift, select the NFT from the offer, and confirm the transfer.",
        "transfer": "🎁 Transfer gift",
        "confirm": "✅ Confirm transfer",
        "reported": "Status noted: you reported a transfer. The actual gift transfer has not been automatically verified.",
        "declined": "❌ Offer declined.",
        "expired": "⌛ This offer has expired.",
        "bad": "Format: /offer CandyCane-3225 1000 en stars",
        "help": "Create offer: /offer CandyCane-3225 1000 en stars\nLanguages: ru, en, zh. Currencies: rub, gram, stars.",
        "currency_note": "Currency",
    },
    "zh": {
        "title": "🎁 礼物报价",
        "gift": "礼物",
        "price": "报价",
        "expires": "有效期",
        "accept": "✅ 接受",
        "decline": "❌ 拒绝",
        "prompt": "请在下方选择操作。",
        "accepted": "✅ 已接受报价",
        "amount": "金额",
        "order": "订单",
        "instructions": "✨ 完成交易：\n打开管理员资料，点击 Transfer Gift，选择报价中的 NFT 并确认转赠。",
        "transfer": "🎁 转赠礼物",
        "confirm": "✅ 确认转赠",
        "reported": "已记录你的申报；系统尚未自动验证礼物是否实际转赠。",
        "declined": "❌ 已拒绝报价。",
        "expired": "⌛ 报价已过期。",
        "bad": "格式：/offer CandyCane-3225 1000 zh stars",
        "help": "创建报价：/offer CandyCane-3225 1000 zh stars\n语言：ru、en、zh。币种：rub、gram、stars。",
        "currency_note": "货币",
    },
}

CURRENCIES = {"rub": "RUB", "gram": "Gram", "stars": "⭐ Stars"}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = "ru"
    if context.args and context.args[0].lower() in TEXT:
        lang = context.args[0].lower()
    await update.effective_message.reply_text(TEXT[lang]["help"])


async def offer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    code = secrets.token_hex(10).upper()
    save_offer(code, update.effective_user.id, gift, amount, lang, currency, update.effective_user.username)
    await update.effective_message.reply_text(
        "✅ Оффер сохранён. Скопируй код ниже и отправь его НЕ в этот личный чат с ботом, а прямо в чат продавца/покупателя, где подключён Telegram Business. Оффер появится именно в том чате, куда отправлен код.\n\n"
        f"<code>{code}</code>\n\n"
        "Если отправить код сюда, оффер придёт сюда же. При ошибке отправки код останется действительным.",
        parse_mode="HTML",
    )


async def send_offer(chat_id, gift, amount, lang, currency, context, business_connection_id=None, buyer_username=None):
    t = TEXT[lang]
    gift_url = "https://t.me/nft/" + quote(gift, safe="-_")
    username = "@" + buyer_username if buyer_username else "Покупатель"
    try:
        numeric_amount = float(amount)
        amount_display = str(int(numeric_amount)) if numeric_amount.is_integer() else str(numeric_amount)
    except (TypeError, ValueError):
        numeric_amount = 0
        amount_display = str(amount)
    usd_note = f" (≈ \${numeric_amount * 0.013:.2f} USD)" if currency == "stars" else ""
    text = (
        f"👤 <b>{html.escape(username)}</b> предлагает купить ваш NFT-подарок:\n\n"
        f'<a href="{html.escape(gift_url, quote=True)}">{html.escape(gift)}</a>\n\n'
        f"💰 <b>Предложение:</b> {html.escape(amount_display)} {html.escape(CURRENCIES[currency])} 🎁{html.escape(usd_note)}\n\n"
        f"⏳ <b>Оффер действует:</b> 5 ч 59 мин\n\n"
        f"<i>Выберите действие ниже.</i>"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(t["accept"], callback_data=f"choose:{lang}"),
        InlineKeyboardButton(t["decline"], callback_data=f"decline:{lang}"),
    ]])
    message = await context.bot.send_message(
        chat_id=chat_id,
        business_connection_id=business_connection_id,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )
    context.job_queue.run_once(
        expire_offer, OFFER_SECONDS,
        data={"chat_id": message.chat_id, "message_id": message.message_id, "lang": lang},
        name=f"offer-{message.chat_id}-{message.message_id}",
    )

async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Handles regular chats and Telegram Business-connected chats.
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not message.text:
        return

    code = message.text.strip().upper()
    if not CODE_RE.fullmatch(code):
        return

    row = get_offer(code, user.id)
    if not row:
        log.info("Offer code not matched (sender=%s, business=%s)", user.id, bool(getattr(message, "business_connection_id", None)))
        return

    business_connection_id = getattr(message, "business_connection_id", None)
    gift, amount, lang, currency, buyer_username = row
    try:
        # Send first. Never delete/consume the one-time code if Telegram rejects the offer.
        await send_offer(
            message.chat_id, gift, amount, lang, currency, context,
            business_connection_id=business_connection_id, buyer_username=buyer_username,
        )
    except Exception as exc:
        log.exception("Could not send offer to target chat; code retained for retry. Telegram error: %s", exc)
        return

    consume_offer(code, user.id)
    try:
        await message.delete()
    except Exception as exc:
        log.warning("Offer sent, but could not delete code message: %s", exc)


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
    t = TEXT[lang]

    if action == "decline":
        await query.answer(t["declined"], show_alert=True)
        try:
            await query.edit_message_text(t["declined"])
        except Exception:
            log.exception("Could not close declined offer")
        return

    # Stop the expiry timer once an offer has been accepted.
    for job in context.job_queue.get_jobs_by_name(
        f"offer-{query.message.chat_id}-{query.message.message_id}"
    ):
        job.schedule_removal()

    original = query.message.text or ""
    lines = [line.strip() for line in original.splitlines() if line.strip()]
    gift = "Gift"
    amount_line = ""
    for i, line in enumerate(lines):
        if "предлагает купить ваш NFT-подарок:" in line and i + 1 < len(lines):
            gift = lines[i + 1]
        if line.startswith("💰 Предложение:"):
            amount_line = line.split(":", 1)[-1].strip()
        elif line.startswith("💰 "):
            amount_line = line.split(":", 1)[-1].strip()
    order_id = "TG-" + secrets.token_hex(3).upper()
    accepted_text = (
        f'{t["accepted"]}\n'
        f'🎁 NFT: {gift}\n'
        f'💰 {t["amount"]}: {amount_line}\n'
        f'🧾 {t["order"]}: {order_id}\n\n'
        f'{t["instructions"]}\n'
        'ℹ️ Передача не считается подтверждённой, пока её не проверят.'
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t["transfer"], url=MANAGER_LINK)],
        [InlineKeyboardButton(t["confirm"], callback_data=f"confirm:{lang}:{order_id}")],
    ])
    await query.answer(t["accepted"], show_alert=True)
    try:
        await query.edit_message_text(
            accepted_text,
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )
    except Exception:
        log.exception("Could not update accepted offer")


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, lang, order_id = query.data.split(":", 2)
    await query.answer(TEXT[lang]["reported"], show_alert=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(TEXT["ru"]["help"])


def main() -> None:
    init_db()
    start_health_server()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("offer", offer))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))
    app.add_handler(CallbackQueryHandler(handle_choice, pattern=r"^(choose|decline):(ru|en|zh)$"))
    app.add_handler(CallbackQueryHandler(handle_confirm, pattern=r"^confirm:(ru|en|zh):[A-F0-9]+$"))
    app.run_polling()


if __name__ == "__main__":
    main()
