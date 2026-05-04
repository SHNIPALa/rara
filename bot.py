#!/usr/bin/env python3
"""
Super Radio DJ – стабильный аудиопоток (final)
Немедленный старт, защита от зависших слушателей, автотуннель Cloudflare.
"""

import os, time, threading, random, logging, asyncio, subprocess, re, socket, json
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from mutagen.mp3 import MP3
from typing import List, Optional, Dict

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

def parse_admin_ids() -> List[int]:
    raw = os.getenv("ADMIN_IDS", "")
    return [int(x.strip()) for x in raw.split(",") if x.strip()] if raw else []

ADMIN_IDS = parse_admin_ids()
PUBLIC_URL = ""
TUNNEL_ERROR: Optional[str] = None

# Создаём папки
Path(MUSIC_FOLDER).mkdir(exist_ok=True)
Path(PENDING_FOLDER).mkdir(exist_ok=True)
Path(DATA_FOLDER).mkdir(exist_ok=True)

PENDING_DB = Path(DATA_FOLDER) / "pending_songs.json"
if not PENDING_DB.exists():
    PENDING_DB.write_text("[]")

# ---------- База заявок ----------
def load_pending_songs() -> list:
    try:
        with open(PENDING_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_pending_songs(songs: list) -> None:
    with open(PENDING_DB, "w", encoding="utf-8") as f:
        json.dump(songs, f, ensure_ascii=False, indent=2)

def add_pending_song(filename: str, user_id: int, user_name: str) -> None:
    songs = load_pending_songs()
    songs.append({"filename": filename, "user_id": user_id, "user_name": user_name,
                  "date": datetime.now().isoformat()})
    save_pending_songs(songs)

def remove_pending_song(filename: str) -> None:
    songs = load_pending_songs()
    songs = [s for s in songs if s["filename"] != filename]
    save_pending_songs(songs)

# ================== Радиоплеер ==================
class RadioPlayer:
    def __init__(self, max_clients=100, client_timeout=30):
        self.playlist: List[Path] = []
        self.current_file: Optional[object] = None
        self.position = 0
        self.next_file: Optional[object] = None
        self.song_info = "Нет треков"
        self.lock = threading.Lock()

        # Учёт клиентов с временем последней активности
        self.clients: Dict[object, float] = {}
        self.clients_lock = threading.Lock()
        self.max_clients = max_clients
        self.client_timeout = client_timeout

    def load_playlist(self):
        with self.lock:
            self.playlist = list(Path(MUSIC_FOLDER).glob("*.mp3"))
            if self.playlist:
                random.shuffle(self.playlist)
                logging.info(f"Плейлист обновлён: {len(self.playlist)} треков")
            else:
                logging.warning("Нет mp3 в папке music/")

    def preload_next(self):
        with self.lock:
            if self.playlist and self.next_file is None:
                path = self.playlist[0]
                try:
                    self.next_file = open(path, 'rb')
                    logging.debug(f"Предзагружен: {path.name}")
                except Exception as e:
                    logging.error(f"Не удалось предзагрузить {path.name}: {e}")
                    self.next_file = None

    def switch_to_next(self):
        with self.lock:
            if self.current_file:
                self.current_file.close()
            self.current_file = self.next_file
            self.next_file = None
            self.position = 0

            if self.current_file:
                path = Path(self.current_file.name)
                try:
                    tags = MP3(path)
                    artist = tags.get("TPE1", ["Неизвестен"])[0]
                    title = tags.get("TIT2", [path.stem])[0]
                    self.song_info = f"{artist} - {title}"
                except:
                    self.song_info = path.stem
                logging.info(f"Сейчас играет: {self.song_info}")
            else:
                self.song_info = "Нет треков"

            if self.playlist:
                self.playlist.pop(0)
            self.preload_next()

    def start_playback_if_idle(self):
        with self.lock:
            if not self.current_file and self.playlist:
                first = self.playlist.pop(0)
                self.current_file = open(first, 'rb')
                self.position = 0
                self.song_info = self._get_song_info(first)
                logging.info(f"Начало вещания: {self.song_info}")
                self.preload_next()

    def _get_song_info(self, path: Path) -> str:
        try:
            tags = MP3(path)
            artist = tags.get("TPE1", ["Неизвестен"])[0]
            title = tags.get("TIT2", [path.stem])[0]
            return f"{artist} - {title}"
        except:
            return path.stem

    # --- Управление клиентами ---
    def add_client(self, wfile) -> bool:
        with self.clients_lock:
            if len(self.clients) >= self.max_clients:
                return False
            self.clients[wfile] = time.monotonic()
            logging.info(f"Слушатель добавлен (всего {len(self.clients)})")
            return True

    def remove_client(self, wfile):
        with self.clients_lock:
            if wfile in self.clients:
                del self.clients[wfile]

    def update_client_activity(self, wfile):
        with self.clients_lock:
            if wfile in self.clients:
                self.clients[wfile] = time.monotonic()

    def prune_inactive_clients(self) -> int:
        now = time.monotonic()
        with self.clients_lock:
            inactive = [w for w, last in self.clients.items() if now - last > self.client_timeout]
            for w in inactive:
                del self.clients[w]
            if inactive:
                logging.info(f"Удалено {len(inactive)} неактивных слушателей")
            return len(inactive)

    def send_initial_chunk(self, wfile):
        """Отправить первый кусок аудио новому клиенту, чтобы плеер сразу начал играть."""
        with self.lock:
            if self.current_file:
                self.current_file.seek(self.position)
                chunk = self.current_file.read(65536)  # 64 КБ для быстрой буферизации
                if chunk:
                    try:
                        wfile.write(chunk)
                        wfile.flush()
                        self.update_client_activity(wfile)
                    except Exception as e:
                        logging.error(f"Ошибка отправки начального чанка: {e}")
                        self.remove_client(wfile)

# Глобальный объект плеера
player = RadioPlayer(max_clients=100, client_timeout=30)

# ---------- HTTP‑сервер ----------
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

        # Любой другой путь – чистый аудиопоток
        if not player.add_client(self.wfile):
            self.send_response(503)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Server full")
            return

        self.send_response(200)
        self.send_header('Content-Type', 'audio/mpeg')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        # Мгновенно отправляем первый фрагмент
        player.send_initial_chunk(self.wfile)

# ---------- Потоковая раздача ----------
def audio_stream_worker():
    last_prune = time.monotonic()
    while True:
        if player.current_file is None:
            time.sleep(0.1)
            continue

        with player.lock:
            if player.current_file is None:
                continue
            player.current_file.seek(player.position)
            chunk = player.current_file.read(32768)  # 32 КБ
            if chunk:
                player.position += len(chunk)
                with player.clients_lock:
                    for wfile in list(player.clients.keys()):
                        try:
                            wfile.write(chunk)
                            wfile.flush()
                            player.update_client_activity(wfile)
                        except:
                            player.remove_client(wfile)
            else:
                player.switch_to_next()

        # Периодическая чистка неактивных клиентов
        now = time.monotonic()
        if now - last_prune >= 10:
            player.prune_inactive_clients()
            last_prune = now

        time.sleep(0.05)

# ---------- Туннель Cloudflare ----------
def cloudflare_tunnel_worker():
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

    cmd = [
        'cloudflared', '--no-autoupdate', 'tunnel',
        '--url', f'http://127.0.0.1:{PORT}',
        '--edge-ip-version', '4'
    ]
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
        line = line.strip()
        logging.info(f"[cloudflared] {line}")
        match = pattern.search(line)
        if match:
            url = match.group(0)
            PUBLIC_URL = url
            logging.info(f"✅ Публичный URL: {url}")
            def consume_stdout():
                for _ in proc.stdout:
                    pass
            threading.Thread(target=consume_stdout, daemon=True).start()
            return
        if time.time() - start_time > 30:
            TUNNEL_ERROR = "Туннель не выдал URL за 30 секунд"
            logging.error(TUNNEL_ERROR)
            break
    else:
        TUNNEL_ERROR = f"cloudflared завершился с кодом {proc.poll()}"
        logging.error(TUNNEL_ERROR)

# ---------- Telegram‑бот ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
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
        info = f"❌ Ошибка: {TUNNEL_ERROR}\n"
    elif PUBLIC_URL:
        song_escaped = player.song_info.replace("<", "&lt;").replace(">", "&gt;")
        url_escaped = PUBLIC_URL.replace("<", "&lt;").replace(">", "&gt;")
        info = (f"🎧 <b>{song_escaped}</b>\n"
                f"🔊 Прямой эфир: <a href='{url_escaped}'>{url_escaped}</a>\n")
    else:
        info = "⏳ Туннель поднимается...\n"
    await message.answer(f"🎵 <b>Super Radio DJ</b>\n{info}", parse_mode=ParseMode.HTML, reply_markup=kb)

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id
    if data == "upload":
        await callback.message.edit_text("📤 Отправь MP3. Если ты не админ, трек попадёт на модерацию.")
    elif data == "next_song" and user_id in ADMIN_IDS:
        player.switch_to_next()
        await callback.answer("⏭ Трек переключён")
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

def approve_song(filename: str):
    src = Path(PENDING_FOLDER) / filename
    dst = Path(MUSIC_FOLDER) / filename
    if src.exists():
        src.rename(dst)
        player.load_playlist()
        player.start_playback_if_idle()
    remove_pending_song(filename)

def reject_song(filename: str):
    src = Path(PENDING_FOLDER) / filename
    if src.exists():
        src.unlink()
    remove_pending_song(filename)

@dp.message(F.audio | F.document)
async def handle_file(message: types.Message):
    file = message.audio or message.document
    if not file:
        return
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
            player.load_playlist()
            player.start_playback_if_idle()
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
    logging.info("Запуск Super Radio DJ (final)")

    player.load_playlist()
    player.start_playback_if_idle()

    server = ThreadedHTTPServer(('0.0.0.0', PORT), RadioHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    threading.Thread(target=audio_stream_worker, daemon=True).start()
    threading.Thread(target=cloudflare_tunnel_worker, daemon=True).start()

    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
