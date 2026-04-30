#!/usr/bin/env python3
"""
SUPER RADIO BOT - Полноценная версия с админкой, модерацией и радиостанцией
"""

import os
import time
import threading
import random
import json
import sqlite3
import subprocess
import requests
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from mutagen.mp3 import MP3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# ==================== КОНФИГУРАЦИЯ ====================
PORT = 8080
MUSIC_FOLDER = "music"
DATA_FOLDER = "data"
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
NGROK_TOKEN = os.getenv('NGROK_AUTH_TOKEN')
ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]

# Создаём папки
Path(MUSIC_FOLDER).mkdir(exist_ok=True)
Path(DATA_FOLDER).mkdir(exist_ok=True)

# Глобальные переменные
playlist = []
current_song_index = 0
current_song_data = None
current_song_position = 0
clients = []
public_url = None
ngrok_process = None

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, approved INTEGER DEFAULT 0, date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pending_songs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  filename TEXT, user_id INTEGER, user_name TEXT, date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS approved_songs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  filename TEXT, added_by INTEGER, date TEXT)''')
    conn.commit()
    conn.close()

init_db()

# ==================== NGROK ТУННЕЛЬ ====================
def start_ngrok():
    global public_url
    
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
                        print(f"\n✅ NGROK ТУННЕЛЬ: {public_url}")
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
        for i, song in enumerate(playlist[:5]):
            print(f"   {i+1}. {song.name}")
    else:
        print(f"⚠️ НЕТ MP3! Положите файлы в папку 'music' или загрузите через бота")

def next_song():
    global current_song_index, current_song_data, current_song_position
    if not playlist:
        return
    current_song_index = (current_song_index + 1) % len(playlist)
    if current_song_data:
        current_song_data.close()
    current_song_data = open(playlist[current_song_index], 'rb')
    current_song_position = 0
    
    # Записываем в историю
    conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
    c = conn.cursor()
    c.execute("INSERT INTO approved_songs (filename, added_by, date) VALUES (?, ?, ?)",
              (playlist[current_song_index].name, 0, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    print(f"🎵 Сейчас играет: {playlist[current_song_index].name}")

def get_song_info():
    if playlist and current_song_index < len(playlist):
        song = playlist[current_song_index]
        try:
            audio = MP3(song)
            duration = int(audio.info.length)
            return {
                'title': song.stem,
                'duration': f"{duration//60}:{duration%60:02d}",
                'filename': song.name
            }
        except:
            return {'title': song.stem, 'duration': '0:00', 'filename': song.name}
    return {'title': 'Нет песен', 'duration': '0:00', 'filename': 'Нет'}

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
        .status{{color:#4caf50;font-weight:bold;margin-bottom:20px;animation:pulse 2s infinite}}
        @keyframes pulse{{0%{{opacity:1}}50%{{opacity:0.6}}100%{{opacity:1}}}}
        audio{{width:100%;margin:20px 0;border-radius:30px}}
        .info{{
            background:linear-gradient(135deg,#f5f5f5,#e8e8e8);
            padding:15px;
            border-radius:15px;
            margin:20px 0
        }}
        .song-title{{font-size:1.2em;font-weight:bold;color:#764ba2;margin-bottom:8px}}
        .stats{{display:flex;justify-content:space-around;color:#666}}
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
            margin:5px
        }}
        footer{{margin-top:20px;font-size:11px;color:#999}}
        .live{{background:#ff4444;color:white;padding:2px 8px;border-radius:10px;font-size:10px;margin-left:5px;animation:pulse 1s infinite;display:inline-block}}
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
        <div class="url">🔗 <a href="{web_url}">{web_url}</a></div>
        <button onclick="window.location.href='/radio.mp3'">📥 Скачать поток</button>
        <footer>💡 Вставьте в VLC: Media → Open Network Stream</footer>
    </div>
    <script>
        setInterval(()=>{{
            fetch('/status')
                .then(res=>res.json())
                .then(d=>{{
                    document.querySelector('.song-title').innerHTML=`🎤 ${{d.current_song}}`;
                    document.querySelector('.stats').innerHTML=`<span>👥 ${{d.listeners}} слушателей</span><span>📀 ${{d.playlist_size}} песен</span>`;
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

# ==================== TELEGRAM БОТ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "No username"
    
    # Сохраняем пользователя
    conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, date) VALUES (?, ?, ?)",
              (user_id, username, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    info = get_song_info()
    web_url = public_url if public_url else f"http://localhost:{PORT}"
    
    keyboard = [
        [InlineKeyboardButton("🎵 ОТКРЫТЬ ПЛЕЕР", url=web_url)],
        [InlineKeyboardButton("📥 СКАЧАТЬ ПОТОК", url=f"{web_url}/radio.mp3")],
        [InlineKeyboardButton("📤 ОТПРАВИТЬ ТРЕК", callback_data="upload")],
        [InlineKeyboardButton("📊 СТАТУС", callback_data="status")]
    ]
    
    if user_id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("🔧 АДМИН ПАНЕЛЬ", callback_data="admin")])
    
    await update.message.reply_text(
        f"🎵 *SUPER RADIO*\n\n"
        f"┌─ 🎤 `{info['title']}`\n"
        f"├─ 👥 {len(clients)} слушателей онлайн\n"
        f"├─ 📀 {len(playlist)} песен в ротации\n"
        f"├─ 🌍 Статус: {'✅ Публичный' if public_url else '⏳ Локальный'}\n"
        f"└─ 🔗 `{web_url}`\n\n"
        f"💡 *Как слушать:*\n"
        f"• Открыть ссылку в браузере\n"
        f"• Или вставить в VLC\n\n"
        f"📤 *Хотите добавить трек?*\n"
        f"Нажмите «Отправить трек» и загрузите MP3",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "status":
        info = get_song_info()
        web_url = public_url if public_url else "Локальный режим"
        await query.edit_message_text(
            f"📊 *СТАТУС РАДИО*\n\n"
            f"┌─ 🎵 Сейчас: `{info['title']}`\n"
            f"├─ ⏱️ Длительность: {info['duration']}\n"
            f"├─ 👥 Слушателей: {len(clients)}\n"
            f"├─ 📀 Плейлист: {len(playlist)} песен\n"
            f"├─ 🌍 Публичный URL: {web_url}\n"
            f"└─ 🎚️ Сервер: ✅ Активен",
            parse_mode='Markdown'
        )
    
    elif query.data == "upload":
        await query.edit_message_text(
            "📤 *ОТПРАВКА ТРЕКА*\n\n"
            "Просто отправьте мне MP3 файл!\n\n"
            "После отправки трек уйдёт на модерацию.\n"
            "Администратор одобрит его, и он появится в эфире.\n\n"
            "✅ *Требования:*\n"
            "• Формат: MP3\n"
            "• Размер: до 50MB\n"
            "• Качество: любое",
            parse_mode='Markdown'
        )
    
    elif query.data == "admin" and user_id in ADMIN_IDS:
        await show_admin_panel(update, context)
    
    elif query.data.startswith("approve_"):
        song_id = int(query.data.split("_")[1])
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
            await query.edit_message_text(f"✅ Трек «{filename}» одобрен и добавлен в эфир!")
        else:
            await query.edit_message_text("❌ Трек не найден")
        conn.commit()
        conn.close()
        await show_admin_panel(update, context)
    
    elif query.data.startswith("reject_"):
        song_id = int(query.data.split("_")[1])
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
            await query.edit_message_text(f"❌ Трек «{filename}» отклонён")
        else:
            await query.edit_message_text("❌ Трек не найден")
        conn.commit()
        conn.close()
        await show_admin_panel(update, context)
    
    elif query.data.startswith("user_"):
        target_id = int(query.data.split("_")[1])
        conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
        c = conn.cursor()
        c.execute("UPDATE users SET approved = 1 WHERE user_id = ?", (target_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"✅ Пользователь одобрен!")
        await show_admin_panel(update, context)
    
    elif query.data == "back":
        await start(update, context)

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
    c = conn.cursor()
    
    # Получаем треки на модерации
    c.execute("SELECT id, filename, user_name, date FROM pending_songs ORDER BY date DESC")
    pending = c.fetchall()
    
    # Получаем пользователей на модерации
    c.execute("SELECT user_id, username FROM users WHERE approved = 0")
    users = c.fetchall()
    
    conn.close()
    
    keyboard = []
    
    if pending:
        keyboard.append([InlineKeyboardButton("📀 ТРЕКИ НА МОДЕРАЦИИ:", callback_data="none")])
        for song_id, filename, user_name, date in pending[:10]:
            keyboard.append([
                InlineKeyboardButton(f"✅ {filename[:25]}", callback_data=f"approve_{song_id}"),
                InlineKeyboardButton(f"❌", callback_data=f"reject_{song_id}")
            ])
    
    if users:
        keyboard.append([InlineKeyboardButton("👥 ПОЛЬЗОВАТЕЛИ:", callback_data="none")])
        for user_id, username in users[:10]:
            keyboard.append([
                InlineKeyboardButton(f"➕ {username or user_id}", callback_data=f"user_{user_id}")
            ])
    
    if not pending and not users:
        keyboard.append([InlineKeyboardButton("✅ Нет новых треков или пользователей", callback_data="none")])
    
    keyboard.append([InlineKeyboardButton("◀️ НАЗАД", callback_data="back")])
    
    await query.edit_message_text(
        f"🔧 *АДМИН ПАНЕЛЬ*\n\n"
        f"📀 Треков на модерации: {len(pending)}\n"
        f"👥 Пользователей на модерации: {len(users)}\n\n"
        f"Управление:",
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
        
        msg = await update.message.reply_text(f"📥 Загружаю {file_name}...")
        
        try:
            new_file = await context.bot.get_file(file.file_id)
            
            # Сохраняем в pending
            Path("pending").mkdir(exist_ok=True)
            file_path = Path("pending") / file_name
            await new_file.download_to_drive(file_path)
            
            # Сохраняем в БД
            conn = sqlite3.connect(f'{DATA_FOLDER}/radio.db')
            c = conn.cursor()
            c.execute("INSERT INTO pending_songs (filename, user_id, user_name, date) VALUES (?, ?, ?, ?)",
                      (file_name, user_id, username, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            
            # Уведомляем админов
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"📀 *НОВЫЙ ТРЕК НА МОДЕРАЦИЮ!*\n\n"
                        f"От: {username}\n"
                        f"Файл: {file_name}\n"
                        f"Размер: {file.file_size / 1024 / 1024:.2f} MB",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            
            await msg.edit_text(
                f"✅ *Трек отправлен на модерацию!*\n\n"
                f"📀 {file_name}\n"
                f"После одобрения трек появится в эфире",
                parse_mode='Markdown'
            )
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка: {str(e)}")

async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    web_url = public_url if public_url else "Туннель ещё не готов"
    await update.message.reply_text(
        f"🔗 *ССЫЛКА ДЛЯ ДРУЗЕЙ*\n\n"
        f"`{web_url}`\n\n"
        f"📱 Отправьте эту ссылку друзьям!\n"
        f"🎵 Откроется веб-плеер с радио\n\n"
        f"💡 Также можно вставить в VLC:\n"
        f"`{web_url}/radio.mp3`",
        parse_mode='Markdown'
    )

# ==================== ЗАПУСК ====================
def main():
    print("\n" + "=" * 50)
    print("🎵 SUPER RADIO BOT v2.0")
    print("=" * 50)
    
    # Загружаем плейлист
    load_playlist()
    
    # Запускаем радио сервер
    server_thread = threading.Thread(target=run_radio_server, daemon=True)
    server_thread.start()
    
    time.sleep(2)
    
    # Запускаем аудио поток
    stream_thread = threading.Thread(target=audio_stream, daemon=True)
    stream_thread.start()
    
    # Запускаем ngrok
    print("\n🔄 Запуск ngrok туннеля...")
    ngrok_thread = threading.Thread(target=start_ngrok, daemon=True)
    ngrok_thread.start()
    
    # Ждём ngrok
    for i in range(30):
        if public_url:
            break
        time.sleep(1)
    
    if public_url:
        print(f"\n✅ ТУННЕЛЬ ГОТОВ: {public_url}")
        print("=" * 50)
        print(f"🔗 ССЫЛКА ДЛЯ ДРУЗЕЙ: {public_url}")
        print("=" * 50)
    
    # Запускаем бота
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("link", link_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    
    print("\n✅ БОТ ЗАПУЩЕН!")
    print("=" * 50 + "\n")
    
    application.run_polling()

if __name__ == '__main__':
    main()
