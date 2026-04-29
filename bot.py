#!/usr/bin/env python3
"""
ПРОСТОЕ РАДИО - работает напрямую через ваш IP
Без Icecast, без Ngrok, без LocalTunnel
"""

import os
import time
import threading
import subprocess
import random
import socket
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from mutagen.mp3 import MP3

# ==================== НАСТРОЙКИ ====================
PORT = 8080
MUSIC_FOLDER = "music"
TOKEN = "8726694308:AAF5_WwE1Tu9csG7ZKjwgG50n-1A5nByM4Q"

# Получаем внешний IP
def get_public_ip():
    try:
        import requests
        ip = requests.get('https://api.ipify.org', timeout=3).text
        return ip
    except:
        return socket.gethostbyname(socket.gethostname())

PUBLIC_IP = get_public_ip()
STREAM_URL = f"http://{PUBLIC_IP}:{PORT}/radio.mp3"

print(f"\n🌍 ВАШ ВНЕШНИЙ IP: {PUBLIC_IP}")
print(f"🔗 ССЫЛКА ДЛЯ ДРУЗЕЙ: {STREAM_URL}\n")

# Создаем папку для музыки
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

def get_song_duration(song_path):
    try:
        return int(MP3(song_path).info.length)
    except:
        return 180

def next_song():
    global current_song_index, current_song_data, current_song_position, clients
    current_song_index = (current_song_index + 1) % len(playlist)
    current_song_data = open(playlist[current_song_index], 'rb')
    current_song_position = 0
    print(f"🎵 Сейчас играет: {playlist[current_song_index].name}")

# ==================== HTTP СЕРВЕР (РАЗДАЁТ РАДИО) ====================
class RadioHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        pass  # Отключаем лишние логи
    
    def do_GET(self):
        global clients, current_song_data, current_song_position, playlist
        
        # Главная страница с плеером
        if self.path == '/' or self.path == '/player':
            html = f'''<!DOCTYPE html>
<html>
<head>
    <title>🎵 Super Radio</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 0;
            padding: 20px;
        }}
        .player {{
            background: rgba(255,255,255,0.95);
            border-radius: 20px;
            padding: 40px;
            max-width: 450px;
            width: 100%;
            text-align: center;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }}
        h1 {{
            color: #764ba2;
            margin-bottom: 10px;
        }}
        .status {{
            color: #4caf50;
            font-weight: bold;
            margin-bottom: 20px;
        }}
        audio {{
            width: 100%;
            margin: 20px 0;
            border-radius: 30px;
        }}
        .url {{
            background: #f0f0f0;
            padding: 12px;
            border-radius: 10px;
            font-size: 12px;
            word-break: break-all;
            margin-top: 20px;
        }}
        .button {{
            display: inline-block;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            padding: 10px 20px;
            border-radius: 25px;
            text-decoration: none;
            margin-top: 15px;
        }}
        footer {{
            margin-top: 20px;
            font-size: 11px;
            color: #999;
        }}
    </style>
</head>
<body>
    <div class="player">
        <h1>🎵 Super Radio</h1>
        <div class="status">🟢 ONLINE</div>
        <audio controls autoplay>
            <source src="/radio.mp3" type="audio/mpeg">
            Ваш браузер не поддерживает аудио
        </audio>
        <div class="url">
            🔗 Прямая ссылка:<br>
            <a href="/radio.mp3">{STREAM_URL}</a>
        </div>
        <a href="/radio.mp3" class="button">📥 Скачать поток</a>
        <footer>24/7 | Бесконечный поток | Слушайте в любом плеере</footer>
    </div>
</body>
</html>'''
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(html.encode())
            return
        
        # Аудио поток
        elif self.path == '/radio.mp3' or self.path == '/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Cache-Control', 'no-cache, no-store')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            
            # Добавляем клиента
            clients.append(self.wfile)
            print(f"🔊 Новый слушатель (всего: {len(clients)})")
            
            try:
                # Держим соединение открытым
                while True:
                    time.sleep(1)
                    if not stream_active:
                        break
            except:
                pass
            finally:
                if self.wfile in clients:
                    clients.remove(self.wfile)
                print(f"🔇 Слушатель ушел (осталось: {len(clients)})")
            return
        
        # Статус API
        elif self.path == '/api/status':
            import json
            current_song = playlist[current_song_index] if playlist else None
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'status': 'online',
                'current_song': current_song.name if current_song else 'None',
                'listeners': len(clients),
                'playlist_size': len(playlist),
                'ip': PUBLIC_IP,
                'port': PORT
            }).encode())
            return
        
        else:
            self.send_response(404)
            self.end_headers()

def run_http_server():
    server = HTTPServer(('0.0.0.0', PORT), RadioHandler)
    print(f"✅ HTTP сервер запущен на порту {PORT}")
    server.serve_forever()

