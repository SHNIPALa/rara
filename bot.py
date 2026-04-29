#!/usr/bin/env python3
"""
SUPER RADIO BOT - Docker версия
Работает напрямую через ваш IP
"""

import os
import time
import threading
import subprocess
import socket
import random
import json
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from mutagen.mp3 import MP3

# ==================== КОНФИГУРАЦИЯ ====================
PORT = 8080
MUSIC_FOLDER = "music"
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x]

# Получаем внешний IP
def get_public_ip():
    try:
        import requests
        ip = requests.get('https://api.ipify.org', timeout=3).text
        return ip
    except:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip

PUBLIC_IP = get_public_ip()
STREAM_URL = f"http://{PUBLIC_IP}:{PORT}/radio.mp3"

# Создаём папку для музыки
Path(MUSIC_FOLDER).mkdir(exist_ok=True)

# Глобальные переменные
playlist = []
current_song_index = 0
current_song_data = None
current_song_position = 0
clients = []
stream_active = True

# ==================== ЗАГРУЗКА ПЛЕЙЛИСТА ====================
def load_playlist():
    global playlist
    playlist = list(Path(MUSIC_FOLDER).glob("*.mp3"))
    if playlist:
        random.shuffle(playlist)
        print(f"📀 Загружено {len(playlist)} песен")
        for i, song in enumerate(playlist[:5]):
            print(f"   {i+1}. {song.name}")
    else:
        print(f"⚠️ НЕТ MP3! Положите файлы в папку 'music'")
    return len(playlist)

def next_song():
    global current_song_index, current_song_data, current_song_position
    if not playlist:
        return
    current_song_index = (current_song_index + 1) % len(playlist)
    if current_song_data:
        current_song_data.close()
    current_song_data = open(playlist[current_song_index], 'rb')
    current_song_position = 0
    print(f"🎵 Сейчас: {playlist[current_song_index].name}")

def get_song_info():
    if playlist and current_song_index < len(playlist):
        song = playlist[current_song_index]
        try:
            audio = MP3(song)
            duration = int(audio.info.length)
            return {
                'title': song.stem,
                'duration': f"{duration//60}:{duration%60:02d}",
                'size': round(song.stat().st_size / 1024 / 1024, 2)
            }
        except:
            return {'title': song.stem, 'duration': '0:00', 'size': 0}
    return {'title': 'Нет песен', 'duration': '0:00', 'size': 0}

# ==================== HTTP СЕРВЕР ====================
class RadioHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        global clients
        
        # Аудио поток
        if self.path in ['/radio.mp3', '/stream']:
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Cache-Control', 'no-cache, no-store')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            clients.append(self.wfile)
            print(f"🔊 Слушатель (всего: {len(clients)})")
            
            try:
                while True:
                    time.sleep(1)
            except:
                pass
            finally:
                if self.wfile in clients:
                    clients.remove(self.wfile)
                print(f"🔇 Слушатель ушел (осталось: {len(clients)})")
            return
        
        # Веб-плеер
        elif self.path == '/':
            info = get_song_info()
            html = f'''<!DOCTYPE html>
<html>
<head>
    <title>🎵 Super Radio</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        *{{margin:0;padding:0;box-sizing:border-box}}
        body{{
            font-family:'Segoe UI',sans-serif;
            background:linear-gradient(135deg,#667eea,#764ba2);
            min-height:100vh;
            display:flex;
            justify-content:center;
            align-items:center;
            padding:20px
        }}
        .player{{
            background:rgba(255,255,255,0.95);
            border-radius:30px;
            padding:40px;
            max-width:500px;
            width:100%;
            text-align:center;
            box-shadow:0 25px 50px rgba(0,0,0,0.3)
        }}
        h1{{color:#764ba2;margin-bottom:10px}}
        .status{{color:#4caf50;font-weight:bold;margin-bottom:20px}}
        audio{{width:100%;margin:20px 0;border-radius:30px}}
        .info{{background:#f5f5f5;padding:15px;border-radius:15px;margin:15px 0}}
        .url{{
            background:#f0f0f0;
            padding:12px;
            border-radius:10px;
            font-size:11px;
            word-break:break-all;
            margin-top:15px
        }}
        button{{
            background:linear-gradient(135deg,#667eea,#764ba2);
            color:white;
            border:none;
            padding:12px 24px;
            border-radius:30px;
            cursor:pointer;
            margin-top:15px
        }}
        footer{{margin-top:20px;font-size:11px;color:#999}}
    </style>
</head>
<body>
    <div class="player">
        <h1>🎵 Super Radio</h1>
        <div class="status">🟢 LIVE</div>
        <audio controls autoplay><source src="/radio.mp3"></audio>
        <div class="info">
            <div>🎤 {info['title']}</div>
            <div>⏱️ {info['duration']} | 👥 {len(clients)} слушателей</div>
        </div>
        <div class="url">🔗 {STREAM_URL}</div>
        <a href="/radio.mp3" download><button>📥 Скачать поток</button></a>
        <footer>24/7 | Работает в любом плеере</footer>
    </div>
</body>
</html>'''
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(html.encode())
            return
        
        # API статуса
        elif self.path == '/status':
            info = get_song_info()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'status': 'online',
                'current_song': info['title'],
                'listeners': len(clients),
                'playlist_size': len(playlist),
                'ip': PUBLIC_IP,
                'port': PORT
            }).encode())
            return
        
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    server = HTTPServer(('0.0.0.0', PORT), RadioHandler)
    print(f"✅ HTTP сервер: http://0.0.0.0:{PORT}")
    server.serve_forever()

