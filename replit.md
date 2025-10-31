# RAIDerBot - Discord Guild Management Bot

## Project Overview
RAIDerBot is a comprehensive Discord bot for managing guild characters, combat power tracking, and attendance events with real-time updates. Built specifically for Lineage 2-style guild management.

## Recent Changes
**October 31, 2025**: Project imported and initialized on Replit
- Extracted all project files from zip archive
- Installed Python 3.11 and all dependencies (discord.py 2.6.4, asyncpg 0.30.0, pytz 2025.2)
- PostgreSQL database ready (8 tables will auto-initialize on first run)
- Discord bot token configured via Replit Secrets
- Workflow configured and bot successfully started
- Bot logged in and connected as TEST#1210

## Current Status
✅ Bot is RUNNING and connected to Discord
✅ Database initialized with all required tables
✅ All environment variables configured
✅ Ready for production use

## Database Tables
- **users** - Player data (nickname, characters, CP, attendance responses)
- **attendance_events** - Event scheduling and tracking
- **available_mains** - Main character types
- **available_subclasses** - Subclass options per main
- **dm_messages** - DM tracking for auto-cleanup
- **event_metadata** - Event scheduling metadata
- **leaderboards** - Player rankings
- **settings** - Guild configuration

## Key Features
- Multi-slot character system with dynamic slot configuration (1-10 slots)
- Attendance events with modal creation and live countdown timers
- YES/NO button responses via DM
- Real-time participant counts in channel announcements
- Multi-day recurring events with automatic scheduling
- CSV/JSON exports for all data
- Automatic DM cleanup (48+ hours old)
- Server nickname display (Discord IDs stored internally)

## Environment Variables
All configured via Replit Secrets:
- `DISCORD_BOT_TOKEN` - Discord bot authentication
- `DATABASE_URL` - PostgreSQL connection (auto-configured)
- `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` - Database credentials

## Admin Commands Quick Reference
### Configuration
- `!raider` - List all admin commands
- `!guildname <name>` - Set guild name
- `!setrole <@role>` - Set role for surveys/attendance
- `!setchannel <#channel>` - Set announcement channel
- `!characters <number>` - Set character slots (1-10)
- `!polltitle <title>` - Channel post title
- `!dmtitle <title>` - DM message title

### Character Management
- `!addmain <Main>` - Add main character type
- `!deletemain <Main>` - Remove main character type
- `!addsub <Main> <Class>` - Add subclass
- `!deletesub <Main> <Class>` - Remove subclass

### Data Collection
- `!survey` - Start character survey
- `!poll` - Create attendance event (modal)
- `!poll <id> @user` - Resend attendance DM
- `!deletepoll <id>` - Delete attendance event

### Data Export
- `!exportsurvey` - Export survey data (CSV)
- `!exportpoll` - Export attendance data (CSV)
- `!exportdatabase` - Export full database (JSON)

### Reward Configuration
- `!rewardconfig` - View current reward formula values
- `!setreward <setting> <value>` - Change a reward value
  - Example: `!setreward base_role_reward 3000`
  - Settings: max_reward, base_role_reward, survey_bonus, survey_penalty_no_submit, event_portion, pvp_portion, survey_penalty_1, survey_penalty_2

### Maintenance
- `!deletesurvey` - Clear all survey responses
- `!deletecache` - Clear temporary cache
- `!deletepolls` - Delete all attendance events
- `!msg <text>` - DM all role members

## Player Commands
- Send "survey" via DM to bot - Redo character survey anytime
- Click YES/NO buttons in attendance DMs

## Technical Details
- **Language**: Python 3.11
- **Framework**: discord.py 2.6.4
- **Database**: PostgreSQL with asyncpg (connection pooling: 5-30 connections)
- **Performance**: Optimized for 100+ concurrent users
- **DM Rate Limiting**: 15 concurrent sends with exponential backoff
- **Memory Management**: Automatic cleanup every 6 hours

## Deployment Notes
- Bot runs continuously via Replit workflow
- Auto-restarts on code changes
- Database migrations automatic on startup
- Logs available in Replit console

## Default Character Classes
Pre-configured with Lineage 2 classes:
- **Human**: Duelist, Dreadnought, Phoenix Knight, Hell Knight, Sagittarius, Adventurer, Archmage, Soultaker, Mystic Muse, Storm Screamer, Hierophant, Eva's Saint, Shillien Saint
- **Elf**: Moonlight Sentinel, Sword Muse, Wind Rider, Mystic Muse, Elemental Master, Eva's Saint
- **Dark Elf**: Ghost Hunter, Spectral Dancer, Storm Screamer, Shillien Templar, Shillien Saint
- **Orc**: Titan, Grand Khavatari, Dominator, Doomcryer
- **Dwarf**: Maestro, Fortune Seeker
- **Kamael**: Trickster, Doombringer, Soulhound, Judicator

## Important Notes
- All displayed names use server nicknames (Discord account names NOT shown)
- Discord IDs stored internally for identification
- Event IDs reusable after deletion
- Subclass automatically resets when main character changes
- Combat Power accepts numeric input only (commas auto-formatted)
- DM auto-cleanup runs hourly (database records preserved)
- Countdown updates adaptively: 10-min intervals (>30 min remaining), 1-min intervals (≤30 min)

## Next Steps for Production Use
1. Invite bot to your Discord server with proper permissions
2. Enable **SERVER MEMBERS INTENT** and **MESSAGE CONTENT INTENT** in Discord Developer Portal
3. Run `!setrole @YourRole` to set the member role
4. Run `!setchannel #your-channel` to set announcement channel
5. Run `!guildname YourGuildName` to set guild name
6. Customize titles with `!polltitle` and `!dmtitle`
7. Start your first survey with `!survey`

## Support & Documentation
See README.md for full documentation and workflow examples.
