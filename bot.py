#!/usr/bin/env python3
"""
МИНИ-РАДИО + авто-обнаружение URL от CloudPub
- Стримит mp3 на порту 8080
- Читает публичный URL из /shared/cloudpub_url.txt
- Выводит его в собственный лог
- Позволяет установить URL вручную через /seturl (админ)
"""

import os, time, threading, random, logging, asyncio, re
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.enums import ParseMode

# ---------- НАСТРОЙКИ ----------
PORT = int(os.getenv("PORT", "8080"))
MUSIC_FOLDER = os.getenv("MUSIC_FOLDER", "music")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def parse_admin_ids():
    raw = os.getenv("ADMIN_IDS", "")
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]

ADMIN_IDS = parse_admin_ids()

SHARED_DIR = os.getenv("SHARED_DIR", "/shared")
URL_FILE = Path(SHARED_DIR) / "cloudpub_url.txt"

# Глобальный URL – пытаемся загрузить из файла
PUBLIC_URL = ""
if URL_FILE.exists():
    PUBLIC_URL = URL_FILE.read_text().strip()

Path(MUSIC_FOLDER).mkdir(exist_ok=True)

# ---------- ПЛЕЙЛИСТ ----------
playlist = []
playlist_lock = threading.Lock()
current_song_file = None
current_song_position = 0
song_lock = threading.Lock()
clients = []
clients_lock = threading.Lock()

def load_playlist():
    global playlist
    with playlist_lock:
        playlist = list(Path(MUSIC_FOLDER).glob("*.mp3"))
        if playlist:
            random.shuffle(playlist)
            logging.info(f"Загружено {len(playlist)} треков")
        else:
            logging.warning("Нет mp3 в папке music/")

def next_song():
    global current_song_file, current_song_position
    with playlist_lock:
        if not playlist:
            return
        path = playlist[0]
        playlist.append(playlist.pop(0))
    with song_lock:
        if current_song_file:
            current_song_file.close()
        current_song_file = open(path, 'rb')
        current_song_position = 0
        logging.info(f"Сейчас играет: {path.name}")

# ---------- HTTP-СЕРВЕР ----------
class RadioHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/radio.mp3', '/stream'):
            self.send_audio_stream()
        elif self.path == '/':
            self.serve_web_player()
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
        logging.info(f"Слушатель добавлен (всего {len(clients)})")
        try:
            while True:
                time.sleep(1)
        except:
            pass
        finally:
            with clients_lock:
                if wfile in clients:
                    clients.remove(wfile)

    def serve_web_player(self):
        url = PUBLIC_URL or f"http://localhost:{PORT}"
        stream_url = url.rstrip('/') + "/radio.mp3"
        with clients_lock:
            listeners = len(clients)
        with playlist_lock:
            total = len(playlist)
        html = f'''<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Radio</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font-family:sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh;display:flex;justify-content:center;align-items:center;padding:20px;margin:0}}
.player{{background:rgba(255,255,255,0.95);border-radius:25px;padding:30px;max-width:500px;width:100%;text-align:center;box-shadow:0 20px 40px rgba(0,0,0,0.3)}}
h1{{color:#764ba2}} audio{{width:100%;margin:20px 0}}
button{{background:linear-gradient(135deg,#667eea,#764ba2);color:white;border:none;padding:12px 24px;border-radius:25px;cursor:pointer;margin:5px}}
footer{{margin-top:20px;font-size:12px;color:#999}}
</style></head>
<body><div class="player">
<h1>🎵 Super Radio</h1>
<p>👥 {listeners} слушателей | 📀 {total} треков</p>
<audio controls autoplay><source src="{stream_url}" type="audio/mpeg"></audio>
<a href="{url}">{url}</a><br>
<button onclick="window.open('{stream_url}')">📥 Поток</button>
<footer>Прямой поток: {stream_url}</footer>
</div></body>
</html>'''
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

# ---------- АУДИОПОТОК ----------
def audio_stream():
    global current_song_file, current_song_position
    while True:
        if not playlist:
            time.sleep(5)
            continue
        with song_lock:
            if not current_song_file:
                next_song()
            if current_song_file:
                current_song_file.seek(current_song_position)
                chunk = current_song_file.read(8192)
                if chunk:
                    current_song_position += len(chunk)
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
                    next_song()
        time.sleep(0.05)

