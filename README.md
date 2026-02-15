# ChronoGather Bot

Telegram bot for group scheduling — find common time slots for RPG sessions, meetings, or any group activity. Like Doodle, but inside Telegram.

> 🎲 Made for tabletop RPG groups (Mothership, D&D, etc.), but works for any event requiring 2+ people coordination.

## Features

- ✅ Create events with duration (`/newevent "Mothership S3" 4h`)
- ✅ Participants mark availability via private calendar UI (no spam in group)
- ✅ Automatic intersection calculation ("3 people free 15 Feb 19:00–23:00")
- ✅ Timezone-aware (stores UTC, displays in user's local time)
- ✅ 24h reminders with confirmation prompt
- ✅ SQLite by default → seamless migration to PostgreSQL
- ✅ Self-hosted on your hardware (tested on mini-PCs like mr03)

## Quick Start

### 1. Create bot
1. Talk to [@BotFather](https://t.me/BotFather)
2. `/newbot` → name it `ChronoGatherBot` → username `@ChronoGatherBot`
3. Copy the `BOT_TOKEN` it gives you

### 2. Clone & setup (Windows → mr03 workflow)

```powershell
# On Windows (development)
git clone https://github.com/YOUR_GITHUB/chronogather-bot.git
cd chronogather-bot

# Create virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure
copy .env.example .env
notepad .env  # Edit BOT_TOKEN, TIMEZONE=Europe/Moscow