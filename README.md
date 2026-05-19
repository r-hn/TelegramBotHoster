# Secure Bot Hoster

A Telegram-based Python bot hosting manager with:
- Multi-user access system
- Auto-restart for hosted bots
- Secure file handling
- ZIP upload support
- Redeem code system
- Logs, configs, and bot management
- Virtual environment support

Created by Rehan  
Website: https://skrehan.in

## Features

- Upload `.py` files or `.zip` archives
- Start / stop / restart hosted bots
- Automatic crash recovery
- Per-bot virtual environments
- Secure path validation
- Logs and statistics viewer
- Redeem code access system
- Admin controls for user management

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/r-hn/TelegramBotHoster.git
cd secure-bot-hoster
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Rename `.env.example` to `.env`

```bash
cp .env.example .env
```

Edit `.env`:

```env
API_TOKEN=your_telegram_bot_token_here
OWNER_ID=your_telegram_user_id
```

## Run the bot

```bash
python HostingBotByRehan.py
```

## Supported Uploads

- `.py`
- `.zip`
- `requirements.txt`
- `.env`

## Security

- Path traversal protection
- Isolated hosted directory
- Safe archive extraction
- Process monitoring
- Auto cleanup system

## Credits

Developed by Rehan  
https://skrehan.in
