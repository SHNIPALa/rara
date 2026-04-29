#!/usr/bin/env python3
"""
SUPER RADIO BOT - с альтернативными туннелями
"""

import os
import time
import threading
import random
import json
import subprocess
import re
import urllib.request
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
tunnel_ready = False

# ==================== АЛЬТЕРНАТИВНЫЕ ТУННЕЛИ ====================

def start_bore_tunnel():
    """Bore - простой туннель на Rust"""
    global public_url, tunnel_ready
    
    try:
        # Проверяем наличие bore
        result = subprocess.run(['which', 'bore'], capture_output=True)
        if result.returncode != 0:
            print("  Bore не установлен, пропускаем...")
            return False
        
        print("🔄 Запуск Bore туннеля...")
        process = subprocess.Popen(
            ['bore', 'local', str(PORT), '--to', 'bore.pub'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        for i in range(30):
            if process.stdout:
                try:
                    line = process.stdout.readline()
                    if line:
                        print(f"  {line.strip()}")
                        match = re.search(r'bore\.pub:(\d+)', line)
                        if match:
                            port = match.group(1)
                            public_url = f"https://bore.pub:{port}"
                            tunnel_ready = True
                            print(f"\n✅ BORE ТУННЕЛЬ: {public_url}")
                            return True
                except:
                    pass
            time.sleep(1)
    except Exception as e:
        print(f"Ошибка Bore: {e}")
    return False

def start_cloudflare_tunnel():
    """Cloudflare Tunnel (требует установки cloudflared)"""
    global public_url, tunnel_ready
    
    try:
        result = subprocess.run(['which', 'cloudflared'], capture_output=True)
        if result.returncode != 0:
            print("  cloudflared не установлен, пропускаем...")
            return False
        
        print("🔄 Запуск Cloudflare Tunnel...")
        process = subprocess.Popen(
            ['cloudflared', 'tunnel', '--url', f'http://localhost:{PORT}'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        for i in range(40):
            if process.stdout:
                try:
                    line = process.stdout.readline()
                    if line:
                        print(f"  {line.strip()}")
                        match = re.search(r'https://[a-z0-9\-]+\.trycloudflare\.com', line)
                        if match:
                            public_url = match.group(0)
                            tunnel_ready = True
                            print(f"\n✅ CLOUDFLARE ТУННЕЛЬ: {public_url}")
                            return True
                except:
                    pass
            time.sleep(1)
    except Exception as e:
        print(f"Ошибка Cloudflare: {e}")
    return False

def start_localtunnel():
    """LocalTunnel через npx"""
    global public_url, tunnel_ready
    
    try:
        result = subprocess.run(['which', 'npx'], capture_output=True)
        if result.returncode != 0:
            print("  npx не установлен, пропускаем...")
            return False
        
        print("🔄 Запуск LocalTunnel...")
        process = subprocess.Popen(
            ['npx', 'localtunnel', '--port', str(PORT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        for i in range(40):
            if process.stdout:
                try:
                    line = process.stdout.readline()
                    if line:
                        print(f"  {line.strip()}")
                        match = re.search(r'https://[a-z0-9\-]+\.loca\.lt', line)
                        if match:
                            public_url = match.group(0)
                            tunnel_ready = True
                            print(f"\n✅ LOCALTUNNEL: {public_url}")
                            return True
                except:
                    pass
            time.sleep(1)
    except Exception as e:
        print(f"Ошибка LocalTunnel: {e}")
    return False

def start_ssh_tunnel():
    """SSH туннель с отключенной проверкой хоста"""
    global public_url, tunnel_ready
    
    commands = [
        (['ssh', '-o', 'StrictHostKeyChecking=no', '-p', '443', '-R0:localhost:8080', 'a.pinggy.io'],
         r'https://[a-z0-9]+\.a\.pinggy\.link'),
        (['ssh', '-o', 'StrictHostKeyChecking=no', '-R', '80:localhost:8080', 'localhost.run'],
         r'https://[a-z0-9\-]+\.loca\.lt'),
        (['ssh', '-o', 'StrictHostKeyChecking=no', '-R', '80:localhost:8080', 'serveo.net'],
         r'https://[a-z0-9\-]+\.serveo\.net')
    ]
    
    for cmd, pattern in commands:
        try:
            print(f"🔄 Запуск: {cmd[0]}...")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            for i in range(30):
                if process.stdout:
                    try:
                        line = process.stdout.readline()
                        if line:
                            print(f"  {line.strip()}")
                            match = re.search(pattern, line)
                            if match:
                                public_url = match.group(0)
                                tunnel_ready = True
                                print(f"\n✅ SSH ТУННЕЛЬ: {public_url}")
                                return True
                    except:
                        pass
                time.sleep(1)
            
            process.terminate()
        except Exception as e:
            print(f"Ошибка: {e}")
            continue
    
    return False

def start_tunnel():
    """Пробуем все варианты туннелей по очереди"""
    
    # Сначала пробуем Bore (не требует SSH)
    if start_bore_tunnel():
        return True
    
    # Потом LocalTunnel (через npx)
    if start_localtunnel():
        return True
    
    # Потом SSH туннели
    if start_ssh_tunnel():
        return True
    
    # В конце Cloudflare
    if start_cloudflare_tunnel():
        return True
    
    print("⚠️ Не удалось создать туннель")
    return False

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
            web_url = public_url if public_url else f"http://localhost:{PORT}"
            
            html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>🎵 Super Radio</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
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
        }}
        h1{{color:#764ba2;}}
        audio{{width:100%;margin:20px 0;}}
        .info{{background:#f0f0f0;padding:15px;border-radius:15px;margin:20px 0;}}
        .url{{background:#e0e0e0;padding:12px;border-radius:10px;font-size:11px;word-break:break-all;}}
        button{{background:linear-gradient(135deg,#667eea,#764ba2);color:white;border:none;padding:12px 24px;border-radius:30px;cursor:pointer;margin:5px;}}
    </style>
</head>
<body>
    <div class="player">
        <h1>🎵 Super Radio</h1>
        <audio controls autoplay><source src="/radio.mp3" type="audio/mpeg"></audio>
        <div class="info">
            🎤 {info['title']}<br>
            👥 {len(clients)} слушателей | 📀 {len(playlist)} песен
        </div>
        <div class="url">🔗 {web_url}</div>
        <button onclick="window.location.href='/radio.mp3'">📥 Скачать поток</button>
    </div>
    <script>
        setInterval(async()=>{{
            const res=await fetch('/status');
            const d=await res.json();
            document.querySelector('.info').innerHTML=`🎤 ${{d.current_song}}<br>👥 ${{d.listeners}} слушателей | 📀 ${{d.playlist_size}} песен`;
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
def start_command(update, context):
    global tunnel_ready, public_url
    
    if not tunnel_ready or not public_url:
        update.message.reply_text(
            "⏳ *Радио запускается...*\n\n"
            "Подождите 30-60 секунд, туннель создаётся.\n"
            "Затем отправьте /start снова!",
            parse_mode='Markdown'
        )
        return
    
    info = get_song_info()
    web_url = public_url
    
    keyboard = [
        [InlineKeyboardButton("🎵 ОТКРЫТЬ ПЛЕЕР", url=web_url)],
        [InlineKeyboardButton("📥 СКАЧАТЬ ПОТОК", url=f"{web_url}/radio.mp3")],
        [InlineKeyboardButton("📊 СТАТУС", callback_data="status")]
    ]
    
    update.message.reply_text(
        f"🎵 *SUPER RADIO*\n\n"
        f"🎤 `{info['title']}`\n"
        f"👥 {len(clients)} слушателей\n"
        f"📀 {len(playlist)} песен\n\n"
        f"🔗 *Ссылка для друзей:*\n`{web_url}`\n\n"
        f"💡 Отправьте ссылку друзьям - откроется плеер!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def callback_handler(update, context):
    query = update.callback_query
    query.answer()
    
    if query.data == "status":
        info = get_song_info()
        web_url = public_url if public_url else "Ожидание..."
        query.edit_message_text(
            f"📊 *СТАТУС*\n\n"
            f"🎵 {info['title']}\n"
            f"👥 {len(clients)} слушателей\n"
            f"📀 {len(playlist)} песен\n\n"
            f"🔗 Ссылка: `{web_url}`",
            parse_mode='Markdown'
        )

def handle_audio(update, context):
    if update.message.audio:
        file = update.message.audio
        msg = update.message.reply_text(f"📥 Загружаю {file.file_name}...")
        
        try:
            new_file = context.bot.get_file(file.file_id)
            file_path = Path(MUSIC_FOLDER) / file.file_name
            new_file.download_to_drive(file_path)
            load_playlist()
            msg.edit_text(f"✅ Добавлено! Всего песен: {len(playlist)}")
        except Exception as e:
            msg.edit_text(f"❌ Ошибка: {str(e)}")

# ==================== ЗАПУСК ====================
def main():
    global tunnel_ready, public_url
    
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
    
    # Запускаем туннель
    print("\n🔄 Запуск туннеля...")
    tunnel_thread = threading.Thread(target=start_tunnel, daemon=True)
    tunnel_thread.start()
    
    # Ждём туннель
    for i in range(45):
        if tunnel_ready:
            break
        time.sleep(1)
    
    if tunnel_ready and public_url:
        print(f"\n✅ ТУННЕЛЬ ГОТОВ: {public_url}")
    else:
        print("\n⚠️ Туннель не создан")
        print("💡 Альтернатива: запустите вручную в другом терминале:")
        print("   npx localtunnel --port 8080")
    
    # Запускаем бота
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    
    print("\n✅ БОТ ЗАПУЩЕН!")
    print("=" * 50 + "\n")
    
    app.run_polling()

if __name__ == '__main__':
    main()
