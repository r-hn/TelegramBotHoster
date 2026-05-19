import telebot
from telebot.types import (
    ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton
)
import os
import subprocess
import json
import threading
import time
import sys
import shutil
from datetime import datetime, timedelta
import zipfile
import tempfile
import traceback
import random
import string
from dotenv import load_dotenv

load_dotenv()

# Configuration
API_TOKEN = os.getenv('API_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))
DATA_FILE = 'users.json'
HOSTED_DIR = 'hosted'
BOTS_DIR = os.path.join(HOSTED_DIR, 'bots')
LOGS_DIR = os.path.join(HOSTED_DIR, 'logs')
TEMP_DIR = os.path.join(HOSTED_DIR, 'temp')
REDEEM_CODES_FILE = 'redeem_codes.json'

bot = telebot.TeleBot(API_TOKEN)

# Security: Ensure all paths are within hosted directory
def secure_path(path, base_dir=HOSTED_DIR):
    try:
        abs_path = os.path.abspath(os.path.join(base_dir, path))
        abs_base = os.path.abspath(base_dir)
        if not abs_path.startswith(abs_base):
            raise ValueError("Path traversal attempt detected")
        return abs_path
    except:
        raise ValueError("Invalid path")

# Initialize directories
def init_directories():
    dirs = [HOSTED_DIR, BOTS_DIR, LOGS_DIR, TEMP_DIR]
    for dir_path in dirs:
        os.makedirs(dir_path, exist_ok=True)
    
    for dir_path in [BOTS_DIR, LOGS_DIR, TEMP_DIR]:
        gitkeep_path = os.path.join(dir_path, '.gitkeep')
        if not os.path.exists(gitkeep_path):
            with open(gitkeep_path, 'w') as f:
                f.write('')

init_directories()

# Format timedelta for display
def format_timedelta(td):
    seconds = td.total_seconds()
    periods = [
        ('day', 86400),
        ('hour', 3600),
        ('minute', 60),
        ('second', 1)
    ]
    
    parts = []
    for period_name, period_seconds in periods:
        if seconds > period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            if period_value > 0:
                part = f"{int(period_value)} {period_name}"
                if period_value > 1:
                    part += "s"
                parts.append(part)
    
    return " ".join(parts) if parts else "0 seconds"

# Load redeem codes
def load_redeem_codes():
    try:
        if os.path.exists(REDEEM_CODES_FILE):
            with open(REDEEM_CODES_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {}

# Save redeem codes
def save_redeem_codes(codes):
    with open(REDEEM_CODES_FILE, 'w') as f:
        json.dump(codes, f, indent=2)

# User management system with expiration
def load_users():
    data_path = secure_path(DATA_FILE)
    if os.path.exists(data_path):
        try:
            with open(data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('users', {}), data.get('bot_owners', {}), data.get('bot_configs', {})
        except:
            pass
    return {OWNER_ID: {"expiry": None, "username": "Owner"}}, {}, {}

def save_users(users, bot_owners, bot_configs):
    data_path = secure_path(DATA_FILE)
    try:
        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump({
                'users': users, 
                'bot_owners': bot_owners,
                'bot_configs': bot_configs
            }, f, indent=2)
    except Exception as e:
        print(f"Error saving users: {e}")

users, bot_owners, bot_configs = load_users()
running_bots = {}
bot_upload_states = {}
redeem_codes = load_redeem_codes()

# Notification system with username
def notify_owner(message):
    try:
        bot.send_message(OWNER_ID, f"🔔 <b>System Notification</b>\n{message}", parse_mode="HTML")
    except Exception as e:
        print(f"Error notifying owner: {e}")

def notify_user(user_id, message, parse_mode="HTML"):
    try:
        bot.send_message(user_id, message, parse_mode=parse_mode)
    except Exception as e:
        print(f"Error notifying user {user_id}: {e}")

# Enhanced bot management with security
def install_requirements(bot_name):
    try:
        bot_path = secure_path(os.path.join('bots', bot_name))
        req_path = os.path.join(bot_path, 'requirements.txt')
        
        if os.path.exists(req_path):
            venv_path = os.path.join(bot_path, 'venv')
            if not os.path.exists(venv_path):
                subprocess.run([sys.executable, '-m', 'venv', venv_path], 
                             cwd=bot_path, capture_output=True)
            
            if os.name == 'nt':
                pip_path = os.path.join(venv_path, 'Scripts', 'pip.exe')
            else:
                pip_path = os.path.join(venv_path, 'bin', 'pip')
            
            if os.path.exists(pip_path):
                subprocess.run([pip_path, 'install', '-r', req_path], 
                             cwd=bot_path, capture_output=True, timeout=300)
                return os.path.join(venv_path, 'bin', 'python') if os.name != 'nt' else os.path.join(venv_path, 'Scripts', 'python.exe')
        
        return sys.executable
    except Exception as e:
        print(f"Error installing requirements for {bot_name}: {e}")
        return sys.executable

def restart_bot(name, owner_id):
    try:
        bot_path = secure_path(os.path.join('bots', name))
        main_file = os.path.join(bot_path, f"{name}.py")
        log_path = secure_path(os.path.join('logs', f'{name}.log'))
        
        if not os.path.exists(main_file):
            notify_user(owner_id, f"❌ Main file not found for bot '<code>{name}</code>'")
            return
        
        python_exec = install_requirements(name)
        
        restart_count = 0
        max_restarts = 10
        
        auto_restart = bot_configs.get(name, {}).get('auto_restart', True)
        
        while restart_count < max_restarts and auto_restart:
            try:
                with open(log_path, 'a', encoding='utf-8') as log_file:
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    log_file.write(f"\n--- [{timestamp}] Starting bot {name} (attempt {restart_count + 1}) ---\n")
                    
                    env = os.environ.copy()
                    env['PYTHONPATH'] = bot_path
                    
                    config = bot_configs.get(name, {})
                    for key, value in config.items():
                        env[key] = str(value)
                    
                    process = subprocess.Popen(
                        [python_exec, f"{name}.py"],
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        cwd=bot_path,
                        env=env
                    )
                    
                    running_bots[name] = {
                        'process': process,
                        'start_time': datetime.now(),
                        'restart_count': restart_count
                    }
                    
                    if restart_count == 0:
                        if owner_id != OWNER_ID:
                            notify_owner(f"🚀 Bot '<code>{name}</code>' started by user {owner_id}")
                        notify_user(owner_id, f"✅ Your bot '<code>{name}</code>' is now running!")
                    
                    process.wait()
                    
                    if name not in running_bots:
                        break
                    
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    log_file.write(f"\n--- [{timestamp}] Bot {name} crashed. Restarting... ---\n")
                    
                    if restart_count < max_restarts - 1:
                        notify_user(owner_id, f"⚠️ Your bot '<code>{name}</code>' crashed and is restarting... (attempt {restart_count + 2})")
                        time.sleep(5)
                    
                    restart_count += 1
            
            except Exception as e:
                with open(log_path, 'a', encoding='utf-8') as log_file:
                    log_file.write(f"Error starting bot: {str(e)}\n")
                break
        
        if restart_count >= max_restarts:
            notify_user(owner_id, f"🛑 Bot '<code>{name}</code>' stopped after {max_restarts} failed restart attempts")
        
        if name in running_bots:
            del running_bots[name]
            
    except Exception as e:
        print(f"Error in restart_bot for {name}: {e}")
        notify_user(owner_id, f"❌ Failed to start bot '<code>{name}</code>': {str(e)}")

def start_bot(name):
    try:
        if name in running_bots:
            process_info = running_bots[name]
            if process_info['process'].poll() is None:
                return False
        
        bot_path = secure_path(os.path.join('bots', name))
        if not os.path.exists(os.path.join(bot_path, f"{name}.py")):
            return False
        
        owner_id = bot_owners.get(name, OWNER_ID)
        thread = threading.Thread(target=restart_bot, args=(name, owner_id), daemon=True)
        thread.start()
        return True
    except Exception as e:
        print(f"Error starting bot {name}: {e}")
        return False

def stop_bot(name):
    try:
        if name in running_bots:
            process_info = running_bots[name]
            if process_info['process'].poll() is None:
                process_info['process'].terminate()
                
                try:
                    process_info['process'].wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process_info['process'].kill()
                
                del running_bots[name]
                return True
        return False
    except Exception as e:
        print(f"Error stopping bot {name}: {e}")
        return False

def delete_bot(name):
    try:
        stop_bot(name)
        bot_path = secure_path(os.path.join('bots', name))
        
        if os.path.exists(bot_path):
            shutil.rmtree(bot_path)
            
            if name in bot_owners:
                del bot_owners[name]
            if name in bot_configs:
                del bot_configs[name]
            
            save_users(users, bot_owners, bot_configs)
            
            log_path = secure_path(os.path.join('logs', f'{name}.log'))
            if os.path.exists(log_path):
                os.remove(log_path)
            
            return True
        return False
    except Exception as e:
        print(f"Error deleting bot {name}: {e}")
        return False

# File handling with security
def extract_archive(file_path, extract_path):
    try:
        if file_path.endswith('.zip'):
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    if os.path.isabs(member) or ".." in member:
                        raise ValueError("Unsafe path in archive")
                zip_ref.extractall(extract_path)
                return True
        return False
    except Exception as e:
        print(f"Error extracting archive: {e}")
        return False

def save_uploaded_file(file_data, bot_name, filename):
    try:
        bot_path = secure_path(os.path.join('bots', bot_name))
        os.makedirs(bot_path, exist_ok=True)
        
        file_path = os.path.join(bot_path, filename)
        
        if os.path.isabs(filename) or ".." in filename:
            raise ValueError("Unsafe filename")
        
        with open(file_path, 'wb') as f:
            f.write(file_data)
        
        return file_path
    except Exception as e:
        print(f"Error saving file: {e}")
        return None

# Zip bot folder for download
def zip_bot_folder(bot_name):
    try:
        bot_path = secure_path(os.path.join('bots', bot_name))
        if not os.path.exists(bot_path):
            return None
        
        zip_path = os.path.join(TEMP_DIR, f"{bot_name}_{int(time.time())}.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(bot_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, bot_path)
                    zipf.write(file_path, arcname)
        
        return zip_path
    except Exception as e:
        print(f"Error zipping bot folder: {e}")
        return None

# Enhanced keyboard layouts
def get_main_keyboard(user_id):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    keyboard.add(
        KeyboardButton("🚀 Host New Bot"),
        KeyboardButton("📱 My Bots")
    )
    
    keyboard.add(
        KeyboardButton("📊 Bot Stats"),
        KeyboardButton("🔧 Bot Tools")
    )
    
    if user_id == OWNER_ID:
        keyboard.add(
            KeyboardButton("👥 Manage Users"),
            KeyboardButton("🌐 All Bots"),
            KeyboardButton("🎫 Redeem Codes")
        )
    
    keyboard.add(KeyboardButton("ℹ️ Help"))
    return keyboard

def get_bot_controls(name, user_id):
    markup = InlineKeyboardMarkup()
    
    is_running = False
    if name in running_bots:
        process_info = running_bots[name]
        is_running = process_info['process'].poll() is None
    
    if is_running:
        markup.row(
            InlineKeyboardButton("⛔ Stop", callback_data=f"stop:{name}"),
            InlineKeyboardButton("🔄 Restart", callback_data=f"restart:{name}")
        )
    else:
        markup.row(InlineKeyboardButton("▶️ Start", callback_data=f"start:{name}"))
    
    auto_restart = bot_configs.get(name, {}).get('auto_restart', True)
    toggle_text = "🔴 Disable Auto-Restart" if auto_restart else "🟢 Enable Auto-Restart"
    markup.row(InlineKeyboardButton(toggle_text, callback_data=f"toggle_restart:{name}"))
    
    markup.row(
        InlineKeyboardButton("📄 Logs", callback_data=f"logs:{name}"),
        InlineKeyboardButton("📊 Stats", callback_data=f"stats:{name}"),
    )
    
    markup.row(
        InlineKeyboardButton("📁 Files", callback_data=f"files:{name}"),
        InlineKeyboardButton("⚙️ Config", callback_data=f"config:{name}"),
        InlineKeyboardButton("📦 Download", callback_data=f"download_bot:{name}")
    )
    
    if user_id == OWNER_ID or bot_owners.get(name) == user_id:
        markup.row(InlineKeyboardButton("🗑️ Delete", callback_data=f"delete:{name}"))
    
    return markup

def show_bot_info(user_id, name):
    try:
        is_running = False
        uptime_str = ""
        restart_count = 0
        pid = "N/A"
        
        if name in running_bots:
            process_info = running_bots[name]
            is_running = process_info['process'].poll() is None
            if is_running:
                uptime = datetime.now() - process_info['start_time']
                uptime_str = format_timedelta(uptime)
                pid = process_info['process'].pid
            restart_count = process_info.get('restart_count', 0)
        
        owner_id = bot_owners.get(name, OWNER_ID)
        owner_info = users.get(owner_id, {})
        owner_username = owner_info.get('username', f"User {owner_id}")
        
        auto_restart = bot_configs.get(name, {}).get('auto_restart', True)
        
        msg = f"🤖 <b>{name}</b>\n\n"
        msg += f"🟢 <b>Status:</b> {'Running' if is_running else 'Stopped'}\n"
        
        if is_running:
            msg += f"⏱️ <b>Uptime:</b> {uptime_str}\n"
            msg += f"🆔 <b>PID:</b> <code>{pid}</code>\n"
        
        msg += f"🔄 <b>Restarts:</b> {restart_count}\n"
        msg += f"🔄 <b>Auto-Restart:</b> {'Enabled' if auto_restart else 'Disabled'}\n"
        msg += f"👤 <b>Owner:</b> {owner_username}\n"
        msg += f"🕒 <b>Last Updated:</b> {datetime.now().strftime('%I:%M %p')}"
        
        markup = get_bot_controls(name, user_id)
        
        bot.send_message(user_id, msg, parse_mode="HTML", reply_markup=markup)
    except Exception as e:
        bot.send_message(user_id, f"❌ Error displaying bot info: {str(e)}")

# Message handlers
@bot.message_handler(commands=['start'])
def start_handler(message):
    user_info = users.get(message.chat.id)
    if not user_info:
        return bot.reply_to(message, "❌ Access denied. Contact the owner for access.")
    
    expiry = user_info.get('expiry')
    if expiry and datetime.strptime(expiry, "%Y-%m-%d") < datetime.now():
        del users[message.chat.id]
        save_users(users, bot_owners, bot_configs)
        return bot.reply_to(message, "❌ Your access has expired.")
    
    user_bots = [name for name, owner in bot_owners.items() if owner == message.chat.id]
    running_count = sum(1 for name in user_bots if name in running_bots and running_bots[name]['process'].poll() is None)
    
    username = user_info.get('username', '')
    welcome_msg = f"🎉 <b>Welcome to Secure Bot Hoster, {username}!</b>\n\n"
    
    if message.chat.id == OWNER_ID:
        welcome_msg += "👑 You are the <b>Owner</b>\n"
        total_bots = len(os.listdir(BOTS_DIR)) if os.path.exists(BOTS_DIR) else 0
        welcome_msg += f"🌐 Total System Bots: <b>{total_bots}</b>\n"
    else:
        welcome_msg += "👤 You are an <b>Authorized User</b>\n"
        if expiry:
            welcome_msg += f"⏳ Access Expires: <b>{expiry}</b>\n"
    
    welcome_msg += f"🤖 Your Bots: <b>{len(user_bots)}</b> ({running_count} running)\n"
    welcome_msg += f"📁 Secure Environment: <code>{HOSTED_DIR}</code>"
    
    bot.send_message(message.chat.id, welcome_msg, 
                    parse_mode="HTML", reply_markup=get_main_keyboard(message.chat.id))

# Redeem code handler with enhanced features
@bot.message_handler(commands=['redeem'])
def redeem_handler(message):
    if len(message.text.split()) < 2:
        return bot.reply_to(message, "❌ Usage: /redeem <code>")
    
    code = message.text.split()[1].upper()
    code_info = redeem_codes.get(code)
    
    if not code_info:
        return bot.reply_to(message, "❌ Invalid redeem code")
    
    expiry_date = datetime.fromisoformat(code_info['expiry_date'])
    if datetime.now() > expiry_date:
        return bot.reply_to(message, "❌ Redeem code has expired")
    
    if code_info['redeemed_count'] >= code_info['usage_limit']:
        return bot.reply_to(message, "❌ Redeem code has been fully redeemed")
    
    if message.chat.id in code_info['redeemed_by']:
        return bot.reply_to(message, "❌ You have already redeemed this code")
    
    duration_days = code_info['duration']
    user_expiry = datetime.now() + timedelta(days=duration_days)
    expiry_str = user_expiry.strftime("%Y-%m-%d")
    
    username = f"@{message.from_user.username}" if message.from_user.username else f"User {message.chat.id}"
    users[message.chat.id] = {
        'expiry': expiry_str,
        'username': username
    }
    
    code_info['redeemed_count'] += 1
    code_info['redeemed_by'].append(message.chat.id)
    redeem_codes[code] = code_info
    save_redeem_codes(redeem_codes)
    save_users(users, bot_owners, bot_configs)
    
    bot.reply_to(message, 
                f"✅ Redeem successful! Access granted until {expiry_str}\n\n"
                f"🔑 Code: <code>{code}</code>\n"
                f"⏳ Duration: {duration_days} days\n"
                f"📊 Uses: {code_info['redeemed_count']}/{code_info['usage_limit']}",
                parse_mode="HTML")

# Handle all text messages
@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_all_messages(message):
    user_info = users.get(message.chat.id)
    if not user_info:
        return
    
    # Check if access has expired
    expiry = user_info.get('expiry')
    if expiry and datetime.strptime(expiry, "%Y-%m-%d") < datetime.now():
        del users[message.chat.id]
        save_users(users, bot_owners, bot_configs)
        return bot.reply_to(message, "❌ Your access has expired.")

    user_id = message.chat.id
    text = message.text

    if text == "🚀 Host New Bot":
        bot_upload_states[user_id] = {'step': 'waiting_bot_file'}
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📤 Upload Single File", callback_data="upload_single"))
        markup.add(InlineKeyboardButton("📦 Upload Archive", callback_data="upload_archive"))
        
        bot.send_message(user_id, 
            "📤 <b>Upload Your Bot</b>\n\n"
            "Choose upload method:\n"
            "• <b>Single File:</b> Upload main .py file\n"
            "• <b>Archive:</b> Upload .zip with multiple files\n\n"
            "📝 The filename will be used as the bot name.",
            parse_mode="HTML", reply_markup=markup)

    elif text == "📱 My Bots":
        user_bots = [name for name, owner in bot_owners.items() if owner == user_id]
        if not user_bots:
            return bot.send_message(user_id, "🤖 You haven't hosted any bots yet.\n"
                                           "Use '🚀 Host New Bot' to get started!")
        
        bot.send_message(user_id, f"🤖 <b>Your Bots ({len(user_bots)})</b>", parse_mode="HTML")
        for name in user_bots:
            show_bot_info(user_id, name)

    elif text == "📊 Bot Stats":
        user_bots = [name for name, owner in bot_owners.items() if owner == user_id]
        if not user_bots:
            return bot.send_message(user_id, "🤖 No bots found.")
        
        stats_text = f"📊 <b>Your Bot Statistics</b>\n\n"
        for name in user_bots:
            is_running = name in running_bots and running_bots[name]['process'].poll() is None
            status = "🟢 Running" if is_running else "🔴 Stopped"
            
            if is_running:
                start_time = running_bots[name]['start_time']
                uptime = datetime.now() - start_time
                stats_text += f"🤖 <b>{name}</b>: {status}\n"
                stats_text += f"   ⏱️ Uptime: {str(uptime).split('.')[0]}\n\n"
            else:
                stats_text += f"🤖 <b>{name}</b>: {status}\n\n"
        
        bot.send_message(user_id, stats_text, parse_mode="HTML")

    elif text == "🔧 Bot Tools":
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🔄 Restart All", callback_data="restart_all"),
            InlineKeyboardButton("⛔ Stop All", callback_data="stop_all")
        )
        markup.add(
            InlineKeyboardButton("🧹 Clean Logs", callback_data="clean_logs"),
            InlineKeyboardButton("📋 Export Config", callback_data="export_config")
        )
        
        bot.send_message(user_id, "🔧 <b>Bot Management Tools</b>", 
                        parse_mode="HTML", reply_markup=markup)

    elif text == "🌐 All Bots" and user_id == OWNER_ID:
        bots_list = []
        if os.path.exists(BOTS_DIR):
            bots_list = [d for d in os.listdir(BOTS_DIR) if os.path.isdir(os.path.join(BOTS_DIR, d))]
        
        if not bots_list:
            return bot.send_message(user_id, "🤖 No bots found in the system.")
        
        bot.send_message(user_id, f"🌐 <b>All System Bots ({len(bots_list)})</b>", parse_mode="HTML")
        for name in bots_list:
            show_bot_info(user_id, name)

    elif text == "👥 Manage Users" and user_id == OWNER_ID:
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("➕ Add User", callback_data="add_user"),
            InlineKeyboardButton("➖ Remove User", callback_data="remove_user")
        )
        markup.add(InlineKeyboardButton("📋 List Users", callback_data="list_users"))
        
        bot.send_message(user_id, 
            f"👥 <b>User Management</b>\n\n"
            f"👑 Owner: <code>{OWNER_ID}</code>\n"
            f"👤 Total Users: <b>{len(users)}</b>",
            parse_mode="HTML", reply_markup=markup)
    
    elif text == "🎫 Redeem Codes" and user_id == OWNER_ID:
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("Generate 7-day", callback_data="generate_code:7"),
            InlineKeyboardButton("Generate 30-day", callback_data="generate_code:30"),
            InlineKeyboardButton("Generate 90-day", callback_data="generate_code:90")
        )
        markup.add(
            InlineKeyboardButton("Generate Custom", callback_data="generate_custom_code"),
            InlineKeyboardButton("List Codes", callback_data="list_codes")
        )
        
        bot.send_message(user_id, 
            "🎫 <b>Redeem Code Management</b>\n\n"
            "Generate new redeem codes or list existing ones",
            parse_mode="HTML", reply_markup=markup)

    elif text == "ℹ️ Help":
        help_text = (
            "🤖 <b>Secure Bot Hoster Help</b>\n\n"
            "🚀 <b>Host New Bot:</b> Upload Python bot files\n"
            "📱 <b>My Bots:</b> View and manage your bots\n"
            "📊 <b>Bot Stats:</b> View bot statistics and uptime\n"
            "🔧 <b>Bot Tools:</b> Bulk management tools\n\n"
            "📋 <b>Supported Files:</b>\n"
            "• <code>.py</code> - Python bot files\n"
            "• <code>requirements.txt</code> - Dependencies\n"
            "• <code>.env</code> - Environment variables\n"
            "• <code>.zip</code> - Archive with multiple files\n\n"
            "🔒 <b>Security Features:</b>\n"
            "• All operations contained in hosted folder\n"
            "• Virtual environments for each bot\n"
            "• Path traversal protection\n"
            "• Automatic crash recovery\n\n"
            "✨ Your bots auto-restart on crashes!"
        )
        
        if user_id == OWNER_ID:
            help_text += "\n\n👑 <b>Owner Features:</b>\n• Manage all system bots\n• Add/remove users\n• System-wide controls"
        
        bot.send_message(user_id, help_text, parse_mode="HTML")

def handle_bot_upload(message):
    user_id = message.chat.id
    
    if not message.document:
        return bot.send_message(user_id, "❌ Please upload a valid file.")

    state = bot_upload_states.get(user_id, {})
    upload_type = state.get('upload_type', 'single')

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        filename = message.document.file_name

        if upload_type == 'single':
            if not filename.endswith('.py'):
                return bot.send_message(user_id, "❌ Please upload a Python (.py) file.")
            
            bot_name = filename.rsplit('.', 1)[0]
            file_path = save_uploaded_file(downloaded, bot_name, filename)
            
            if not file_path:
                return bot.send_message(user_id, "❌ Failed to save file.")

        elif upload_type == 'archive':
            if not filename.endswith('.zip'):
                return bot.send_message(user_id, "❌ Please upload a ZIP archive.")
            
            bot_name = filename.rsplit('.', 1)[0]
            
            temp_path = os.path.join(TEMP_DIR, filename)
            with open(temp_path, 'wb') as f:
                f.write(downloaded)
            
            bot_path = secure_path(os.path.join('bots', bot_name))
            if not extract_archive(temp_path, bot_path):
                return bot.send_message(user_id, "❌ Failed to extract archive.")
            
            os.remove(temp_path)
            
            py_files = []
            for root, dirs, files in os.walk(bot_path):
                for file in files:
                    if file.endswith('.py'):
                        py_files.append(file)
            
            if not py_files:
                shutil.rmtree(bot_path)
                return bot.send_message(user_id, "❌ No Python files found in archive.")
            
            main_file = f"{bot_name}.py"
            if main_file not in py_files:
                if 'main.py' in py_files:
                    os.rename(os.path.join(bot_path, 'main.py'), 
                             os.path.join(bot_path, main_file))
                elif len(py_files) == 1:
                    os.rename(os.path.join(bot_path, py_files[0]), 
                             os.path.join(bot_path, main_file))
                else:
                    return bot.send_message(user_id, 
                        f"❌ Multiple Python files found. Please ensure main file is named '{main_file}'")

        bot_owners[bot_name] = user_id
        save_users(users, bot_owners, bot_configs)

        bot_upload_states[user_id] = {'step': 'bot_uploaded', 'bot_name': bot_name}

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("📄 Add requirements.txt", callback_data=f"upload_req:{bot_name}"),
            InlineKeyboardButton("🔧 Add .env", callback_data=f"upload_env:{bot_name}")
        )
        markup.add(InlineKeyboardButton("🚀 Start Bot Now", callback_data=f"start_uploaded:{bot_name}"))

        bot.send_message(user_id, 
            f"✅ <b>Bot '{bot_name}' uploaded successfully!</b>\n\n"
            f"📁 Location: <code>{os.path.join(BOTS_DIR, bot_name)}</code>\n"
            f"🔧 You can now add additional files or start the bot:",
            parse_mode="HTML", reply_markup=markup)

    except Exception as e:
        bot.send_message(user_id, f"❌ Upload failed: {str(e)}")

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    user_id = call.message.chat.id
    user_info = users.get(user_id)
    if not user_info:
        return bot.answer_callback_query(call.id, "Access denied.")
    
    try:
        data_parts = call.data.split(":")
        cmd = data_parts[0]
        
        if cmd == "upload_single":
            bot_upload_states[user_id] = {'step': 'waiting_bot_file', 'upload_type': 'single'}
            msg = bot.send_message(user_id, "📤 Send your Python bot file (.py)")
            bot.register_next_step_handler(msg, handle_bot_upload)
            return bot.answer_callback_query(call.id)
            
        elif cmd == "upload_archive":
            bot_upload_states[user_id] = {'step': 'waiting_bot_file', 'upload_type': 'archive'}
            msg = bot.send_message(user_id, "📦 Send your bot archive (.zip)")
            bot.register_next_step_handler(msg, handle_bot_upload)
            return bot.answer_callback_query(call.id)

        if cmd in ["start", "stop", "restart", "delete", "logs", "stats", "files", "config", "download_bot", "toggle_restart"]:
            name = data_parts[1]
            
            if cmd == "delete" and user_id != OWNER_ID and bot_owners.get(name) != user_id:
                return bot.answer_callback_query(call.id, "❌ You can only delete your own bots!")
            
            if cmd == "start":
                if start_bot(name):
                    bot.edit_message_text(f"✅ Started bot '<code>{name}</code>'", 
                                        call.message.chat.id, call.message.message_id, 
                                        parse_mode="HTML")
                    return bot.answer_callback_query(call.id)
                else:
                    return bot.answer_callback_query(call.id, "⚠️ Bot is already running or failed to start")

            elif cmd == "stop":
                if stop_bot(name):
                    bot.edit_message_text(f"🛑 Stopped bot '<code>{name}</code>'", 
                                        call.message.chat.id, call.message.message_id, 
                                        parse_mode="HTML")
                    return bot.answer_callback_query(call.id)
                else:
                    return bot.answer_callback_query(call.id, "⚠️ Bot is not running")

            elif cmd == "restart":
                stop_bot(name)
                time.sleep(2)
                if start_bot(name):
                    bot.edit_message_text(f"🔄 Restarted bot '<code>{name}</code>'", 
                                        call.message.chat.id, call.message.message_id, 
                                        parse_mode="HTML")
                return bot.answer_callback_query(call.id)

            elif cmd == "delete":
                markup = InlineKeyboardMarkup()
                markup.add(
                    InlineKeyboardButton("✅ Yes, Delete", callback_data=f"confirm_delete:{name}"),
                    InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_delete:{name}")
                )
                bot.edit_message_text(
                    f"🗑️ <b>Confirm Deletion</b>\n\n"
                    f"Are you sure you want to delete bot '<code>{name}</code>'?\n"
                    f"This action cannot be undone!",
                    call.message.chat.id, call.message.message_id,
                    parse_mode="HTML", reply_markup=markup)
                return bot.answer_callback_query(call.id)

            elif cmd == "logs":
                log_path = secure_path(os.path.join('logs', f"{name}.log"))
                if os.path.exists(log_path):
                    try:
                        with open(log_path, 'r', encoding='utf-8') as f:
                            logs = f.read()
                        
                        if not logs.strip():
                            return bot.answer_callback_query(call.id, "📄 Log file is empty")
                        
                        if len(logs) > 4000:
                            logs = "...\n" + logs[-4000:]
                        
                        bot.send_message(call.message.chat.id, 
                                       f"📄 <b>Logs for '{name}':</b>\n\n<pre>{logs}</pre>", 
                                       parse_mode="HTML", 
                                       reply_to_message_id=call.message.message_id)
                        return bot.answer_callback_query(call.id)
                    except Exception as e:
                        bot.send_message(call.message.chat.id, f"❌ Error reading logs: {str(e)}")
                        return bot.answer_callback_query(call.id)
                else:
                    return bot.answer_callback_query(call.id, "📄 No logs found")

            elif cmd == "stats":
                bot_path = secure_path(os.path.join('bots', name))
                
                stats_text = f"📊 <b>Statistics for '{name}'</b>\n\n"
                
                is_running = name in running_bots and running_bots[name]['process'].poll() is None
                status = "🟢 Running" if is_running else "🔴 Stopped"
                stats_text += f"📊 Status: {status}\n"
                
                if is_running:
                    process_info = running_bots[name]
                    uptime = datetime.now() - process_info['start_time']
                    stats_text += f"⏱️ Uptime: {format_timedelta(uptime)}\n"
                    stats_text += f"🔄 Restart Count: {process_info.get('restart_count', 0)}\n"
                    stats_text += f"🆔 Process ID: {process_info['process'].pid}\n"
                
                if os.path.exists(bot_path):
                    files = []
                    total_size = 0
                    for root, dirs, filenames in os.walk(bot_path):
                        for filename in filenames:
                            if not filename.startswith('.') and filename != '__pycache__':
                                filepath = os.path.join(root, filename)
                                size = os.path.getsize(filepath)
                                total_size += size
                                files.append(filename)
                    
                    stats_text += f"📁 Files: {len(files)}\n"
                    stats_text += f"💾 Total Size: {total_size/1024:.2f} KB\n"
                
                log_path = secure_path(os.path.join('logs', f"{name}.log"))
                if os.path.exists(log_path):
                    log_size = os.path.getsize(log_path)
                    stats_text += f"📄 Log Size: {log_size/1024:.2f} KB\n"
                
                config = bot_configs.get(name, {})
                if config:
                    stats_text += f"⚙️ Config Variables: {len(config)}\n"
                
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("🔙 Back", callback_data=f"back_to_bot:{name}"))
                
                bot.edit_message_text(stats_text, call.message.chat.id, call.message.message_id, 
                                    parse_mode="HTML", reply_markup=markup)
                return bot.answer_callback_query(call.id)

            elif cmd == "files":
                bot_path = secure_path(os.path.join('bots', name))
                
                if not os.path.exists(bot_path):
                    error_msg = f"❌ Bot directory not found for '{name}'"
                    bot.edit_message_text(error_msg, call.message.chat.id, call.message.message_id)
                    return bot.answer_callback_query(call.id)
                
                files_text = f"📁 <b>Files for '{name}'</b>\n\n"
                
                files = []
                for root, dirs, filenames in os.walk(bot_path):
                    for filename in filenames:
                        if not filename.startswith('.') and filename not in ['__pycache__']:
                            rel_path = os.path.relpath(os.path.join(root, filename), bot_path)
                            size = os.path.getsize(os.path.join(root, filename))
                            files.append((rel_path, size))
                
                if not files:
                    files_text += "📂 No files found"
                else:
                    for filepath, size in sorted(files):
                        files_text += f"📄 <code>{filepath}</code> ({size/1024:.2f} KB)\n"
                
                markup = InlineKeyboardMarkup()
                markup.add(
                    InlineKeyboardButton("📤 Add File", callback_data=f"add_file:{name}"),
                    InlineKeyboardButton("🗑️ Delete File", callback_data=f"delete_file:{name}")
                )
                markup.add(InlineKeyboardButton("🔙 Back", callback_data=f"back_to_bot:{name}"))
                
                bot.edit_message_text(files_text, call.message.chat.id, call.message.message_id, 
                                    parse_mode="HTML", reply_markup=markup)
                return bot.answer_callback_query(call.id)

            elif cmd == "config":
                config = bot_configs.get(name, {})
                
                config_text = f"⚙️ <b>Configuration for '{name}'</b>\n\n"
                
                if not config:
                    config_text += "📝 No configuration variables set"
                else:
                    for key, value in config.items():
                        if any(secret in key.lower() for secret in ['token', 'key', 'secret', 'password']):
                            display_value = '*' * len(str(value))
                        else:
                            display_value = str(value)
                        config_text += f"🔧 <code>{key}</code> = <code>{display_value}</code>\n"
                
                markup = InlineKeyboardMarkup()
                markup.add(
                    InlineKeyboardButton("➕ Add Variable", callback_data=f"add_config:{name}"),
                    InlineKeyboardButton("🗑️ Remove Variable", callback_data=f"remove_config:{name}")
                )
                markup.add(InlineKeyboardButton("🔙 Back", callback_data=f"back_to_bot:{name}"))
                
                bot.edit_message_text(config_text, call.message.chat.id, call.message.message_id, 
                                    parse_mode="HTML", reply_markup=markup)
                return bot.answer_callback_query(call.id)
            
            elif cmd == "download_bot":
                name = data_parts[1]
                zip_path = zip_bot_folder(name)
                if zip_path:
                    with open(zip_path, 'rb') as f:
                        bot.send_document(user_id, f, caption=f"📦 Bot '{name}' files")
                    os.remove(zip_path)
                    return bot.answer_callback_query(call.id, "✅ Bot files downloaded")
                else:
                    return bot.answer_callback_query(call.id, "❌ Failed to create zip")
            
            elif cmd == "toggle_restart":
                name = data_parts[1]
                if name not in bot_configs:
                    bot_configs[name] = {}
                    
                current = bot_configs[name].get('auto_restart', True)
                bot_configs[name]['auto_restart'] = not current
                save_users(users, bot_owners, bot_configs)
                show_bot_info(user_id, name)
                return bot.answer_callback_query(call.id, f"🔄 Auto-restart {'enabled' if not current else 'disabled'}")

        elif cmd == "confirm_delete":
            name = data_parts[1]
            if delete_bot(name):
                bot.edit_message_text(f"🗑️ Bot '<code>{name}</code>' deleted successfully", 
                                    call.message.chat.id, call.message.message_id, 
                                    parse_mode="HTML")
            else:
                bot.edit_message_text(f"❌ Failed to delete bot '<code>{name}</code>'", 
                                    call.message.chat.id, call.message.message_id, 
                                    parse_mode="HTML")
            return bot.answer_callback_query(call.id)

        elif cmd == "cancel_delete":
            name = data_parts[1]
            show_bot_info(call.message.chat.id, name)
            bot.delete_message(call.message.chat.id, call.message.message_id)
            return bot.answer_callback_query(call.id)

        elif cmd == "start_uploaded":
            name = data_parts[1]
            if start_bot(name):
                bot.edit_message_text(f"🚀 <b>Bot '{name}' is now running!</b>\n\n"
                                    f"Use '📱 My Bots' to manage it.", 
                                    call.message.chat.id, call.message.message_id, 
                                    parse_mode="HTML")
            return bot.answer_callback_query(call.id)

        elif cmd in ["upload_req", "upload_env"]:
            name = data_parts[1]
            file_type = "requirements.txt" if cmd == "upload_req" else ".env"
            bot_upload_states[user_id] = {'step': f'waiting_{cmd}', 'bot_name': name}
            
            msg = bot.send_message(user_id, f"📤 Upload your <code>{file_type}</code> file for bot '{name}'", 
                                 parse_mode="HTML")
            bot.register_next_step_handler(msg, handle_additional_file)
            return bot.answer_callback_query(call.id)

        elif cmd == "restart_all":
            user_bots = [name for name, owner in bot_owners.items() if owner == user_id]
            restarted = 0
            for bot_name in user_bots:
                if stop_bot(bot_name):
                    time.sleep(1)
                    if start_bot(bot_name):
                        restarted += 1
            return bot.answer_callback_query(call.id, f"🔄 Restarted {restarted} bots")

        elif cmd == "stop_all":
            user_bots = [name for name, owner in bot_owners.items() if owner == user_id]
            stopped = 0
            for bot_name in user_bots:
                if stop_bot(bot_name):
                    stopped += 1
            return bot.answer_callback_query(call.id, f"⛔ Stopped {stopped} bots")

        elif cmd == "clean_logs":
            try:
                user_bots = [name for name, owner in bot_owners.items() if owner == user_id]
                cleaned = 0
                for bot_name in user_bots:
                    log_path = secure_path(os.path.join('logs', f"{bot_name}.log"))
                    if os.path.exists(log_path):
                        with open(log_path, 'w') as f:
                            f.write(f"--- Log cleaned at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                        cleaned += 1
                return bot.answer_callback_query(call.id, f"🧹 Cleaned {cleaned} log files")
            except Exception as e:
                return bot.answer_callback_query(call.id, f"❌ Error cleaning logs: {str(e)}")

        elif cmd == "export_config":
            try:
                user_bots = [name for name, owner in bot_owners.items() if owner == user_id]
                config_data = {
                    'user_id': user_id,
                    'bots': user_bots,
                    'configs': {name: bot_configs.get(name, {}) for name in user_bots},
                    'timestamp': datetime.now().isoformat()
                }
                
                config_json = json.dumps(config_data, indent=2)
                temp_file = os.path.join(TEMP_DIR, f"config_{user_id}_{int(time.time())}.json")
                
                with open(temp_file, 'w') as f:
                    f.write(config_json)
                
                with open(temp_file, 'rb') as f:
                    bot.send_document(call.message.chat.id, f, 
                                    caption="📋 Your bot configuration export")
                
                os.remove(temp_file)
                return bot.answer_callback_query(call.id, "✅ Config exported")
            except Exception as e:
                return bot.answer_callback_query(call.id, f"❌ Export failed: {str(e)}")

        elif cmd == "add_user" and user_id == OWNER_ID:
            msg = bot.send_message(user_id, "👤 Send the user ID to add:")
            bot.register_next_step_handler(msg, handle_add_user)
            return bot.answer_callback_query(call.id)

        elif cmd == "remove_user" and user_id == OWNER_ID:
            msg = bot.send_message(user_id, "👤 Send the user ID to remove:")
            bot.register_next_step_handler(msg, handle_remove_user)
            return bot.answer_callback_query(call.id)

        elif cmd == "list_users" and user_id == OWNER_ID:
            user_list = []
            for uid, info in users.items():
                username = info.get('username', f"User {uid}")
                expiry = info.get('expiry', 'Permanent')
                user_list.append(f"• {username} (<code>{uid}</code>) - Expires: {expiry}")
            
            user_list_text = "\n".join(user_list)
            bot.send_message(user_id, f"👥 <b>Authorized Users:</b>\n\n{user_list_text}", parse_mode="HTML")
            return bot.answer_callback_query(call.id)
        
        elif cmd == "generate_code" and user_id == OWNER_ID:
            duration = int(data_parts[1])
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            expiry_date = datetime.now() + timedelta(days=30)
            redeem_codes[code] = {
                'duration': duration,
                'usage_limit': 1,
                'redeemed_count': 0,
                'redeemed_by': [],
                'created_by': user_id,
                'created_at': datetime.now().isoformat(),
                'expiry_date': expiry_date.isoformat()
            }
            save_redeem_codes(redeem_codes)
            bot.send_message(user_id, 
                f"🎫 <b>Redeem Code Generated</b>\n\n"
                f"🔑 Code: <code>{code}</code>\n"
                f"⏳ Duration: {duration} days\n"
                f"📊 Usage Limit: 1 user\n"
                f"📅 Expires: {expiry_date.strftime('%Y-%m-%d')}\n\n"
                "Users can redeem with:\n"
                f"<code>/redeem {code}</code>",
                parse_mode="HTML")
            return bot.answer_callback_query(call.id)
        
        elif cmd == "generate_custom_code" and user_id == OWNER_ID:
            msg = bot.send_message(user_id, "⌛ Enter duration in days:")
            bot.register_next_step_handler(msg, handle_custom_duration)
            return bot.answer_callback_query(call.id)
        
        elif cmd == "list_codes" and user_id == OWNER_ID:
            codes_list = []
            for code, info in redeem_codes.items():
                status = "🟢 Available" if len(info['redeemed_by']) < info['usage_limit'] else "🔴 Fully redeemed"
                expiry_date = datetime.fromisoformat(info['expiry_date'])
                expiry_str = expiry_date.strftime('%Y-%m-%d')
                codes_list.append(
                    f"• <code>{code}</code> - {info['duration']} days\n"
                    f"  📊 Uses: {len(info['redeemed_by'])}/{info['usage_limit']}\n"
                    f"  📅 Expires: {expiry_str}\n"
                    f"  {status}"
                )
            
            codes_text = "\n\n".join(codes_list) if codes_list else "No redeem codes found"
            bot.send_message(user_id, f"🎫 <b>Redeem Codes:</b>\n\n{codes_text}", parse_mode="HTML")
            return bot.answer_callback_query(call.id)
        
        elif cmd == "back_to_bot":
            name = data_parts[1]
            show_bot_info(call.message.chat.id, name)
            return bot.answer_callback_query(call.id)

    except Exception as e:
        print(f"Error in callback query: {e}")
        traceback.print_exc()
        return bot.answer_callback_query(call.id, f"❌ Error: {str(e)}")

def handle_additional_file(message):
    user_id = message.chat.id
    state = bot_upload_states.get(user_id, {})
    
    if not message.document:
        return bot.send_message(user_id, "❌ Please upload a valid file.")

    try:
        bot_name = state.get('bot_name')
        step = state.get('step')
        
        if not bot_name:
            return bot.send_message(user_id, "❌ Session expired. Please start over.")
        
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        if step == 'waiting_upload_req':
            filename = 'requirements.txt'
        elif step == 'waiting_upload_env':
            filename = '.env'
        else:
            filename = message.document.file_name
        
        file_path = save_uploaded_file(downloaded, bot_name, filename)
        
        if file_path:
            bot.send_message(user_id, f"✅ File '<code>{filename}</code>' uploaded for bot '{bot_name}'!", 
                           parse_mode="HTML")
        else:
            bot.send_message(user_id, f"❌ Failed to upload file '{filename}'")
            
    except Exception as e:
        bot.send_message(user_id, f"❌ Upload error: {str(e)}")

def handle_add_user(message):
    try:
        new_user_id = int(message.text.strip())
        if new_user_id not in users:
            username = f"@{message.from_user.username}" if message.from_user.username else f"User {new_user_id}"
            users[new_user_id] = {
                'expiry': None,
                'username': username
            }
            save_users(users, bot_owners, bot_configs)
            bot.send_message(message.chat.id, 
                           f"✅ User <code>{new_user_id}</code> added successfully!", 
                           parse_mode="HTML")
            notify_user(new_user_id, f"🎉 You have been granted access to the Bot Hoster!\nUse /start to begin.")
        else:
            bot.send_message(message.chat.id, 
                           f"⚠️ User <code>{new_user_id}</code> is already authorized!", 
                           parse_mode="HTML")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Please send a valid user ID (numbers only).")

def handle_remove_user(message):
    try:
        remove_user_id = int(message.text.strip())
        if remove_user_id == OWNER_ID:
            return bot.send_message(message.chat.id, "❌ Cannot remove the owner!")
        
        if remove_user_id in users:
            del users[remove_user_id]
            save_users(users, bot_owners, bot_configs)
            bot.send_message(message.chat.id, 
                           f"✅ User <code>{remove_user_id}</code> removed successfully!", 
                           parse_mode="HTML")
            notify_user(remove_user_id, f"❌ Your access to the Bot Hoster has been revoked.")
        else:
            bot.send_message(message.chat.id, 
                           f"⚠️ User <code>{remove_user_id}</code> is not in the system!", 
                           parse_mode="HTML")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Please send a valid user ID (numbers only).")

# Custom redeem code generation
def handle_custom_duration(message):
    try:
        duration = int(message.text.strip())
        if duration <= 0:
            return bot.send_message(message.chat.id, "❌ Duration must be positive number")
        
        bot_upload_states[message.chat.id] = {
            'step': 'waiting_custom_limit',
            'duration': duration
        }
        bot.send_message(message.chat.id, "👥 Enter usage limit (number of users who can redeem):")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Please enter a valid number")

def handle_custom_limit(message):
    try:
        usage_limit = int(message.text.strip())
        if usage_limit <= 0:
            return bot.send_message(message.chat.id, "❌ Usage limit must be positive number")
        
        state = bot_upload_states.get(message.chat.id, {})
        duration = state.get('duration')
        
        if not duration:
            return bot.send_message(message.chat.id, "❌ Session expired. Start over.")
        
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        expiry_date = datetime.now() + timedelta(days=30)
        
        redeem_codes[code] = {
            'duration': duration,
            'usage_limit': usage_limit,
            'redeemed_count': 0,
            'redeemed_by': [],
            'created_by': message.chat.id,
            'created_at': datetime.now().isoformat(),
            'expiry_date': expiry_date.isoformat()
        }
        save_redeem_codes(redeem_codes)
        
        bot.send_message(message.chat.id, 
            f"🎫 <b>Custom Redeem Code Generated</b>\n\n"
            f"🔑 Code: <code>{code}</code>\n"
            f"⏳ Duration: {duration} days\n"
            f"👥 Usage Limit: {usage_limit} users\n"
            f"📅 Code Expires: {expiry_date.strftime('%Y-%m-%d')}\n\n"
            "Users can redeem with:\n"
            f"<code>/redeem {code}</code>",
            parse_mode="HTML")
        
        del bot_upload_states[message.chat.id]
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Please enter a valid number")

# Grant access by forwarded message
@bot.message_handler(func=lambda m: m.forward_from and users.get(m.chat.id) and m.chat.id == OWNER_ID)
def handle_forwarded_user(message):
    try:
        user = message.forward_from
        username = f"@{user.username}" if user.username else f"User {user.id}"
        
        if user.id in users:
            return bot.reply_to(message, f"ℹ️ {username} already has access")
        
        expiry_date = datetime.now() + timedelta(days=30)
        expiry_str = expiry_date.strftime("%Y-%m-%d")
        users[user.id] = {
            'expiry': expiry_str,
            'username': username
        }
        save_users(users, bot_owners, bot_configs)
        
        try:
            bot.send_message(user.id, 
                f"🎉 You've been granted access to the Bot Hoster!\n"
                f"⏳ Your access expires on {expiry_str}\n\n"
                "Use /start to begin")
        except:
            pass
        
        bot.reply_to(message, f"✅ Access granted to {username} until {expiry_str}")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# Auto-start existing bots on startup
def auto_start_bots():
    try:
        if os.path.exists(BOTS_DIR):
            for bot_name in os.listdir(BOTS_DIR):
                bot_path = os.path.join(BOTS_DIR, bot_name)
                if os.path.isdir(bot_path):
                    main_file = os.path.join(bot_path, f"{bot_name}.py")
                    if os.path.exists(main_file):
                        threading.Thread(target=start_bot, args=(bot_name,)).start()
    except Exception as e:
        print(f"Error in auto-start: {e}")

# System cleanup on shutdown
def cleanup_system():
    try:
        print("🧹 Cleaning up system...")
        
        for name in list(running_bots.keys()):
            stop_bot(name)
        
        if os.path.exists(TEMP_DIR):
            for file in os.listdir(TEMP_DIR):
                if not file.startswith('.'):
                    try:
                        file_path = os.path.join(TEMP_DIR, file)
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                    except:
                        pass
        
        print("✅ Cleanup completed")
    except Exception as e:
        print(f"Error during cleanup: {e}")

# Initialize and start system
if __name__ == "__main__":
    try:
        print("🤖 Secure Bot Hoster Starting...")
        print(f"📁 Hosted Directory: {os.path.abspath(HOSTED_DIR)}")
        print(f"👑 Owner ID: {OWNER_ID}")
        print(f"👥 Authorized Users: {len(users)}")
        
        import atexit
        atexit.register(cleanup_system)
        
        auto_start_bots()
        
        print("✅ Secure Bot Hoster is running! Press Ctrl+C to stop")
        print("🔒 All operations are contained within the hosted directory")
        
        while True:
            try:
                bot.infinity_polling(timeout=60, long_polling_timeout=60)
            except Exception as e:
                print(f"⚠️ Polling error: {e}")
                traceback.print_exc()
                time.sleep(10)
        
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        cleanup_system()
    except Exception as e:
        print(f"❌ Critical error: {e}")
        traceback.print_exc()
        cleanup_system()
