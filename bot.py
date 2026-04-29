#!/usr/bin/env python3
"""
SUPER RADIO BOT - Встроенный туннель и веб-плеер
"""

import os
import time
import threading
import socket
import random
import json
import requests
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from mutagen.mp3 import MP3

# ==================== КОНФИГУРАЦИЯ ====================
PORT = 8080
TUNNEL_PORT = 8081  # Порт для туннеля
MUSIC_FOLDER = "music"
TOKEN = "8726694308:AAF5_WwE1Tu9csG7ZKjwgG50n-1A5nByM4Q"

# Создаём папку для музыки
Path(MUSIC_FOLDER).mkdir(exist_ok=True)

# Глобальные переменные
playlist = []
current_song_index = 0
current_song_data = None
current_song_position = 0
clients = []
tunnel_url = None
public_ip = None

# ==================== ОПРЕДЕЛЕНИЕ IP ====================
def get_public_ip():
    """Получение внешнего IP"""
    try:
        ip = requests.get('https://api.ipify.org', timeout=3).text.strip()
        return ip
    except:
        try:
            ip = requests.get('https://icanhazip.com', timeout=3).text.strip()
            return ip
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
                'duration': f"{duration//60}:{duration%60:02d}",
                'size': round(song.stat().st_size / 1024 / 1024, 2)
            }
        except:
            return {'title': song.stem, 'duration': '0:00', 'size': 0}
    return {'title': 'Нет песен', 'duration': '0:00', 'size': 0}

# ==================== HTTP РАДИО СЕРВЕР ====================
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
        
        # Красивый веб-плеер
        elif self.path == '/':
            info = get_song_info()
            stream_url = f"http://{public_ip}:{PORT}/radio.mp3" if public_ip else f"http://localhost:{PORT}/radio.mp3"
            
            html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>🎵 Super Radio</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}
        
        .player {{
            background: rgba(255, 255, 255, 0.95);
            border-radius: 30px;
            padding: 40px;
            max-width: 500px;
            width: 100%;
            text-align: center;
            box-shadow: 0 25px 50px rgba(0, 0, 0, 0.3);
            backdrop-filter: blur(10px);
            transition: transform 0.3s;
        }}
        
        .player:hover {{
            transform: scale(1.02);
        }}
        
        h1 {{
            color: #764ba2;
            margin-bottom: 10px;
            font-size: 2em;
        }}
        
        .subtitle {{
            color: #666;
            margin-bottom: 20px;
            font-size: 0.9em;
        }}
        
        .status {{
            color: #4caf50;
            font-weight: bold;
            margin-bottom: 20px;
            animation: pulse 2s infinite;
        }}
        
        @keyframes pulse {{
            0% {{ opacity: 1; }}
            50% {{ opacity: 0.6; }}
            100% {{ opacity: 1; }}
        }}
        
        audio {{
            width: 100%;
            margin: 20px 0;
            border-radius: 30px;
        }}
        
        .info {{
            background: linear-gradient(135deg, #f5f5f5, #e8e8e8);
            padding: 15px;
            border-radius: 15px;
            margin: 20px 0;
        }}
        
        .song-title {{
            font-size: 1.2em;
            font-weight: bold;
            color: #764ba2;
            margin-bottom: 8px;
        }}
        
        .stats {{
            display: flex;
            justify-content: space-around;
            color: #666;
            font-size: 0.9em;
        }}
        
        .url {{
            background: #f0f0f0;
            padding: 12px;
            border-radius: 10px;
            font-size: 11px;
            word-break: break-all;
            margin-top: 15px;
        }}
        
        .buttons {{
            margin-top: 15px;
        }}
        
        button {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 30px;
            cursor: pointer;
            font-size: 14px;
            margin: 5px;
            transition: opacity 0.3s;
        }}
        
        button:hover {{
            opacity: 0.9;
        }}
        
        footer {{
            margin-top: 20px;
            font-size: 11px;
            color: #999;
        }}
        
        a {{
            color: #764ba2;
            text-decoration: none;
        }}
        
        .live {{
            display: inline-block;
            background: #ff4444;
            color: white;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 10px;
            margin-left: 5px;
            animation: pulse 1s infinite;
        }}
    </style>
