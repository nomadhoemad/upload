# RAIDerBot - Discord Guild Management Bot

## Project Overview

RAIDerBot is a comprehensive Discord bot for guild management with features including:
- Multi-slot character tracking with main + subclass system
- Combat Power (CP) tracking with formatted display
- Attendance event system with live countdowns and recurring events
- Survey system via DMs for character data collection
- CSV/JSON data exports
- Server nickname-based user management

**Status:** ✅ Bot is running and connected to Discord
**Database:** ✅ PostgreSQL configured and initialized
**Last Updated:** October 31, 2025

## Recent Changes

### October 31, 2025 - Production Deployment Preparation
- ✅ Code analyzed for errors and memory leaks
- ✅ Fixed `!reward` command (removed ID display)
- ✅ Fixed `!restart` command (bulk delete all channel messages)
- ✅ Integrated cache clearing into `!restart` process
- ✅ Created comprehensive deployment documentation
- ✅ Prepared files for Railway and GitHub deployment
- ✅ Added GitHub Actions CI/CD workflow
- ✅ Created LICENSE (MIT), CONTRIBUTING.md, CODE_HEALTH_REPORT.md
- ✅ Bot running successfully with all optimizations active

### October 31, 2025 - Initial Setup
- Imported bot codebase from zip archive
- Installed dependencies: discord.py, asyncpg, pytz
- Configured PostgreSQL database with DATABASE_URL
- Set up DISCORD_BOT_TOKEN secret
- Created RAIDerBot workflow to run the bot
- Bot successfully connected to Discord

## Project Architecture

### File Structure
```
main.py           - Entry point, starts the bot
bot.py            - Main bot logic, commands, and event handlers
database.py       - PostgreSQL database operations with connection pooling
characters.py     - Character class definitions for Lineage 2
requirements.txt  - Python dependencies
pyproject.toml    - Project metadata and dependencies
.gitignore        - Git ignore rules for Python
```

### Database Schema
- **users** table: discord_id, nickname, characters (JSONB), combat_power (BIGINT), attendances (JSONB), timestamps
- **settings** table: key-value pairs for guild configuration
- **attendance_events** table: event_id, message, time, am_pm, date, channel_message_id, timestamp

### Key Features
1. **Dynamic character slots**: Admin configurable (1-10 slots per player)
2. **Automatic subclass reset**: When main character changes, subclass clears
3. **Live countdown timers**: Updates every 10 minutes (>30 min) or 1 minute (≤30 min)
4. **Connection pooling**: 5-30 PostgreSQL connections for high performance
5. **Per-user locks**: Fine-grained concurrency control for data integrity
6. **DM auto-cleanup**: Removes bot DMs older than 48 hours (database preserved)

## Environment Variables

Required secrets (configured in Replit Secrets):
- `DISCORD_BOT_TOKEN` - Discord bot authentication token
- `DATABASE_URL` - PostgreSQL connection string (auto-configured)

Additional database variables (auto-configured):
- `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`

## Admin Commands

### Configuration
- `!raider` - List all admin commands
- `!guildname <name>` - Set guild name
- `!setrole <@role>` - Set role for surveys/attendance
- `!setchannel <#channel>` - Set announcement channel
- `!characters <number>` - Set number of character slots (1-10)
- `!polltitle <title>` - Set attendance channel post title
- `!dmtitle <title>` - Set attendance DM title

### Character Management
- `!addmain <Main>` - Add main character type
- `!deletemain <Main>` - Remove main character type
- `!addsub <Main> <Class>` - Add subclass under main
- `!deletesub <Main> <Class>` - Remove subclass
- `!addcharacter` - Add character slot
- `!deletecharacter <1/2/3>` - Remove specific slot

### Data Collection
- `!survey` - Start survey DM to all role members
- `!poll` - Create attendance event (modal flow)
- `!poll <id> @user` - Resend attendance DM
- `!deletepoll <id>` - Delete attendance event

### Data Export
- `!exportsurvey` - Export survey data as CSV
- `!exportpoll` - Export attendance data as CSV
- `!exportdatabase` - Export full database as JSON

### Maintenance
- `!deletesurvey` - Clear all survey responses
- `!deletecache` - Clear temporary cache
- `!deletepolls` - Delete all attendance events
- `!msg <text>` - DM all role members
- `!editdatabase @user character <slot> main|subclass <value>`

## Player Commands

- DM "survey" to bot - Redo character survey
- Click YES/NO buttons in attendance DMs

## Workflows

### RAIDerBot (Main Bot)
- **Command:** `python main.py`
- **Status:** Running
- **Output:** Console logs
- **Purpose:** Discord bot connection and command handling

## User Preferences

- All user-facing names display server nicknames, not Discord usernames
- Discord IDs stored internally for identification only
- CSV exports use wide format for multi-slot data
- Event IDs are reusable after deletion

## Development Notes

### Dependencies
- Python 3.11+
- discord.py 2.6.4+ (with SERVER MEMBERS and MESSAGE CONTENT intents)
- asyncpg 0.30.0+ (PostgreSQL async driver)
- pytz 2025.2+ (Timezone handling)

### Performance Optimizations
- Connection pooling: 5-30 connections, 10s timeout
- Per-user locks: Write locking only, reads are lock-free
- DM concurrency: 15 simultaneous sends with rate limiting
- Lock cleanup: 24-hour max age for inactive locks
- Memory cleanup: Automatic every 6 hours

### Discord Bot Requirements
**Required Intents in Discord Developer Portal:**
1. Go to https://discord.com/developers/applications
2. Select your bot
3. Navigate to "Bot" section
4. Enable under "Privileged Gateway Intents":
   - ✅ SERVER MEMBERS INTENT
   - ✅ MESSAGE CONTENT INTENT

## Next Steps

To use the bot:
1. Invite bot to your Discord server using OAuth2 URL with proper permissions
2. Run `!raider` in a channel to see all admin commands
3. Configure with `!guildname`, `!setrole`, `!setchannel`
4. Add character types with `!addmain` and `!addsub`
5. Set character slots with `!characters <number>`
6. Run `!survey` to start collecting player data
7. Create attendance events with `!poll`

## Support

For issues or questions, check:
- README.md for detailed documentation
- Database logs in PostgreSQL
- Bot console logs in RAIDerBot workflow
