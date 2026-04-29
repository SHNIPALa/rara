#!/usr/bin/env python3
"""
SUPER RADIO BOT
Мощный Telegram бот для интернет-радио с авто-туннелем
"""

import os
import time
import threading
import sqlite3
import random
import asyncio
import json
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from mutagen.mp3 import MP3
from dotenv import load_dotenv

load_dotenv()

# ==================== КОНФИГУРАЦИЯ ====================
PORT = 8080
MUSIC_FOLDER = "music"
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]

# Создаем папки
Path(MUSIC_FOLDER).mkdir(exist_ok=True)

# Глобальные переменные
playlist: List[Path] = []
current_song: Optional[Path] = None
current_file = None
current_position = 0
listeners = 0
current_status = "⏸️ Остановлено"

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect('radio.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS stats
                 (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  song_name TEXT, listeners INT, date TEXT)''')
    conn.commit()
    conn.close()

init_db()

def save_stats():
    conn = sqlite3.connect('radio.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO stats (key, value) VALUES (?, ?)",
              ('total_listeners', str(listeners)))
    c.execute("INSERT INTO history (song_name, listeners, date) VALUES (?, ?, ?)",
              (current_song.name if current_song else 'None', listeners, datetime.now().isoformat()))
    conn.commit()
    conn.close()

# ==================== РАДИО ПЛЕЙЛИСТ ====================
def load_playlist():
    global playlist, current_song
    playlist = []
    for mp3 in Path(MUSIC_FOLDER).rglob("*.mp3"):
        playlist.append(mp3)
    if playlist:
        random.shuffle(playlist)
        current_song = playlist[0]
        print(f"📀 Загружено {len(playlist)} песен")
        print(f"🎵 Первая песня: {current_song.name}")
    else:
        print(f"⚠️ Нет MP3! Положите файлы в папку 'music'")

def next_song():
    global current_song, current_file, current_position, current_status
    if not playlist:
        return
    if current_file:
        current_file.close()
        current_file = None
    if current_song in playlist:
        idx = playlist.index(current_song)
        current_song = playlist[(idx + 1) % len(playlist)]
    else:
        current_song = playlist[0]
    current_position = 0
    current_status = f"🎵 {current_song.stem}"
    print(f"🎵 Сейчас: {current_song.name}")
    save_stats()

def get_song_info():
    if current_song and current_song.exists():
        try:
            audio = MP3(current_song)
            return {
                'title': current_song.stem,
                'duration': int(audio.info.length),
                'duration_str': f"{int(audio.info.length)//60}:{int(audio.info.length)%60:02d}",
                'size_mb': round(current_song.stat().st_size / 1024 / 1024, 2)
            }
        except:
            pass
    return {'title': 'Нет песен', 'duration': 0, 'duration_str': '0:00', 'size_mb': 0}

# ==================== HTTP РАДИО СЕРВЕР ====================
class RadioHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        global listeners, current_file, current_position, current_song, playlist
        
        # АУДИО ПОТОК
        if self.path in ['/stream.mp3', '/stream']:
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Content-Disposition', 'attachment; filename="radio.mp3"')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            listeners += 1
            print(f"🔊 Слушатель #{listeners}: {self.client_address[0]}")
            
            try:
                while True:
                    if not playlist:
                        time.sleep(1)
                        continue
                    
                    if not current_song and playlist:
                        current_song = playlist[0]
                    
                    if not current_file and current_song:
                        current_file = open(current_song, 'rb')
                        current_position = 0
                        print(f"▶️ {current_song.name}")
                    
                    if current_file:
                        current_file.seek(current_position)
                        data = current_file.read(8192)
                        
                        if data:
                            current_position += len(data)
                            self.wfile.write(data)
                            self.wfile.flush()
                        else:
                            current_file.close()
                            current_file = None
                            next_song()
                    
                    await_asyncio(0.05)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                listeners -= 1
                print(f"🔇 Слушатель ушел (осталось: {listeners})")
        
        # КРАСИВЫЙ ВЕБ-ПЛЕЕР
        elif self.path == '/':
            info = get_song_info()
            stream_url = f"{os.getenv('STREAM_URL', 'http://localhost:8080')}/stream.mp3"
            
            html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>🎵 SUPER RADIO | Интернет-радио</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}
        .player {{
            background: rgba(255,255,255,0.95);
            border-radius: 30px;
            padding: 40px;
            max-width: 500px;
            width: 100%;
            box-shadow: 0 25px 50px rgba(0,0,0,0.3);
            backdrop-filter: blur(10px);
            transition: transform 0.3s;
        }}
        .player:hover {{ transform: scale(1.02); }}
        h1 {{
            text-align: center;
            color: #333;
            margin-bottom: 10px;
            font-size: 2em;
        }}
        .subtitle {{
            text-align: center;
            color: #666;
            margin-bottom: 30px;
            font-size: 0.9em;
        }}
        audio {{
            width: 100%;
            margin: 20px 0;
            border-radius: 30px;
        }}
        .info {{
            background: linear-gradient(135deg, #667eea15, #764ba215);
            padding: 20px;
            border-radius: 20px;
            margin: 20px 0;
            text-align: center;
        }}
        .song-title {{
            font-size: 1.3em;
            font-weight: bold;
            color: #764ba2;
            margin-bottom: 5px;
        }}
        .stats {{
            display: flex;
            justify-content: space-around;
            margin-top: 10px;
            color: #666;
            font-size: 0.9em;
        }}
        .url {{
            background: #f0f0f0;
            padding: 12px;
            border-radius: 15px;
            font-size: 12px;
            word-break: break-all;
            text-align: center;
            margin-top: 15px;
        }}
        .url a {{ color: #764ba2; text-decoration: none; }}
        button {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 30px;
            cursor: pointer;
            font-size: 16px;
            width: 100%;
            margin-top: 15px;
            transition: opacity 0.3s;
        }}
        button:hover {{ opacity: 0.9; }}
        .online {{ color: #4caf50; font-weight: bold; }}
        @keyframes pulse {{
            0% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
            100% {{ opacity: 1; }}
        }}
        .live {{ animation: pulse 2s infinite; color: #f44336; }}
    </style>
</head>
<body>
    <div class="player">
        <h1>🎵 SUPER RADIO</h1>
        <div class="subtitle">24/7 Интернет-радио</div>
        
        <audio controls autoplay>
            <source src="/stream.mp3" type="audio/mpeg">
        </audio>
        
        <div class="info">
            <div class="song-title">🎤 {info['title']}</div>
            <div class="stats">
                <span>⏱️ {info['duration_str']}</span>
                <span>💾 {info['size_mb']} MB</span>
                <span>👥 {listeners} слушателей</span>
            </div>
        </div>
        
        <div class="url">
            🔗 Прямая ссылка:<br>
            <a href="{stream_url}">{stream_url}</a>
        </div>
        
        <button onclick="window.location.href='{stream_url}'">
            📥 Скачать поток
        </button>
    </div>
</body>
</html>'''
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(html.encode())
        
        # API СТАТУСА
        elif self.path == '/api/status':
            info = get_song_info()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({
                'status': 'online',
                'current_song': info['title'],
                'listeners': listeners,
                'playlist_size': len(playlist),
                'uptime': current_status
            }).encode())
        
        else:
            self.send_response(404)
            self.end_headers()