</head>
<body>
    <div class="player">
        <h1>🎵 Super Radio</h1>
        <div class="subtitle">24/7 Интернет-радио</div>
        <div class="status">
            🟢 LIVE <span class="live">LIVE</span>
        </div>
        
        <audio controls autoplay>
            <source src="/radio.mp3" type="audio/mpeg">
            Ваш браузер не поддерживает аудио
        </audio>
        
        <div class="info">
            <div class="song-title">🎤 {info['title']}</div>
            <div class="stats">
                <span>⏱️ {info['duration']}</span>
                <span>👥 {len(clients)} слушателей</span>
                <span>📀 {len(playlist)} песен</span>
            </div>
        </div>
        
        <div class="url">
            🔗 Прямая ссылка:<br>
            <a href="{stream_url}">{stream_url}</a>
        </div>
        
        <div class="buttons">
            <a href="/radio.mp3" download>
                <button>📥 Скачать поток</button>
            </a>
            <button onclick="window.location.reload()">🔄 Обновить</button>
        </div>
        
        <footer>
            💡 Вставьте ссылку в VLC: Media → Open Network Stream
        </footer>
    </div>
    
    <script>
        setInterval(async () => {{
            try {{
                const res = await fetch('/status');
                const data = await res.json();
                document.querySelector('.song-title').innerHTML = `🎤 ${{data.current_song}}`;
                document.querySelector('.stats').innerHTML = `
                    <span>👥 ${{data.listeners}} слушателей</span>
                    <span>📀 ${{data.playlist_size}} песен</span>
                `;
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
        
        # API статуса
        elif self.path == '/status':
            info = get_song_info()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({
                'status': 'online',
                'current_song': info['title'],
                'listeners': len(clients),
                'playlist_size': len(playlist),
                'port': PORT
            }).encode())
            return
        
        else:
            self.send_response(404)
            self.end_headers()

def run_radio_server():
    server = HTTPServer(('0.0.0.0', PORT), RadioHandler)
    print(f"✅ Радио сервер: http://0.0.0.0:{PORT}")
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

# ==================== СВОЙ ТУННЕЛЬ (альтернатива LocalTunnel) ====================
class TunnelHandler(BaseHTTPRequestHandler):
    """Прокси для перенаправления трафика"""
    
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        try:
            # Перенаправляем запрос на локальный радио сервер
            resp = requests.get(f'http://localhost:{PORT}{self.path}', stream=True)
            self.send_response(resp.status_code)
            for header, value in resp.headers.items():
                if header.lower() not in ['transfer-encoding', 'content-length']:
                    self.send_header(header, value)
            self.end_headers()
            
            if resp.status_code == 200:
                for chunk in resp.iter_content(chunk_size=8192):
                    self.wfile.write(chunk)
        except:
            self.send_response(502)
            self.end_headers()

def run_tunnel():
    """Запуск простого туннеля на другом порту"""
    server = HTTPServer(('0.0.0.0', TUNNEL_PORT), TunnelHandler)
    print(f"✅ Туннель: http://0.0.0.0:{TUNNEL_PORT}")
    server.serve_forever()

# ==================== TELEGRAM БОТ ====================
async def start(update, context):
    global tunnel_url, public_ip
    
    # Определяем IP для ссылки
    if not public_ip:
        public_ip = get_public_ip()
    
    if public_ip:
        main_url = f"http://{public_ip}:{PORT}"
        tunnel_url = f"http://{public_ip}:{TUNNEL_PORT}"
    else:
        main_url = f"http://localhost:{PORT}"
        tunnel_url = f"http://localhost:{TUNNEL_PORT}"
    
    info = get_song_info()
    
    keyboard = [
        [InlineKeyboardButton("🎵 ОТКРЫТЬ ПЛЕЕР", url=main_url)],
        [InlineKeyboardButton("📥 СКАЧАТЬ ПОТОК", url=f"{main_url}/radio.mp3")],
        [InlineKeyboardButton("🔄 АЛЬТЕРНАТИВНЫЙ ПОРТ", url=tunnel_url)],
        [InlineKeyboardButton("📊 СТАТУС", callback_data="status")],
        [InlineKeyboardButton("📤 ДОБАВИТЬ ТРЕК", callback_data="upload")]
    ]
    
    await update.message.reply_text(
        f"🎵 *SUPER RADIO*\n\n"
        f"┌─ 🎤 `{info['title']}`\n"
        f"├─ 👥 {len(clients)} слушателей\n"
        f"├─ 📀 {len(playlist)} песен\n"
        f"└─ 🌍 Порт: {PORT}\n\n"
        f"🔗 *Главная ссылка:*\n`{main_url}`\n\n"
        f"🔄 *Запасной порт:*\n`{tunnel_url}`\n\n"
        f"💡 Отправьте ссылку друзьям - откроется плеер!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    
    if query.data == "status":
        info = get_song_info()
        await query.edit_message_text(
            f"📊 *СТАТУС РАДИО*\n\n"
            f"🎵 Сейчас: `{info['title']}`\n"
            f"⏱️ Длительность: {info['duration']}\n"
            f"👥 Слушателей: {len(clients)}\n"
            f"📀 Песен: {len(playlist)}\n"
            f"✅ Сервер: Активен\n\n"
            f"🔗 Ссылка: http://{public_ip}:{PORT}/radio.mp3" if public_ip else "Локальный доступ",
            parse_mode='Markdown'
        )
    elif query.data == "upload":
        await query.edit_message_text(
            "📤 *ЗАГРУЗКА МУЗЫКИ*\n\n"
            "1. Положите MP3 в папку `music`\n"
            "2. Или отправьте MP3 файл прямо сейчас\n\n"
            "✅ Поддерживаются MP3 до 50MB\n"
            "🎵 После загрузки трек появится в плейлисте",
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
            
            await msg.edit_text(
                f"✅ *Добавлено!*\n\n"
                f"📀 {file.file_name}\n"
                f"📊 Всего песен: {len(playlist)}",
                parse_mode='Markdown'
            )
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка: {str(e)}")

async def link_command(update, context):
    if public_ip:
        main_url = f"http://{public_ip}:{PORT}"
        await update.message.reply_text(
            f"🔗 *ССЫЛКИ ДЛЯ ДРУЗЕЙ*\n\n"
            f"🎵 *Веб-плеер:*\n`{main_url}`\n\n"
            f"📥 *Прямой поток:*\n`{main_url}/radio.mp3`\n\n"
            f"🔄 *Запасной порт:*\n`http://{public_ip}:{TUNNEL_PORT}`\n\n"
            f"💡 Откройте в браузере или VLC",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"🔗 *ЛОКАЛЬНАЯ ССЫЛКА*\n\n"
            f"http://localhost:{PORT}\n\n"
            f"⚠️ Вы в локальной сети, используйте ngrok",
            parse_mode='Markdown'
        )

# ==================== ЗАПУСК ====================
def main():
    global public_ip
    
    print("\n" + "=" * 50)
    print("🎵 SUPER RADIO BOT")
    print("=" * 50)
    
    # Получаем внешний IP
    public_ip = get_public_ip()
    
    if public_ip:
        print(f"🌍 ВНЕШНИЙ IP: {public_ip}")
        print(f"🔗 ВЕБ-ПЛЕЕР: http://{public_ip}:{PORT}")
        print(f"📡 ПОТОК: http://{public_ip}:{PORT}/radio.mp3")
        print(f"🔄 ЗАПАСНОЙ ПОРТ: http://{public_ip}:{TUNNEL_PORT}")
    else:
        print("⚠️ НЕ УДАЛОСЬ ОПРЕДЕЛИТЬ ВНЕШНИЙ IP")
        print("🔗 ЛОКАЛЬНЫЙ ДОСТУП: http://localhost:{PORT}")
    
    print("=" * 50 + "\n")
    
    # Загружаем плейлист
    load_playlist()
    
    # Запускаем основной радио сервер
    radio_thread = threading.Thread(target=run_radio_server, daemon=True)
    radio_thread.start()
    
    # Запускаем туннель на другом порту
    tunnel_thread = threading.Thread(target=run_tunnel, daemon=True)
    tunnel_thread.start()
    
    time.sleep(2)
    
    # Запускаем фоновый стриминг
    stream_thread = threading.Thread(target=background_stream, daemon=True)
    stream_thread.start()
    
    # Запускаем бота
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    
    print("✅ Бот запущен! Откройте Telegram и отправьте /start")
    print("=" * 50 + "\n")
    
    app.run_polling()

if __name__ == '__main__':
    main()
