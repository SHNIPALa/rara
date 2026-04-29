#!/usr/bin/env python3
"""
SUPER RADIO BOT + ICECAST
Профессиональное интернет-радио с Icecast
"""

import os
import time
import threading
import sqlite3
import random
import subprocess
import signal
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from mutagen.mp3 import MP3
from dotenv import load_dotenv

load_dotenv()

# ==================== КОНФИГУРАЦИЯ ====================
MUSIC_FOLDER = "music"
ICECAST_URL = "icecast:8000"
ICECAST_SOURCE = "source:superpass"
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]

# Публичный URL (будет получен из ngrok)
PUBLIC_URL = None
STREAM_URL = None

Path(MUSIC_FOLDER).mkdir(exist_ok=True)

# Глобальные переменные
playlist: List[Path] = []
current_song_index = 0
current_status = "⏸️ Остановлено"
listeners = 0
ffmpeg_process = None

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect('radio.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS stats
                 (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  song_name TEXT, date TEXT)''')
    conn.commit()
    conn.close()

init_db()

# ==================== ПЛЕЙЛИСТ ====================
def load_playlist():
    global playlist
    playlist = []
    for mp3 in Path(MUSIC_FOLDER).rglob("*.mp3"):
        playlist.append(mp3)
    if playlist:
        random.shuffle(playlist)
        print(f"📀 Загружено {len(playlist)} песен")
        for i, song in enumerate(playlist[:5]):
            print(f"   {i+1}. {song.name}")
        if len(playlist) > 5:
            print(f"   ... и еще {len(playlist)-5}")
    else:
        print(f"⚠️ НЕТ MP3! Положите файлы в папку 'music'")
    return len(playlist)

def get_current_song():
    if playlist and current_song_index < len(playlist):
        return playlist[current_song_index]
    return None

def next_song():
    global current_song_index, ffmpeg_process, current_status
    
    if not playlist:
        return None
    
    current_song_index = (current_song_index + 1) % len(playlist)
    song = get_current_song()
    
    if song:
        current_status = f"🎵 {song.stem}"
        print(f"🎵 Следующий трек: {song.name}")
        
        # Останавливаем текущий ffmpeg
        if ffmpeg_process:
            ffmpeg_process.terminate()
            time.sleep(1)
        
        # Записываем в историю
        conn = sqlite3.connect('radio.db')
        c = conn.cursor()
        c.execute("INSERT INTO history (song_name, date) VALUES (?, ?)",
                  (song.name, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    return song

def start_stream():
    """Запускает ffmpeg для стриминга в Icecast"""
    global ffmpeg_process
    
    if not playlist:
        print("❌ Нет песен для стриминга")
        return
    
    song = playlist[current_song_index]
    print(f"▶️ Начинаем стрим: {song.name}")
    
    cmd = [
        'ffmpeg',
        '-re', '-i', str(song),
        '-c', 'copy',
        '-f', 'mp3',
        f'icecast://{ICECAST_SOURCE}@{ICECAST_URL}/stream'
    ]
    
    ffmpeg_process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid if os.name != 'nt' else None
    )
    
    # Планируем следующий трек
    def schedule_next():
        time.sleep(song_duration(song) + 1)
        next_song()
        start_stream()
    
    threading.Thread(target=schedule_next, daemon=True).start()

def song_duration(song_path):
    try:
        audio = MP3(song_path)
        return int(audio.info.length)
    except:
        return 180  # 3 минуты по умолчанию

def get_stats():
    conn = sqlite3.connect('radio.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM history")
    total_played = c.fetchone()[0]
    conn.close()
    
    song = get_current_song()
    return {
        'current': song.stem if song else 'Нет',
        'playlist_size': len(playlist),
        'total_played': total_played,
        'listeners': listeners
    }

# ==================== ПОЛУЧЕНИЕ ПУБЛИЧНОГО URL ====================
def get_ngrok_url():
    try:
        import requests
        resp = requests.get('http://localhost:4040/api/tunnels', timeout=3)
        tunnels = resp.json().get('tunnels', [])
        for tunnel in tunnels:
            if tunnel.get('proto') == 'https':
                return tunnel.get('public_url')
    except:
        pass
    return None

def update_public_url():
    global PUBLIC_URL, STREAM_URL
    PUBLIC_URL = get_ngrok_url()
    if PUBLIC_URL:
        STREAM_URL = f"{PUBLIC_URL}/stream"
    else:
        STREAM_URL = f"http://193.233.114.7:8000/stream"
    return STREAM_URL

# ==================== TELEGRAM БОТ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats()
    stream_url = STREAM_URL or "http://193.233.114.7:8000/stream"
    
    keyboard = [
        [InlineKeyboardButton("🎵 СЛУШАТЬ РАДИО", url=stream_url)],
        [InlineKeyboardButton("🌐 ICECAST ПЛЕЕР", url=stream_url.replace('/stream', ''))],
        [InlineKeyboardButton("📊 СТАТУС", callback_data="status")],
        [InlineKeyboardButton("📤 ЗАГРУЗИТЬ ТРЕК", callback_data="upload")],
        [InlineKeyboardButton("ℹ️ ПОМОЩЬ", callback_data="help")]
    ]
    
    await update.message.reply_text(
        f"🎵 *SUPER RADIO (ICEcast)*\n\n"
        f"┌─ 🎤 Сейчас: `{stats['current']}`\n"
        f"├─ 👥 Слушателей: {stats['listeners']}\n"
        f"├─ 📀 Песен: {stats['playlist_size']}\n"
        f"└─ 🎧 Всего сыграно: {stats['total_played']}\n\n"
        f"🔗 *Ссылка для друзей:*\n`{stream_url}`\n\n"
        f"💡 Просто отправьте эту ссылку друзьям —\n"
        f"   она откроется в любом браузере или плеере!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "status":
        stats = get_stats()
        await query.edit_message_text(
            f"📊 *СТАТУС РАДИО*\n\n"
            f"┌─ 🎵 Сейчас: `{stats['current']}`\n"
            f"├─ 👥 Слушателей: {stats['listeners']}\n"
            f"├─ 📀 Плейлист: {stats['playlist_size']} песен\n"
            f"├─ 🎧 Всего треков: {stats['total_played']}\n"
            f"├─ 🎚️ Сервер: ✅ Активен\n"
            f"└─ 🔊 Источник: Icecast v2.4\n\n"
            f"🔗 Ссылка: `{STREAM_URL}`",
            parse_mode='Markdown'
        )
    elif query.data == "upload":
        await query.edit_message_text(
            "📤 *ЗАГРУЗКА МУЗЫКИ*\n\n"
            "1. Положите MP3 файлы в папку `music`\n"
            "2. Или отправьте мне MP3 файл прямо сейчас\n\n"
            "✅ Поддерживаются MP3 до 50MB\n"
            "🎵 После добавления трек появится в плейлисте",
            parse_mode='Markdown'
        )
    elif query.data == "help":
        await query.edit_message_text(
            f"🎵 *КАК СЛУШАТЬ РАДИО*\n\n"
            f"📱 *В браузере:*\n"
            f"   Просто откройте ссылку\n\n"
            f"💻 *В VLC:*\n"
            f"   Media → Open Network Stream\n"
            f"   Вставьте: `{STREAM_URL}`\n\n"
            f"📱 *В приложениях:*\n"
            f"   Любой плеер с поддержкой Icecast\n\n"
            f"🔥 *Технологии:* Icecast + FFmpeg",
            parse_mode='Markdown'
        )

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.audio:
        file = update.message.audio
        msg = await update.message.reply_text(f"📥 Загружаю {file.file_name}...")
        
        try:
            new_file = await context.bot.get_file(file.file_id)
            file_path = Path(MUSIC_FOLDER) / file.file_name
            await new_file.download_to_drive(file_path)
            
            # Обновляем плейлист
            load_playlist()
            
            await msg.edit_text(
                f"✅ *Трек добавлен!*\n\n"
                f"📀 {file.file_name}\n"
                f"📊 Всего песен: {len(playlist)}",
                parse_mode='Markdown'
            )
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка: {str(e)}")

async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🔗 *ССЫЛКА ДЛЯ ДРУЗЕЙ*\n\n"
        f"`{STREAM_URL}`\n\n"
        f"📱 Отправьте эту ссылку друзьям,\n"
        f"   чтобы они могли слушать радио!",
        parse_mode='Markdown'
    )

async def now_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats()
    await update.message.reply_text(
        f"🎵 *СЕЙЧАС В ЭФИРЕ*\n\n"
        f"`{stats['current']}`\n\n"
        f"👥 Слушателей: {stats['listeners']}\n"
        f"📀 Плейлист: {stats['playlist_size']} песен",
        parse_mode='Markdown'
    )

# ==================== ЗАПУСК ====================
def main():
    # Загружаем плейлист
    if load_playlist() == 0:
        print("\n⚠️ ВНИМАНИЕ: Нет музыкальных файлов!")
        print("📁 Положите MP3 файлы в папку 'music'")
        print("   Или отправьте их через Telegram бота\n")
    
    # Запускаем стриминг
    if playlist:
        start_stream()
    
    # Ждем Icecast и получаем URL
    time.sleep(5)
    update_public_url()
    
    # Запускаем бота
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("link", link_command))
    application.add_handler(CommandHandler("now", now_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    
    print("\n" + "=" * 60)
    print("🎵 SUPER RADIO BOT v3.0 (Icecast)")
    print("=" * 60)
    print(f"\n🔗 ССЫЛКА ДЛЯ ДРУЗЕЙ:")
    print(f"   {STREAM_URL}")
    print(f"\n🌐 ВЕБ-ПЛЕЕР ICECAST:")
    print(f"   {STREAM_URL.replace('/stream', '')}")
    print(f"\n📊 АДМИН-ПАНЕЛЬ ICECAST:")
    print(f"   http://localhost:8000/admin")
    print(f"   Логин: admin | Пароль: adminpass")
    print(f"\n🎧 БОТ АКТИВЕН в Telegram")
    print("=" * 60 + "\n")
    
    application.run_polling()

if __name__ == '__main__':
    main()
