#!/usr/bin/env python3
"""
СУПЕР-РАДИО + МОДЕРАЦИЯ ТРЕКОВ
- Чистый аудиопоток (без HTML)
- Авто-туннель Cloudflare с health-check
- Обычные пользователи загружают треки в pending
- Админы принимают/отклоняют треки через кнопку "Модерация"
- Читаемые названия через mutagen
"""

import os, time, threading, random, logging, asyncio, subprocess, re, socket, json
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from mutagen.mp3 import MP3

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.enums import ParseMode

# ---------- КОНФИГУРАЦИЯ ----------
PORT = int(os.getenv("PORT", "8080"))
MUSIC_FOLDER = os.getenv("MUSIC_FOLDER", "music")
PENDING_FOLDER = os.getenv("PENDING_FOLDER", "pending")
DATA_FOLDER = os.getenv("DATA_FOLDER", "data")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def parse_admin_ids():
    raw = os.getenv("ADMIN_IDS", "")
    return [int(x.strip()) for x in raw.split(",") if x.strip()] if raw else []

ADMIN_IDS = parse_admin_ids()
PUBLIC_URL = ""
TUNNEL_ERROR = None

# Создаём необходимые папки
Path(MUSIC_FOLDER).mkdir(exist_ok=True)
Path(PENDING_FOLDER).mkdir(exist_ok=True)
Path(DATA_FOLDER).mkdir(exist_ok=True)

# Файл для хранения списка треков на модерации
PENDING_DB = Path(DATA_FOLDER) / "pending_songs.json"
if not PENDING_DB.exists():
    PENDING_DB.write_text("[]")

# ---------- РАБОТА С БАЗОЙ ПРЕДЛОЖЕННЫХ ТРЕКОВ ----------
def load_pending_songs():
    try:
        with open(PENDING_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_pending_songs(songs):
    with open(PENDING_DB, "w", encoding="utf-8") as f:
        json.dump(songs, f, ensure_ascii=False, indent=2)

def add_pending_song(filename, user_id, user_name):
    songs = load_pending_songs()
    songs.append({
        "filename": filename,
        "user_id": user_id,
        "user_name": user_name,
        "date": datetime.now().isoformat()
    })
    save_pending_songs(songs)

def remove_pending_song(filename):
    songs = load_pending_songs()
    songs = [s for s in songs if s["filename"] != filename]
    save_pending_songs(songs)

# ---------- ПЛЕЙЛИСТ ----------
playlist, playlist_lock = [], threading.Lock()
current_song_file, current_song_position, current_song_info = None, 0, "Нет треков"
song_lock = threading.Lock()
clients, clients_lock = [], threading.Lock()

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
    global current_song_file, current_song_position, current_song_info
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
        try:
            tags = MP3(path)
            artist = tags.get("TPE1", ["Неизвестен"])[0]
            title = tags.get("TIT2", [path.stem])[0]
            current_song_info = f"{artist} - {title}"
        except:
            current_song_info = path.stem
        logging.info(f"Сейчас играет: {current_song_info}")

# ---------- HTTP-СЕРВЕР ----------
class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class RadioHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logging.info(f"[HTTP] {self.address_string()} - {format % args}")

    def do_GET(self):
        logging.info(f"Запрос: {self.path}")
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b"OK")
            return

        # Аудиопоток
        self.send_response(200)
        self.send_header('Content-Type', 'audio/mpeg')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        wfile = self.wfile

        # Немедленно отправляем начальный фрагмент
        with song_lock:
            if current_song_file:
                current_song_file.seek(current_song_position)
                initial_chunk = current_song_file.read(16384)
                if initial_chunk:
                    wfile.write(initial_chunk)
                    wfile.flush()

        with clients_lock:
            clients.append(wfile)
        logging.info(f"Слушатель добавлен (всего {len(clients)})")

        try:
            while True:
                time.sleep(60)
        except:
            pass
        finally:
            with clients_lock:
                if wfile in clients:
                    clients.remove(wfile)

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
        time.sleep(0.1)

def playlist_monitor():
    while True:
        load_playlist()
        time.sleep(30)