# ==================== ФОНОВЫЙ СТРИМИНГ ====================
def background_stream():
    global current_song_data, current_song_position, clients
    
    while True:
        if not playlist:
            time.sleep(5)
            continue
        
        if not current_song_data:
            next_song()
        
        if current_song_data:
            current_song_data.seek(current_song_position)
            chunk = current_song_data.read(8192)
            
            if chunk:
                current_song_position += len(chunk)
                for client in clients[:]:
                    try:
                        client.write(chunk)
                        client.flush()
                    except:
                        if client in clients:
                            clients.remove(client)
            else:
                next_song()
        
        time.sleep(0.05)

# ==================== TELEGRAM БОТ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info = get_song_info()
    
    keyboard = [
        [InlineKeyboardButton("🎵 СЛУШАТЬ", url=STREAM_URL)],
        [InlineKeyboardButton("🌐 ПЛЕЕР", url=f"http://{PUBLIC_IP}:{PORT}")],
        [InlineKeyboardButton("📊 СТАТУС", callback_data="status")],
        [InlineKeyboardButton("📤 ДОБАВИТЬ ТРЕК", callback_data="upload")]
    ]
    
    await update.message.reply_text(
        f"🎵 *SUPER RADIO*\n\n"
        f"┌─ 🎤 `{info['title']}`\n"
        f"├─ 👥 {len(clients)} слушателей\n"
        f"├─ 📀 {len(playlist)} песен\n"
        f"└─ 🌍 {PUBLIC_IP}:{PORT}\n\n"
        f"🔗 *Ссылка:*\n`{STREAM_URL}`\n\n"
        f"💡 Отправьте ссылку друзьям!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "status":
        info = get_song_info()
        await query.edit_message_text(
            f"📊 *СТАТУС*\n\n"
            f"🎵 {info['title']}\n"
            f"👥 {len(clients)} слушателей\n"
            f"📀 {len(playlist)} песен\n"
            f"✅ Сервер активен\n\n"
            f"🔗 {STREAM_URL}",
            parse_mode='Markdown'
        )
    elif query.data == "upload":
        await query.edit_message_text(
            "📤 *ЗАГРУЗКА*\n\n"
            "Просто отправьте мне MP3 файл!\n\n"
            "✅ Максимум 50MB\n"
            "🎵 Поддерживаются MP3",
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
            
            load_playlist()
            
            await msg.edit_text(
                f"✅ *Добавлено!*\n\n"
                f"📀 {file.file_name}\n"
                f"📊 Всего: {len(playlist)} песен",
                parse_mode='Markdown'
            )
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка: {str(e)}")

async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🔗 *Ссылка для друзей*\n\n`{STREAM_URL}`\n\n"
        f"📱 Откройте в браузере или VLC",
        parse_mode='Markdown'
    )

# ==================== ЗАПУСК ====================
def main():
    print("\n" + "=" * 50)
    print("🎵 SUPER RADIO BOT")
    print("=" * 50)
    print(f"🌍 Внешний IP: {PUBLIC_IP}")
    print(f"📡 Порт: {PORT}")
    print(f"🔗 Ссылка: {STREAM_URL}")
    print("=" * 50 + "\n")
    
    # Загружаем плейлист
    load_playlist()
    
    # Запускаем HTTP сервер
    http_thread = threading.Thread(target=run_server, daemon=True)
    http_thread.start()
    
    time.sleep(2)
    
    # Запускаем стриминг
    stream_thread = threading.Thread(target=background_stream, daemon=True)
    stream_thread.start()
    
    # Запускаем бота
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    
    print("✅ Бот запущен!")
    app.run_polling()

if __name__ == '__main__':
    main()
