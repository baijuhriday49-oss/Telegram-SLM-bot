import logging
import httpx
import os
import base64
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CF_API_TOKEN   = os.environ["CF_API_TOKEN"]
CF_ACCOUNT_ID  = os.environ["CF_ACCOUNT_ID"]
MODEL          = "@cf/meta/llama-3.2-1b-instruct"
IMAGE_MODEL    = "@cf/black-forest-labs/flux-1-schnell"
VIDEO_MODEL    = "@cf/google/veo-3"
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

async def generate_image(prompt):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{IMAGE_MODEL}"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url,
            headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"},
            json={"prompt": prompt, "num_steps": 4})
        r.raise_for_status()
        result = r.json()["result"]["image"]
        return base64.b64decode(result)

async def generate_video(prompt):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{VIDEO_MODEL}"
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(url,
            headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"},
            json={"prompt": prompt, "duration": "6s", "aspect_ratio": "16:9", "resolution": "720p"})
        r.raise_for_status()
        return r.content

async def start(update: Update, context):
    histories[update.effective_chat.id] = []
    await update.message.reply_text(
        "👋 Hi! I'm your AI assistant powered by Llama 3.2 on Cloudflare.\n\n"
        "Commands:\n"
        "/start — reset\n"
        "/clear — clear history\n"
        "/image <prompt> — generate an image 🎨\n"
        "/video <prompt> — generate a video 🎥"
    )

async def clear(update: Update, context):
    histories[update.effective_chat.id] = []
    await update.message.reply_text("🗑️ Cleared.")

async def image(update: Update, context):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Please provide a prompt!\nExample: /image a sunset over mountains")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
    try:
        image_bytes = await generate_image(prompt)
        await update.message.reply_photo(photo=image_bytes, caption=f"🎨 {prompt}")
    except Exception as e:
        logging.error(f"Image error: {e}")
        await update.message.reply_text(f"⚠️ Image generation failed: {e}")

async def video(update: Update, context):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Please provide a prompt!\nExample: /video a dog running on a beach")
        return
    await update.message.reply_text("⏳ Generating video, this may take a minute...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_video")
    try:
        video_bytes = await generate_video(prompt)
        await update.message.reply_video(video=video_bytes, caption=f"🎥 {prompt}")
    except Exception as e:
        logging.error(f"Video error: {e}")
        await update.message.reply_text(f"⚠️ Video generation failed: {e}")

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
    app.add_handler(CommandHandler("image", image))
    app.add_handler(CommandHandler("video", video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