# ---------- ТУННЕЛЬ ----------
def start_cloudflare_tunnel():
    global PUBLIC_URL, TUNNEL_ERROR
    logging.info(f"Ожидание порта {PORT}...")
    for _ in range(60):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        if s.connect_ex(('127.0.0.1', PORT)) == 0:
            s.close()
            logging.info("Порт открыт, запускаю cloudflared...")
            break
        s.close()
        time.sleep(0.5)
    else:
        TUNNEL_ERROR = "HTTP-сервер не запустился"
        logging.error(TUNNEL_ERROR)
        return

    cmd = ['cloudflared', 'tunnel', '--no-autoupdate', '--url', f'http://127.0.0.1:{PORT}']
    logging.info(f"Выполняется: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    except Exception as e:
        TUNNEL_ERROR = f"Не удалось запустить cloudflared: {e}"
        logging.error(TUNNEL_ERROR)
        return

    pattern = re.compile(r'https://[a-zA-Z0-9\-]+\.trycloudflare\.com')
    start_time = time.time()
    for line in proc.stdout:
        logging.info(f"[cloudflared] {line.strip()}")
        match = pattern.search(line)
        if match:
            url = match.group(0)
            PUBLIC_URL = url
            logging.info(f"✅ Публичный URL: {url}")
            def keep_alive():
                for _ in proc.stdout:
                    pass
            threading.Thread(target=keep_alive, daemon=True).start()
            return
        if time.time() - start_time > 30:
            TUNNEL_ERROR = "Туннель не выдал URL за 30 секунд"
            logging.error(TUNNEL_ERROR)
            break
    else:
        TUNNEL_ERROR = f"cloudflared завершился (код {proc.poll()})"
        logging.error(TUNNEL_ERROR)

# ---------- TELEGRAM БОТ ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Клавиатура для админов в /start
def main_menu_keyboard(user_id):
    buttons = []
    if PUBLIC_URL:
        buttons.append([InlineKeyboardButton(text="🎵 СЛУШАТЬ", url=PUBLIC_URL)])
    buttons.append([InlineKeyboardButton(text="📤 ЗАГРУЗИТЬ", callback_data="upload")])
    if user_id in ADMIN_IDS:
        pending_count = len(load_pending_songs())
        btn_text = f"🔧 МОДЕРАЦИЯ ({pending_count})" if pending_count else "🔧 МОДЕРАЦИЯ"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data="moderate")])
        buttons.append([InlineKeyboardButton(text="⏭ СЛЕДУЮЩИЙ", callback_data="next")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    kb = main_menu_keyboard(user_id)

    info_text = ""
    if TUNNEL_ERROR:
        info_text = f"❌ Ошибка туннеля: {TUNNEL_ERROR}\n"
    elif PUBLIC_URL:
        info_text = f"🔊 {current_song_info}\n🎧 Прямой эфир: `{PUBLIC_URL}`\n"
    else:
        info_text = "⏳ Туннель ещё поднимается...\n"

    await message.answer(
        f"🎵 *Super Radio Stream*\n{info_text}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id

    if data == "upload":
        await callback.message.edit_text("📤 Отправь мне MP3 файл.\nЕсли ты не админ, трек попадёт на модерацию.")
    elif data == "next" and user_id in ADMIN_IDS:
        next_song()
        await callback.answer("⏭ Трек переключён")
    elif data == "moderate" and user_id in ADMIN_IDS:
        await show_moderation_panel(callback)
    elif data.startswith("approve_") and user_id in ADMIN_IDS:
        filename = data[len("approve_"):]
        approve_song(filename)
        await callback.answer("✅ Трек одобрен")
        await show_moderation_panel(callback)
    elif data.startswith("reject_") and user_id in ADMIN_IDS:
        filename = data[len("reject_"):]
        reject_song(filename)
        await callback.answer("❌ Трек отклонён")
        await show_moderation_panel(callback)
    elif data == "back_to_main":
        await start_cmd(callback.message)
    await callback.answer()

async def show_moderation_panel(callback):
    songs = load_pending_songs()
    if not songs:
        await callback.message.edit_text(
            "🎛 *Модерация треков*\n\nНет треков на рассмотрении.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
            ])
        )
        return

    text = "🎛 *Треки на модерации:*\n\n"
    kb = []
    for song in songs:
        fname = song["filename"]
        text += f"📁 `{fname[:25]}` от {song['user_name']} ({song['date'][:10]})\n"
        kb.append([
            InlineKeyboardButton(text=f"✅ {fname[:10]}", callback_data=f"approve_{fname}"),
            InlineKeyboardButton(text="❌", callback_data=f"reject_{fname}")
        ])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")])

    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

def approve_song(filename):
    src = Path(PENDING_FOLDER) / filename
    dst = Path(MUSIC_FOLDER) / filename
    if src.exists():
        src.rename(dst)
        load_playlist()
    remove_pending_song(filename)

def reject_song(filename):
    src = Path(PENDING_FOLDER) / filename
    if src.exists():
        src.unlink()
    remove_pending_song(filename)

# Обработчик загрузки файлов
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
        user_id = message.from_user.id
        user_name = message.from_user.username or str(user_id)

        if user_id in ADMIN_IDS:
            # Админы загружают сразу в музыку
            dest = Path(MUSIC_FOLDER) / fname
            await bot.download_file(file_info.file_path, destination=str(dest))
            load_playlist()
            await msg.edit_text("✅ Трек сразу добавлен в эфир!")
        else:
            # Обычные пользователи – в pending
            dest = Path(PENDING_FOLDER) / fname
            await bot.download_file(file_info.file_path, destination=str(dest))
            add_pending_song(fname, user_id, user_name)
            await msg.edit_text("📨 Трек отправлен на модерацию. Спасибо!")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

async def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    logging.info("Super Radio + Moderation запускается...")
    load_playlist()

    server = ThreadedHTTPServer(('0.0.0.0', PORT), RadioHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=audio_stream, daemon=True).start()
    threading.Thread(target=playlist_monitor, daemon=True).start()
    threading.Thread(target=start_cloudflare_tunnel, daemon=True).start()

    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