def playlist_monitor():
    while True:
        load_playlist()
        time.sleep(30)

# ---------- ОБНАРУЖЕНИЕ URL ----------
def watch_for_url():
    """Фоновый поток: читает файл, вытаскивает URL и печатает в лог."""
    global PUBLIC_URL
    pattern = re.compile(r'(https://[a-zA-Z0-9\-]+\.cloudpub\.ru)')
    while True:
        try:
            if URL_FILE.exists():
                text = URL_FILE.read_text()
                match = pattern.search(text)
                if match:
                    url = match.group(1)
                    if url != PUBLIC_URL:
                        PUBLIC_URL = url
                        logging.info(f"✅ Публичный URL радио: {PUBLIC_URL}")
        except Exception as e:
            logging.error(f"Ошибка чтения файла URL: {e}")
        time.sleep(5)

# ---------- TELEGRAM БОТ ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    stream_url = ""
    if PUBLIC_URL:
        stream_url = PUBLIC_URL.rstrip('/') + "/radio.mp3"
    buttons = []
    if stream_url.startswith("https://"):
        buttons.append([InlineKeyboardButton(text="🎵 СЛУШАТЬ ПОТОК", url=stream_url)])
    buttons.append([InlineKeyboardButton(text="📤 ЗАГРУЗИТЬ", callback_data="upload")])
    if message.from_user.id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="⏭ СЛЕДУЮЩИЙ", callback_data="next")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(
        f"🎵 *Super Radio Mini*\n"
        f"Поток: `{stream_url or 'не задан'}`\n"
        f"Используйте /seturl <адрес> для ручной установки.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

@dp.message(Command("seturl"))
async def set_url_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔ Только для администраторов.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Использование: `/seturl https://ваш-домен.cloudpub.ru`", parse_mode=ParseMode.MARKDOWN)
        return
    new_url = parts[1].strip().rstrip('/')
    if not new_url.startswith("https://"):
        await message.reply("❌ URL должен начинаться с https://")
        return
    global PUBLIC_URL
    PUBLIC_URL = new_url
    try:
        URL_FILE.parent.mkdir(parents=True, exist_ok=True)
        URL_FILE.write_text(new_url)
        logging.info(f"Публичный URL установлен вручную: {PUBLIC_URL}")
        await message.reply(f"✅ Публичный URL сохранён:\n`{PUBLIC_URL}`", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logging.error(f"Ошибка записи URL: {e}")
        await message.reply(f"⚠️ URL установлен только на эту сессию: {e}")

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    if callback.data == "upload":
        await callback.message.edit_text("📤 Отправь мне MP3 файл.")
    elif callback.data == "next" and callback.from_user.id in ADMIN_IDS:
        next_song()
        await callback.answer("⏭ Переключили трек")
    await callback.answer()

@dp.message(F.audio | F.document)
async def handle_file(message: types.Message):
    file = message.audio or message.document
    if not file:
        return
    fname = file.file_name or "track.mp3"
    if not fname.lower().endswith((".mp3", ".ogg")):
        await message.reply("❌ Только MP3 или OGG")
        return
    if file.file_size > 50*1024*1024:
        await message.reply("❌ Файл >50 МБ")
        return
    msg = await message.reply("📥 Загружаю…")
    try:
        file_info = await bot.get_file(file.file_id)
        dest = Path(MUSIC_FOLDER) / fname
        await bot.download_file(file_info.file_path, destination=str(dest))
        load_playlist()
        await msg.edit_text("✅ Трек добавлен!")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

async def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    logging.info("Запуск мини-радио")
    load_playlist()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', PORT), RadioHandler).serve_forever(), daemon=True).start()
    threading.Thread(target=audio_stream, daemon=True).start()
    threading.Thread(target=playlist_monitor, daemon=True).start()
    threading.Thread(target=watch_for_url, daemon=True).start()
    logging.info("Бот запущен, ожидаю публичный URL...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
