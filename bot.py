#!/usr/bin/env python3
"""
МИНИ-РАДИО на CloudPub
- Встроенный HTTP-плеер на порту 8080
- Стриминг mp3-потока /radio.mp3
- Telegram-бот для загрузки треков
"""

import os, sys, time, threading, random, logging, asyncio
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.enums import ParseMode

# ---------- КОНФИГУРАЦИЯ ----------
PORT = int(os.getenv("PORT", "8080"))
MUSIC_FOLDER = os.getenv("MUSIC_FOLDER", "music")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
PUBLIC_URL = os.getenv("PUBLIC_URL", "")

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
        path = playlist[0]  # цикл по кругу можно добавить, но оставим случайный
        playlist.append(playlist.pop(0))
    with song_lock:
        if current_song_file:
            current_song_file.close()
        current_song_file = open(path, 'rb')
        current_song_position = 0
        logging.info(f"Сейчас играет: {path.name}")

# ---------- HTTP-СЕРВЕР РАДИО ----------
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
<audio controls autoplay><source src="/radio.mp3" type="audio/mpeg"></audio>
<a href="{url}">{url}</a><br>
<button onclick="window.open('/radio.mp3')">📥 Поток</button>
<footer>Открой в VLC: Media → Open Network Stream → {url}/radio.mp3</footer>
</div></body>
</html>'''
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

# ---------- ПОТОКОВАЯ РАЗДАЧА ----------
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

# ---------- TELEGRAM БОТ ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    buttons = []
    if PUBLIC_URL.startswith("https://"):
        buttons.append([InlineKeyboardButton(text="🎵 СЛУШАТЬ", url=PUBLIC_URL)])
    buttons.append([InlineKeyboardButton(text="📤 ЗАГРУЗИТЬ", callback_data="upload")])
    if message.from_user.id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="⏭ СЛЕДУЮЩИЙ", callback_data="next")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(
        f"🎵 *Super Radio Mini*\nСсылка: `{PUBLIC_URL}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

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
        await message.reply("❌ Только MP3")
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
    logging.basicConfig(level=logging.INFO)
    load_playlist()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', PORT), RadioHandler).serve_forever(), daemon=True).start()
    threading.Thread(target=audio_stream, daemon=True).start()
    threading.Thread(target=playlist_monitor, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
