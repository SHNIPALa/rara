#!/usr/bin/env python3
"""
SUPER RADIO BOT - with ngrok
"""

import os
import time
import threading
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
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "8726694308:AAF5_WwE1Tu9csG7ZKjwgG50n-1A5nByM4Q")
PUBLIC_URL = os.getenv('PUBLIC_URL', 'http://localhost:8080')

Path(MUSIC_FOLDER).mkdir(exist_ok=True)

# Глобальные переменные
playlist = []
current_song_index = 0
current_song_data = None
current_song_position = 0
clients = []

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
                'duration': f"{duration//60}:{duration%60:02d}"
            }
        except:
            return {'title': song.stem, 'duration': '0:00'}
    return {'title': 'Нет песен', 'duration': '0:00'}

# ==================== HTTP РАДИО СЕРВЕР ====================
class RadioHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        global clients
        
        if self.path in ['/radio.mp3', '/stream']:
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Cache-Control', 'no-cache')
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
        
        elif self.path == '/':
            info = get_song_info()
            web_url = PUBLIC_URL
            
            html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>🎵 Super Radio</title>
    <style>
        body{{
            font-family:'Segoe UI',sans-serif;
            background:linear-gradient(135deg,#667eea,#764ba2);
            min-height:100vh;
            display:flex;
            justify-content:center;
            align-items:center;
            margin:0;
            padding:20px;
        }}
        .player{{
            background:rgba(255,255,255,0.95);
            border-radius:30px;
            padding:40px;
            max-width:500px;
            width:100%;
            text-align:center;
            box-shadow:0 25px 50px rgba(0,0,0,0.3);
        }}
        h1{{color:#764ba2;margin-bottom:10px}}
        .status{{color:#4caf50;font-weight:bold;margin-bottom:20px}}
        audio{{width:100%;margin:20px 0;border-radius:30px}}
        .info{{
            background:#f5f5f5;
            padding:15px;
            border-radius:15px;
            margin:20px 0
        }}
        .url{{
            background:#e8e8e8;
            padding:12px;
            border-radius:10px;
            font-size:11px;
            word-break:break-all
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
        <audio controls autoplay><source src="/radio.mp3" type="audio/mpeg"></audio>
        <div class="info">
            🎤 {info['title']}<br>
            👥 {len(clients)} слушателей | 📀 {len(playlist)} песен
        </div>
        <div class="url">🔗 {web_url}</div>
        <button onclick="window.location.href='/radio.mp3'">📥 Скачать поток</button>
        <footer>💡 Вставьте в VLC: Media → Open Network Stream</footer>
    </div>
    <script>
        setInterval(()=>{{
            fetch('/status')
                .then(res=>res.json())
                .then(d=>{{
                    document.querySelector('.info').innerHTML=`🎤 ${{d.current_song}}<br>👥 ${{d.listeners}} слушателей | 📀 ${{d.playlist_size}} песен`;
                }});
        }},5000);
    </script>
</body>
</html>'''
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(html.encode())
            return
        
        elif self.path == '/status':
            info = get_song_info()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'current_song': info['title'],
                'listeners': len(clients),
                'playlist_size': len(playlist)
            }).encode())
            return
        
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    server = HTTPServer(('0.0.0.0', PORT), RadioHandler)
    print(f"✅ Радио сервер: http://localhost:{PORT}")
    server.serve_forever()

# ==================== СТРИМИНГ ====================
def background_stream():
    global current_song_data, current_song_position, clients
    
    while True:
        if not playlist:
            time.sleep(5)
            load_playlist()
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
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info = get_song_info()
    web_url = PUBLIC_URL
    
    keyboard = [
        [InlineKeyboardButton("🎵 ОТКРЫТЬ ПЛЕЕР", url=web_url)],
        [InlineKeyboardButton("📥 СКАЧАТЬ ПОТОК", url=f"{web_url}/radio.mp3")],
        [InlineKeyboardButton("📊 СТАТУС", callback_data="status")],
        [InlineKeyboardButton("📤 ДОБАВИТЬ ТРЕК", callback_data="upload")]
    ]
    
    await update.message.reply_text(
        f"🎵 *SUPER RADIO*\n\n"
        f"🎤 `{info['title']}`\n"
        f"👥 {len(clients)} слушателей\n"
        f"📀 {len(playlist)} песен\n\n"
        f"🔗 *Ссылка для друзей:*\n`{web_url}`\n\n"
        f"💡 Отправьте ссылку друзьям - откроется плеер!",
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
            f"📀 {len(playlist)} песен\n\n"
            f"🔗 Ссылка: `{PUBLIC_URL}`",
            parse_mode='Markdown'
        )
    elif query.data == "upload":
        await query.edit_message_text(
            "📤 *ЗАГРУЗКА МУЗЫКИ*\n\n"
            "Отправьте MP3 файл боту, и он добавится в плейлист!\n\n"
            "✅ Поддерживаются MP3 до 50MB",
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
            await msg.edit_text(f"✅ Добавлено! Всего песен: {len(playlist)}")
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка: {str(e)}")

async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🔗 *ССЫЛКА ДЛЯ ДРУЗЕЙ*\n\n"
        f"`{PUBLIC_URL}`\n\n"
        f"📱 Отправьте эту ссылку друзьям!\n"
        f"🎵 Она работает в браузере как плеер",
        parse_mode='Markdown'
    )

# ==================== ЗАПУСК ====================
def main():
    print("\n" + "=" * 50)
    print("🎵 SUPER RADIO BOT")
    print("=" * 50)
    
    # Загружаем плейлист
    load_playlist()
    
    # Запускаем HTTP сервер в потоке
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    time.sleep(2)
    
    # Запускаем стриминг
    stream_thread = threading.Thread(target=background_stream, daemon=True)
    stream_thread.start()
    
    # Запускаем бота
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    
    print(f"\n🔗 ПУБЛИЧНАЯ ССЫЛКА: {PUBLIC_URL}")
    print("\n✅ БОТ ЗАПУЩЕН!")
    print("=" * 50 + "\n")
    
    app.run_polling()

if __name__ == '__main__':
    main()
