import os
import sys
import json
import csv
import io
import logging
import warnings
import threading
import asyncio
import time
import urllib.request
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.request import HTTPXRequest

# Abaikan warning
warnings.filterwarnings("ignore")

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-mmpg.onrender.com")
TEMPLATES_FILE = "templates.json"
GOOGLE_SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1Q33PvIAGYj3lNWJQ3YngLvuOcCm8tA1pD7gT0ixmUfI/export?format=csv"
GOOGLE_APPS_SCRIPT_URL = os.getenv("GOOGLE_APPS_SCRIPT_URL", "")

def sync_templates():
    """Membaca data dari Google Sheets dan local file tanpa paksaan default"""
    data = {}
    
    # 1. Baca dari Google Sheets secara live
    try:
        r = requests.get(GOOGLE_SHEET_CSV_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if r.status_code == 200 and r.text.strip():
            reader = csv.reader(io.StringIO(r.text))
            rows = list(reader)
            for row in rows:
                if len(row) >= 2:
                    key = row[0].replace("/", "").strip().lower()
                    val = row[1].strip()
                    if key and key != "kategori" and val:
                        data[key] = val
            return data
    except Exception as e:
        logging.warning(f"Gagal sync Google Sheets: {e}")

    # 2. Fallback baca dari file lokal jika offline
    if os.path.exists(TEMPLATES_FILE):
        try:
            with open(TEMPLATES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    return data

def save_local_templates(data):
    try:
        with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Gagal menyimpan local templates: {e}")

def write_to_google_sheet(key, val, action="set"):
    """Mengirimkan data baru/hapus ke Google Sheets Apps Script Webhook"""
    if not GOOGLE_APPS_SCRIPT_URL:
        return
    try:
        payload = {"key": key, "val": val, "action": action}
        requests.post(GOOGLE_APPS_SCRIPT_URL, json=payload, timeout=5)
    except Exception as e:
        logging.error(f"Gagal menulis ke Google Sheet Webhook: {e}")

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
        self.wfile.write(b"OK - Bot Telegram Template Handler Active 24/7")

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
        f"Selamat datang di Bot Templat Kategori. Siapa saja di grup ini bisa membuat, merubah, atau memakai templat balasan! 🤖✨\n\n"
        f"📌 *Perintah Utama*:\n"
        f"• `/menu` - Tampilkan tombol menu pilihan kategori\n"
        f"• `/set [nama_kategori] [pesan_jawaban]` - Simpan kategori baru\n"
        f"• `/list` - Lihat daftar semua kategori tersimpan\n"
        f"• `/del [nama_kategori]` - Hapus kategori\n"
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode="Markdown")

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan tombol inline keyboard untuk daftar kategori murni dari Google Sheets"""
    current_templates = sync_templates()
    if not current_templates:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Belum ada kategori yang dibuat 😊 Ketik `/set [nama] [pesan]` untuk menambahkan kategori baru!",
            parse_mode="Markdown"
        )
        return

    keyboard = []
    items = list(current_templates.keys())
    for i in range(0, len(items), 2):
        row = [InlineKeyboardButton(f"📁 /{items[i]}", callback_data=f"tmpl_{items[i]}")]
        if i + 1 < len(items):
            row.append(InlineKeyboardButton(f"📁 /{items[i+1]}", callback_data=f"tmpl_{items[i+1]}"))
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Silakan pilih Kategori di bawah ini (atau ketik langsung `/[nama_kategori]`):",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def set_template_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menambah atau merubah teks kategori (Dengan Proteksi Duplikasi)"""
    if not context.args or len(context.args) < 2:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Cara Penggunaan:\n`/set [nama_kategori] [isi pesan]`\n\nContoh:\n`/set bukaakun Baik kak 🙏 Mohon ditunggu data sedang diperbaiki 😊`",
            parse_mode="Markdown"
        )
        return

    key = context.args[0].replace("/", "").strip().lower()
    val = " ".join(context.args[1:])

    current = sync_templates()

    # VALIDASI CEK DUPLIKASI NAMA KATEGORI
    if key in current:
        msg = (
            f"⚠️ *Pendaftaran Kategori Gagal! Nama Kategori Sudah Ada!*\n\n"
            f"Kategori `/{key}` sudah terdaftar sebelumnya di dalam sistem/Google Sheets. "
            f"Nama kategori tidak boleh sama (duplikat) 😊\n\n"
            f"💡 *Solusi*:\n"
            f"• Gunakan nama kategori lain (contoh: `/{key}2` atau `/{key}_baru`)\n"
            f"• Atau hapus dulu kategori lama dengan `/del {key}` jika ingin menggantinya!"
        )
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode="Markdown")
        return

    current[key] = val
    save_local_templates(current)
    
    # Menuliskan secara otomatis ke Google Sheets
    threading.Thread(target=write_to_google_sheet, args=(key, val, "set"), daemon=True).start()

    msg = (
        f"✅ *Kategori Baru Berhasil Disimpan!* 🎉\n\n"
        f"📌 *Nama Kategori*: `{key}`\n"
        f"💬 *Panggil Dengan*: `/{key}` atau via `/menu`\n\n"
        f"📝 *Isi Pesan*:\n{val}"
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode="Markdown")

async def list_templates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Melihat daftar semua kategori"""
    current = sync_templates()
    if not current:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Belum ada kategori tersimpan 😊")
        return

    text = "📋 *Daftar Kategori Tersimpan*:\n\n"
    for k in current.keys():
        text += f"• `/{k}`\n"
    text += "\n💡 Ketik `/menu` untuk melihat tombol pilihan."
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown")

async def del_template_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menghapus kategori"""
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Gunakan: `/del [nama_kategori]`", parse_mode="Markdown")
        return

    key = context.args[0].replace("/", "").strip().lower()
    current = sync_templates()
    if key in current:
        del current[key]
        save_local_templates(current)
        threading.Thread(target=write_to_google_sheet, args=(key, "", "del"), daemon=True).start()
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
        current = sync_templates()
        if key in current:
            await query.message.reply_text(current[key])
        else:
            await query.message.reply_text("❌ Kategori tidak ditemukan.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memproses panggilan command kategori"""
    if not update.message or not update.message.text:
        return

    raw_text = update.message.text.strip()
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type

    bot_username = context.bot.username
    cleaned_text = raw_text
    if bot_username and f"@{bot_username}" in cleaned_text:
        cleaned_text = cleaned_text.replace(f"@{bot_username}", "").strip()

    possible_cmd = cleaned_text.replace("/", "").strip().lower()
    current = sync_templates()
    if possible_cmd in current:
        await context.bot.send_message(
            chat_id=chat_id,
            text=current[possible_cmd],
            reply_to_message_id=update.message.message_id if chat_type in ['group', 'supergroup'] else None
        )
        return

if __name__ == '__main__':
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN tidak ditemukan pada file .env!")
        exit(1)
        
    print("Bot Telegram Template Handler sedang berjalan...")
    
    server_thread = threading.Thread(target=run_health_server, daemon=True)
    server_thread.start()
    start_self_ping()

    request_config = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).request(request_config).build()
    
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('menu', menu_command))
    app.add_handler(CommandHandler('set', set_template_command))
    app.add_handler(CommandHandler('list', list_templates_command))
    app.add_handler(CommandHandler('del', del_template_command))
    
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(MessageHandler(filters.COMMAND, handle_message))
    
    app.run_polling()
