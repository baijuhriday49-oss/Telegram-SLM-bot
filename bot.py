import logging
import httpx
import os
import base64
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CF_API_TOKEN   = os.environ["CF_API_TOKEN"]
CF_ACCOUNT_ID  = os.environ["CF_ACCOUNT_ID"]
MAX_HISTORY    = 10
SYSTEM_PROMPT  = "You are a helpful, concise AI assistant."

# Available models (verified from Cloudflare docs)
TEXT_MODELS = {
    "llama-1b":   "@cf/meta/llama-3.2-1b-instruct",
    "llama-3b":   "@cf/meta/llama-3.2-3b-instruct",
    "llama-8b":   "@cf/meta/llama-3.1-8b-instruct-fast",
    "llama-70b":  "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "mistral-7b": "@cf/mistralai/mistral-7b-instruct-v0.2",
    "deepseek":   "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
    "qwq-32b":    "@cf/qwen/qwq-32b",
}

IMAGE_MODELS = {
    "flux":           "@cf/black-forest-labs/flux-1-schnell",
    "sdxl":           "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    "dreamshaper":    "@cf/lykon/dreamshaper-8-lcm",
    "sdxl-lightning": "@cf/bytedance/stable-diffusion-xl-lightning",
}

# Default models
current_text_model  = TEXT_MODELS["llama-8b"]
current_image_model = IMAGE_MODELS["flux"]
VISION_MODEL        = "@cf/meta/llama-3.2-11b-vision-instruct"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
histories = {}

def get_history(chat_id):
    if chat_id not in histories:
        histories[chat_id] = []
    return histories[chat_id]

async def call_cf(messages):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{current_text_model}"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url,
            headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"},
            json={"messages": messages, "max_tokens": 512})
        r.raise_for_status()
        return r.json()["result"]["response"].strip()

async def generate_image(prompt):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{current_image_model}"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url,
            headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"},
            json={"prompt": prompt})
        r.raise_for_status()
        try:
            result = r.json()["result"]["image"]
            return base64.b64decode(result)
        except:
            return r.content

async def understand_image(image_bytes, question):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{VISION_MODEL}"
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url,
            headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"},
            json={
                "messages": [
                    {"role": "user", "content": [
                        {"type": "image", "image": image_b64},
                        {"type": "text", "text": question or "What is in this image?"}
                    ]}
                ],
                "max_tokens": 512
            })
        r.raise_for_status()
        return r.json()["result"]["response"].strip()

async def web_search(query):
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        )
        data = r.json()
        results = []
        if data.get("AbstractText"):
            results.append(data["AbstractText"])
        for topic in data.get("RelatedTopics", [])[:3]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(topic["Text"])
        if results:
            return "\n\n".join(results)
        return "No results found."

async def start(update: Update, context):
    histories[update.effective_chat.id] = []
    await update.message.reply_text(
        "👋 Hi! I'm your AI assistant powered by Cloudflare.\n\n"
        "Commands:\n"
        "/start — reset\n"
        "/clear — clear history\n"
        "/image <prompt> — generate an image 🎨\n"
        "/search <query> — web search 🌐\n"
        "/model — manage models ⚙️\n\n"
        "Send a photo to analyze it with AI 🖼️"
    )

async def clear(update: Update, context):
    histories[update.effective_chat.id] = []
    await update.message.reply_text("🗑️ Cleared.")

async def model_cmd(update: Update, context):
    global current_text_model, current_image_model
    args = context.args

    if not args or args[0] == "list":
        text_list = "\n".join([f"  `{k}` {'✅' if TEXT_MODELS[k] == current_text_model else ''}" for k in TEXT_MODELS])
        image_list = "\n".join([f"  `{k}` {'✅' if IMAGE_MODELS[k] == current_image_model else ''}" for k in IMAGE_MODELS])
        await update.message.reply_text(
            f"*Text models:*\n{text_list}\n\n*Image models:*\n{image_list}\n\n"
            "Usage:\n`/model text llama-70b`\n`/model image dreamshaper`",
            parse_mode="Markdown"
        )
        return

    if len(args) < 2:
        await update.message.reply_text("Usage: `/model text <name>` or `/model image <name>`", parse_mode="Markdown")
        return

    if args[0] == "text":
        if args[1] in TEXT_MODELS:
            current_text_model = TEXT_MODELS[args[1]]
            await update.message.reply_text(f"✅ Text model switched to `{args[1]}`", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Unknown model. Use `/model list` to see options.", parse_mode="Markdown")

    elif args[0] == "image":
        if args[1] in IMAGE_MODELS:
            current_image_model = IMAGE_MODELS[args[1]]
            await update.message.reply_text(f"✅ Image model switched to `{args[1]}`", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Unknown model. Use `/model list` to see options.", parse_mode="Markdown")

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

async def search(update: Update, context):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Please provide a search query!\nExample: /search latest AI news")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        results = await web_search(query)
        await update.message.reply_text(f"🌐 *{query}*\n\n{results}", parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Search error: {e}")
        await update.message.reply_text(f"⚠️ Search failed: {e}")

async def handle_photo(update: Update, context):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    photo = update.message.photo[-1]
    caption = update.message.caption or "What is in this image?"
    file = await context.bot.get_file(photo.file_id)
    async with httpx.AsyncClient() as client:
        r = await client.get(file.file_path)
        image_bytes = r.content
    try:
        reply = await understand_image(image_bytes, caption)
        await update.message.reply_text(f"🖼️ {reply}")
    except Exception as e:
        logging.error(f"Vision error: {e}")
        await update.message.reply_text(f"⚠️ Image understanding failed: {e}")

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
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("model", model_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
