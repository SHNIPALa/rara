#!/usr/bin/env python3
"""
SUPER RADIO BOT - Aiogram версия (стабильная)
"""

import os
import time
import threading
import random
import json
import sqlite3
import subprocess
import requests
import asyncio
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from mutagen.mp3 import MP3
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from dotenv import load_dotenv

load_dotenv()

# ==================== КОНФИГУРАЦИЯ ====================
PORT = 8080
MUSIC_FOLDER = "music"
DATA_FOLDER = "data"
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
NGROK_TOKEN = os.getenv('NGROK_AUTH_TOKEN')
ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]

# Создаём папки
Path(MUSIC_FOLDER).mkdir(exist_ok=True)
Path(DATA_FOLDER).mkdir(exist_ok=True)
Path("pending").mkdir(exist_ok=True)

# Глобальные переменные
playlist = []
current_song_index = 0
current_song_data = None
current_song_position = 0
clients = []
public_url = None
ngrok_ready = False

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pending_songs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  filename TEXT, user_id INTEGER, user_name TEXT, date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS approved_songs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  filename TEXT, date TEXT)''')
    conn.commit()
    conn.close()

init_db()

# ==================== NGROK ТУННЕЛЬ ====================
def start_ngrok():
    global public_url, ngrok_ready
    
    try:
        subprocess.run(['ngrok', 'config', 'add-authtoken', NGROK_TOKEN], capture_output=True)
        subprocess.Popen(
            ['ngrok', 'http', str(PORT), '--log=stdout'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        for i in range(30):
            try:
                resp = requests.get('http://localhost:4040/api/tunnels', timeout=2)
                tunnels = resp.json().get('tunnels', [])
                for tunnel in tunnels:
                    if tunnel.get('proto') == 'https':
                        public_url = tunnel.get('public_url')
                        ngrok_ready = True
                        print(f"\n✅ NGROK: {public_url}")
                        return True
            except:
                pass
            time.sleep(1)
        return False
    except Exception as e:
        print(f"Ngrok error: {e}")
        return False

# ==================== РАДИО ПЛЕЙЛИСТ ====================
def load_playlist():
    global playlist
    playlist = []
    for mp3 in Path(MUSIC_FOLDER).glob("*.mp3"):
        playlist.append(mp3)
    if playlist:
        random.shuffle(playlist)
        print(f"📀 Загружено {len(playlist)} песен")
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
    
    conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
    c = conn.cursor()
    c.execute("INSERT INTO approved_songs (filename, date) VALUES (?, ?)",
              (playlist[current_song_index].name, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
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
            web_url = public_url if public_url else f"http://localhost:{PORT}"
            
            html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>🎵 Super Radio</title>
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

def run_radio_server():
    server = HTTPServer(('0.0.0.0', PORT), RadioHandler)
    print(f"✅ Радио сервер: http://localhost:{PORT}")
    server.serve_forever()

# ==================== АУДИО ПОТОК ====================
def audio_stream():
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

# ==================== AIOGRAM БОТ ====================
@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "No username"
    
    conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, date) VALUES (?, ?, ?)",
              (user_id, username, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    if not ngrok_ready or not public_url:
        await message.answer(
            "🎵 *SUPER RADIO*\n\n"
            "⏳ *Радио запускается...*\n\n"
            "Подождите 30 секунд, туннель создаётся.\n"
            "Отправьте /start снова через минуту!",
            parse_mode="Markdown"
        )
        return
    
    info = get_song_info()
    web_url = public_url
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 ОТКРЫТЬ ПЛЕЕР", url=web_url)],
        [InlineKeyboardButton(text="📥 СКАЧАТЬ ПОТОК", url=f"{web_url}/radio.mp3")],
        [InlineKeyboardButton(text="📤 ОТПРАВИТЬ ТРЕК", callback_data="upload")],
        [InlineKeyboardButton(text="📊 СТАТУС", callback_data="status")]
    ])
    
    if user_id in ADMIN_IDS:
        keyboard.inline_keyboard.append(
            [InlineKeyboardButton(text="🔧 АДМИН ПАНЕЛЬ", callback_data="admin")]
        )
    
    await message.answer(
        f"🎵 *SUPER RADIO*\n\n"
        f"┌─ 🎤 `{info['title']}`\n"
        f"├─ 👥 {len(clients)} слушателей\n"
        f"├─ 📀 {len(playlist)} песен\n"
        f"└─ 🔗 `{web_url}`\n\n"
        f"Отправьте ссылку друзьям!",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if callback.data == "status":
        info = get_song_info()
        web_url = public_url if public_url else "Локальный"
        await callback.message.edit_text(
            f"📊 *СТАТУС*\n\n"
            f"🎵 {info['title']}\n"
            f"👥 {len(clients)} слушателей\n"
            f"📀 {len(playlist)} песен\n"
            f"🔗 {web_url}",
            parse_mode="Markdown"
        )
        await callback.answer()
    
    elif callback.data == "upload":
        await callback.message.edit_text(
            "📤 *ОТПРАВЬТЕ MP3*\n\n"
            "Просто отправьте мне MP3 файл!\n\n"
            "После одобрения трек появится в эфире.",
            parse_mode="Markdown"
        )
        await callback.answer()
    
    elif callback.data == "admin" and user_id in ADMIN_IDS:
        await show_admin_panel(callback)
    
    elif callback.data.startswith("approve_"):
        song_id = int(callback.data.split("_")[1])
        conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
        c = conn.cursor()
        c.execute("SELECT filename FROM pending_songs WHERE id = ?", (song_id,))
        result = c.fetchone()
        
        if result:
            filename = result[0]
            src = Path("pending") / filename
            dst = Path(MUSIC_FOLDER) / filename
            if src.exists():
                src.rename(dst)
                load_playlist()
            c.execute("DELETE FROM pending_songs WHERE id = ?", (song_id,))
            await callback.message.edit_text(f"✅ Трек одобрен!")
        else:
            await callback.message.edit_text("❌ Трек не найден")
        conn.commit()
        conn.close()
        await callback.answer()
    
    elif callback.data.startswith("reject_"):
        song_id = int(callback.data.split("_")[1])
        conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
        c = conn.cursor()
        c.execute("SELECT filename FROM pending_songs WHERE id = ?", (song_id,))
        result = c.fetchone()
        
        if result:
            filename = result[0]
            src = Path("pending") / filename
            if src.exists():
                src.unlink()
            c.execute("DELETE FROM pending_songs WHERE id = ?", (song_id,))
            await callback.message.edit_text(f"❌ Трек отклонён")
        else:
            await callback.message.edit_text("❌ Трек не найден")
        conn.commit()
        conn.close()
        await callback.answer()
    
    elif callback.data == "back":
        await start_command(callback.message)
    
    else:
        await callback.answer()

async def show_admin_panel(callback: types.CallbackQuery):
    conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
    c = conn.cursor()
    c.execute("SELECT id, filename, user_name, date FROM pending_songs ORDER BY date DESC")
    pending = c.fetchall()
    conn.close()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    if pending:
        keyboard.inline_keyboard.append(
            [InlineKeyboardButton(text="📀 ТРЕКИ НА МОДЕРАЦИИ:", callback_data="none")]
        )
        for song_id, filename, user_name, date in pending[:10]:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text=f"✅ {filename[:20]}", callback_data=f"approve_{song_id}"),
                InlineKeyboardButton(text="❌", callback_data=f"reject_{song_id}")
            ])
    else:
        keyboard.inline_keyboard.append(
            [InlineKeyboardButton(text="✅ Нет треков", callback_data="none")]
        )
    
    keyboard.inline_keyboard.append(
        [InlineKeyboardButton(text="◀️ НАЗАД", callback_data="back")]
    )
    
    await callback.message.edit_text(
        f"🔧 *АДМИН ПАНЕЛЬ*\n\n"
        f"Треков на модерации: {len(pending)}",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message()
async def handle_audio(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "No username"
    
    if message.audio:
        file = message.audio
        file_name = file.file_name
        
        if file.file_size > 50 * 1024 * 1024:
            await message.reply("❌ Файл слишком большой! Максимум 50MB")
            return
        
        msg = await message.reply(f"📥 Загружаю {file_name}...")
        
        try:
            file_path = Path("pending") / file_name
            await bot.download_file(file.file_id, destination=str(file_path))
            
            conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
            c = conn.cursor()
            c.execute("INSERT INTO pending_songs (filename, user_id, user_name, date) VALUES (?, ?, ?, ?)",
                      (file_name, user_id, username, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"📀 *НОВЫЙ ТРЕК!*\n\nОт: {username}\nФайл: {file_name}",
                        parse_mode="Markdown"
                    )
                except:
                    pass
            
            await msg.edit_text(f"✅ Трек отправлен на модерацию!")
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка: {str(e)}")

@dp.message(Command("link"))
async def link_command(message: types.Message):
    if not ngrok_ready or not public_url:
        await message.reply("⏳ Туннель ещё создаётся, подождите 30 секунд...")
        return
    
    await message.reply(
        f"🔗 *ССЫЛКА ДЛЯ ДРУЗЕЙ*\n\n"
        f"`{public_url}`\n\n"
        f"📱 Отправьте эту ссылку друзьям!",
        parse_mode="Markdown"
    )

# ==================== ЗАПУСК ====================
async def on_startup():
    print("\n" + "=" * 50)
    print("🎵 SUPER RADIO BOT (Aiogram)")
    print("=" * 50)
    
    load_playlist()
    
    # Запуск сервера
    threading.Thread(target=run_radio_server, daemon=True).start()
    await asyncio.sleep(2)
    threading.Thread(target=audio_stream, daemon=True).start()
    
    # Запуск ngrok
    print("\n🔄 Запуск ngrok...")
    threading.Thread(target=start_ngrok, daemon=True).start()
    
    # Ждём ngrok
    for i in range(30):
        if ngrok_ready and public_url:
            print(f"\n✅ ССЫЛКА ДЛЯ ДРУЗЕЙ: {public_url}")
            break
        await asyncio.sleep(1)
    
    print("\n✅ БОТ ЗАПУЩЕН!")
    print("=" * 50 + "\n")

async def main():
    await on_startup()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
