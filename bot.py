import os
import sys
import json
import logging
import warnings
import threading
import asyncio
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.request import HTTPXRequest

# Abaikan warning deprecation
warnings.filterwarnings("ignore")

import google.generativeai as genai

# Load environment variables dari file .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-mmpg.onrender.com")
TEMPLATES_FILE = "templates.json"

# SYSTEM INSTRUCTION: Memaksa AI selalu ramah dan SELALU sertakan emoji/emote di setiap jawaban
SYSTEM_PROMPT = (
    "Kamu adalah Asisten AI yang sangat ramah, sopan, profesional, dan ceria. "
    "ATURAN WAJIB: Di setiap jawaban atau balasan yang kamu berikan, kamu HARUS SELALU menyertakan "
    "emoji / emote (seperti 😊, 🙏, 🤖, ✨, 🏨, 👍, dll.) yang sesuai dengan konteks percakapan!"
)

# Konfigurasi Gemini AI
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

MODEL_NAMES = ['gemini-2.5-flash', 'gemini-flash-latest', 'gemini-3.6-flash', 'gemini-2.5-pro']

def get_ai_response(user_text):
    """Mencoba memanggil Gemini AI dengan fallback model jika terkena 429 Rate Limit"""
    last_error = None
    for model_name in MODEL_NAMES:
        try:
            m = genai.GenerativeModel(model_name, system_instruction=SYSTEM_PROMPT)
            res = m.generate_content(user_text)
            if res and res.text:
                return res.text
        except Exception as e:
            last_error = e
            time.sleep(0.5)
            continue
    raise last_error

# --- MANAJEMEN TEMPLATE KATEGORI LOKAL ---
def load_templates():
    if os.path.exists(TEMPLATES_FILE):
        try:
            with open(TEMPLATES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {
        "tungguvalidasi": (
            "Baik kak 🙏\nMohon ditunggu sebentar ya kak. Saat ini kami sedang membantu mengubah "
            "data rekening pada ID kakak dari yang sebelumnya tidak valid menjadi rekening yang valid "
            "agar akun dapat digunakan kembali dengan normal.\n"
            "Proses sedang kami lakukan, mohon kesediaannya untuk menunggu sebentar ya kak. "
            "Terima kasih atas kesabaran kakak 😊"
        )
    }

def save_templates(data):
    try:
        with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Gagal menyimpan templates: {e}")

templates = load_templates()

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
    msg = (
        f"Halo {user_name}! 👋😊\n"
        f"Saya adalah Bot Asisten AI Kolaboratif. Siapa saja di grup ini bisa membuat, mengubah, atau memakai templat kategori! 🤖✨\n\n"
        f"📌 *Perintah Utama*:\n"
        f"• `/menu` - Tampilkan tombol menu kategori\n"
        f"• `/set [nama_kategori] [pesan_jawaban]` - Tambah/Ubah kategori (Bisa dilakukan siapa saja!)\n"
        f"• `/list` - Lihat semua daftar kategori tersimpan\n"
        f"• `/del [nama_kategori]` - Hapus kategori\n"
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode="Markdown")

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan tombol inline keyboard untuk daftar kategori"""
    if not templates:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Belum ada kategori yang dibuat 😊 Ketik `/set [nama] [pesan]` untuk menambahkan kategori baru!"
        )
        return

    keyboard = []
    # Buat tombol 2 kolom
    items = list(templates.keys())
    for i in range(0, len(items), 2):
        row = [InlineKeyboardButton(f"📁 {items[i]}", callback_data=f"tmpl_{items[i]}")]
        if i + 1 < len(items):
            row.append(InlineKeyboardButton(f"📁 {items[i+1]}", callback_data=f"tmpl_{items[i+1]}"))
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=" Silakan pilih Kategori di bawah ini (atau ketik langsung `/[nama_kategori]`):",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def set_template_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menambah atau merubah teks kategori oleh SIAPA SAJA"""
    if not context.args or len(context.args) < 2:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Cara Penggunaan:\n`/set [nama_kategori] [isi pesan]`\n\nContoh:\n`/set tungguvalidasi Baik kak, mohon tunggu data rekening sedang divalidasi 🙏`",
            parse_mode="Markdown"
        )
        return

    key = context.args[0].replace("/", "").strip().lower()
    val = " ".join(context.args[1:])

    templates[key] = val
    save_templates(templates)

    msg = (
        f"✅ *Kategori Berhasil Disimpan / Diperbarui!* 🎉\n\n"
        f"📌 *Nama Kategori*: `{key}`\n"
        f"💬 *Panggil Dengan*: `/{key}` atau via `/menu`\n\n"
        f"📝 *Isi Pesan*:\n{val}"
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode="Markdown")