def await_asyncio(seconds):
    """Хак для ожидания в синхронном коде"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(asyncio.sleep(seconds))
    loop.close()

def run_radio_server():
    server = HTTPServer(('0.0.0.0', PORT), RadioHandler)
    print(f"✅ Радио сервер: http://localhost:{PORT}")
    server.serve_forever()

# ==================== TELEGRAM БОТ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info = get_song_info()
    stream_url = os.getenv('STREAM_URL', f'http://localhost:{PORT}/stream.mp3')
    
    keyboard = [
        [InlineKeyboardButton("🎵 СЛУШАТЬ РАДИО", url=stream_url)],
        [InlineKeyboardButton("🌐 ОТКРЫТЬ ВЕБ-ПЛЕЕР", url=stream_url.replace('/stream.mp3', ''))],
        [InlineKeyboardButton("📥 СКАЧАТЬ ПОТОК", url=stream_url)],
        [InlineKeyboardButton("📊 СТАТУС", callback_data="status")],
        [InlineKeyboardButton("ℹ️ ПОМОЩЬ", callback_data="help")]
    ]
    
    await update.message.reply_text(
        f"🎵 *SUPER RADIO BOT*\n\n"
        f"┌─ 🎤 Сейчас: `{info['title']}`\n"
        f"├─ ⏱️ Длительность: {info['duration_str']}\n"
        f"├─ 👥 Слушателей: {listeners}\n"
        f"└─ 📀 Песен: {len(playlist)}\n\n"
        f"🔗 *Ссылка для друзей:*\n`{stream_url}`\n\n"
        f"💡 Просто отправьте эту ссылку друзьям —\n"
        f"   она откроется в любом браузере!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "status":
        info = get_song_info()
        await query.edit_message_text(
            f"📊 *СТАТУС РАДИО*\n\n"
            f"┌─ 🎵 Сейчас: `{info['title']}`\n"
            f"├─ ⏱️ Длительность: {info['duration_str']}\n"
            f"├─ 👥 Слушателей: {listeners}\n"
            f"├─ 📀 Песен: {len(playlist)}\n"
            f"└─ 🎚️ Сервер: ✅ Активен\n\n"
            f"🔗 Ссылка: `{os.getenv('STREAM_URL')}`",
            parse_mode='Markdown'
        )
    elif query.data == "help":
        await query.edit_message_text(
            f"ℹ️ *ПОМОЩЬ*\n\n"
            f"🎵 *Как слушать:*\n"
            f"1. Нажмите «Слушать радио»\n"
            f"2. Или откройте ссылку в браузере\n"
            f"3. Или вставьте в VLC (Media → Open Network Stream)\n\n"
            f"📤 *Как добавить музыку:*\n"
            f"• Положите MP3 в папку `music`\n"
            f"• Или отправьте боту через /upload\n\n"
            f"🔄 *Плейлист обновляется автоматически*",
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
            
            # Добавляем в плейлист
            playlist.append(file_path)
            if not current_song:
                load_playlist()
            
            await msg.edit_text(
                f"✅ *Добавлено в плейлист!*\n\n"
                f"📀 {file.file_name}\n"
                f"📊 Всего песен: {len(playlist)}",
                parse_mode='Markdown'
            )
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка: {str(e)}")

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 *SUPER RADIO BOT v2.0*\n\n"
        f"⚡ Поддерживает до 100 слушателей\n"
        f"🎵 Автоматическое переключение песен\n"
        f"📡 HTTP/HTTPS поток\n"
        f"🎧 Работает в любом плеере\n\n"
        f"📱 *Разработка:* @super_radio",
        parse_mode='Markdown'
    )

def main():
    # Загружаем плейлист
    load_playlist()
    
    # Запускаем радио сервер в отдельном потоке
    radio_thread = threading.Thread(target=run_radio_server, daemon=True)
    radio_thread.start()
    
    time.sleep(2)
    
    # Запускаем бота
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    
    stream_url = os.getenv('STREAM_URL', f'http://localhost:{PORT}/stream.mp3')
    
    print("\n" + "=" * 50)
    print("🤖 SUPER RADIO BOT v2.0")
    print("=" * 50)
    print(f"\n🔗 ССЫЛКА ДЛЯ ДРУЗЕЙ:")
    print(f"   {stream_url}")
    print(f"\n🌐 ВЕБ-ПЛЕЕР:")
    print(f"   {stream_url.replace('/stream.mp3', '')}")
    print(f"\n📊 API СТАТУСА:")
    print(f"   {stream_url.replace('/stream.mp3', '/api/status')}")
    print("\n🤖 Telegram бот активен")
    print("=" * 50 + "\n")
    
    application.run_polling()

if __name__ == '__main__':
    main()
