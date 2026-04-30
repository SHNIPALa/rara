#!/usr/bin/env python3
"""
SUPER RADIO BOT 2.0 – Linux + Docker + гибкий туннель
"""

import os
import sys
import time
import threading
import random
import json
import sqlite3
import subprocess
import re
import logging
import signal
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from mutagen.mp3 import MP3

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.enums import ParseMode

# ==================== ЛОГГИРОВАНИЕ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("radio.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ==================== КОНФИГУРАЦИЯ ИЗ ENV ====================
PORT = int(os.getenv("PORT", "8080"))
MUSIC_FOLDER = os.getenv("MUSIC_FOLDER", "music")
DATA_FOLDER = os.getenv("DATA_FOLDER", "data")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
TUNNEL_SERVICE = os.getenv("TUNNEL_SERVICE", "localhost")  # localhost, ngrok, cloudflare
PUBLIC_URL = os.getenv("PUBLIC_URL", "")

NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")       # нужен для ngrok
CLOUDFLARE_TUNNEL_NAME = os.getenv("CLOUDFLARE_TUNNEL_NAME", "")  # если есть именованный туннель

# Создаём папки
Path(MUSIC_FOLDER).mkdir(exist_ok=True)
Path(DATA_FOLDER).mkdir(exist_ok=True)
Path("pending").mkdir(exist_ok=True)

# ==================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ====================
playlist = []
playlist_lock = threading.Lock()
current_song_index = 0
current_song_file = None
current_song_path = None
current_song_position = 0
song_lock = threading.Lock()

clients = []
clients_lock = threading.Lock()

