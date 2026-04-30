#!/usr/bin/env python3
"""
Telegram-бот для MPD + Icecast радио.
"""
import os, logging, sys, asyncio
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.enums import ParseMode
from mpd import MPDClient

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8000/radio.mp3")
MPD_HOST = os.getenv("MPD_HOST", "mpd")
MPD_PORT = int(os.getenv("MPD_PORT", "6600"))
MUSIC_DIR = os.getenv("MUSIC_DIR", "/music")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def mpd_client():
    c = MPDClient()
    c.timeout = 5
    c.connect(MPD_HOST, MPD_PORT)
    return c

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    buttons = [
        [InlineKeyboardButton(text="🎵 СЛУШАТЬ", url=PUBLIC_URL)],
        [InlineKeyboardButton(text="📤 ЗАГРУЗИТЬ", callback_data="upload")],
        [InlineKeyboardButton(text="📊 СТАТУС", callback_data="status")]
    ]
    if message.from_user.id in ADMIN_IDS:
        buttons.extend([
            [InlineKeyboardButton(text="⏯ ПАУЗА/ИГРАТЬ", callback_data="toggle")],
            [InlineKeyboardButton(text="⏭ ДАЛЕЕ", callback_data="next")],
            [InlineKeyboardButton(text="🔁 ОБНОВИТЬ БД", callback_data="update")]
        ])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(
        "🎵 *MPD + Icecast Radio*\n"
        f"Слушать: `{PUBLIC_URL}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    data = callback.data
    if data == "status":
        try:
            with mpd_client() as c:
                status = c.status()
                song = c.currentsong()
                title = song.get("title", "нет трека")
            text = f"🎤 {title}\n🔊 {status['state']}"
        except Exception as e:
            text = f"Ошибка MPD: {e}"
        await callback.message.edit_text(text)
    elif data == "upload":
        await callback.message.edit_text("📤 Отправь мне MP3/FLAC/OGG файл.")
    elif data == "toggle" and callback.from_user.id in ADMIN_IDS:
        try:
            with mpd_client() as c:
                if c.status()["state"] == "play":
                    c.pause(1)
                    await callback.answer("⏸ Пауза")
                else:
                    c.play()
                    await callback.answer("▶ Играет")
        except Exception as e:
            await callback.answer(f"Ошибка: {e}")
    elif data == "next" and callback.from_user.id in ADMIN_IDS:
        try:
            with mpd_client() as c:
                c.next()
            await callback.answer("⏭ Следующий")
        except Exception as e:
            await callback.answer(f"Ошибка: {e}")
    elif data == "update" and callback.from_user.id in ADMIN_IDS:
        try:
            with mpd_client() as c:
                c.update()
            await callback.answer("🔁 База обновляется")
        except Exception as e:
            await callback.answer(f"Ошибка: {e}")
    else:
        await callback.answer()
    await callback.answer()

@dp.message(F.audio | F.document)
async def handle_file(message: types.Message):
    file = message.audio or message.document
    if not file:
        return
    allowed = (".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wav")
    fname = file.file_name or "track.mp3"
    if not fname.lower().endswith(allowed):
        await message.reply("❌ Поддерживаются только mp3, flac, ogg, m4a, aac, wav")
        return
    if file.file_size > 50 * 1024 * 1024:
        await message.reply("❌ Файл >50 МБ")
        return
    msg = await message.reply("📥 Загружаю…")
    try:
        file_info = await bot.get_file(file.file_id)
        dest = Path(MUSIC_DIR) / fname
        await bot.download_file(file_info.file_path, destination=str(dest))
        with mpd_client() as c:
            c.update()
        await msg.edit_text("✅ Загружено, база обновлена.")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

async def main():
    logger.info("Бот стартовал")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
