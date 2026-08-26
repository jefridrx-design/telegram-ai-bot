import os
import sys
import logging
import warnings
import threading
import asyncio
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

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
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-mmpg.onrender.com")

# SYSTEM INSTRUCTION: Memaksa AI selalu ramah dan SELALU sertakan emoji/emote di setiap jawaban
SYSTEM_PROMPT = (
    "Kamu adalah Asisten AI yang sangat ramah, sopan, profesional, dan ceria. "
    "ATURAN WAJIB: Di setiap jawaban atau balasan yang kamu berikan, kamu HARUS SELALU menyertakan "
    "emoji / emote (seperti 😊, 🙏, 🤖, ✨, 🏨, 👍, dll.) yang sesuai dengan konteks percakapan!"
)

# Konfigurasi Gemini AI menggunakan model gemini-3.6-flash
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        model = genai.GenerativeModel(
            'gemini-3.6-flash',
            system_instruction=SYSTEM_PROMPT
        )
    except Exception:
        model = genai.GenerativeModel(
            'gemini-flash-latest',
            system_instruction=SYSTEM_PROMPT
        )
else:
    model = None

# Konfigurasi Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- WEB SERVER KECIL UNTUK HEALTH CHECK & ANTI-SLEEP RENDER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"OK - Bot Telegram AI is Active 24/7")

    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

def start_self_ping():
    """Thread di latar belakang yang otomatis nge-ping URL setiap 60 detik agar tidak pernah sleep"""
    def ping_loop():
        time.sleep(10)
        while True:
            try:
                req = urllib.request.Request(RENDER_URL, headers={'User-Agent': 'KeepAliveBot/1.0'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    logging.info("⚡ Self-Ping Berhasil: Bot terjaga 100% aktif (1 menit sekali)")
            except Exception as e:
                logging.info(f"⚡ Ping status check: {e}")
            time.sleep(60)

    t = threading.Thread(target=ping_loop, daemon=True)
    t.start()

# --- HANDLER TELEGRAM BOT ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fungsi merespons perintah /start"""
    user_name = update.effective_user.first_name
    greeting = f"Halo {user_name}! 👋😊\nSaya adalah Bot Asisten AI (Hotel AI). Ada yang bisa saya bantu hari ini? 🤖✨"
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
            text="Gemini API Key belum diisi dengan benar pada file .env! ⚠️"
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
            text=f"Maaf, terjadi kesalahan saat memproses jawaban: {str(e)} 😅"
        )

if __name__ == '__main__':
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN tidak ditemukan pada file .env!")
        exit(1)
        
    print("Bot Telegram AI sedang berjalan...")
    
    # Jalankan server web kecil untuk Render Health Check & Self Ping
    server_thread = threading.Thread(target=run_health_server, daemon=True)
    server_thread.start()
    start_self_ping()

    # Tambahkan timeout 30 detik agar koneksi ke Telegram API lebih stabil
    request_config = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).request(request_config).build()
    
    # Handler untuk perintah /start
    app.add_handler(CommandHandler('start', start))
    
    # Handler untuk semua pesan teks
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # Jalankan bot dengan sistem polling
    app.run_polling()
