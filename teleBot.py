import os
import logging
import random
import re
import urllib.parse
import requests
from io import BytesIO

from dotenv import load_dotenv
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ---- CONFIG ----
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not BOT_TOKEN or not GEMINI_API_KEY:
    raise RuntimeError("Missing BOT_TOKEN or GEMINI_API_KEY — check your .env file.")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    "gemini-3.5-flash-lite",  # updated model name (2.5-flash-lite was deprecated for new users)
    system_instruction=(
        "You are a warm, playful chatbot themed around cats, named cat_meme. "
        "Keep replies short (1-2 sentences), casual, and friendly, like texting a friend. "
        "Never mention that you are an AI or a language model."
    )
)

# Per-user conversation history: {user_id: [{"role": "user"/"model", "parts": [text]}]}
conversation_history = {}
MAX_HISTORY_MESSAGES = 10  # keep last 10 exchanges to limit cost/latency

# Mood keywords to pick a relevant cat meme caption (separate from the actual chat reply)
MOOD_CAPTIONS = {
    "greeting": (["hi", "hello", "hey", "yo", "hola"], ["hello friend", "hi there", "hey you", "sup"]),
    "tired": (["tired", "sleepy", "exhausted", "burnt", "burnout"], ["running on empty", "five more minutes", "send coffee"]),
    "happy": (["happy", "great", "awesome", "excited", "yay"], ["living my best life", "vibing", "today's a good day"]),
    "sad": (["sad", "upset", "down", "crying", "bad day"], ["comfort cat", "here for you", "sending hugs"]),
    "studying": (["studying", "study", "exam", "homework", "assignment"], ["me pretending to study", "focus mode", "brain overload"]),
    "bored": (["bored", "boring", "nothing to do"], ["existential crisis", "waiting for something to happen", "send help"]),
}
DEFAULT_CAPTIONS = ["just vibing", "no thoughts head empty", "this is fine", "monday mood"]


def pick_caption(text: str) -> str:
    lowered = text.lower()
    words = set(re.findall(r"\b\w+\b", lowered))
    for keywords, captions in MOOD_CAPTIONS.values():
        if any(word in words for word in keywords):
            return random.choice(captions)
    return random.choice(DEFAULT_CAPTIONS)


async def send_cat_meme(update: Update, context: ContextTypes.DEFAULT_TYPE, caption_text: str):
    safe_caption = urllib.parse.quote(caption_text[:60], safe='')
    cache_buster = random.randint(1, 999999)
    cat_url = f"https://cataas.com/cat/says/{safe_caption}?fontSize=40&fontColor=white&r={cache_buster}"

    try:
        response = requests.get(cat_url, timeout=10)
        response.raise_for_status()
        image_bytes = BytesIO(response.content)
        image_bytes.name = "cat.png"
        await update.message.reply_photo(photo=image_bytes)
    except requests.RequestException as e:
        logging.error(f"Failed to fetch cat image: {e}")


def get_gemini_reply(user_id: int, user_text: str) -> str:
    history = conversation_history.get(user_id, [])

    try:
        chat = model.start_chat(history=history)
        response = chat.send_message(user_text)
        reply_text = response.text.strip()

        # Update stored history, trimmed to avoid unbounded growth
        history.append({"role": "user", "parts": [user_text]})
        history.append({"role": "model", "parts": [reply_text]})
        conversation_history[user_id] = history[-MAX_HISTORY_MESSAGES * 2:]

        return reply_text
    except Exception as e:
        logging.error(f"Gemini API error: {e}")
        # Shows the real error in-chat while testing so future issues are easy to spot.
        # Remove the debug text once things are stable.
        return f"Hmm, I got distracted chasing a laser pointer. (debug: {str(e)[:150]})"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history.pop(user_id, None)  # fresh start
    await update.message.reply_text(
        f"Hi {update.effective_user.first_name}! I'm cat_meme. Talk to me about anything."
    )
    await send_cat_meme(update, context, "hello friend")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Just chat with me normally — I'll reply and send a matching cat meme.")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history.pop(user_id, None)
    await update.message.reply_text("Alright, clean slate! What's up?")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    reply_text = get_gemini_reply(user_id, text)
    await update.message.reply_text(reply_text)

    caption = pick_caption(text)
    await send_cat_meme(update, context, caption)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    port = int(os.environ.get("PORT", 8443))
    render_url = os.environ.get("RENDER_EXTERNAL_URL")

    print("Cat meme bot (Gemini-powered) is running via webhook...")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{render_url}/{BOT_TOKEN}"
    )


if __name__ == "__main__":
    main()



