# RAIDerBot - Discord Guild Management Bot

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Discord.py](https://img.shields.io/badge/discord.py-2.6.4-blue.svg)](https://github.com/Rapptz/discord.py)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-required-blue.svg)](https://www.postgresql.org/)

A comprehensive Discord bot for managing guild characters, combat power tracking, and attendance events with real-time updates. Built for Lineage 2-style guild management with production-ready features.

## ✨ Features

### Character Management
- **Multi-slot character system** with main + subclass tracking
- **Dynamic slot configuration** (1-10 character slots per player)
- **Automatic subclass reset** when main character changes
- **Combat Power (CP) tracking** with formatted display (1,234,567 CP)
- **Server nickname display** for all messages and exports

### Attendance System
- **Modal-based event creation** with timezone support
- **Live countdown timer** with adaptive update frequency
  - 10-minute updates when >30 minutes remaining
  - 1-minute updates when ≤30 minutes remaining
- **YES/NO button responses** via DM
- **Real-time participant counts** in channel announcements
- **Multi-day recurring events** with automatic scheduling
- **Reusable Event IDs** after deletion

### Data Management
- **CSV exports** for survey and attendance data
- **JSON database exports** for backup
- **Admin database editing** commands
- **Automatic DM cleanup** (messages older than 48 hours)

### Performance & Scalability
- **Production-ready** for 100+ concurrent users
- **PostgreSQL connection pooling** (5-30 connections)
- **Per-user locking** for save operations
- **Lock-free reads** for optimal performance
- **15 concurrent DM sends** with rate limiting
- **Memory leak prevention** with automatic cleanup

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL database
- Discord Bot Token with **SERVER MEMBERS INTENT** and **MESSAGE CONTENT INTENT** enabled

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/raiderbot.git
   cd raiderbot
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set environment variables:**
   ```bash
   export DISCORD_BOT_TOKEN="your_bot_token_here"
   export DATABASE_URL="postgresql://user:password@host:port/database"
   ```

4. **Run the bot:**
   ```bash
   python main.py
   ```

## 🌐 Deployment

### Deploy to Railway (Recommended)

See [RAILWAY_DEPLOYMENT.md](RAILWAY_DEPLOYMENT.md) for comprehensive deployment guide.

**Quick steps:**
1. Push code to GitHub
2. Connect Railway to your repository
3. Add PostgreSQL database in Railway
4. Set `DISCORD_BOT_TOKEN` environment variable
5. Deploy!

### Deploy to Replit

1. Import repository to Replit
2. Add `DISCORD_BOT_TOKEN` to Secrets
3. Database auto-configured
4. Click Run!

## 📋 Commands

### Configuration Commands (Admin Only)
```
!raider                         - List all admin commands
!guildname <name>              - Set guild name
!setrole <@role>               - Set role for surveys/attendance
!setchannel <#channel>         - Set announcement channel
!characters <number>           - Set number of character slots (1-10)
!polltitle <title>             - Set title for channel posts
!dmtitle <title>               - Set title for DM messages
```

### Character Management (Admin Only)
```
!addmain <Main>                - Add a main character type
!deletemain <Main>             - Remove a main character type
!addsub <Main> <Class>         - Add subclass under main
!deletesub <Main> <Class>      - Remove subclass under main
!addcharacter                  - Add character slot
!deletecharacter <1/2/3>       - Remove specific slot
```

### Data Collection (Admin Only)
```
!survey                        - Start survey DM to all role members
!poll                          - Create attendance event (opens modal)
!poll <id> @user              - Resend attendance DM to specific user
!deletepoll <id>              - Delete attendance event
```

### Data Export (Admin Only)
```
!exportsurvey                  - Export survey data as CSV
!exportpoll                    - Export attendance data as CSV
!exportdatabase                - Export full database as JSON
```

### Maintenance (Admin Only)
```
!deletesurvey                  - Clear all survey responses
!deletecache                   - Clear temporary cache
!deletepolls                   - Delete all attendance events
!msg <text>                    - DM all role members
!editdatabase @user character <slot> main|subclass <value>
```

### Player Commands
```
DM "survey" to bot             - Redo your character survey
```

## 🗄️ Database Schema

### Users Table
- `discord_id` - Discord user ID (primary key)
- `nickname` - Server nickname
- `characters` - JSON array of character slots
- `combat_power` - Numeric CP value (BIGINT)
- `attendances` - JSON object {event_id: "YES"/"NO"/"No Response"}
- `timestamp` - Last update timestamp

### Attendance Events Table
- `event_id` - Auto-incrementing event ID (reusable)
- `message` - Event message
- `time` - Event time (HH:MM)
- `am_pm` - AM/PM
- `date` - Event date (MM/DD/YYYY)
- `channel_message_id` - Discord message ID for channel announcement
- `timestamp` - Creation timestamp

### Settings Table
- `key` - Setting name
- `value` - Setting value

## 🎮 Workflow Examples

### Survey Flow
1. Admin runs `!survey`
2. Bot sends DM to all role members
3. Players select main character from dropdown
4. Players select subclass from dropdown (auto-filtered by main)
5. Players enter Combat Power (numeric only, commas auto-formatted)
6. Confirmation message shown
7. Data saved with server nickname
8. Admin exports with `!exportsurvey`

### Attendance Flow
1. Admin runs `!poll`
2. Modal opens with fields (event message, time, timezone, date)
3. Admin submits modal
4. Bot creates Event ID
5. Bot sends DM to all role members with YES/NO buttons
6. Bot posts channel announcement with live countdown
7. Countdown updates automatically
8. Players click YES/NO to confirm
9. Channel post updates in real-time with counts
10. Admin exports with `!exportpoll`

## 🛠️ Technical Details

- **Language:** Python 3.11
- **Framework:** discord.py 2.6.4
- **Database:** PostgreSQL with asyncpg
- **Async:** Full async/await implementation
- **Connection Pool:** 5-30 connections with 10s command timeout
- **Concurrency:** Per-user locks for saves, lock-free reads
- **DM Throughput:** 15 concurrent sends with exponential backoff
- **Memory Management:** Automatic cleanup every 6 hours
- **Production Ready:** Optimized for 100+ simultaneous users

## 🔧 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | ✅ Yes | Discord bot token from Developer Portal |
| `DATABASE_URL` | ✅ Yes | PostgreSQL connection string |
| `PGHOST` | Optional | PostgreSQL host (if not using DATABASE_URL) |
| `PGPORT` | Optional | PostgreSQL port (default: 5432) |
| `PGUSER` | Optional | PostgreSQL username |
| `PGPASSWORD` | Optional | PostgreSQL password |
| `PGDATABASE` | Optional | PostgreSQL database name |

## 📝 Default Character Classes

Includes Lineage 2 character classes:
- **Human:** Duelist, Dreadnought, Phoenix Knight, Hell Knight, Sagittarius, Adventurer, Archmage, Soultaker, Mystic Muse, Storm Screamer, Hierophant, Eva's Saint, Shillien Saint
- **Elf:** Moonlight Sentinel, Sword Muse, Wind Rider, Mystic Muse, Elemental Master, Eva's Saint
- **Dark Elf:** Ghost Hunter, Spectral Dancer, Storm Screamer, Shillien Templar, Shillien Saint
- **Orc:** Titan, Grand Khavatari, Dominator, Doomcryer
- **Dwarf:** Maestro, Fortune Seeker
- **Kamael:** Trickster, Doombringer, Soulhound, Judicator

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License.

## 🔗 Links

- [Discord Developer Portal](https://discord.com/developers/applications)
- [Railway Deployment Guide](RAILWAY_DEPLOYMENT.md)
- [Quick Fix Guide](RAILWAY_QUICK_FIX.md)

## ⚠️ Important Notes

- All displayed names use server nicknames (Discord IDs stored internally)
- Event IDs are reusable after deletion
- Countdown updates adaptively based on time remaining
- DMs auto-cleanup after 48 hours (database records remain)
- Subclass automatically resets when main character changes
- Combat Power only accepts numeric input with automatic comma formatting

## 📊 Performance Metrics

- **Concurrent Users:** Tested and optimized for 100+ users
- **Database Connections:** 5-30 connection pool
- **DM Rate Limit:** 15 concurrent with 0.1-0.2s jitter
- **Memory Cleanup:** Every 6 hours
- **Lock Cleanup:** 24-hour max age for inactive locks
- **Cache TTL:** 5 minutes for settings cache

---

**Made with ❤️ for guild management**
