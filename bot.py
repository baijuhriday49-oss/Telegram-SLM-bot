import logging
import httpx
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CF_API_TOKEN   = os.environ["CF_API_TOKEN"]
CF_ACCOUNT_ID  = os.environ["CF_ACCOUNT_ID"]
MODEL          = "@cf/meta/llama-3.2-1b-instruct"
MAX_HISTORY    = 10
SYSTEM_PROMPT  = "You are a helpful, concise AI assistant."

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
histories = {}

def get_history(chat_id):
    if chat_id not in histories:
        histories[chat_id] = []
    return histories[chat_id]

async def call_cf(messages):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{MODEL}"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url,
            headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"},
            json={"messages": messages, "max_tokens": 512})
        r.raise_for_status()
        return r.json()["result"]["response"].strip()

async def start(update: Update, context):
    histories[update.effective_chat.id] = []
    await update.message.reply_text("👋 Hi! I'm your AI assistant powered by Llama 3.2 on Cloudflare.\n/start — reset\n/clear — clear history")

async def clear(update: Update, context):
    histories[update.effective_chat.id] = []
    await update.message.reply_text("🗑️ Cleared.")

async def handle_message(update: Update, context):
    chat_id = update.effective_chat.id
    history = get_history(chat_id)
    history.append({"role": "user", "content": update.message.text})
    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        reply = await call_cf([{"role": "system", "content": SYSTEM_PROMPT}] + history)
    except Exception as e:
        logging.error(f"CF error: {e}")
        reply = f"⚠️ Error: {e}"
    history.append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply, parse_mode="Markdown")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