public_url = PUBLIC_URL if PUBLIC_URL else None
tunnel_ready = threading.Event() if not PUBLIC_URL else threading.Event()
if PUBLIC_URL:
    tunnel_ready.set()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                 user_id INTEGER PRIMARY KEY,
                 username TEXT,
                 date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pending_songs (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 filename TEXT,
                 user_id INTEGER,
                 user_name TEXT,
                 date TEXT)''')
    conn.commit()
    conn.close()

init_db()

# ==================== ТУННЕЛЬ ====================
class TunnelManager:
    def __init__(self, service, port):
        self.service = service
        self.port = port
        self.process = None
        self.url = None
        self._stop = threading.Event()

    def start(self):
        """Запускает туннель и возвращает URL или None"""
        if PUBLIC_URL:
            logger.info(f"Используется ручной PUBLIC_URL: {PUBLIC_URL}")
            self.url = PUBLIC_URL
            tunnel_ready.set()
            return self.url

        if self.service == "localhost":
            self.url = self._start_localhost_run()
        elif self.service == "ngrok":
            self.url = self._start_ngrok()
        elif self.service == "cloudflare":
            self.url = self._start_cloudflare()
        else:
            logger.warning(f"Неизвестный сервис туннеля: {self.service}, fallback на localhost.run")
            self.url = self._start_localhost_run()

        if self.url:
            tunnel_ready.set()
        return self.url

    def _start_localhost_run(self):
        try:
            logger.info("Запуск localhost.run туннеля...")
            self.process = subprocess.Popen(
                ['ssh', '-o', 'StrictHostKeyChecking=no', '-R', f'80:localhost:{self.port}', 'localhost.run'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            for _ in range(60):
                if self._stop.is_set():
                    return None
                line = self.process.stdout.readline()
                if line:
                    logger.debug(f"  {line.strip()}")
                    match = re.search(r'https://[a-z0-9\-]+\.loca\.lt', line)
                    if match:
                        url = match.group(0)
                        logger.info(f"Туннель localhost.run: {url}")
                        return url
                time.sleep(1)
            logger.warning("Не удалось получить URL от localhost.run")
            return None
        except Exception as e:
            logger.error(f"Ошибка localhost.run: {e}")
            return None

    def _start_ngrok(self):
        try:
            if not NGROK_AUTH_TOKEN:
                logger.error("Не задан NGROK_AUTH_TOKEN")
                return None
            logger.info("Запуск ngrok...")
            # Установим авторизационный токен
            subprocess.run(['ngrok', 'config', 'add-authtoken', NGROK_AUTH_TOKEN], capture_output=True)
            self.process = subprocess.Popen(
                ['ngrok', 'http', str(self.port), '--log=stdout'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            for _ in range(30):
                if self._stop.is_set():
                    return None
                line = self.process.stdout.readline()
                if line:
                    logger.debug(f"  {line.strip()}")
                    m = re.search(r'url=([^\s]+)', line)
                    if m:
                        url = m.group(1)
                        logger.info(f"Туннель ngrok: {url}")
                        return url
                time.sleep(1)
            logger.warning("Не удалось получить URL от ngrok")
            return None
        except Exception as e:
            logger.error(f"Ошибка ngrok: {e}")
            return None

    def _start_cloudflare(self):
        try:
            logger.info("Запуск Cloudflare Tunnel...")
            if CLOUDFLARE_TUNNEL_NAME:
                cmd = ['cloudflared', 'tunnel', 'run', '--url', f'http://localhost:{self.port}', CLOUDFLARE_TUNNEL_NAME]
            else:
                cmd = ['cloudflared', 'tunnel', '--url', f'http://localhost:{self.port}', '--no-autoupdate']
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            for _ in range(30):
                if self._stop.is_set():
                    return None
                line = self.process.stdout.readline()
                if line:
                    logger.debug(f"  {line.strip()}")
                    m = re.search(r'https://[a-z0-9\-]+\.trycloudflare\.com', line)
                    if m:
                        url = m.group(0)
                        logger.info(f"Туннель Cloudflare: {url}")
                        return url
                time.sleep(1)
            logger.warning("Не удалось получить URL от Cloudflare")
            return None
        except Exception as e:
            logger.error(f"Ошибка Cloudflare Tunnel: {e}")
            return None

    def stop(self):
        self._stop.set()
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def maintain_tunnel(self):
        """Бесконечный мониторинг и перезапуск при обрыве"""
        while not self._stop.is_set():
            if self.process and self.process.poll() is not None:
                logger.warning("Туннель упал, перезапуск через 5 сек...")
                time.sleep(5)
                self.start()
            time.sleep(10)

# ==================== ПЛЕЙЛИСТ ====================
def load_playlist():
    global playlist
    with playlist_lock:
        existing = set(playlist)
        new_files = set(Path(MUSIC_FOLDER).glob("*.mp3"))
        playlist = list(new_files)
        if playlist:
            random.shuffle(playlist)
            added = len(new_files - existing)
            removed = len(existing - new_files)
            if added or removed:
                logger.info(f"Плейлист обновлён: {len(playlist)} треков (+{added} -{removed})")
        else:
            logger.warning("Нет mp3 в папке music/")

def get_next_song_path():
    """Возвращает путь к новому треку, переключая индекс с потокобезопасностью"""
    global current_song_index, current_song_file, current_song_path, current_song_position
    with playlist_lock:
        if not playlist:
            return None
        current_song_index = (current_song_index + 1) % len(playlist)
        path = playlist[current_song_index]
    with song_lock:
        if current_song_file:
            current_song_file.close()
        current_song_file = open(path, 'rb')
        current_song_path = path
        current_song_position = 0
    logger.info(f"Сейчас играет: {path.name}")
    return str(path)

def get_current_song_info():
    with playlist_lock:
        if playlist and current_song_index < len(playlist):
            song = playlist[current_song_index]
            try:
                audio = MP3(song)
                duration = int(audio.info.length)
                title = os.path.splitext(song.name)[0]
                return {'title': title, 'duration': f"{duration//60}:{duration%60:02d}"}
            except Exception as e:
                logger.error(f"Ошибка чтения тегов: {e}")
                return {'title': os.path.splitext(song.name)[0], 'duration': '0:00'}
    return {'title': 'нет треков', 'duration': '0:00'}

# ==================== HTTP РАДИО СЕРВЕР ====================
class RadioHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # отключаем дефолтный лог

    def do_GET(self):
        if self.path in ['/radio.mp3', '/stream']:
            self.send_audio_stream()
        elif self.path == '/':
            self.serve_web_player()
        elif self.path == '/status':
            self.serve_json_status()
        else:
            self.send_error(404)

    def send_audio_stream(self):
        self.send_response(200)
        self.send_header('Content-Type', 'audio/mpeg')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        wfile = self.wfile
        with clients_lock:
            clients.append(wfile)
        logger.info(f"Слушатель подключился (всего: {len(clients)})")
        try:
            while True:
                time.sleep(1)  # держим соединение открытым
        except:
            pass
        finally:
            with clients_lock:
                if wfile in clients:
                    clients.remove(wfile)
            logger.info(f"Слушатель отключился (осталось: {len(clients)})")

    def serve_web_player(self):
        info = get_current_song_info()
        url = public_url or f"http://localhost:{PORT}"
        with clients_lock:
            listeners = len(clients)
        with playlist_lock:
            total = len(playlist)

        html = f'''<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<title>Super Radio</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh;display:flex;justify-content:center;align-items:center;padding:20px}}
