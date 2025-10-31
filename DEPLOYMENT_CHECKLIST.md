# Deployment Checklist

Use this checklist before deploying RAIDerBot to production.

## Pre-Deployment

### Discord Bot Setup
- [ ] Created Discord bot application
- [ ] Enabled **SERVER MEMBERS INTENT**
- [ ] Enabled **MESSAGE CONTENT INTENT**
- [ ] Copied bot token
- [ ] Generated invite URL with correct permissions
- [ ] Invited bot to Discord server

### Code Preparation
- [ ] All code committed to Git
- [ ] `.env` file NOT committed (in `.gitignore`)
- [ ] `requirements.txt` is up to date
- [ ] `Procfile` exists with `worker: python main.py`
- [ ] `runtime.txt` specifies Python 3.11+

### Environment Variables
- [ ] `DISCORD_BOT_TOKEN` ready to set
- [ ] `DATABASE_URL` will be auto-configured (Railway/Replit)

## Railway Deployment

### Railway Setup
- [ ] Created Railway account
- [ ] Connected GitHub repository
- [ ] Created new Railway project
- [ ] Added PostgreSQL database service
- [ ] Set `DISCORD_BOT_TOKEN` environment variable
- [ ] Verified `DATABASE_URL` is auto-set

### Post-Deployment
- [ ] Checked deployment logs for errors
- [ ] Verified bot shows online in Discord
- [ ] Tested basic command: `!raider`
- [ ] Configured guild settings:
  - [ ] `!guildname <name>`
  - [ ] `!setrole @role`
  - [ ] `!setchannel #channel`
  - [ ] `!characters <number>`

## Replit Deployment

### Replit Setup
- [ ] Imported code to Replit
- [ ] Added `DISCORD_BOT_TOKEN` to Secrets
- [ ] Database auto-configured (PostgreSQL)
- [ ] Workflow configured to run `python main.py`

### Post-Deployment
- [ ] Bot running and connected
- [ ] Database initialized successfully
- [ ] All commands responding
- [ ] No errors in console

## Testing

### Basic Commands
- [ ] `!raider` - Lists commands
- [ ] `!guildname TestGuild` - Sets guild name
- [ ] `!setrole @TestRole` - Sets role
- [ ] `!setchannel #test` - Sets channel

### Character System
- [ ] `!addmain Human` - Adds main character
- [ ] `!addsub Human Dreadnought` - Adds subclass
- [ ] Default characters loaded correctly

### Survey System
- [ ] `!survey` - Sends DM to role members
- [ ] Survey flow works (main → subclass → CP)
- [ ] Data saved correctly
- [ ] `!exportsurvey` - Exports CSV

### Attendance System
- [ ] `!poll` - Opens modal
- [ ] Modal submission creates event
- [ ] DMs sent to role members
- [ ] YES/NO buttons work
- [ ] Channel announcement shows countdown
- [ ] `!exportpoll` - Exports CSV

### Data Management
- [ ] `!exportdatabase` - Exports JSON
- [ ] Database persists after restart
- [ ] Nicknames update correctly

## Memory & Performance

### Memory Leak Prevention
- [ ] DM cleanup task running (hourly)
- [ ] Cache cleanup working
- [ ] Lock cleanup working
- [ ] No unbounded dictionary growth

### Performance Metrics
- [ ] Bot responds to commands quickly (<2s)
- [ ] Survey DMs sent in parallel (15 concurrent)
- [ ] Database queries optimized
- [ ] Connection pool configured (5-30 connections)

## Security

### Secrets Management
- [ ] Bot token stored in environment variables
- [ ] No secrets in code or committed files
- [ ] `.gitignore` includes `.env` and sensitive files
- [ ] Database credentials secure

### Discord Permissions
- [ ] Admin commands require administrator permission
- [ ] Bot has minimal required permissions
- [ ] No unnecessary elevated permissions

## Monitoring

### Railway (if using)
- [ ] Monitoring dashboard accessible
- [ ] Logs viewable
- [ ] Resource usage within limits
- [ ] Alerts configured (optional)

### Error Handling
- [ ] Error messages clear and helpful
- [ ] Critical errors logged
- [ ] Graceful degradation on failures
- [ ] Retry logic for Discord API calls

## Documentation

- [ ] README.md updated
- [ ] Command list accurate
- [ ] Deployment guide available
- [ ] Environment variables documented

## Backup & Recovery

- [ ] Database backup strategy planned
- [ ] `!exportdatabase` command tested
- [ ] Recovery procedure documented
- [ ] Regular export schedule established

## Final Checks

- [ ] Bot has been running for 24 hours without issues
- [ ] No memory leaks detected
- [ ] All commands tested in production
- [ ] User feedback collected
- [ ] Performance acceptable for user count
- [ ] Database queries optimized
- [ ] No error spam in logs

## Post-Launch

### Week 1
- [ ] Monitor logs daily
- [ ] Check memory usage
- [ ] Verify DM cleanup running
- [ ] Test all major features
- [ ] Collect user feedback

### Month 1
- [ ] Review database size
- [ ] Export and backup data
- [ ] Check for any recurring errors
- [ ] Optimize based on usage patterns
- [ ] Update documentation as needed

---

## Rollback Plan

If issues occur after deployment:

1. **Check logs immediately** - Identify the error
2. **Revert code if needed:**
   ```bash
   git revert HEAD
   git push
   ```
3. **Railway auto-redeploys** with previous version
4. **Verify bot is working** with basic commands
5. **Review and fix** issues before redeploying

---

**Deployment Status:** ⬜ Not Started | 🟡 In Progress | ✅ Complete

Mark this checklist as you deploy to ensure nothing is missed!
