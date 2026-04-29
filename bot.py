#!/usr/bin/env python3
"""
SUPER RADIO BOT - с bore.pub туннелем
"""

import os
import time
import threading
import random
import json
import requests
import subprocess
import re
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from mutagen.mp3 import MP3

# ==================== КОНФИГУРАЦИЯ ====================
PORT = 8080
MUSIC_FOLDER = "music"
TOKEN = "8726694308:AAF5_WwE1Tu9csG7ZKjwgG50n-1A5nByM4Q"

Path(MUSIC_FOLDER).mkdir(exist_ok=True)

# Глобальные переменные
playlist = []
current_song_index = 0
current_song_data = None
current_song_position = 0
clients = []
public_url = None
bore_process = None

# ==================== BORE ТУННЕЛЬ ====================
def get_bore_url():
    """Получение URL от bore"""
    try:
        # Ждём появления URL в логах
        for i in range(30):
            result = subprocess.run(['pgrep', '-a', 'bore'], capture_output=True, text=True)
            if result.stdout:
                # Пытаемся получить URL через API bore (если есть)
                try:
                    resp = requests.get('http://localhost:4040/api/tunnels', timeout=2)
                    tunnels = resp.json().get('tunnels', [])
                    for tunnel in tunnels:
                        if tunnel.get('proto') == 'https':
                            return tunnel.get('public_url')
                except:
                    pass
            time.sleep(1)
        return None
    except:
        return None

# ==================== ЗАГРУЗКА ПЛЕЙЛИСТА ====================
def load_playlist():
    global playlist
    playlist = list(Path(MUSIC_FOLDER).glob("*.mp3"))
    if playlist:
        random.shuffle(playlist)
        print(f"📀 Загружено {len(playlist)} песен")
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
                'duration': f"{duration//60}:{duration%60:02d}"
            }
        except:
            return {'title': song.stem, 'duration': '0:00'}
    return {'title': 'Нет песен', 'duration': '0:00'}

# ==================== HTTP СЕРВЕР ====================
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
            stream_url = f"{public_url}/radio.mp3" if public_url else f"http://localhost:{PORT}/radio.mp3"
            
            html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>🎵 Super Radio</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', sans-serif;
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
            text-align: center;
            box-shadow: 0 25px 50px rgba(0,0,0,0.3);
        }}
        h1 {{ color: #764ba2; margin-bottom: 10px; }}
        .status {{ color: #4caf50; font-weight: bold; margin-bottom: 20px; animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0% {{ opacity: 1; }} 50% {{ opacity: 0.6; }} 100% {{ opacity: 1; }} }}
        audio {{ width: 100%; margin: 20px 0; border-radius: 30px; }}
        .info {{
            background: linear-gradient(135deg, #f5f5f5, #e8e8e8);
            padding: 15px;
            border-radius: 15px;
            margin: 20px 0;
        }}
        .song-title {{ font-size: 1.2em; font-weight: bold; color: #764ba2; margin-bottom: 8px; }}
        .stats {{ display: flex; justify-content: space-around; color: #666; }}
        .url {{
            background: #f0f0f0;
            padding: 12px;
            border-radius: 10px;
            font-size: 11px;
            word-break: break-all;
            margin-top: 15px;
        }}
        button {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 30px;
            cursor: pointer;
            margin: 5px;
        }}
        footer {{ margin-top: 20px; font-size: 11px; color: #999; }}
        .live {{ background: #ff4444; color: white; padding: 2px 8px; border-radius: 10px; font-size: 10px; margin-left: 5px; animation: pulse 1s infinite; display: inline-block; }}
    </style>
</head>
<body>
    <div class="player">
        <h1>🎵 Super Radio</h1>
        <div class="status">🟢 LIVE <span class="live">LIVE</span></div>
        <audio controls autoplay><source src="/radio.mp3" type="audio/mpeg"></audio>
        <div class="info">
            <div class="song-title">🎤 {info['title']}</div>
            <div class="stats">
                <span>⏱️ {info['duration']}</span>
                <span>👥 {len(clients)} слушателей</span>
                <span>📀 {len(playlist)} песен</span>
            </div>
        </div>
        <div class="url">🔗 <a href="{stream_url}">{stream_url}</a></div>
        <button onclick="window.location.href='/radio.mp3'">📥 Скачать поток</button>
        <footer>💡 Вставьте ссылку в VLC: Media → Open Network Stream</footer>
    </div>
    <script>
        setInterval(async () => {{
            try {{
                const res = await fetch('/status');
                const data = await res.json();
                document.querySelector('.song-title').innerHTML = `🎤 ${{data.current_song}}`;
            }} catch(e) {{}}
        }}, 5000);
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
async def start(update, context):
    global public_url
    
    if not public_url:
        public_url = "http://localhost:8080"
    
    stream_url = f"{public_url}/radio.mp3"
    info = get_song_info()
    
    keyboard = [
        [InlineKeyboardButton("🎵 ОТКРЫТЬ ПЛЕЕР", url=public_url)],
        [InlineKeyboardButton("📥 СКАЧАТЬ ПОТОК", url=stream_url)],
        [InlineKeyboardButton("📊 СТАТУС", callback_data="status")],
        [InlineKeyboardButton("📤 ДОБАВИТЬ ТРЕК", callback_data="upload")]
    ]
    
    await update.message.reply_text(
        f"🎵 *SUPER RADIO*\n\n"
        f"┌─ 🎤 `{info['title']}`\n"
        f"├─ 👥 {len(clients)} слушателей\n"
        f"├─ 📀 {len(playlist)} песен\n"
        f"└─ 🌍 {public_url}\n\n"
        f"🔗 *Ссылка:*\n`{public_url}`\n\n"
        f"💡 Отправьте ссылку друзьям!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    
    if query.data == "status":
        info = get_song_info()
        await query.edit_message_text(
            f"📊 *СТАТУС*\n\n"
            f"🎵 {info['title']}\n"
            f"👥 {len(clients)} слушателей\n"
            f"📀 {len(playlist)} песен\n"
            f"🔗 {public_url}",
            parse_mode='Markdown'
        )
    elif query.data == "upload":
        await query.edit_message_text(
            "📤 Отправьте MP3 файл!\n\n"
            "Поддерживаются MP3 до 50MB",
            parse_mode='Markdown'
        )

async def handle_audio(update, context):
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

# ==================== ЗАПУСК ====================
def main():
    global public_url
    
    print("\n" + "=" * 50)
    print("🎵 SUPER RADIO BOT")
    print("=" * 50)
    
    # Загружаем плейлист
    load_playlist()
    
    # Запускаем сервер
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    time.sleep(2)
    
    # Запускаем стриминг
    stream_thread = threading.Thread(target=background_stream, daemon=True)
    stream_thread.start()
    
    print("\n✅ Радио работает локально: http://localhost:8080")
    print("\n🔗 ДЛЯ ПУБЛИЧНОГО ДОСТУПА:")
    print("   Запустите в ДРУГОМ терминале:")
    print("   bore local 8080 --to bore.pub")
    print("\n   После запуска появится ссылка вида:")
    print("   https://bore.pub:12345")
    print("\n   Это и есть ваша ссылка для друзей!")
    
    # Запускаем бота
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    
    print("\n✅ Бот запущен!")
    app.run_polling()

if __name__ == '__main__':
    main()