async def list_templates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Melihat daftar semua kategori"""
    if not templates:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Belum ada kategori tersimpan 😊")
        return

    text = "📋 *Daftar Kategori Tersimpan* (Bisa digunakan oleh siapa saja):\n\n"
    for k in templates.keys():
        text += f"• `/{k}`\n"
    text += "\n💡 Ketik `/menu` untuk melihat tombol interaktif atau ketik `/set` untuk merubah."
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown")

async def del_template_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menghapus kategori"""
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Gunakan: `/del [nama_kategori]`", parse_mode="Markdown")
        return

    key = context.args[0].replace("/", "").strip().lower()
    if key in templates:
        del templates[key]
        save_templates(templates)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🗑️ Kategori `/{key}` berhasil dihapus!", parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Kategori `/{key}` tidak ditemukan.", parse_mode="Markdown")

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Merespons ketika pengguna mengklik tombol kategori"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("tmpl_"):
        key = data.replace("tmpl_", "")
        if key in templates:
            await query.message.reply_text(templates[key])
        else:
            await query.message.reply_text("❌ Kategori tidak ditemukan.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memproses pesan umum atau panggilan command kategori tanpa slash"""
    if not update.message or not update.message.text:
        return

    raw_text = update.message.text.strip()
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type

    bot_username = context.bot.username
    cleaned_text = raw_text
    if bot_username and f"@{bot_username}" in cleaned_text:
        cleaned_text = cleaned_text.replace(f"@{bot_username}", "").strip()

    # Cek apakah pesan diawali slash command khusus kategori (seperti /tungguvalidasi)
    possible_cmd = cleaned_text.replace("/", "").strip().lower()
    if possible_cmd in templates:
        await context.bot.send_message(
            chat_id=chat_id,
            text=templates[possible_cmd],
            reply_to_message_id=update.message.message_id if chat_type in ['group', 'supergroup'] else None
        )
        return

    if not GEMINI_KEY:
        await context.bot.send_message(chat_id=chat_id, text="Gemini API Key belum diisi! ⚠️")
        return

    # Tampilkan efek 'sedang mengetik' di Telegram
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        reply_text = get_ai_response(cleaned_text)
        await context.bot.send_message(
            chat_id=chat_id, 
            text=reply_text,
            reply_to_message_id=update.message.message_id if chat_type in ['group', 'supergroup'] else None
        )
    except Exception as e:
        err_str = str(e)
        logging.error(f"Error AI: {err_str}")
        
        if "429" in err_str or "quota" in err_str.lower():
            friendly_msg = (
                "Maaf ya kak 🙏 AI sedang melayani banyak pertanyaan dalam waktu singkat (Batas Kuota Sementara) 😅\n\n"
                "Mohon tunggu sekitar 10-15 detik lalu coba kirimkan lagi pertanyaannya ya kak! Terima kasih atas kesabarannya 😊✨"
            )
        else:
            friendly_msg = "Maaf kak, sedang ada sedikit kendala koneksi dengan AI. Mohon coba sebentar lagi ya kak! 🙏😊"

        await context.bot.send_message(
            chat_id=chat_id, 
            text=friendly_msg,
            reply_to_message_id=update.message.message_id if chat_type in ['group', 'supergroup'] else None
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

    request_config = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).request(request_config).build()
    
    # Registered Commands
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('menu', menu_command))
    app.add_handler(CommandHandler('set', set_template_command))
    app.add_handler(CommandHandler('list', list_templates_command))
    app.add_handler(CommandHandler('del', del_template_command))
    
    # Callback query handler untuk tombol inline
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    
    # Handler pesan umum
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # Handler fallback untuk command dinamis
    app.add_handler(MessageHandler(filters.COMMAND, handle_message))
    
    app.run_polling()