# ==================== ФОНОВЫЙ СТРИМИНГ ====================
def background_stream():
    global current_song_data, current_song_position, clients, current_song_index, playlist
    
    while True:
        if not playlist:
            time.sleep(5)
            continue
        
        # Открываем файл если нужно
        if not current_song_data:
            current_song_data = open(playlist[current_song_index], 'rb')
            current_song_position = 0
            print(f"🎵 Начало: {playlist[current_song_index].name}")
        
        # Читаем кусок файла
        current_song_data.seek(current_song_position)
        chunk = current_song_data.read(8192)
        
        if chunk:
            current_song_position += len(chunk)
            # Отправляем всем клиентам
            for client in clients[:]:
                try:
                    client.write(chunk)
                    client.flush()
                except:
                    if client in clients:
                        clients.remove(client)
        else:
            # Конец песни - переключаем
            current_song_data.close()
            current_song_data = None
            current_song_index = (current_song_index + 1) % len(playlist)
            print(f"⏭️ Следующий трек: {playlist[current_song_index].name}")
        
        time.sleep(0.05)  # 50ms задержка

# ==================== TELEGRAM БОТ ====================
async def start(update, context):
    current_song = playlist[current_song_index] if playlist else None
    
    keyboard = [
        [InlineKeyboardButton("🎵 СЛУШАТЬ РАДИО", url=STREAM_URL)],
        [InlineKeyboardButton("🌐 ВЕБ-ПЛЕЕР", url=f"http://{PUBLIC_IP}:{PORT}")],
        [InlineKeyboardButton("📥 СКАЧАТЬ ПОТОК", url=STREAM_URL)],
        [InlineKeyboardButton("📊 СТАТУС", callback_data="status")]
    ]
    
    await update.message.reply_text(
        f"🎵 *Super Radio*\n\n"
        f"┌─ 🎤 Сейчас: `{current_song.name if current_song else 'Нет песен'}`\n"
        f"├─ 👥 Слушателей: {len(clients)}\n"
        f"├─ 📀 Песен: {len(playlist)}\n"
        f"└─ 🌍 Ваш IP: {PUBLIC_IP}\n\n"
        f"🔗 *Ссылка для друзей:*\n"
        f"`{STREAM_URL}`\n\n"
        f"💡 Просто отправьте ссылку друзьям!\n"
        f"Она работает в браузере и VLC",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def status_callback(update, context):
    query = update.callback_query
    await query.answer()
    
    current_song = playlist[current_song_index] if playlist else None
    await query.edit_message_text(
        f"📊 *Статус радио*\n\n"
        f"┌─ 🎵 Сейчас: `{current_song.name if current_song else 'Нет'}`\n"
        f"├─ 👥 Слушателей: {len(clients)}\n"
        f"├─ 📀 Плейлист: {len(playlist)} песен\n"
        f"├─ 🌍 Порт: {PORT}\n"
        f"└─ 🎚️ Статус: ✅ Активен\n\n"
        f"🔗 Ссылка: `{STREAM_URL}`",
        parse_mode='Markdown'
    )

async def handle_audio(update, context):
    if update.message.audio:
        file = update.message.audio
        msg = await update.message.reply_text(f"📥 Загружаю {file.file_name}...")
        
        new_file = await context.bot.get_file(file.file_id)
        file_path = Path(MUSIC_FOLDER) / file.file_name
        await new_file.download_to_drive(file_path)
        
        load_playlist()
        await msg.edit_text(f"✅ Добавлено! Всего песен: {len(playlist)}")

async def link_command(update, context):
    await update.message.reply_text(
        f"🔗 *Ссылка для друзей*\n\n"
        f"`{STREAM_URL}`\n\n"
        f"📱 Отправьте эту ссылку - она работает как радио!",
        parse_mode='Markdown'
    )

# ==================== ЗАПУСК ====================
def main():
    # Загружаем музыку
    if load_playlist() == 0:
        print("\n⚠️ ВНИМАНИЕ: Нет музыкальных файлов!")
        print("📁 Положите MP3 файлы в папку 'music'")
        print("   Или отправьте их через Telegram бота\n")
    
    # Запускаем HTTP сервер в потоке
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    
    time.sleep(2)
    
    # Запускаем фоновый стриминг
    stream_thread = threading.Thread(target=background_stream, daemon=True)
    stream_thread.start()
    
    # Запускаем бота
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(CallbackQueryHandler(status_callback, pattern="status"))
    
    print("\n" + "=" * 50)
    print("🎵 SUPER RADIO ЗАПУЩЕН")
    print("=" * 50)
    print(f"\n🔗 ССЫЛКА ДЛЯ ДРУЗЕЙ:")
    print(f"   {STREAM_URL}")
    print(f"\n🌐 ВЕБ-ПЛЕЕР:")
    print(f"   http://{PUBLIC_IP}:{PORT}")
    print(f"\n📊 API СТАТУСА:")
    print(f"   http://{PUBLIC_IP}:{PORT}/api/status")
    print("\n🤖 БОТ АКТИВЕН в Telegram")
    print("=" * 50 + "\n")
    
    app.run_polling()

if __name__ == '__main__':
    main()
