import os
import sys
import logging
import warnings
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from telegram.request import HTTPXRequest

# Abaikan warning deprecation
warnings.filterwarnings("ignore")

import google.generativeai as genai

# Load environment variables dari file .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Konfigurasi Gemini AI menggunakan model gemini-3.6-flash
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        model = genai.GenerativeModel('gemini-3.6-flash')
    except Exception:
        model = genai.GenerativeModel('gemini-flash-latest')
else:
    model = None

# Konfigurasi Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fungsi merespons perintah /start"""
    user_name = update.effective_user.first_name
    greeting = f"Halo {user_name}!\nSaya adalah Bot Asisten AI berbasis Google Gemini. Ada yang bisa saya bantu?"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=greeting)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fungsi memproses pesan teks dari pengguna dan memanggil Gemini AI"""
    if not update.message or not update.message.text:
        return

    user_text = update.message.text
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type

    # Bersihkan sebutan username bot di grup (@HotelAI_bot)
    bot_username = context.bot.username
    if bot_username and f"@{bot_username}" in user_text:
        user_text = user_text.replace(f"@{bot_username}", "").strip()

    if not model:
        await context.bot.send_message(
            chat_id=chat_id, 
            text="Gemini API Key belum diisi dengan benar pada file .env!"
        )
        return

    # Tampilkan efek 'sedang mengetik' di Telegram
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        # Memanggil Gemini AI untuk merespons pesan pengguna
        response = model.generate_content(user_text)
        reply_text = response.text
        
        # Kirim balasan AI ke chat Telegram (langsung me-reply pesan di grup)
        await context.bot.send_message(
            chat_id=chat_id, 
            text=reply_text,
            reply_to_message_id=update.message.message_id if chat_type in ['group', 'supergroup'] else None
        )
    except Exception as e:
        logging.error(f"Error AI: {e}")
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"Maaf, terjadi kesalahan saat memproses jawaban: {str(e)}"
        )

if __name__ == '__main__':
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN tidak ditemukan pada file .env!")
        exit(1)
        
    print("Bot Telegram AI sedang berjalan...")
    
    # Tambahkan timeout 30 detik agar koneksi ke Telegram API lebih stabil
    request_config = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).request(request_config).build()
    
    # Handler untuk perintah /start
    app.add_handler(CommandHandler('start', start))
    
    # Handler untuk semua pesan teks
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # Jalankan bot dengan sistem polling
    app.run_polling()
