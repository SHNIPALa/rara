#!/usr/bin/env python3
"""
Super Radio DJ – MPD + авто‑туннель Cloudflare.
"""

import os, time, threading, logging, asyncio, subprocess, re, socket, json
from pathlib import Path
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.enums import ParseMode
from mpd import MPDClient

# ---------- Настройки ----------
PORT = int(os.getenv("PORT", "8000"))            # порт HTTP-потока MPD
MUSIC_FOLDER = os.getenv("MUSIC_FOLDER", "/music")
PENDING_FOLDER = os.getenv("PENDING_FOLDER", "/pending")
DATA_FOLDER = os.getenv("DATA_FOLDER", "/data")
SHARED_DIR = os.getenv("SHARED_DIR", "/shared")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MPD_HOST = os.getenv("MPD_HOST", "mpd")
MPD_PORT = int(os.getenv("MPD_PORT", "6600"))

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

# ---------- MPD-клиент ----------
def mpd_connect():
    client = MPDClient()
    client.timeout = 5
    client.connect(MPD_HOST, MPD_PORT)
    return client

def current_track_info():
    try:
        with mpd_connect() as c:
            song = c.currentsong()
            if not song:
                return "Нет треков"
            artist = song.get("artist", "Неизвестен")
            title = song.get("title", song.get("file", "Без названия"))
            return f"{artist} - {title}"
    except:
        return "MPD недоступен"

def toggle_pause():
    try:
        with mpd_connect() as c:
            if c.status().get("state") == "play":
                c.pause(1)
            else:
                c.play()
    except Exception as e:
        logging.error(f"MPD toggle error: {e}")

def next_song():
    try:
        with mpd_connect() as c:
            c.next()
    except Exception as e:
        logging.error(f"MPD next error: {e}")

def update_db():
    try:
        with mpd_connect() as c:
            c.update()
    except Exception as e:
        logging.error(f"MPD update error: {e}")

# ---------- Туннель Cloudflare (в том же контейнере) ----------
def start_cloudflare_tunnel():
    global PUBLIC_URL, TUNNEL_ERROR
    logging.info(f"Ожидание порта {PORT}...")
    for _ in range(60):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        if s.connect_ex(('127.0.0.1', PORT)) == 0:
            s.close()
            logging.info("Порт MPD открыт, запускаю cloudflared...")
            break
        s.close()
        time.sleep(0.5)
    else:
        TUNNEL_ERROR = "HTTP-порт MPD не доступен"
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
    # Записываем URL в файл в общей папке, чтобы бот его подхватил
    url_file = Path(SHARED_DIR) / "public_url.txt"
    start_time = time.time()
    for line in proc.stdout:
        logging.info(f"[cloudflared] {line.strip()}")
        match = pattern.search(line)
        if match:
            url = match.group(0)
            PUBLIC_URL = url
            url_file.write_text(url)
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

def watch_for_url():
    """Фоновый поток: читает URL из файла, если он появился."""
    global PUBLIC_URL
    url_file = Path(SHARED_DIR) / "public_url.txt"
    while True:
        if url_file.exists():
            url = url_file.read_text().strip()
            if url.startswith("https://") and url != PUBLIC_URL:
                PUBLIC_URL = url
                logging.info(f"Публичный URL обновлён из файла: {url}")
        time.sleep(5)

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
        try:
            with mpd_connect() as c:
                state = c.status().get("state", "stop")
                toggle_text = "⏸ ПАУЗА" if state == "play" else "▶ ИГРАТЬ"
                buttons.append([InlineKeyboardButton(text=toggle_text, callback_data="toggle_play")])
        except:
            pass
        buttons.append([InlineKeyboardButton(text="⏭ СЛЕДУЮЩИЙ", callback_data="next_song")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    kb = main_menu_keyboard(message.from_user.id)
    song = current_track_info()
    info = ""
    if TUNNEL_ERROR:
        info = f"❌ Ошибка туннеля: {TUNNEL_ERROR}\n"
    elif PUBLIC_URL:
        url_escaped = PUBLIC_URL.replace("<", "&lt;").replace(">", "&gt;")
        info = (f"🎧 <b>{song}</b>\n"
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
    elif data == "toggle_play" and user_id in ADMIN_IDS:
        toggle_pause()
        await callback.answer("⏯ Переключено")
        await start_cmd(callback.message)
    elif data == "next_song" and user_id in ADMIN_IDS:
        next_song()
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
        update_db()
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
            update_db()
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

    # Фоновый монитор URL
    threading.Thread(target=watch_for_url, daemon=True).start()
    # Запускаем туннель (ждёт открытия порта 8000 от MPD)
    threading.Thread(target=start_cloudflare_tunnel, daemon=True).start()

    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
