# RAIDerBot Deployment Guide

## Pre-Deployment Checklist

### 1. Environment Variables Required

#### For All Platforms:
- `DISCORD_BOT_TOKEN` - Your Discord bot token from [Discord Developer Portal](https://discord.com/developers/applications)
- `DATABASE_URL` - PostgreSQL connection string (auto-provided by Railway, manual for others)

#### Optional Database Variables (if not using DATABASE_URL):
- `PGHOST` - PostgreSQL hostname
- `PGPORT` - PostgreSQL port (default: 5432)
- `PGUSER` - PostgreSQL username
- `PGPASSWORD` - PostgreSQL password
- `PGDATABASE` - PostgreSQL database name

### 2. Discord Bot Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application or select existing
3. Navigate to "Bot" section
4. **CRITICAL**: Enable these Privileged Gateway Intents:
   - ✅ **SERVER MEMBERS INTENT** (required for role management)
   - ✅ **MESSAGE CONTENT INTENT** (required for commands)
5. Copy your bot token (keep it secret!)

### 3. Bot Permissions

When inviting the bot to your server, it needs these permissions:
- Read Messages/View Channels
- Send Messages
- Manage Messages
- Embed Links
- Read Message History
- Add Reactions
- Use Application Commands

**Invite URL Template:**
```
https://discord.com/api/oauth2/authorize?client_id=YOUR_BOT_CLIENT_ID&permissions=277025508416&scope=bot
```

Replace `YOUR_BOT_CLIENT_ID` with your actual bot's client ID from the Developer Portal.

---

## Railway Deployment (Recommended)

Railway provides automatic PostgreSQL provisioning and easy deployment.

### Step 1: Prepare Your Repository

1. **Push to GitHub:**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/raiderbot.git
   git push -u origin main
   ```

### Step 2: Deploy to Railway

1. Go to [Railway.app](https://railway.app)
2. Click "Start a New Project"
3. Select "Deploy from GitHub repo"
4. Select your RAIDerBot repository
5. Railway will auto-detect the Python project

### Step 3: Add PostgreSQL Database

1. Click "New" → "Database" → "Add PostgreSQL"
2. Railway automatically creates `DATABASE_URL` environment variable
3. Wait for database to provision (~30 seconds)

### Step 4: Configure Environment Variables

1. Go to your project's "Variables" tab
2. Add `DISCORD_BOT_TOKEN`:
   - Click "New Variable"
   - Name: `DISCORD_BOT_TOKEN`
   - Value: Your Discord bot token
3. Verify `DATABASE_URL` exists (auto-created by PostgreSQL addon)

### Step 5: Deploy

1. Click "Deploy" or push changes to GitHub
2. Railway automatically:
   - Installs dependencies from `requirements.txt`
   - Runs database migrations
   - Starts the bot with `python main.py`

### Step 6: Monitor Logs

1. Click "Deployments" → Select latest deployment
2. View real-time logs to verify:
   ```
   Bot logged in as YourBotName#1234
   Database initialized
   Default character classes loaded
   RAIDerBot is ready!
   ```

### Step 7: Verify Bot is Online

1. Check your Discord server - bot should show as online
2. Run `!raider` to verify commands work
3. Run `!config` to set up your server

---

## Replit Deployment (Development/Testing)

### Step 1: Import Project

1. Go to [Replit](https://replit.com)
2. Click "Create Repl"
3. Select "Import from GitHub"
4. Paste your repository URL
5. Click "Import from GitHub"

### Step 2: Configure Secrets

1. Click "Secrets" (lock icon in left sidebar)
2. Add `DISCORD_BOT_TOKEN`:
   - Key: `DISCORD_BOT_TOKEN`
   - Value: Your Discord bot token
3. Database is auto-configured by Replit

### Step 3: Run

1. Click "Run" button
2. Bot starts automatically
3. Monitor console for logs

---

## Heroku Deployment

### Step 1: Install Heroku CLI

```bash
npm install -g heroku
heroku login
```

### Step 2: Create Heroku App

```bash
heroku create raiderbot-YOUR_NAME
```

### Step 3: Add PostgreSQL

```bash
heroku addons:create heroku-postgresql:essential-0
```

### Step 4: Set Environment Variables

```bash
heroku config:set DISCORD_BOT_TOKEN="your_discord_token_here"
```

### Step 5: Deploy

```bash
git push heroku main
```

### Step 6: Scale Worker

```bash
heroku ps:scale worker=1
```

### Step 7: View Logs

```bash
heroku logs --tail
```

---

## Docker Deployment (Advanced)

### Dockerfile (create this file):

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

### docker-compose.yml (create this file):

```yaml
version: '3.8'

services:
  bot:
    build: .
    environment:
      - DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN}
      - DATABASE_URL=${DATABASE_URL}
    depends_on:
      - db
    restart: unless-stopped

  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_DB=raiderbot
      - POSTGRES_USER=raiderbot
      - POSTGRES_PASSWORD=${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  postgres_data:
```

### .env file (create this, don't commit):

```env
DISCORD_BOT_TOKEN=your_token_here
DB_PASSWORD=secure_password_here
DATABASE_URL=postgresql://raiderbot:secure_password_here@db:5432/raiderbot
```

### Deploy:

```bash
docker-compose up -d
```

---

## Post-Deployment Configuration

### Initial Setup Commands

Once your bot is online, run these commands in your Discord server:

```
!config                          # Interactive setup wizard
!guildname YourGuildName         # Set guild name
!setrole @MemberRole             # Set member role
!setchannel #announcements       # Set announcement channel
!polltitle Event Attendance      # Set attendance title
!dmtitle Attendance Reminder     # Set DM title
```

### Verify Installation

```
!raider                          # Shows all commands
!survey                          # Test survey system
!leaderboard #channel            # Create leaderboard
```

### Add Character Classes (Optional)

Default Lineage 2 classes are pre-loaded. To customize:

```
!addmain ClassName               # Add new main character
!addsub ClassName SubclassName   # Add subclass option
```

---

## Troubleshooting

### Bot Won't Start

**Error:** `DISCORD_BOT_TOKEN environment variable not set`
- **Solution:** Add `DISCORD_BOT_TOKEN` to your platform's environment variables

**Error:** `DATABASE_URL environment variable is not set`
- **Solution:** Add PostgreSQL database to your deployment platform

**Error:** `Failed to create database connection pool`
- **Solution:** Verify DATABASE_URL format: `postgresql://user:pass@host:port/dbname`

### Bot is Online But Not Responding

**Check 1:** Verify Privileged Gateway Intents are enabled
- Go to Discord Developer Portal → Bot → Privileged Gateway Intents
- Enable **SERVER MEMBERS INTENT** and **MESSAGE CONTENT INTENT**

**Check 2:** Verify bot permissions in server
- Right-click bot → View Permissions
- Ensure "Send Messages" and "Read Message History" are enabled

**Check 3:** Check command prefix
- Bot uses `!` prefix by default
- Try `!raider` to see available commands

### Database Errors

**Error:** `relation "users" does not exist`
- **Solution:** Database tables are created automatically on first run
- Wait a few seconds after startup, then retry command

**Error:** `connection pool exhausted`
- **Solution:** Reduce concurrent operations or increase `max_size` in `database.py` (line 65)

### Memory Issues

**Warning:** `High memory usage`
- **Solution:** Memory cleanup runs every 6 hours automatically
- Force cleanup: `!deletecache`

---

## Scaling Considerations

### For 100+ Users:

1. **Database Connection Pool:**
   - Current: 5-30 connections (line 64-65 in `database.py`)
   - Increase if needed based on load

2. **Railway Resources:**
   - Upgrade to Pro plan for better performance
   - Monitor memory and CPU usage

3. **Rate Limiting:**
   - Current: 15 concurrent DM sends (line 96 in `bot.py`)
   - Adjust based on Discord rate limits

### For 500+ Users:

1. Consider database replication
2. Implement Redis caching
3. Use multiple bot instances with sharding

---

## Maintenance

### Backup Database

**Railway:**
```bash
# Export via Railway CLI
railway run pg_dump $DATABASE_URL > backup.sql
```

**Manual:**
```bash
pg_dump DATABASE_URL > backup_$(date +%Y%m%d).sql
```

### Update Bot

```bash
git pull origin main
# Railway auto-deploys on git push
# Heroku: git push heroku main
# Docker: docker-compose up -d --build
```

### Monitor Logs

- **Railway:** Dashboard → Deployments → Logs
- **Heroku:** `heroku logs --tail`
- **Docker:** `docker-compose logs -f bot`

---

## Security Best Practices

1. **Never commit `.env` files or secrets**
   - Use `.gitignore` to exclude sensitive files
   - Secrets should only exist in environment variables

2. **Rotate bot token if exposed**
   - Discord Developer Portal → Bot → Reset Token
   - Update `DISCORD_BOT_TOKEN` in deployment platform

3. **Use environment variables for all secrets**
   - Database credentials
   - API keys
   - Bot tokens

4. **Regular backups**
   - Export database weekly: `!exportdatabase`
   - Store backups securely off-platform

---

## Support

For issues or questions:
- Check deployment logs first
- Review this guide's troubleshooting section
- Ensure all environment variables are set correctly
- Verify Discord bot configuration (intents, permissions)

---

**Ready for production! 🚀**
