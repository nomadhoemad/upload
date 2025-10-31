# Railway Deployment Guide for RAIDerBot

Complete guide to deploy RAIDerBot to Railway with PostgreSQL database.

## Prerequisites

1. **GitHub Account** - To host your code
2. **Railway Account** - Sign up at [railway.app](https://railway.app)
3. **Discord Bot Token** - From [Discord Developer Portal](https://discord.com/developers/applications)

## Step-by-Step Deployment

### Step 1: Prepare Your Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Select your bot or create a new application
3. Navigate to **Bot** section
4. Enable these **Privileged Gateway Intents**:
   - ✅ **SERVER MEMBERS INTENT**
   - ✅ **MESSAGE CONTENT INTENT**
5. Copy your bot token (you'll need it later)

### Step 2: Push Code to GitHub

1. **Create a new GitHub repository:**
   ```bash
   # Initialize git if not already done
   git init
   
   # Add all files
   git add .
   
   # Commit
   git commit -m "Initial commit - RAIDerBot"
   
   # Add your GitHub repository as remote
   git remote add origin https://github.com/yourusername/raiderbot.git
   
   # Push to GitHub
   git push -u origin main
   ```

### Step 3: Create Railway Project

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Authorize Railway to access your GitHub
5. Select your `raiderbot` repository

### Step 4: Add PostgreSQL Database

1. In your Railway project, click **"New"** → **"Database"** → **"Add PostgreSQL"**
2. Railway automatically creates a PostgreSQL database
3. The `DATABASE_URL` environment variable is automatically set

### Step 5: Configure Environment Variables

1. Click on your bot service (not the database)
2. Go to **"Variables"** tab
3. Click **"New Variable"**
4. Add your Discord bot token:
   - **Variable Name:** `DISCORD_BOT_TOKEN`
   - **Value:** Your Discord bot token from Step 1

### Step 6: Deploy

Railway automatically deploys your bot!

1. Check the **"Deployments"** tab to see deployment progress
2. Once deployed, check the **"Logs"** tab
3. You should see:
   ```
   Bot logged in as YourBot#1234
   Database initialized
   Default character classes loaded
   RAIDerBot is ready! Connected to X server(s)
   ```

## Verification

### Check Bot Status

1. In Railway logs, look for:
   - ✅ `Bot logged in as...`
   - ✅ `Database initialized`
   - ✅ `RAIDerBot is ready!`

2. In Discord, check:
   - Bot shows as online
   - Try `!raider` command to list available commands

### Test Database Connection

Run a test command in Discord:
```
!guildname MyGuild
```

If successful, the database is working correctly.

## Common Issues & Solutions

### Issue: Bot Not Starting

**Check logs for:**
```
DISCORD_BOT_TOKEN environment variable not set
```

**Solution:** Add the `DISCORD_BOT_TOKEN` variable in Railway Variables tab.

---

### Issue: Database Connection Failed

**Check logs for:**
```
DATABASE_URL environment variable is not set
```

**Solution:** 
1. Ensure PostgreSQL service is running in Railway
2. Check that both services are in the same project
3. Restart the bot service

---

### Issue: Bot Online But Commands Don't Work

**Causes:**
- Missing intents in Discord Developer Portal
- Bot not invited to server with proper permissions

**Solution:**
1. Enable **SERVER MEMBERS INTENT** and **MESSAGE CONTENT INTENT**
2. Re-invite bot with these permissions:
   - Read Messages/View Channels
   - Send Messages
   - Manage Messages (for !restart command)
   - Read Message History
   - Add Reactions
   - Use External Emojis

**Invite URL Template:**
```
https://discord.com/api/oauth2/authorize?client_id=YOUR_BOT_CLIENT_ID&permissions=387136&scope=bot
```

Replace `YOUR_BOT_CLIENT_ID` with your bot's Client ID from Discord Developer Portal.

---

### Issue: Memory Issues on Railway

**Solution:** Railway free tier has memory limits. If you hit them:
1. Upgrade to Railway Pro ($5/month)
2. Or reduce concurrent operations in code (already optimized for Railway free tier)

## Monitoring & Maintenance

### View Logs

1. Go to Railway Dashboard
2. Click on your bot service
3. Click **"Logs"** tab
4. Monitor for errors or issues

### Restart Bot

**In Railway:**
1. Go to your bot service
2. Click **"..."** menu
3. Select **"Restart"**

**Or trigger restart from Discord:**
```
!restart
```
(Note: This clears data, not a bot restart)

### Update Bot Code

1. Make changes to your local code
2. Commit and push to GitHub:
   ```bash
   git add .
   git commit -m "Update bot features"
   git push
   ```
3. Railway automatically redeploys!

## Scaling & Performance

### Database Connection Pooling

RAIDerBot is configured with:
- **Min connections:** 5
- **Max connections:** 30
- **Command timeout:** 10 seconds
- **Optimized for 100+ concurrent users**

### Memory Management

Automatic cleanup prevents memory leaks:
- DM cleanup: Every 1 hour (removes messages >48 hours old)
- Cache cleanup: Every 6 hours
- Lock cleanup: Every 24 hours

## Cost Estimation

### Railway Pricing

- **Hobby Plan (Free):** $5 free credit/month
  - Suitable for small guilds (10-30 users)
  - Bot usage: ~$1-3/month
  - PostgreSQL: ~$1-2/month

- **Pro Plan:** $20/month + usage
  - Recommended for large guilds (50+ users)
  - Unlimited projects
  - Priority support

### Optimization Tips

1. **Use !restart wisely** - Only when needed, not frequently
2. **Monitor usage** - Check Railway metrics dashboard
3. **Database size** - Export and clean old data periodically with `!exportdatabase`

## Security Best Practices

1. **Never commit your bot token** - Always use environment variables
2. **Restrict admin commands** - Use Discord role permissions
3. **Regular backups** - Use `!exportdatabase` to backup data
4. **Monitor logs** - Check for suspicious activity

## Support

If you encounter issues:

1. **Check Railway logs** - Most errors are shown here
2. **Check Discord bot status** - Ensure bot is online
3. **Verify environment variables** - Ensure `DISCORD_BOT_TOKEN` and `DATABASE_URL` are set
4. **Review this guide** - Common issues section

## Next Steps After Deployment

1. **Configure your bot:**
   ```
   !guildname YourGuildName
   !setrole @YourRole
   !setchannel #announcements
   !characters 2
   ```

2. **Set up character classes:**
   ```
   !addmain Human
   !addsub Human Dreadnought
   ```

3. **Start collecting data:**
   ```
   !survey
   ```

4. **Create attendance events:**
   ```
   !poll
   ```

---

**Deployment Complete!** 🎉

Your RAIDerBot is now running on Railway with automatic scaling, database persistence, and 99.9% uptime.
