import os
import time
import threading
import sqlite3
import random
import subprocess
from pathlib import Path
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from mutagen.mp3 import MP3

# ===== КОНФИГУРАЦИЯ =====
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "8726694308:AAF5_WwE1Tu9csG7ZKjwgG50n-1A5nByM4Q")
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x]
STREAM_URL = os.getenv('STREAM_URL', 'http://193.233.114.7:8000/stream')
MUSIC_FOLDER = "music"
PENDING_FOLDER = "pending"

# Создаем папки
os.makedirs(MUSIC_FOLDER, exist_ok=True)
os.makedirs(PENDING_FOLDER, exist_ok=True)
os.makedirs("data", exist_ok=True)

# Глобальные переменные
playlist = []
current_song = None


# ===== БАЗА ДАННЫХ =====
def init_db():
    conn = sqlite3.connect('data/radio.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, approved INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pending_songs
                 (id INTEGER PRIMARY KEY, filename TEXT, user_id INTEGER, user_name TEXT, date TEXT)''')
    conn.commit()
    conn.close()


init_db()


# ===== РАДИО ПЛЕЙЛИСТ =====
def load_playlist():
    global playlist, current_song
    playlist = []
    for mp3 in Path(MUSIC_FOLDER).rglob("*.mp3"):
        playlist.append(mp3)
    if playlist:
        random.shuffle(playlist)
        current_song = playlist[0]
        print(f"📀 Загружено {len(playlist)} песен")
    else:
        print(f"⚠️ Нет MP3 в папке '{MUSIC_FOLDER}'")


def get_song_info():
    if current_song and current_song.exists():
        try:
            audio = MP3(current_song)
            return {
                'title': current_song.stem,
                'duration_str': f"{int(audio.info.length) // 60}:{int(audio.info.length) % 60:02d}"
            }
        except:
            pass
    return {'title': 'Нет песен', 'duration_str': '0:00'}


# ===== TELEGRAM БОТ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "No username"

    conn = sqlite3.connect('data/radio.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

    info = get_song_info()

    keyboard = [
        [InlineKeyboardButton("🎵 Слушать радио", url=STREAM_URL)],
        [InlineKeyboardButton("🎧 Веб-плеер", url=STREAM_URL.replace('/stream', ''))],
        [InlineKeyboardButton("📤 Отправить трек", callback_data="upload")],
        [InlineKeyboardButton("📊 Статус", callback_data="status")]
    ]

    if user_id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("🔧 Админ панель", callback_data="admin")])

    await update.message.reply_text(
        f"🎵 *РАДИО БОТ*\n\n"
        f"🔗 *Ссылка для друзей:*\n"
        f"`{STREAM_URL}`\n\n"
        f"📊 *Сейчас в эфире:*\n"
        f"🎵 {info['title']}\n"
        f"📀 {len(playlist)} песен в ротации\n\n"
        f"💡 *Как слушать:*\n"
        f"• Открыть ссылку в браузере\n"
        f"• Или вставить в VLC: Media → Open Network Stream\n\n"
        f"💡 *Как добавить трек:*\n"
        f"Нажмите 'Отправить трек' и загрузите MP3",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "get_link":
        await query.edit_message_text(
            f"🔗 *ССЫЛКА ДЛЯ ДРУЗЕЙ*\n\n"
            f"📥 *Прямая ссылка:*\n"
            f"`{STREAM_URL}`\n\n"
            f"📱 Отправьте эту ссылку друзьям - они смогут слушать в браузере!",
            parse_mode='Markdown'
        )

    elif query.data == "upload":
        await query.edit_message_text(
            "📤 *Отправьте MP3 файл*\n\n"
            "Просто отправьте MP3 файл, он уйдет на модерацию.\n"
            "После одобрения появится в эфире!\n\n"
            "✅ Максимальный размер: 50MB",
            parse_mode='Markdown'
        )

    elif query.data == "status":
        info = get_song_info()
        await query.edit_message_text(
            f"📊 *СТАТУС РАДИО*\n\n"
            f"🎵 Сейчас: *{info['title']}*\n"
            f"⏱️ {info['duration_str']}\n"
            f"📀 Песен в плейлисте: *{len(playlist)}*\n"
            f"🔗 Ссылка: `{STREAM_URL}`\n\n"
            f"🎚️ Сервер: ✅ Активен",
            parse_mode='Markdown'
        )

    elif query.data == "admin" and user_id in ADMIN_IDS:
        await show_admin_panel(update, context)

    elif query.data.startswith("approve_"):
        song_id = int(query.data.split("_")[1])
        conn = sqlite3.connect('data/radio.db')
        c = conn.cursor()
        c.execute("SELECT filename FROM pending_songs WHERE id = ?", (song_id,))
        song = c.fetchone()
        if song:
            # Перемещаем из pending в music
            src = Path(PENDING_FOLDER) / song[0]
            dst = Path(MUSIC_FOLDER) / song[0]
            if src.exists():
                src.rename(dst)
                load_playlist()
                # Перезапускаем FFmpeg
                os.system("pkill ffmpeg")
            c.execute("DELETE FROM pending_songs WHERE id = ?", (song_id,))
            await query.edit_message_text(f"✅ Трек одобрен! Он уже в эфире")
        else:
            await query.edit_message_text(f"❌ Трек не найден")
        conn.commit()
        conn.close()
        await show_admin_panel(update, context)

    elif query.data.startswith("reject_"):
        song_id = int(query.data.split("_")[1])
        conn = sqlite3.connect('data/radio.db')
        c = conn.cursor()
        c.execute("SELECT filename FROM pending_songs WHERE id = ?", (song_id,))
        song = c.fetchone()
        if song:
            src = Path(PENDING_FOLDER) / song[0]
            if src.exists():
                src.unlink()
            c.execute("DELETE FROM pending_songs WHERE id = ?", (song_id,))
            await query.edit_message_text(f"❌ Трек отклонен")
        else:
            await query.edit_message_text(f"❌ Трек не найден")
        conn.commit()
        conn.close()
        await show_admin_panel(update, context)

    elif query.data == "back":
        await start(update, context)


async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    conn = sqlite3.connect('data/radio.db')
    c = conn.cursor()
    c.execute("SELECT id, filename, user_name, date FROM pending_songs ORDER BY date DESC")
    pending = c.fetchall()
    conn.close()

    keyboard = []

    if pending:
        keyboard.append([InlineKeyboardButton("📀 ТРЕКИ НА МОДЕРАЦИИ:", callback_data="none")])
        for song_id, filename, user_name, date in pending:
            keyboard.append([
                InlineKeyboardButton(f"✅ {filename[:25]}", callback_data=f"approve_{song_id}"),
                InlineKeyboardButton(f"❌", callback_data=f"reject_{song_id}")
            ])
    else:
        keyboard.append([InlineKeyboardButton("✅ Нет треков на модерации", callback_data="none")])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back")])

    await query.edit_message_text(
        "🔧 *АДМИН ПАНЕЛЬ*\n\n"
        f"📀 Треков ожидают: {len(pending)}\n\n"
        "Управление треками:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "No username"

    if update.message.audio:
        file = update.message.audio
        file_name = file.file_name

        if file.file_size > 50 * 1024 * 1024:
            await update.message.reply_text("❌ Файл слишком большой! Максимум 50MB")
            return

        status_msg = await update.message.reply_text(f"📥 Загружаю {file_name}...")

        try:
            new_file = await context.bot.get_file(file.file_id)
            file_path = Path(PENDING_FOLDER) / file_name
            await new_file.download_to_drive(file_path)

            conn = sqlite3.connect('data/radio.db')
            c = conn.cursor()
            c.execute("INSERT INTO pending_songs (filename, user_id, user_name, date) VALUES (?, ?, ?, ?)",
                      (file_name, user_id, username, datetime.now().isoformat()))
            conn.commit()
            conn.close()

            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"📀 *НОВЫЙ ТРЕК!*\n\n"
                        f"От: {username}\n"
                        f"Файл: {file_name}",
                        parse_mode='Markdown'
                    )
                except:
                    pass

            await status_msg.edit_text(
                f"✅ *Трек отправлен на модерацию!*\n\n"
                f"📀 {file_name}\n"
                f"После одобрения трек появится в эфире",
                parse_mode='Markdown'
            )
        except Exception as e:
            await status_msg.edit_text(f"❌ Ошибка: {str(e)}")


def main():
    load_playlist()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio))

    print("\n" + "=" * 50)
    print("✅ БОТ ЗАПУЩЕН!")
    print("=" * 50)
    print(f"\n🔗 ССЫЛКА ДЛЯ ДРУЗЕЙ:")
    print(f"   {STREAM_URL}")
    print(f"\n🌐 ВЕБ-ПЛЕЕР:")
    print(f"   {STREAM_URL.replace('/stream', '')}")
    print("\n🤖 Бот готов к работе в Telegram")
    print("=" * 50 + "\n")

    application.run_polling()


if __name__ == '__main__':
    main()