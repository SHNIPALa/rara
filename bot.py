#!/usr/bin/env python3
"""
Super Radio – автодиджей с плавными переходами.
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

# ---------- Настройки ----------
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

Path(MUSIC_FOLDER).mkdir(exist_ok=True)
Path(PENDING_FOLDER).mkdir(exist_ok=True)
Path(DATA_FOLDER).mkdir(exist_ok=True)

PENDING_DB = Path(DATA_FOLDER) / "pending_songs.json"
if not PENDING_DB.exists():
    PENDING_DB.write_text("[]")

# ---------- База заявок ----------
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
    songs.append({"filename": filename, "user_id": user_id, "user_name": user_name, "date": datetime.now().isoformat()})
    save_pending_songs(songs)

def remove_pending_song(filename):
    songs = load_pending_songs()
    songs = [s for s in songs if s["filename"] != filename]
    save_pending_songs(songs)

# ---------- Плейлист с предзагрузкой ----------
playlist, playlist_lock = [], threading.Lock()
current_song_file = None          # текущий открытый файл
current_song_position = 0
next_song_file = None             # предзагруженный следующий файл
current_song_info = "Нет треков"
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

def preload_next():
    """Загружаем следующий трек (файл) в next_song_file, если есть."""
    global next_song_file
    with playlist_lock:
        if not playlist:
            return
        # берём следующий, не трогая основной список
        if len(playlist) >= 1:
            path = playlist[0]   # первый в очереди (после текущего)
            try:
                next_song_file = open(path, 'rb')
                logging.info(f"Предзагружен: {path.name}")
            except Exception as e:
                logging.error(f"Ошибка предзагрузки {path.name}: {e}")
                next_song_file = None

def switch_to_next():
    """Переключаем текущий трек на предзагруженный."""
    global current_song_file, current_song_position, current_song_info, next_song_file
    with song_lock:
        # Закрываем старый
        if current_song_file:
            current_song_file.close()
        # Подставляем предзагруженный
        current_song_file = next_song_file
        next_song_file = None
        current_song_position = 0
        if current_song_file:
            # Читаем теги
            path = Path(current_song_file.name)
            try:
                tags = MP3(path)
                artist = tags.get("TPE1", ["Неизвестен"])[0]
                title = tags.get("TIT2", [path.stem])[0]
                current_song_info = f"{artist} - {title}"
            except:
                current_song_info = path.stem
            logging.info(f"Сейчас играет: {current_song_info}")
        else:
            current_song_info = "Нет треков"
    # Перемещаем плейлист: удаляем первый элемент (который только что стал текущим)
    with playlist_lock:
        if playlist:
            playlist.pop(0)   # убираем текущий
        # Запускаем предзагрузку следующего (новый первый элемент)
        preload_next()

# ---------- HTTP-сервер ----------
class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class RadioHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logging.info(f"[HTTP] {self.address_string()} - {format % args}")

    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b"OK")
            return

        # Чистый аудиопоток
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
                time.sleep(60)
        except:
            pass
        finally:
            with clients_lock:
                if wfile in clients:
                    clients.remove(wfile)

# ---------- Потоковая раздача (с автодиджеем) ----------
def audio_stream():
    global current_song_file, current_song_position
    while True:
        if not playlist and not current_song_file:
            time.sleep(5)
            continue
        with song_lock:
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
                    # Трек закончился, переключаем на следующий
                    switch_to_next()
        time.sleep(0.05)

def playlist_monitor():
    while True:
        load_playlist()
        # Если плейлист есть, но воспроизведение не начато – запускаем
        with song_lock:
            if playlist and not current_song_file:
                # Берём первый трек
                path = playlist.pop(0)
                current_song_file = open(path, 'rb')
                current_song_position = 0
                # обновим info
                try:
                    tags = MP3(path)
                    artist = tags.get("TPE1", ["Неизвестен"])[0]
                    title = tags.get("TIT2", [path.stem])[0]
                    current_song_info = f"{artist} - {title}"
                except:
                    current_song_info = path.stem
                logging.info(f"Начало вещания: {current_song_info}")
                preload_next()  # загружаем следующий сразу
        time.sleep(30)

# ---------- Туннель Cloudflare ----------
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

    cmd = ['cloudflared', '--no-autoupdate', 'tunnel', '--url', f'http://127.0.0.1:{PORT}']
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

# ---------- Бот ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def main_menu_keyboard(user_id):
    buttons = []
    if PUBLIC_URL:
        buttons.append([InlineKeyboardButton(text="🔊 СЛУШАТЬ ПОТОК", url=PUBLIC_URL)])
    buttons.append([InlineKeyboardButton(text="📤 ЗАГРУЗИТЬ", callback_data="upload")])
    if user_id in ADMIN_IDS:
        pending_count = len(load_pending_songs())
        btn_text = f"🔧 МОДЕРАЦИЯ ({pending_count})" if pending_count else "🔧 МОДЕРАЦИЯ"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data="moderate")])
        buttons.append([InlineKeyboardButton(text="⏭ СЛЕДУЮЩИЙ", callback_data="next_song")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    kb = main_menu_keyboard(message.from_user.id)
    info = ""
    if TUNNEL_ERROR:
        info = f"❌ Ошибка туннеля: {TUNNEL_ERROR}\n"
    elif PUBLIC_URL:
        song_escaped = current_song_info.replace("<", "&lt;").replace(">", "&gt;")
        url_escaped = PUBLIC_URL.replace("<", "&lt;").replace(">", "&gt;")
        info = (f"🎧 <b>{song_escaped}</b>\n"
                f"🔊 Прямой эфир: <a href='{url_escaped}'>{url_escaped}</a>\n")
    else:
        info = "⏳ Туннель ещё поднимается...\n"
    await message.answer(f"🎵 <b>Super Radio DJ</b>\n{info}", parse_mode=ParseMode.HTML, reply_markup=kb)

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id
    if data == "upload":
        await callback.message.edit_text("📤 Отправь MP3. Если ты не админ, трек попадёт на модерацию.")
    elif data == "next_song" and user_id in ADMIN_IDS:
        switch_to_next()   # принудительное переключение
        await callback.answer("⏭ Следующий трек")
        await start_cmd(callback.message)
    elif data == "moderate" and user_id in ADMIN_IDS:
        await show_moderation_panel(callback)
    elif data.startswith("approve_") and user_id in ADMIN_IDS:
        filename = data[len("approve_"):]
        approve_song(filename)
        await callback.answer("✅ Одобрено")
        await show_moderation_panel(callback)
    elif data.startswith("reject_") and user_id in ADMIN_IDS:
        filename = data[len("reject_"):]
        reject_song(filename)
        await callback.answer("❌ Отклонено")
        await show_moderation_panel(callback)
    elif data == "back_to_main":
        await start_cmd(callback.message)
    await callback.answer()

async def show_moderation_panel(callback):
    songs = load_pending_songs()
    if not songs:
        await callback.message.edit_text("🎛 *Модерация*\n\nНет треков.", parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
            ]))
        return
    text = "🎛 *Треки на модерации:*\n\n"
    kb = []
    for song in songs:
        fname = song["filename"]
        text += f"📁 `{fname[:25]}` от {song['user_name']}\n"
        kb.append([
            InlineKeyboardButton(text=f"✅ {fname[:10]}", callback_data=f"approve_{fname}"),
            InlineKeyboardButton(text="❌", callback_data=f"reject_{fname}")
        ])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")])
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

def approve_song(filename):
    src = Path(PENDING_FOLDER) / filename
    dst = Path(MUSIC_FOLDER) / filename
    if src.exists():
        src.rename(dst)
        load_playlist()
        # если текущего трека нет, запустим воспроизведение
        with song_lock:
            if not current_song_file and playlist:
                first = playlist.pop(0)
                global current_song_file, current_song_position, current_song_info
                current_song_file = open(first, 'rb')
                current_song_position = 0
                try:
                    tags = MP3(first)
                    artist = tags.get("TPE1", ["Неизвестен"])[0]
                    title = tags.get("TIT2", [first.stem])[0]
                    current_song_info = f"{artist} - {title}"
                except:
                    current_song_info = first.stem
                preload_next()
    remove_pending_song(filename)

def reject_song(filename):
    src = Path(PENDING_FOLDER) / filename
    if src.exists():
        src.unlink()
    remove_pending_song(filename)

@dp.message(F.audio | F.document)
async def handle_file(message: types.Message):
    file = message.audio or message.document
    if not file: return
    fname = file.file_name or "track.mp3"
    if not fname.lower().endswith((".mp3", ".ogg", ".flac", ".m4a", ".wav")):
        await message.reply("❌ Поддерживаются MP3, OGG, FLAC, M4A, WAV")
        return
    if file.file_size > 50*1024*1024:
        await message.reply("❌ >50 МБ")
        return
    msg = await message.reply("📥 Загружаю…")
    try:
        file_info = await bot.get_file(file.file_id)
        user_id = message.from_user.id
        user_name = message.from_user.username or str(user_id)
        if user_id in ADMIN_IDS:
            dest = Path(MUSIC_FOLDER) / fname
            await bot.download_file(file_info.file_path, destination=str(dest))
            load_playlist()
            # если ничего не играет, запустим
            with song_lock:
                if not current_song_file and playlist:
                    first = playlist.pop(0)
                    global current_song_file, current_song_position, current_song_info
                    current_song_file = open(first, 'rb')
                    current_song_position = 0
                    try:
                        tags = MP3(first)
                        artist = tags.get("TPE1", ["Неизвестен"])[0]
                        title = tags.get("TIT2", [first.stem])[0]
                        current_song_info = f"{artist} - {title}"
                    except:
                        current_song_info = first.stem
                    preload_next()
            await msg.edit_text("✅ Трек сразу в эфире!")
        else:
            dest = Path(PENDING_FOLDER) / fname
            await bot.download_file(file_info.file_path, destination=str(dest))
            add_pending_song(fname, user_id, user_name)
            await msg.edit_text("📨 Отправлено на модерацию. Спасибо!")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

async def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    logging.info("Запуск Super Radio DJ...")
    load_playlist()
    # Стартуем сервер
    server = ThreadedHTTPServer(('0.0.0.0', PORT), RadioHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=audio_stream, daemon=True).start()
    threading.Thread(target=playlist_monitor, daemon=True).start()
    threading.Thread(target=start_cloudflare_tunnel, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
