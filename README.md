# Telegram Gift Offer Bot

Telegram bot for posting gift offers with a 5h 59m expiry, RU/EN/ZH text, and RUB, Gram, or Stars price labels.

## Deploy on Render
1. Create a **Background Worker** from this repository.
2. Build command: `pip install -r requirements.txt`
3. Start command: `python main.py`
4. Add environment variables:
   - `BOT_TOKEN`: token from BotFather (keep it private).
   - `ADMIN_ID`: your numeric Telegram user ID. Only this user can create offers.
5. Deploy and open the bot in Telegram.

## Create an offer
`/offer CandyCane-3225 1000 ru stars`

Syntax: `/offer GIFT_ID AMOUNT LANGUAGE CURRENCY`
- Languages: `ru`, `en`, `zh`
- Currencies: `rub`, `gram`, `stars`

Choosing an offer is not payment verification or proof of gift transfer. Currency labels are display-only and are not connected to a payment processor. Confirm payment and delivery separately through a trusted process.