.player{{background:rgba(255,255,255,0.95);border-radius:30px;padding:40px;max-width:500px;width:100%;text-align:center;box-shadow:0 25px 50px rgba(0,0,0,0.3)}}
h1{{color:#764ba2;margin-bottom:10px}}
.status{{color:#4caf50;font-weight:bold}}
audio{{width:100%;margin:20px 0;border-radius:30px}}
button{{background:linear-gradient(135deg,#667eea,#764ba2);color:white;border:none;padding:12px 24px;border-radius:30px;cursor:pointer;margin:5px}}
footer{{margin-top:20px;font-size:11px;color:#999}}
</style>
</head>
<body><div class="player">
<h1>🎵 Super Radio</h1>
<div class="status">🟢 LIVE</div>
<audio controls autoplay><source src="/radio.mp3" type="audio/mpeg"></audio>
<p>{info['title']} • 👥 {listeners} слушателей • 📀 {total} треков</p>
<a href="{url}">{url}</a><br>
<button onclick="window.open('/radio.mp3')">📥 Поток</button>
<button onclick="navigator.clipboard.writeText('{url}')">🔗 Копировать ссылку</button>
<footer>Открой в VLC: Media → Open Network Stream → {url}/radio.mp3</footer>
</div></body>
</html>'''
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def serve_json_status(self):
        info = get_current_song_info()
        with clients_lock:
            listeners = len(clients)
        with playlist_lock:
            total = len(playlist)
        data = {
            'current_song': info['title'],
            'duration': info['duration'],
            'listeners': listeners,
            'playlist_size': total
        }
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

def run_radio_server():
    server = HTTPServer(('0.0.0.0', PORT), RadioHandler)
    logger.info(f"Радио HTTP сервер на порту {PORT}")
    server.serve_forever()

# ==================== АУДИО ПОТОК ====================
def audio_stream():
    global current_song_file, current_song_position
    while True:
        try:
            if not playlist:
                time.sleep(5)
                continue
            # Если нет текущего трека – запускаем следующий
            with song_lock:
                if not current_song_file:
                    get_next_song_path()

            # Читаем и раздаём
            with song_lock:
                if current_song_file:
                    current_song_file.seek(current_song_position)
                    chunk = current_song_file.read(8192)
                    if chunk:
                        current_song_position += len(chunk)
                        # Рассылаем клиентам
                        with clients_lock:
                            broken = []
                            for client in clients:
                                try:
                                    client.write(chunk)
                                    client.flush()
                                except:
                                    broken.append(client)
                            for b in broken:
                                clients.remove(b)
                    else:
                        # Песня кончилась
                        get_next_song_path()
            time.sleep(0.05)
        except Exception as e:
            logger.error(f"Ошибка в аудиопотоке: {e}")
            time.sleep(2)
            # Попробуем переоткрыть файл
            with song_lock:
                if current_song_file:
                    current_song_file.close()
                    current_song_file = None

def playlist_monitor():
    """Фоновый поток, периодически проверяющий новые файлы"""
    while True:
        load_playlist()
        time.sleep(30)

# ==================== TELEGRAM БОТ ====================
@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "No username"
    conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, date) VALUES (?, ?, ?)",
              (user_id, username, datetime.now().isoformat()))
    conn.commit()
    conn.close()

    if not tunnel_ready.is_set():
        await message.answer("⏳ Радио ещё запускается, подождите 30-60 секунд...")
        return

    info = get_current_song_info()
    with clients_lock:
        listeners = len(clients)

    buttons = [
        [InlineKeyboardButton(text="🎵 ОТКРЫТЬ ПЛЕЕР", url=public_url)],
        [InlineKeyboardButton(text="📥 СКАЧАТЬ ПОТОК", url=f"{public_url}/radio.mp3")],
        [InlineKeyboardButton(text="📤 ОТПРАВИТЬ ТРЕК", callback_data="upload")],
        [InlineKeyboardButton(text="📊 СТАТУС", callback_data="status")]
    ]
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="⏭ ПРОПУСТИТЬ", callback_data="skip")])
        buttons.append([InlineKeyboardButton(text="🔁 ОБНОВИТЬ ПЛЕЙЛИСТ", callback_data="reload")])
        buttons.append([InlineKeyboardButton(text="🔧 АДМИН", callback_data="admin")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        f"🎵 *SUPER RADIO 2.0*\n\n"
        f"🎤 `{info['title']}`\n"
        f"👥 {listeners} слушателей | 📀 {len(playlist)} треков\n"
        f"🔗 `{public_url}`",
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    data = callback.data
    if data == "status":
        info = get_current_song_info()
        with clients_lock:
            listeners = len(clients)
        await callback.message.edit_text(
            f"📊 *СТАТУС*\n🎵 {info['title']}\n👥 {listeners} слушателей\n📀 {len(playlist)} треков",
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == "upload":
        await callback.message.edit_text("📤 Отправь мне MP3 файл (до 50 МБ).")
    elif data == "skip" and callback.from_user.id in ADMIN_IDS:
        get_next_song_path()
        await callback.answer("⏭ Трек пропущен!")
    elif data == "reload" and callback.from_user.id in ADMIN_IDS:
        load_playlist()
        await callback.answer("🔁 Плейлист обновлён!")
    elif data == "admin" and callback.from_user.id in ADMIN_IDS:
        await show_admin_panel(callback)
    elif data.startswith("approve_"):
        await approve_reject_song(callback, approve=True)
    elif data.startswith("reject_"):
        await approve_reject_song(callback, approve=False)
    elif data == "back":
        await start_command(callback.message)
    else:
        await callback.answer()
    await callback.answer()

async def show_admin_panel(callback: types.CallbackQuery):
    conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
    c = conn.cursor()
    c.execute("SELECT id, filename, user_name, date FROM pending_songs ORDER BY date DESC LIMIT 10")
    pending = c.fetchall()
    conn.close()
    kb = []
    for id_, fname, uname, _ in pending:
        kb.append([
            InlineKeyboardButton(text=f"✅ {fname[:25]}", callback_data=f"approve_{id_}"),
            InlineKeyboardButton(text="❌", callback_data=f"reject_{id_}")
        ])
    if not pending:
        kb.append([InlineKeyboardButton(text="Нет треков", callback_data="none")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back")])
    await callback.message.edit_text(
        f"🔧 *АДМИН ПАНЕЛЬ*\nТреков на модерации: {len(pending)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode=ParseMode.MARKDOWN
    )

async def approve_reject_song(callback: types.CallbackQuery, approve: bool):
    song_id = int(callback.data.split('_')[1])
    conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
    c = conn.cursor()
    c.execute("SELECT filename FROM pending_songs WHERE id = ?", (song_id,))
    row = c.fetchone()
    if not row:
        await callback.message.edit_text("❌ Трек не найден")
        conn.close()
        return
    filename = row[0]
    src = Path("pending") / filename
    if approve:
        dst = Path(MUSIC_FOLDER) / filename
        if src.exists():
            src.rename(dst)
            load_playlist()
        c.execute("DELETE FROM pending_songs WHERE id=?", (song_id,))
        await callback.message.edit_text("✅ Трек одобрен!")
    else:
        if src.exists():
            src.unlink()
        c.execute("DELETE FROM pending_songs WHERE id=?", (song_id,))
        await callback.message.edit_text("❌ Трек отклонён")
    conn.commit()
    conn.close()
    await show_admin_panel(callback)

@dp.message(F.audio)
async def handle_audio(message: types.Message):
    if message.audio.file_size > 50 * 1024 * 1024:
        await message.reply("❌ Файл > 50 МБ")
        return
    msg = await message.reply("📥 Загружаю...")
    try:
        file_info = await bot.get_file(message.audio.file_id)
        filename = message.audio.file_name or "track.mp3"
        dest = Path("pending") / filename
        await bot.download_file(file_info.file_path, destination=str(dest))
        conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
        c = conn.cursor()
        c.execute("INSERT INTO pending_songs (filename, user_id, user_name, date) VALUES (?,?,?,?)",
                  (filename, message.from_user.id, message.from_user.username, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        await msg.edit_text("✅ Трек отправлен на модерацию")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

@dp.message(Command("link"))
async def link_command(message: types.Message):
    if not public_url:
        await message.reply("⏳ Туннель ещё не готов")
        return
    await message.reply(f"🔗 Ссылка для друзей:\n`{public_url}`", parse_mode=ParseMode.MARKDOWN)

# ==================== ГЛАВНАЯ ЛОГИКА ЗАПУСКА ====================
async def main():
    logger.info("=" * 50)
    logger.info("  SUPER RADIO BOT 2.0")
    logger.info("=" * 50)

    # Загружаем плейлист
    load_playlist()

    # HTTP сервер
    threading.Thread(target=run_radio_server, daemon=True).start()
    # Аудио поток
    threading.Thread(target=audio_stream, daemon=True).start()
    # Монитор плейлиста
    threading.Thread(target=playlist_monitor, daemon=True).start()

    # Туннель
    global public_url
    if not PUBLIC_URL:
        tm = TunnelManager(TUNNEL_SERVICE, PORT)
        public_url = tm.start()
        if public_url:
            threading.Thread(target=tm.maintain_tunnel, daemon=True).start()
        else:
            logger.warning("Туннель не запущен, но радио работает локально")
    else:
        public_url = PUBLIC_URL

    if public_url:
        logger.info(f"Публичная ссылка: {public_url}")

    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == '__main__':
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановка...")
