import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import Button, View, Select, Modal, TextInput
import os
import asyncio
from datetime import datetime, timedelta
import pytz
import csv
import json
from database import Database
from characters import initialize_default_classes
from functools import wraps
import random

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)
db = Database()

active_surveys = {}
countdown_tasks = {}
settings_cache = {}
cache_timestamps = {}
leaderboard_tracker_task = None

# Retry logic with exponential backoff
async def retry_with_backoff(func, max_retries=3, base_delay=1.0):
    """Retry Discord API calls with exponential backoff"""
    for attempt in range(max_retries):
        try:
            return await func()
        except (discord.HTTPException, discord.errors.DiscordServerError, asyncio.TimeoutError) as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            print(f'Retry attempt {attempt + 1}/{max_retries} after {delay:.2f}s: {e}')
            await asyncio.sleep(delay)
        except discord.Forbidden:
            raise
        except Exception as e:
            print(f'Non-retryable error: {e}')
            raise

# Settings cache helper
async def get_cached_setting(key, ttl=300):
    """Get setting from cache or database with TTL"""
    now = datetime.now()
    if key in settings_cache:
        timestamp = cache_timestamps.get(key)
        if timestamp and (now - timestamp).total_seconds() < ttl:
            return settings_cache[key]
    
    value = await db.get_setting(key)
    settings_cache[key] = value
    cache_timestamps[key] = now
    return value

def clear_settings_cache():
    """Clear the settings cache"""
    settings_cache.clear()
    cache_timestamps.clear()

def cleanup_expired_cache():
    """Remove expired cache entries to prevent memory leak"""
    now = datetime.now()
    expired_keys = [
        key for key, timestamp in cache_timestamps.items()
        if (now - timestamp).total_seconds() > 3600  # 1 hour TTL
    ]
    for key in expired_keys:
        settings_cache.pop(key, None)
        cache_timestamps.pop(key, None)
    return len(expired_keys)

def parse_time_string(time_str):
    """Parse time string like '15D', '2H', '1M' into seconds"""
    time_str = time_str.strip().upper()
    if len(time_str) < 2:
        return None
    
    unit = time_str[-1]
    try:
        value = int(time_str[:-1])
    except ValueError:
        return None
    
    if unit == 'M':
        return value * 60
    elif unit == 'H':
        return value * 3600
    elif unit == 'D':
        return value * 86400
    else:
        return None

# Parallel DM sender with rate limiting - Optimized for high concurrency
async def send_dm_batch(members, send_func, max_concurrent=15):
    """Send DMs in parallel with controlled concurrency (optimized for 100+ users)"""
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def limited_send(member):
        async with semaphore:
            try:
                await send_func(member)
                # Reduced delay with jitter for better rate limiting
                await asyncio.sleep(0.1 + random.uniform(0, 0.1))
                return True, None
            except discord.Forbidden:
                return False, f"Cannot DM {member.name} (DMs disabled)"
            except Exception as e:
                return False, f"Failed to DM {member.name}: {str(e)}"
    
    results = await asyncio.gather(*[limited_send(m) for m in members], return_exceptions=True)
    sent = sum(1 for r in results if isinstance(r, tuple) and r[0])
    failed = len(results) - sent
    return sent, failed

# Leaderboard functions
def format_cp_abbreviated(cp):
    """Format Combat Power with K/M/B abbreviations"""
    if cp >= 1_000_000_000:
        value = cp / 1_000_000_000
        formatted = f"{value:.1f}".rstrip('0').rstrip('.')
        return f"{formatted}B"
    elif cp >= 1_000_000:
        value = cp / 1_000_000
        formatted = f"{value:.2f}".rstrip('0').rstrip('.')
        return f"{formatted}M"
    elif cp >= 1_000:
        value = cp / 1_000
        formatted = f"{value:.1f}".rstrip('0').rstrip('.')
        return f"{formatted}K"
    else:
        return str(cp)

async def _format_leaderboard():
    """Internal async function to format leaderboard"""
    users = await db.get_all_users()
    
    if not users:
        return "No member data available yet. Use !survey to collect data."
    
    # Get configured role to filter users
    role_id = await db.get_setting('survey_role')
    if not role_id:
        return "No role configured. Use !config to set up the guild role first."
    
    # Get guild members with the configured role
    guild = None
    for g in bot.guilds:
        guild = g
        break
    
    if not guild:
        return "Bot is not in any server."
    
    role = guild.get_role(int(role_id))
    if not role:
        return "Configured role not found. Please run !config again to set a valid role."
    
    # Get all guild members with the configured role (matches !reward behavior)
    members_with_role = [member for member in role.members]
    
    if not members_with_role:
        return f"No members found with the {role.name} role."
    
    # Create a dict for quick database lookup
    users_dict = {user['discord_id']: user for user in users}
    
    # Build list of all role members with their data (from DB if exists, otherwise empty)
    role_users = []
    for member in members_with_role:
        discord_id = str(member.id)
        user_data = users_dict.get(discord_id, {
            'discord_id': discord_id,
            'nickname': member.display_name,
            'characters': [],
            'combat_power': 0,
            'attendances': {},
            'timestamp': None
        })
        # Update nickname to current display name
        user_data['nickname'] = member.display_name
        role_users.append(user_data)
    
    # Split users into ranked (CP > 0) and unranked (CP = 0 or no data)
    ranked_users = [u for u in role_users if u['characters'] and len(u['characters']) > 0 and u['combat_power'] > 0]
    unranked_users = [u for u in role_users if not (u['characters'] and len(u['characters']) > 0 and u['combat_power'] > 0)]
    
    # Sort ranked users by combat power (highest first)
    ranked_users.sort(key=lambda x: x['combat_power'], reverse=True)
    
    # Get tracking settings
    warning_seconds = await db.get_setting('track_warning_seconds')
    poop_seconds = await db.get_setting('track_poop_seconds')
    
    # Build leaderboard with header
    lines = ["Leaderboard", ""]
    current_time = datetime.now(pytz.UTC)
    
    # Add ranked users first (sorted by CP, highest to lowest)
    for user in ranked_users:
        nickname = user['nickname']
        # Get main character's subclass
        main_char = user['characters'][0] if user['characters'] else {}
        subclass = main_char.get('subclass', 'None')
        cp = user['combat_power']
        
        # Format CP with K/M/B abbreviations
        cp_formatted = format_cp_abbreviated(cp)
        
        # Add emoji prefix based on survey age
        prefix = ""
        if warning_seconds and poop_seconds:
            try:
                timestamp = user.get('timestamp')
                if timestamp:
                    if isinstance(timestamp, str):
                        # Handle various timestamp formats and strip duplicate timezone info
                        ts_str = timestamp.replace('Z', '+00:00')
                        # Fix double timezone suffix bug
                        if ts_str.count('+00:00') > 1:
                            ts_str = ts_str.replace('+00:00+00:00', '+00:00')
                        timestamp = datetime.fromisoformat(ts_str)
                    elif not timestamp.tzinfo:
                        timestamp = timestamp.replace(tzinfo=pytz.UTC)
                    
                    age_seconds = (current_time - timestamp).total_seconds()
                    
                    if age_seconds >= int(poop_seconds):
                        prefix = "💩"
                    elif age_seconds >= int(warning_seconds):
                        prefix = "⚠️"
            except Exception as e:
                print(f"Error calculating emoji for {nickname}: {e}")
                pass
        
        lines.append(f"{prefix}{nickname} | {subclass} | {cp_formatted} CP")
    
    # Add unranked users at the bottom
    for user in unranked_users:
        nickname = user['nickname']
        # Check if they have any data
        if user['characters'] and len(user['characters']) > 0:
            main_char = user['characters'][0]
            subclass = main_char.get('subclass', 'None')
            lines.append(f"{nickname} | {subclass} | No CP")
        else:
            lines.append(f"{nickname} | No survey data")
    
    # Add participant count
    lines.append("")
    lines.append(f"Members: {len(ranked_users)}")
    
    # Add footer
    lines.append("")
    lines.append("DM/1:1 SURVEY to RAIDerBot to update your data")
    
    return "\n".join(lines)

async def update_all_leaderboards():
    """Update all active leaderboard messages"""
    try:
        leaderboards = await db.get_all_leaderboards()
        if not leaderboards:
            return
        
        message_content = await _format_leaderboard()
        
        for channel_id, message_id in leaderboards:
            try:
                channel = bot.get_channel(int(channel_id))
                if not channel:
                    continue
                
                message = await channel.fetch_message(int(message_id))
                await message.edit(content=message_content)
            except discord.NotFound:
                # Message was deleted, remove from database
                await db.delete_leaderboard(channel_id)
            except discord.Forbidden:
                # No permission to edit, remove from database
                await db.delete_leaderboard(channel_id)
            except Exception as e:
                print(f"Error updating leaderboard in channel {channel_id}: {e}")
    except Exception as e:
        print(f"Error in update_all_leaderboards: {e}")

async def leaderboard_update_loop():
    """Background task to update leaderboards every 24 hours for emoji indicators"""
    try:
        print("Leaderboard auto-update loop started (24-hour interval)")
        while True:
            # Get update interval
            interval_str = await db.get_setting('track_update_interval')
            if not interval_str:
                print("No tracking interval found, stopping tracker")
                break
            
            # Update every 24 hours for memory efficiency
            # Emoji indicators don't need frequent updates
            update_frequency = 86400  # 24 hours in seconds
            await asyncio.sleep(update_frequency)
            
            # Update all leaderboards
            await update_all_leaderboards()
            print(f"Auto-updated leaderboards (24-hour cycle, emoji indicators refreshed)")
    except asyncio.CancelledError:
        print("Leaderboard tracker task cancelled")
    except Exception as e:
        print(f"Error in leaderboard update loop: {e}")

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")
    
    try:
        await db.init_db()
        print("Database initialized")
    except ValueError as e:
        print(f"FATAL ERROR - Database Configuration: {e}")
        print("Bot cannot start without a properly configured database.")
        await bot.close()
        return
    except RuntimeError as e:
        print(f"FATAL ERROR - Database Connection: {e}")
        print("Bot cannot start without a database connection.")
        await bot.close()
        return
    except Exception as e:
        print(f"FATAL ERROR - Unexpected database error: {e}")
        print("Bot cannot start. Please check your database configuration.")
        await bot.close()
        return
    
    try:
        await initialize_default_classes(db)
        print("Default character classes loaded")
    except Exception as e:
        print(f"Warning: Could not load default character classes: {e}")
    
    cleanup_old_dms.start()
    cleanup_old_events.start()
    cleanup_memory.start()
    
    # Start leaderboard tracker if configured
    global leaderboard_tracker_task
    track_interval = await db.get_setting('track_update_interval')
    if track_interval:
        leaderboard_tracker_task = asyncio.create_task(leaderboard_update_loop())
        print("Leaderboard tracker started")
    
    print(f"RAIDerBot is ready! Connected to {len(bot.guilds)} server(s)")

async def shutdown_cleanup():
    """Clean shutdown: cancel tasks and close database"""
    print("Starting shutdown cleanup...")
    
    # Cancel background cleanup tasks if they're running
    if cleanup_old_dms.is_running():
        cleanup_old_dms.cancel()
    if cleanup_old_events.is_running():
        cleanup_old_events.cancel()
    if cleanup_memory.is_running():
        cleanup_memory.cancel()
    
    # Cancel leaderboard tracker task
    global leaderboard_tracker_task
    if leaderboard_tracker_task and not leaderboard_tracker_task.done():
        leaderboard_tracker_task.cancel()
        try:
            await leaderboard_tracker_task
        except asyncio.CancelledError:
            pass
    
    # Cancel all countdown tasks defensively
    for event_id, task in list(countdown_tasks.items()):
        if not task.done():
            task.cancel()
        try:
            await asyncio.wait_for(task, timeout=0.1)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
    countdown_tasks.clear()
    
    # Close database connection pool
    try:
        await db.close()
    except Exception as e:
        print(f"Error closing database: {e}")
    
    print("Shutdown cleanup complete.")

@bot.command(name='raider')
@commands.has_permissions(administrator=True)
async def raider_help(ctx):
    embed = discord.Embed(
        title="⚔️ RAIDerBot Admin Commands",
        description="Complete command reference for guild management",
        color=0x5865F2
    )
    
    embed.add_field(
        name="⚙️ Configuration",
        value=(
            "`!config` - Interactive setup wizard\n"
            "`!characters <number>` - Set character slots (1-10)\n"
            "`!polltitle <title>` - Set channel post title\n"
            "`!dmtitle <title>` - Set DM message title"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🎮 Character Management",
        value=(
            "`!addmain <Main>` - Add main character type\n"
            "`!deletemain <Main>` - Remove main character\n"
            "`!addsub <Main> <Class>` - Add subclass\n"
            "`!deletesub <Main> <Class>` - Remove subclass\n"
            "`!addcharacter` - Add character slot\n"
            "`!deletecharacter <slot>` - Remove slot"
        ),
        inline=False
    )
    
    embed.add_field(
        name="📊 Data Collection",
        value=(
            "`!survey` - Send survey to all role members\n"
            "`!survey @user1 @user2` - Send to specific users\n"
            "`!poll` - Create attendance event (modal)\n"
            "`!poll <#channel> <@role>` - Targeted poll\n"
            "`!poll <id> @user` - Resend attendance DM\n"
            "`!deletepoll <id>` - Delete event\n"
            "`!event` - Reaction-based event\n"
            "`!deleteevent <id>` - Delete reaction event"
        ),
        inline=False
    )
    
    embed.add_field(
        name="💰 Rewards",
        value=(
            "`!reward` - Post reward distribution\n"
            "`!rewardconfig` - View reward formula\n"
            "`!setreward <setting> <value>` - Update formula"
        ),
        inline=False
    )
    
    embed.add_field(
        name="📁 Data Export",
        value=(
            "`!exportsurvey` - Export survey CSV\n"
            "`!exportpoll` - Export attendance CSV\n"
            "`!exportdatabase` - Export database JSON"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🏆 Leaderboard",
        value=(
            "`!leaderboard #channel` - Live leaderboard\n"
            "`!tracksurvey <time1> <time2>` - Survey age tracking"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🔧 Maintenance",
        value=(
            "`!deleteuser <nickname>` - Delete user\n"
            "`!deletecache` - Clear cache\n"
            "`!restart` - Reset events & refresh nicknames\n"
            "`!msg <text>` - DM all role members\n"
            "`!msg @users <text>` - DM specific users\n"
            "`!msg #channel <text>` - Send to channel\n"
            "`!editdatabase @user character <slot> main|subclass <value>`"
        ),
        inline=False
    )
    
    embed.set_footer(text="💡 Tip: Use !config for quick setup | All commands require Administrator permission")
    
    await ctx.send(embed=embed)

@bot.command(name='config')
@commands.has_permissions(administrator=True)
async def interactive_config(ctx):
    """Interactive configuration setup"""
    
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel
    
    try:
        # Question 1: Guild Name
        await ctx.send("**What's the Guild's Name:**")
        try:
            msg = await bot.wait_for('message', timeout=60.0, check=check)
            guild_name = msg.content
            await db.set_setting('guildname', guild_name)
            await ctx.send(f'✅ Guild name set to: **{guild_name}**')
        except asyncio.TimeoutError:
            await ctx.send('❌ Configuration timed out. Please run `!config` again.')
            return
        
        # Question 2: Guild Discord Role
        await ctx.send("**What's the Guild's discord role:** (mention the role with @)")
        try:
            msg = await bot.wait_for('message', timeout=60.0, check=check)
            if msg.role_mentions:
                role = msg.role_mentions[0]
                await db.set_setting('survey_role', str(role.id))
                await ctx.send(f'✅ Guild role set to: **{role.name}**')
            else:
                await ctx.send('❌ No role mentioned. Please run `!config` again and mention a role.')
                return
        except asyncio.TimeoutError:
            await ctx.send('❌ Configuration timed out. Please run `!config` again.')
            return
        
        # Question 3: PvP Players Role
        await ctx.send("**What's the PvP Players role:** (mention the role with @)")
        try:
            msg = await bot.wait_for('message', timeout=60.0, check=check)
            if msg.role_mentions:
                pvp_role = msg.role_mentions[0]
                await db.set_setting('pvp_role', str(pvp_role.id))
                await ctx.send(f'✅ PvP role set to: **{pvp_role.name}**')
            else:
                await ctx.send('❌ No role mentioned. Please run `!config` again and mention a role.')
                return
        except asyncio.TimeoutError:
            await ctx.send('❌ Configuration timed out. Please run `!config` again.')
            return
        
        # Question 4: Announcement Channel
        await ctx.send("**What's the Channel for Announcement:** (mention the channel with #)")
        try:
            msg = await bot.wait_for('message', timeout=60.0, check=check)
            if msg.channel_mentions:
                channel = msg.channel_mentions[0]
                await db.set_setting('announcement_channel', str(channel.id))
                await ctx.send(f'✅ Announcement channel set to: **{channel.mention}**')
            else:
                await ctx.send('❌ No channel mentioned. Please run `!config` again and mention a channel.')
                return
        except asyncio.TimeoutError:
            await ctx.send('❌ Configuration timed out. Please run `!config` again.')
            return
        
        # Clear cache and confirm
        clear_settings_cache()
        await ctx.send('✅ **Configuration complete!**')
        
    except Exception as e:
        await ctx.send(f'❌ An error occurred during configuration: {str(e)}')
        print(f"Config error: {e}")

@bot.command(name='characters')
@commands.has_permissions(administrator=True)
async def set_character_slots(ctx, number: int):
    if number < 1 or number > 10:
        await ctx.send('Character slots must be between 1 and 10.')
        return
    await db.set_setting('survey_slot_count', str(number))
    clear_settings_cache()
    await ctx.send(f'Character slots set to: {number}')

@bot.command(name='polltitle')
@commands.has_permissions(administrator=True)
async def set_attendance_title(ctx, *, title: str):
    await db.set_setting('attendance_title', title)
    clear_settings_cache()
    await ctx.send(f'Poll title set to: {title}')

@bot.command(name='dmtitle')
@commands.has_permissions(administrator=True)
async def set_dm_title(ctx, *, title: str):
    await db.set_setting('dmtitle', title)
    clear_settings_cache()
    await ctx.send(f'DM title set to: {title}')

@bot.command(name='addmain')
@commands.has_permissions(administrator=True)
async def add_main(ctx, *, main_name: str):
    await db.add_main(main_name)
    await ctx.send(f'Added main character: {main_name}')

@bot.command(name='deletemain')
@commands.has_permissions(administrator=True)
async def remove_main(ctx, *, main_name: str):
    await db.remove_main(main_name)
    await ctx.send(f'Removed main character: {main_name}')

@bot.command(name='addsub')
@commands.has_permissions(administrator=True)
async def add_sub(ctx, main_name: str, *, subclass_name: str):
    mains = await db.get_all_mains()
    if main_name not in mains:
        await ctx.send(f'Main character "{main_name}" does not exist. Add it first with !addmain')
        return
    await db.add_subclass(main_name, subclass_name)
    await ctx.send(f'Added subclass "{subclass_name}" to {main_name}')

@bot.command(name='deletesub')
@commands.has_permissions(administrator=True)
async def remove_sub(ctx, main_name: str, *, subclass_name: str):
    await db.remove_subclass(main_name, subclass_name)
    await ctx.send(f'Removed subclass "{subclass_name}" from {main_name}')

@bot.command(name='survey')
@commands.has_permissions(administrator=True)
async def start_survey(ctx, members: commands.Greedy[discord.Member] = None):
    guild = ctx.guild
    guildname = await get_cached_setting('guildname') or 'Guild'
    
    # If specific users are mentioned, send only to them
    if members:
        # Filter out bots from mentioned users
        members_to_send = [m for m in members if not m.bot]
        
        if not members_to_send:
            await ctx.send('No valid members to survey (all mentioned users are bots).')
            return
        
        await ctx.send(f'Sending survey prompts to {len(members_to_send)} mentioned member(s)...')
    else:
        # No mentions - send to all role members
        role_id = await get_cached_setting('survey_role')
        if not role_id:
            await ctx.send('Please set a role first using !setrole')
            return
        
        role = guild.get_role(int(role_id))
        if not role:
            await ctx.send('Configured role not found.')
            return
        
        members_to_send = [m for m in role.members if not m.bot]
        
        if not members_to_send:
            await ctx.send('No members to survey.')
            return
        
        await ctx.send(f'Sending survey prompts to {len(members_to_send)} members...')
    
    async def send_to_member(member):
        await send_survey_dm(member, guild, guildname, send_prompt_only=True)
    
    sent, failed = await send_dm_batch(members_to_send, send_to_member)
    
    if members:
        await ctx.send(f'Survey prompts sent to {sent} mentioned member(s). Failed: {failed}\nUsers will need to type "SURVEY" in their DMs to start.')
    else:
        await ctx.send(f'Survey prompts sent to {sent} members. Failed: {failed}\nUsers will need to type "SURVEY" in their DMs to start.')

async def send_survey_dm(member, guild, guildname, send_prompt_only=False):
    slot_count = int(await get_cached_setting('survey_slot_count') or 2)
    
    survey_key = f"{member.id}"
    
    if send_prompt_only:
        # Send only the prompt message asking user to type SURVEY
        try:
            msg = await retry_with_backoff(lambda: member.send(f'{guildname} needs you to update your Characters for our record. Type SURVEY to start.'))
            await db.add_dm_message(msg.id, member.id)
        except (discord.Forbidden, discord.HTTPException, Exception) as e:
            print(f'Failed to send survey prompt to {member.name}: {e}')
        return
    
    # Full survey flow - create survey and send character selection
    active_surveys[survey_key] = {
        'user_id': member.id,
        'guild_id': guild.id,
        'characters': [],
        'current_slot': 0,
        'slot_count': slot_count
    }
    
    try:
        await asyncio.sleep(0.5)
        await send_character_selection(member, survey_key, 0)
    except (discord.Forbidden, discord.HTTPException, Exception) as e:
        # Clean up survey entry if DM fails to prevent memory leak
        if survey_key in active_surveys:
            del active_surveys[survey_key]
        print(f'Failed to send survey DM to {member.name}: {e}')
        raise

async def send_character_selection(member, survey_key, slot_index):
    survey = active_surveys.get(survey_key)
    if not survey:
        return
    
    mains = await db.get_all_mains()
    
    if slot_index == 0:
        slot_label = "Main Character"
    else:
        slot_label = f"Character {slot_index + 1}"
    
    view = MainSelectionView(survey_key, slot_index, mains)
    msg = await retry_with_backoff(lambda: member.send(f'Select your {slot_label} :', view=view))
    await db.add_dm_message(msg.id, member.id)

class MainSelectionView(View):
    def __init__(self, survey_key, slot_index, mains):
        super().__init__(timeout=300)
        self.survey_key = survey_key
        self.slot_index = slot_index
        
        options = [discord.SelectOption(label=main, value=main) for main in mains[:25]]
        select = Select(placeholder="Choose main character", options=options, custom_id=f"main_{survey_key}_{slot_index}")
        select.callback = self.main_selected
        self.add_item(select)
    
    async def on_timeout(self):
        if self.survey_key in active_surveys:
            del active_surveys[self.survey_key]
    
    async def main_selected(self, interaction: discord.Interaction):
        survey = active_surveys.get(self.survey_key)
        if not survey:
            await interaction.response.send_message('Survey session expired.', ephemeral=True)
            return
        
        main = interaction.data['values'][0]
        
        if self.slot_index < len(survey['characters']):
            survey['characters'][self.slot_index] = {'main': main, 'subclass': ''}
        else:
            survey['characters'].append({'main': main, 'subclass': ''})
        
        await interaction.response.defer()
        
        subclasses = await db.get_subclasses_for_main(main)
        if subclasses:
            try:
                view = SubclassSelectionView(self.survey_key, self.slot_index, main, subclasses)
                msg = await interaction.user.send(f'Select your subclass for {main}:', view=view)
                await db.add_dm_message(msg.id, interaction.user.id)
            except (discord.Forbidden, discord.HTTPException, Exception) as e:
                # Clean up survey entry if subclass DM fails
                if self.survey_key in active_surveys:
                    del active_surveys[self.survey_key]
                print(f'Failed to send subclass selection to {interaction.user.name}: {e}')
        else:
            await check_next_slot_or_cp(interaction.user, self.survey_key)

class SubclassSelectionView(View):
    def __init__(self, survey_key, slot_index, main, subclasses):
        super().__init__(timeout=300)
        self.survey_key = survey_key
        self.slot_index = slot_index
        self.main = main
        
        options = [discord.SelectOption(label=sub, value=sub) for sub in subclasses[:25]]
        select = Select(placeholder="Choose subclass", options=options, custom_id=f"sub_{survey_key}_{slot_index}")
        select.callback = self.subclass_selected
        self.add_item(select)
    
    async def on_timeout(self):
        if self.survey_key in active_surveys:
            del active_surveys[self.survey_key]
    
    async def subclass_selected(self, interaction: discord.Interaction):
        survey = active_surveys.get(self.survey_key)
        if not survey:
            await interaction.response.send_message('Survey session expired.', ephemeral=True)
            return
        
        subclass = interaction.data['values'][0]
        survey['characters'][self.slot_index]['subclass'] = subclass
        
        await interaction.response.defer()
        await check_next_slot_or_cp(interaction.user, self.survey_key)

async def check_next_slot_or_cp(user, survey_key):
    survey = active_surveys.get(survey_key)
    if not survey:
        return
    
    survey['current_slot'] += 1
    
    if survey['current_slot'] < survey['slot_count']:
        try:
            await send_character_selection(user, survey_key, survey['current_slot'])
        except (discord.Forbidden, discord.HTTPException, Exception) as e:
            # Clean up survey entry if character selection DM fails
            if survey_key in active_surveys:
                del active_surveys[survey_key]
            print(f'Failed to send character selection to {user.name}: {e}')
    else:
        try:
            dm_channel = await user.create_dm()
            msg = await dm_channel.send("Click below to enter your Combat Power:")
            await db.add_dm_message(msg.id, user.id)
            
            view = CombatPowerButtonView(survey_key)
            
            msg2 = await dm_channel.send(view=view)
            await db.add_dm_message(msg2.id, user.id)
        except (discord.Forbidden, discord.HTTPException, Exception) as e:
            # Clean up survey entry if CP DM fails to prevent memory leak
            if survey_key in active_surveys:
                del active_surveys[survey_key]
            print(f'Failed to send CP prompt to {user.name}: {e}')

class CombatPowerButtonView(View):
    def __init__(self, survey_key):
        super().__init__(timeout=300)
        self.survey_key = survey_key
        button = Button(label="Enter Combat Power", style=discord.ButtonStyle.primary, custom_id=f"cp_{survey_key}")
        button.callback = self.button_callback
        self.add_item(button)
    
    async def button_callback(self, interaction):
        # Create fresh modal for each user to avoid shared state
        modal = CombatPowerModal(self.survey_key)
        await interaction.response.send_modal(modal)
    
    async def on_timeout(self):
        if self.survey_key in active_surveys:
            del active_surveys[self.survey_key]

class CombatPowerModal(Modal, title='Combat Power'):
    def __init__(self, survey_key):
        super().__init__(timeout=None)
        self.survey_key = survey_key
        self.cp_input = TextInput(label='Combat Power (numbers only)', placeholder='1234567', required=True, max_length=15)
        self.add_item(self.cp_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        survey = active_surveys.get(self.survey_key)
        if not survey:
            await interaction.response.send_message('Survey session expired.', ephemeral=True)
            return
        
        cp_str = self.cp_input.value.replace(',', '').replace(' ', '')
        
        if not cp_str.isdigit():
            await interaction.response.send_message('Combat Power must be numbers only.', ephemeral=True)
            return
        
        combat_power = int(cp_str)
        
        guild = bot.get_guild(survey['guild_id'])
        if not guild:
            await interaction.response.send_message('Error: Guild not found.', ephemeral=True)
            return
        
        member = guild.get_member(survey['user_id'])
        if not member:
            await interaction.response.send_message('Error: Member not found.', ephemeral=True)
            return
        
        nickname = member.display_name
        
        user_data = await db.get_user(str(survey['user_id']))
        attendances = user_data['attendances'] if user_data else {}
        
        await db.save_user(
            str(survey['user_id']),
            nickname,
            survey['characters'],
            combat_power,
            attendances,
            update_survey_timestamp=True
        )
        
        # Update all leaderboards after survey completion
        await update_all_leaderboards()
        
        formatted_cp = f"{combat_power:,}"
        
        char_summary = []
        for char in survey['characters']:
            if char['subclass']:
                char_summary.append(f"{char['main']} > {char['subclass']}")
            else:
                char_summary.append(f"{char['main']}")
        
        confirmation = f"**Survey Complete!**\n\n"
        for i, char_str in enumerate(char_summary, 1):
            confirmation += f"Character {i}: {char_str}\n"
        confirmation += f"Combat Power: {formatted_cp}\n\nThank you for updating your character data!"
        
        msg = await interaction.response.send_message(confirmation, ephemeral=False)
        
        if self.survey_key in active_surveys:
            del active_surveys[self.survey_key]

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    if isinstance(message.channel, discord.DMChannel):
        content = message.content.strip()
        content_lower = content.lower()
        
        if content_lower in ['survey', 'ok']:
            for guild in bot.guilds:
                member = guild.get_member(message.author.id)
                if member:
                    guildname = await get_cached_setting('guildname') or 'Guild'
                    try:
                        await send_survey_dm(member, guild, guildname)
                        return
                    except Exception as e:
                        print(f'Error sending survey: {e}')
                        await message.channel.send('Error starting survey. Please contact an admin.')
                        return
        
        parts = content.split()
        if len(parts) >= 1 and parts[0].upper() in ['YES', 'NO']:
            response = parts[0].upper()
            event_id = None
            
            if len(parts) == 2 and parts[1].isdigit():
                event_id = int(parts[1])
            elif len(parts) == 1:
                events = await db.get_all_attendance_events()
                if events and len(events) == 1:
                    event_id = events[0]['event_id']
            
            if event_id:
                try:
                    event = await db.get_attendance_event(event_id)
                    if not event:
                        await message.channel.send(f'❌ Event ID {event_id} not found.')
                        return
                    
                    user_data = await db.get_user(str(message.author.id))
                    
                    if user_data:
                        attendances = user_data['attendances']
                        attendances[str(event_id)] = response
                        
                        await db.save_user(
                            user_data['discord_id'],
                            user_data['nickname'],
                            user_data['characters'],
                            user_data['combat_power'],
                            attendances,
                            update_timestamp=False
                        )
                    else:
                        guild = None
                        for g in bot.guilds:
                            member = g.get_member(message.author.id)
                            if member:
                                guild = g
                                break
                        
                        if guild:
                            member = guild.get_member(message.author.id)
                            nickname = member.nick if member.nick else member.name
                            attendances = {str(event_id): response}
                            
                            await db.save_user(
                                str(message.author.id),
                                nickname,
                                [],
                                0,
                                attendances,
                                update_timestamp=False
                            )
                    
                    await message.channel.send(f'✅ Attendance recorded: **{response}** for Event ID {event_id}')
                    
                    try:
                        for guild in bot.guilds:
                            await update_attendance_announcement(guild, event_id)
                    except Exception as e:
                        print(f'Error updating attendance message: {e}')
                    
                    return
                except Exception as e:
                    print(f'Error recording attendance: {e}')
                    await message.channel.send('❌ Error recording attendance. Please try again.')
                    return
            else:
                events = await db.get_all_attendance_events()
                if events and len(events) > 1:
                    event_list = ', '.join([str(e['event_id']) for e in events])
                    await message.channel.send(f'❌ Multiple events active. Please specify Event ID.\nExample: **YES {events[0]["event_id"]}** or **NO {events[0]["event_id"]}**\n\nActive Events: {event_list}')
                    return
    
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        if error.param.name == 'subclass_name':
            await ctx.send(f'❌ Missing subclass name! Usage: `{ctx.prefix}{ctx.command} <Main> <Subclass>`\nExample: `!addsub Human Duelist`')
        elif error.param.name == 'main_name':
            await ctx.send(f'❌ Missing main character name! Usage: `{ctx.prefix}{ctx.command} <Main>`')
        else:
            await ctx.send(f'❌ Missing required argument: {error.param.name}')
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send('❌ You need administrator permissions to use this command.')
    elif isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.MemberNotFound) or isinstance(error, commands.BadArgument):
        if ctx.command and ctx.command.name == 'poll':
            await ctx.send('❌ Invalid usage!\n\n**To create a new attendance event:**\n`!poll` (no arguments)\n\n**To resend attendance DM to a user:**\n`!poll <event_id> @username`\n\n*Note: You must mention a **user** (@username), not a role!*')
        else:
            await ctx.send(f'❌ {error}')
    else:
        print(f'Command error in {ctx.command}: {error}')

@bot.command(name='poll')
@commands.has_permissions(administrator=True)
async def attendance(ctx, channel: discord.TextChannel = None, role: discord.Role = None, event_id_or_question=None, user: discord.Member = None):
    # Handle resending attendance DM: !poll <event_id> @user
    if event_id_or_question and event_id_or_question.isdigit() and user:
        event_id = int(event_id_or_question)
        event = await db.get_attendance_event(event_id)
        if not event:
            await ctx.send(f'Event ID {event_id} not found.')
            return
        
        guildname = await get_cached_setting('guildname') or 'Guild'
        dmtitle = await get_cached_setting('dmtitle') or 'Attendance'
        
        try:
            await send_attendance_dm(user, event, guildname, dmtitle)
            await ctx.send(f'Resent attendance DM to {user.mention}')
        except Exception as e:
            await ctx.send(f'Failed to send DM: {e}')
        return
    
    # Targeted poll: !poll <#channel> <@role>
    if channel and role:
        modal = AttendanceModal(target_channel=channel, target_role=role)
        await ctx.send(f'Creating targeted poll for {role.mention} in {channel.mention}.\nPlease fill out the attendance form:', view=AttendanceButtonView(modal))
        return
    
    # Default poll: !poll
    channel_id = await get_cached_setting('announcement_channel')
    if not channel_id:
        await ctx.send('Please set an announcement channel first using !setchannel')
        return
    
    role_id = await get_cached_setting('survey_role')
    if not role_id:
        await ctx.send('Please set a role first using !setrole')
        return
    
    modal = AttendanceModal()
    await ctx.send('Please fill out the attendance form:', view=AttendanceButtonView(modal))

class AttendanceButtonView(View):
    def __init__(self, modal):
        super().__init__(timeout=300)
        self.modal = modal
        button = Button(label="Create Attendance Event", style=discord.ButtonStyle.primary)
        button.callback = self.open_modal
        self.add_item(button)
    
    async def open_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(self.modal)

class AttendanceModal(Modal, title='Create Attendance Event'):
    event_message = TextInput(label='Event Message', style=discord.TextStyle.paragraph, required=True)
    datetime_input = TextInput(label='Date & Time', placeholder='10/30/2025 07:00 PM', required=True)
    
    def __init__(self, target_channel=None, target_role=None):
        super().__init__()
        self.target_channel = target_channel
        self.target_role = target_role
    
    async def on_submit(self, interaction: discord.Interaction):
        # Defer the response immediately to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        datetime_str = self.datetime_input.value.strip()
        timezone_str = 'US/Pacific'  # Always use Pacific timezone
        
        # Parse datetime
        parts = datetime_str.split()
        if len(parts) != 3:
            await interaction.followup.send(
                f'❌ Invalid format. You entered: "{datetime_str}"\n'
                f'✅ Required format: MM/DD/YYYY HH:MM AM/PM\n'
                f'📝 Example: 10/30/2025 07:00 PM',
                ephemeral=True
            )
            return
        
        date_str = parts[0]
        time_str = parts[1]
        am_pm_str = parts[2].upper()
        
        # Validate date
        try:
            datetime.strptime(date_str, '%m/%d/%Y')
        except ValueError:
            await interaction.followup.send(
                f'❌ Invalid date: "{date_str}"\n'
                f'✅ Required format: MM/DD/YYYY\n'
                f'📝 Example: 10/30/2025',
                ephemeral=True
            )
            return
        
        # Validate time
        try:
            if ':' not in time_str:
                raise ValueError("Missing colon")
            hour, minute = map(int, time_str.split(':'))
            if not (1 <= hour <= 12 and 0 <= minute <= 59):
                raise ValueError("Invalid time range")
        except ValueError as e:
            await interaction.followup.send(
                f'❌ Invalid time: "{time_str}"\n'
                f'✅ Required format: HH:MM (1-12 hours, 00-59 minutes)\n'
                f'📝 Example: 07:00 or 11:30',
                ephemeral=True
            )
            return
        
        # Validate AM/PM
        if am_pm_str not in ['AM', 'PM']:
            await interaction.followup.send(
                f'❌ Invalid AM/PM: "{am_pm_str}"\n'
                f'✅ Must be either AM or PM\n'
                f'📝 Example: 07:00 PM',
                ephemeral=True
            )
            return
        
        event_id = await db.get_next_event_id()
        
        await db.save_attendance_event(
            event_id,
            self.event_message.value,
            time_str,
            am_pm_str,
            date_str
        )
        
        # Store targeted poll metadata if provided
        if self.target_channel and self.target_role:
            await db.set_event_metadata(event_id, {
                'target_channel_id': str(self.target_channel.id),
                'target_role_id': str(self.target_role.id),
                'is_targeted': True
            })
            await send_attendance_to_targeted_users(interaction.guild, event_id, self.target_channel, self.target_role)
            await post_attendance_announcement(interaction.guild, event_id, self.target_channel)
        else:
            await send_attendance_to_role(interaction.guild, event_id)
            await post_attendance_announcement(interaction.guild, event_id)
        
        await interaction.followup.send(f'Attendance event created with ID: {event_id}', ephemeral=True)

async def send_attendance_to_role(guild, event_id):
    event = await db.get_attendance_event(event_id)
    if not event:
        return
    
    role_id = await db.get_setting('survey_role')
    if not role_id:
        return
    
    role = guild.get_role(int(role_id))
    if not role:
        return
    
    guildname = await get_cached_setting('guildname') or 'Guild'
    dmtitle = await get_cached_setting('dmtitle') or 'Attendance'
    
    for member in role.members:
        if member.bot:
            continue
        try:
            await send_attendance_dm(member, event, guildname, dmtitle)
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f'Failed to send attendance DM to {member.name}: {e}')

async def send_attendance_to_targeted_users(guild, event_id, target_channel, target_role):
    """Send attendance DMs to users with specific role who can view specific channel"""
    event = await db.get_attendance_event(event_id)
    if not event:
        return
    
    guildname = await get_cached_setting('guildname') or 'Guild'
    dmtitle = await get_cached_setting('dmtitle') or 'Attendance'
    
    # Get members with the role who can view the channel
    targeted_members = []
    for member in target_role.members:
        if member.bot:
            continue
        # Check if member can view the target channel
        permissions = target_channel.permissions_for(member)
        if permissions.view_channel:
            targeted_members.append(member)
    
    # Send DMs to targeted members
    for member in targeted_members:
        try:
            await send_attendance_dm(member, event, guildname, dmtitle)
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f'Failed to send attendance DM to {member.name}: {e}')

async def send_attendance_dm(member, event, guildname, dmtitle):
    event_id = event['event_id']
    message = event['message']
    time_str = event['time']
    am_pm = event['am_pm']
    date_str = event['date']
    
    pst_tz = pytz.timezone('US/Pacific')
    est_tz = pytz.timezone('US/Eastern')
    
    if am_pm == 'PM' and not time_str.startswith('12'):
        hour = int(time_str.split(':')[0]) + 12
        minute = time_str.split(':')[1]
        time_24 = f"{hour}:{minute}"
    elif am_pm == 'AM' and time_str.startswith('12'):
        minute = time_str.split(':')[1]
        time_24 = f"00:{minute}"
    else:
        time_24 = time_str
    
    try:
        event_dt = datetime.strptime(f"{date_str} {time_24}", '%m/%d/%Y %H:%M')
        event_dt = pst_tz.localize(event_dt)
        est_dt = event_dt.astimezone(est_tz)
        
        # Get day of week
        day_of_week = event_dt.strftime('%A')
        
        # Format: Monday 10/30/2025 07:00 PM PST | 10:00 PM EST
        pst_display = f"{day_of_week} {event_dt.strftime('%m/%d/%Y %I:%M %p')} PST"
        est_display = f"{est_dt.strftime('%I:%M %p')} EST"
        event_dt_display = f"{pst_display} | {est_display}"
    except:
        event_dt_display = f"{date_str} {time_str} {am_pm} PST"
    
    dm_text = f"**{guildname} {dmtitle} (Event ID: {event_id})**\n\n"
    dm_text += f"{message}\n\n"
    dm_text += f"**Event Time:** {event_dt_display}\n\n"
    dm_text += "**Please Confirm your Attendance by Typing YES or NO.**\n"
    dm_text += f"If there are multiple attendance events, you may answer **YES {event_id}** or **NO {event_id}** corresponding to the Event ID number."
    
    msg = await member.send(dm_text)
    await db.add_dm_message(msg.id, member.id)

class ChannelAttendanceView(View):
    def __init__(self, event_id):
        super().__init__(timeout=None)
        self.event_id = event_id
        
        yes_button = Button(label="YES", style=discord.ButtonStyle.success, custom_id=f"channel_yes_{event_id}")
        yes_button.callback = self.yes_callback
        
        no_button = Button(label="NO", style=discord.ButtonStyle.danger, custom_id=f"channel_no_{event_id}")
        no_button.callback = self.no_callback
        
        self.add_item(yes_button)
        self.add_item(no_button)
    
    async def yes_callback(self, interaction: discord.Interaction):
        await self.record_channel_response(interaction, "YES")
    
    async def no_callback(self, interaction: discord.Interaction):
        await self.record_channel_response(interaction, "NO")
    
    async def record_channel_response(self, interaction, response):
        await interaction.response.defer(ephemeral=True)
        
        try:
            user_id = str(interaction.user.id)
            user_data = await db.get_user(user_id)
            
            if user_data:
                attendances = user_data['attendances']
                current_response = attendances.get(str(self.event_id))
                
                # Toggle logic: if clicking same button, unmark; if clicking different button, switch
                if current_response == response:
                    attendances[str(self.event_id)] = "No Response"
                    final_response = "No Response"
                else:
                    attendances[str(self.event_id)] = response
                    final_response = response
                
                await db.save_user(
                    user_data['discord_id'],
                    user_data['nickname'],
                    user_data['characters'],
                    user_data['combat_power'],
                    attendances,
                    update_timestamp=False
                )
            else:
                # New user - create their record
                member = interaction.guild.get_member(interaction.user.id)
                if member:
                    nickname = member.display_name
                    await db.save_user(
                        user_id,
                        nickname,
                        [],
                        0,
                        {str(self.event_id): response},
                        update_timestamp=False
                    )
                    final_response = response
                else:
                    await interaction.followup.send(f'❌ Error: Could not find member.', ephemeral=True)
                    return
            
            await interaction.followup.send(f'✅ Response recorded: {final_response}', ephemeral=True)
            
            # Update the channel message
            await update_attendance_announcement(interaction.guild, self.event_id)
        except Exception as e:
            print(f'Error recording channel attendance response: {e}')
            try:
                await interaction.followup.send(f'❌ Error recording response. Please try again.', ephemeral=True)
            except:
                pass

class AttendanceResponseView(View):
    def __init__(self, event_id, user_id):
        super().__init__(timeout=86400)
        self.event_id = event_id
        self.user_id = user_id
        
        yes_button = Button(label="YES", style=discord.ButtonStyle.success, custom_id=f"yes_{event_id}_{user_id}")
        yes_button.callback = self.yes_callback
        
        no_button = Button(label="NO", style=discord.ButtonStyle.danger, custom_id=f"no_{event_id}_{user_id}")
        no_button.callback = self.no_callback
        
        self.add_item(yes_button)
        self.add_item(no_button)
    
    async def yes_callback(self, interaction: discord.Interaction):
        await self.record_response(interaction, "YES")
    
    async def no_callback(self, interaction: discord.Interaction):
        await self.record_response(interaction, "NO")
    
    async def record_response(self, interaction, response):
        # CRITICAL: Defer immediately to prevent Discord timeout with high concurrency
        await interaction.response.defer(ephemeral=True)
        
        try:
            user_data = await db.get_user(str(self.user_id))
            
            if user_data:
                attendances = user_data['attendances']
                attendances[str(self.event_id)] = response
                
                await db.save_user(
                    user_data['discord_id'],
                    user_data['nickname'],
                    user_data['characters'],
                    user_data['combat_power'],
                    attendances,
                    update_timestamp=False
                )
            else:
                guild = None
                for g in bot.guilds:
                    member = g.get_member(self.user_id)
                    if member:
                        guild = g
                        break
                
                if guild:
                    member = guild.get_member(self.user_id)
                    if member:
                        nickname = member.display_name
                        
                        await db.save_user(
                            str(self.user_id),
                            nickname,
                            [],
                            0,
                            {str(self.event_id): response},
                            update_timestamp=False
                        )
            
            # Send followup instead of response (already deferred)
            await interaction.followup.send(f'✅ Response recorded: {response}', ephemeral=True)
            
            # Update announcements in background without blocking
            for guild in bot.guilds:
                event = await db.get_attendance_event(self.event_id)
                if event and event.get('channel_message_id'):
                    await update_attendance_announcement(guild, self.event_id)
        except Exception as e:
            print(f'Error recording attendance response: {e}')
            try:
                await interaction.followup.send(f'❌ Error recording response. Please try again.', ephemeral=True)
            except:
                pass

async def post_attendance_announcement(guild, event_id, target_channel=None):
    # Use target_channel if provided, otherwise use default announcement channel
    if target_channel:
        channel = target_channel
    else:
        channel_id = await get_cached_setting('announcement_channel')
        if not channel_id:
            return
        channel = guild.get_channel(int(channel_id))
        if not channel:
            return
    
    event = await db.get_attendance_event(event_id)
    if not event:
        return
    
    message_text = await build_attendance_message(guild, event_id)
    
    try:
        # Send announcement without buttons (users respond via DM)
        msg = await channel.send(message_text)
        await db.update_channel_message_id(event_id, str(msg.id))
        
        if event_id not in countdown_tasks:
            task = asyncio.create_task(countdown_updater(guild, event_id))
            countdown_tasks[event_id] = task
    except Exception as e:
        print(f'Error posting announcement: {e}')

async def build_attendance_message(guild, event_id):
    event = await db.get_attendance_event(event_id)
    if not event:
        return ""
    
    # Check if this is a targeted poll
    metadata = await db.get_event_metadata(event_id)
    is_targeted = metadata and metadata.get('is_targeted', False)
    
    attendance_title = await get_cached_setting('attendance_title') or 'Attendance'
    
    time_str = event['time']
    am_pm = event['am_pm']
    date_str = event['date']
    
    pst_tz = pytz.timezone('US/Pacific')
    est_tz = pytz.timezone('US/Eastern')
    
    if am_pm == 'PM' and not time_str.startswith('12'):
        hour = int(time_str.split(':')[0]) + 12
        minute = time_str.split(':')[1]
        time_24 = f"{hour}:{minute}"
    elif am_pm == 'AM' and time_str.startswith('12'):
        minute = time_str.split(':')[1]
        time_24 = f"00:{minute}"
    else:
        time_24 = time_str
    
    try:
        event_dt = datetime.strptime(f"{date_str} {time_24}", '%m/%d/%Y %H:%M')
        event_dt = pst_tz.localize(event_dt)
        est_dt = event_dt.astimezone(est_tz)
        
        # Get day of week
        day_of_week = event_dt.strftime('%A')
        
        # Format: Monday 10/30/2025 07:00 PM PST | 10:00 PM EST
        event_dt_display = f"{day_of_week} {event_dt.strftime('%m/%d/%Y %I:%M %p')} PST | {est_dt.strftime('%I:%M %p')} EST"
        
        now = datetime.now(pst_tz)
        time_diff = event_dt - now
        
        if time_diff.total_seconds() > 0:
            total_seconds = int(time_diff.total_seconds())
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            minutes = (total_seconds % 3600) // 60
            
            if days > 0:
                countdown_text = f"Event is in: {days}d {hours}h"
            elif hours > 0:
                countdown_text = f"Event is in: {hours}h {minutes}m"
            else:
                countdown_text = f"Event is in: {minutes}m"
        else:
            countdown_text = "Event has started!"
    except Exception:
        event_dt_display = f"{date_str} {time_str} {am_pm} PST"
        countdown_text = ""
    
    users = await db.get_all_users()
    yes_count = 0
    no_count = 0
    yes_users = []
    no_users = []
    
    for user in users:
        response = user['attendances'].get(str(event_id))
        if response == "YES":
            yes_count += 1
            # Collect usernames only for targeted polls
            if is_targeted:
                member = guild.get_member(int(user['discord_id']))
                if member:
                    yes_users.append(member.display_name)
                else:
                    yes_users.append(user['nickname'])
        elif response == "NO":
            no_count += 1
            # Collect usernames only for targeted polls
            if is_targeted:
                member = guild.get_member(int(user['discord_id']))
                if member:
                    no_users.append(member.display_name)
                else:
                    no_users.append(user['nickname'])
    
    message_text = f"**{attendance_title} (check your DM/1:1 to confirm)**\n\n"
    message_text += f"{event['message']}\n\n"
    message_text += f"**Event Time:** {event_dt_display}\n"
    if countdown_text:
        message_text += f"**{countdown_text}**\n\n"
    
    message_text += f"**YES:** {yes_count} | **NO:** {no_count}\n\n"
    
    # Add username lists ONLY for targeted polls
    if is_targeted:
        if yes_users:
            message_text += f"**YES ({yes_count}):** {', '.join(yes_users)}\n\n"
        
        if no_users:
            message_text += f"**NO ({no_count}):** {', '.join(no_users)}\n\n"
    
    message_text += f"Event ID: {event_id}"
    
    return message_text

async def update_attendance_announcement(guild, event_id):
    # Try to get event metadata to find target channel
    metadata = await db.get_event_metadata(event_id)
    
    if metadata and metadata.get('is_targeted'):
        target_channel_id = metadata.get('target_channel_id')
        channel = guild.get_channel(int(target_channel_id)) if target_channel_id else None
    else:
        channel_id = await get_cached_setting('announcement_channel')
        if not channel_id:
            return
        channel = guild.get_channel(int(channel_id))
    
    if not channel:
        return
    
    event = await db.get_attendance_event(event_id)
    if not event or not event.get('channel_message_id'):
        return
    
    try:
        message = await channel.fetch_message(int(event['channel_message_id']))
        message_text = await build_attendance_message(guild, event_id)
        # Update without buttons (users respond via DM only)
        await message.edit(content=message_text)
    except Exception as e:
        print(f'Error updating announcement: {e}')

async def countdown_updater(guild, event_id):
    try:
        while True:
            try:
                event = await db.get_attendance_event(event_id)
                if not event:
                    break
                
                time_str = event['time']
                am_pm = event['am_pm']
                date_str = event['date']
                
                event_tz = pytz.timezone('US/Pacific')
                
                if am_pm == 'PM' and not time_str.startswith('12'):
                    hour = int(time_str.split(':')[0]) + 12
                    minute = time_str.split(':')[1]
                    time_24 = f"{hour}:{minute}"
                elif am_pm == 'AM' and time_str.startswith('12'):
                    minute = time_str.split(':')[1]
                    time_24 = f"00:{minute}"
                else:
                    time_24 = time_str
                
                try:
                    event_dt = datetime.strptime(f"{date_str} {time_24}", '%m/%d/%Y %H:%M')
                    event_dt = event_tz.localize(event_dt)
                    
                    now = datetime.now(event_tz)
                    time_diff = event_dt - now
                    
                    total_minutes = time_diff.total_seconds() / 60
                    
                    if total_minutes <= 0:
                        channel_id = await get_cached_setting('announcement_channel')
                        if channel_id and event.get('channel_message_id'):
                            channel = guild.get_channel(int(channel_id))
                            if channel:
                                try:
                                    message = await channel.fetch_message(int(event['channel_message_id']))
                                    await message.delete()
                                    print(f'Deleted attendance message for event {event_id}')
                                except Exception as e:
                                    print(f'Error deleting attendance message: {e}')
                        
                        print(f'Event {event_id} has ended - message deleted, data preserved in database')
                        break
                    elif total_minutes <= 30:
                        await update_attendance_announcement(guild, event_id)
                        await asyncio.sleep(60)
                    else:
                        await update_attendance_announcement(guild, event_id)
                        await asyncio.sleep(600)
                except Exception:
                    break
            except asyncio.CancelledError:
                print(f'Countdown task for event {event_id} cancelled')
                break
            except Exception as e:
                print(f'Error in countdown updater: {e}')
                break
    finally:
        # Always clean up task from dictionary
        if event_id in countdown_tasks:
            del countdown_tasks[event_id]

@bot.command(name='deletepoll')
@commands.has_permissions(administrator=True)
async def remove_attendance(ctx, event_id: int):
    event = await db.get_attendance_event(event_id)
    if not event:
        await ctx.send(f'❌ Event ID {event_id} not found.')
        return
    
    deleted_message = False
    if event.get('channel_message_id'):
        # Try to get the target channel from event metadata first
        metadata = await db.get_event_metadata(event_id)
        channel_id = None
        
        if metadata and metadata.get('target_channel_id'):
            # This was a targeted poll, use the target channel
            channel_id = metadata['target_channel_id']
        else:
            # This was a default poll, use the default announcement channel
            channel_id = await get_cached_setting('announcement_channel')
        
        if channel_id:
            channel = ctx.guild.get_channel(int(channel_id))
            if channel:
                try:
                    message = await channel.fetch_message(int(event['channel_message_id']))
                    await message.delete()
                    deleted_message = True
                    print(f'Deleted channel message for event {event_id} from channel {channel.name}')
                except discord.NotFound:
                    print(f'Channel message for event {event_id} not found (already deleted)')
                except discord.Forbidden:
                    print(f'Missing permissions to delete message for event {event_id}')
                except Exception as e:
                    print(f'Error deleting channel message for event {event_id}: {e}')
    
    if event_id in countdown_tasks:
        countdown_tasks[event_id].cancel()
        del countdown_tasks[event_id]
    
    # Delete event metadata if it exists
    if metadata:
        await db.delete_event_metadata(event_id)
    
    await db.delete_attendance_event(event_id)
    
    if deleted_message:
        await ctx.send(f'✅ Attendance event {event_id} deleted (channel post removed, countdown stopped, database cleared).')
    else:
        await ctx.send(f'✅ Attendance event {event_id} deleted (countdown stopped, database cleared). Channel post was not found or already removed.')

@bot.command(name='restart')
@commands.has_permissions(administrator=True)
async def restart_system(ctx):
    """Restart system: deletes ALL bot messages from ALL channels, clears all events, and refreshes user nicknames"""
    await ctx.send('🔄 Starting system restart...')
    
    # Step 1: Delete ALL bot messages from ALL channels
    await ctx.send('🧹 Deleting ALL bot messages from ALL channels...')
    total_deleted = 0
    channels_processed = 0
    
    # Get bot user ID
    bot_id = bot.user.id
    
    # Iterate through all text channels in the guild
    for channel in ctx.guild.text_channels:
        try:
            channel_deleted = 0
            
            # Keep purging in batches until no more messages can be bulk deleted
            # Discord's purge can only delete messages < 14 days old
            while True:
                try:
                    deleted = await channel.purge(limit=100, check=lambda m: m.author.id == bot_id)
                    batch_count = len(deleted)
                    channel_deleted += batch_count
                    
                    # If we deleted fewer than 100, we've cleared all recent messages
                    if batch_count < 100:
                        break
                    
                    # Small delay to avoid rate limits
                    await asyncio.sleep(0.5)
                    
                except discord.HTTPException as e:
                    print(f'Purge error in #{channel.name}: {e}')
                    break
            
            # Now delete older messages individually (>14 days old)
            old_messages_deleted = 0
            try:
                async for message in channel.history(limit=500):
                    if message.author.id == bot_id:
                        try:
                            await message.delete()
                            old_messages_deleted += 1
                            channel_deleted += 1
                            await asyncio.sleep(0.2)
                        except discord.HTTPException:
                            pass
            except Exception as e:
                print(f'Error deleting old messages from #{channel.name}: {e}')
            
            if channel_deleted > 0:
                total_deleted += channel_deleted
                channels_processed += 1
                print(f'Deleted {channel_deleted} bot message(s) from #{channel.name} ({old_messages_deleted} old messages)')
        
        except discord.Forbidden:
            print(f'Missing permissions to delete messages in #{channel.name}')
        except Exception as e:
            print(f'Error deleting messages from #{channel.name}: {e}')
    
    await ctx.send(f'✅ Deleted {total_deleted} bot message(s) from {channels_processed} channel(s).')
    
    # Stop all countdown timers
    for task_id, task in list(countdown_tasks.items()):
        task.cancel()
    countdown_tasks.clear()
    
    # Clear all !poll attendance events and user attendances
    await db.clear_all_attendance_events()
    await db.clear_all_user_attendances()
    
    # Delete all event_id_* settings (used by both !poll and !event commands)
    all_settings = await db.get_all_settings()
    event_settings_deleted = 0
    for setting in all_settings:
        key = setting.get('key', '')
        if key.startswith('event_id_'):
            await db.delete_setting(key)
            event_settings_deleted += 1
    
    # Clear all caches
    active_surveys.clear()
    clear_settings_cache()
    cleanup_expired_cache()
    
    await ctx.send(f'✅ Cleared {event_settings_deleted} event metadata, all !poll and !event data deleted, caches cleared.')
    
    # Step 2: Refresh all user nicknames
    await ctx.send('🔄 Refreshing user nicknames...')
    
    all_users = await db.get_all_users()
    updated_count = 0
    skipped_count = 0
    
    for user in all_users:
        discord_id = user['discord_id']
        old_nickname = user['nickname']
        
        # Find member in the guild
        member = ctx.guild.get_member(int(discord_id))
        
        if member:
            current_nickname = member.display_name
            
            # Only update if nickname has changed
            if current_nickname != old_nickname:
                await db.save_user(
                    discord_id,
                    current_nickname,
                    user['characters'],
                    user['combat_power'],
                    user['attendances'],
                    update_timestamp=False
                )
                updated_count += 1
                print(f"Updated nickname: {old_nickname} → {current_nickname}")
        else:
            skipped_count += 1
            print(f"User {discord_id} ({old_nickname}) not found in server")
    
    # Step 3: Report results
    await ctx.send(f'✅ Nickname refresh complete:\n- **Updated:** {updated_count}\n- **Skipped:** {skipped_count} (users not in server)\n\n🎉 System restart complete!')

@bot.command(name='clearID')
@commands.has_permissions(administrator=True)
async def clear_event_id(ctx):
    """Clear ALL event IDs from both !poll and !event - makes all IDs reusable"""
    
    await ctx.send('🧹 Clearing ALL event IDs from !poll and !event...')
    
    deleted_counts = {
        'poll_events': 0,
        'event_messages': 0,
        'countdown_timers': 0,
        'reaction_events': 0,
        'user_records_cleared': 0
    }
    
    # 1. Get all !poll events and delete their messages
    poll_events = await db.get_all_attendance_events()
    channel_id = await get_cached_setting('announcement_channel')
    
    if channel_id:
        channel = ctx.guild.get_channel(int(channel_id))
        if channel:
            for event in poll_events:
                # Delete channel messages
                if event.get('channel_message_id'):
                    try:
                        message = await channel.fetch_message(int(event['channel_message_id']))
                        await message.delete()
                        deleted_counts['event_messages'] += 1
                    except:
                        pass
                
                # Delete event metadata
                event_id = event.get('event_id')
                if event_id:
                    await db.delete_event_metadata(event_id)
    
    deleted_counts['poll_events'] = len(poll_events)
    
    # 2. Cancel all countdown timers
    for task_id, task in list(countdown_tasks.items()):
        task.cancel()
        deleted_counts['countdown_timers'] += 1
    countdown_tasks.clear()
    
    # 3. Delete all !poll attendance events from database
    await db.clear_all_attendance_events()
    
    # 4. Find and delete all !event (reaction-based) events
    # Get all settings to find event_ keys
    all_settings = await db.get_all_settings()
    event_message_ids = []
    event_ids_to_clear = []
    
    for setting in all_settings:
        key = setting.get('key', '')
        # Find all event_{message_id} entries
        if key.startswith('event_') and not key.startswith('event_id_'):
            event_message_ids.append(key)
        # Find all event_id_{id} entries
        elif key.startswith('event_id_'):
            event_id = key.replace('event_id_', '')
            if event_id.isdigit():
                event_ids_to_clear.append(event_id)
    
    # Delete all reaction event data
    for event_key in event_message_ids:
        await db.set_setting(event_key, None)
        deleted_counts['reaction_events'] += 1
    
    for event_id in event_ids_to_clear:
        await db.set_setting(f'event_id_{event_id}', None)
    
    # 5. Clear ALL event attendance data from all users
    users = await db.get_all_users()
    for user in users:
        attendances = user.get('attendances', {})
        if attendances:
            # Clear all attendance records
            await db.save_user(
                user['discord_id'],
                user['nickname'],
                user['characters'],
                user['combat_power'],
                {}  # Empty attendances
            )
            deleted_counts['user_records_cleared'] += 1
    
    # Send summary
    summary = f"""✅ **All Event IDs Cleared Successfully!**
    
**Deleted:**
• {deleted_counts['poll_events']} !poll attendance events
• {deleted_counts['event_messages']} channel messages
• {deleted_counts['countdown_timers']} countdown timers
• {deleted_counts['reaction_events']} !event reaction events
• {deleted_counts['user_records_cleared']} users' attendance records cleared

**Status:** All Event IDs are now reusable. You can start fresh with ID #1."""
    
    await ctx.send(summary)

@bot.command(name='rewardconfig')
@commands.has_permissions(administrator=True)
async def show_reward_config(ctx):
    """Show current reward formula configuration
    
    Usage: !rewardconfig
    """
    # Default values
    defaults = {
        'max_reward': 7000,
        'base_role_reward': 2000,
        'survey_bonus': 1000,
        'survey_penalty_no_submit': 2000,
        'event_portion': 3000,
        'pvp_portion': 1000,
        'survey_penalty_1': 500,
        'survey_penalty_2': 1000
    }
    
    # Get current values from database or use defaults
    config = {}
    for key, default_value in defaults.items():
        value = await db.get_setting(f'reward_{key}')
        config[key] = int(value) if value else default_value
    
    # Format output
    output = f"""**💰 Reward Formula Configuration**

**Current Settings:**
• Max Reward: **{config['max_reward']:,}** reds
• Base Role Reward: **{config['base_role_reward']:,}** reds
• Survey Bonus: **{config['survey_bonus']:,}** reds
• Survey Penalty (no submit): **{config['survey_penalty_no_submit']:,}** reds
• Event Portion (total): **{config['event_portion']:,}** reds
• PvP Portion: **{config['pvp_portion']:,}** reds
• Survey Penalty 1 (>time1): **{config['survey_penalty_1']:,}** reds
• Survey Penalty 2 (>time2): **{config['survey_penalty_2']:,}** reds

**To change a value, use:**
`!setreward <setting> <value>`

**Available settings:**
`max_reward`, `base_role_reward`, `survey_bonus`, `survey_penalty_no_submit`, `event_portion`, `pvp_portion`, `survey_penalty_1`, `survey_penalty_2`

**Examples:**
`!setreward base_role_reward 3000`
`!setreward event_portion 4000`
`!setreward max_reward 10000`"""
    
    await ctx.send(output)

@bot.command(name='setreward')
@commands.has_permissions(administrator=True)
async def set_reward_config(ctx, setting: str = None, value: int = None):
    """Set a reward formula value
    
    Usage: !setreward <setting> <value>
    Example: !setreward base_role_reward 3000
    """
    valid_settings = [
        'max_reward', 'base_role_reward', 'survey_bonus', 
        'survey_penalty_no_submit', 'event_portion', 'pvp_portion',
        'survey_penalty_1', 'survey_penalty_2'
    ]
    
    if not setting or not value:
        await ctx.send('❌ Usage: `!setreward <setting> <value>`\n\nExample: `!setreward base_role_reward 3000`\n\nUse `!rewardconfig` to see all available settings.')
        return
    
    setting = setting.lower()
    
    if setting not in valid_settings:
        await ctx.send(f'❌ Invalid setting: `{setting}`\n\nValid settings: {", ".join(f"`{s}`" for s in valid_settings)}\n\nUse `!rewardconfig` to see current values.')
        return
    
    if value < 0:
        await ctx.send('❌ Value must be 0 or greater.')
        return
    
    # Save to database
    await db.set_setting(f'reward_{setting}', str(value))
    clear_settings_cache()
    
    # Get friendly name
    friendly_names = {
        'max_reward': 'Max Reward',
        'base_role_reward': 'Base Role Reward',
        'survey_bonus': 'Survey Bonus',
        'survey_penalty_no_submit': 'Survey Penalty (no submit)',
        'event_portion': 'Event Portion (total)',
        'pvp_portion': 'PvP Portion',
        'survey_penalty_1': 'Survey Penalty 1 (>time1)',
        'survey_penalty_2': 'Survey Penalty 2 (>time2)'
    }
    
    await ctx.send(f'✅ **{friendly_names[setting]}** set to **{value:,}** reds\n\nUse `!rewardconfig` to see all current values.')

@bot.command(name='reward')
@commands.has_permissions(administrator=True)
async def export_reward_data(ctx):
    """Calculate and export reds for each user based on survey, attendance, and PvP role
    
    Usage: !reward
    CSV format: nickname | Combat Power | Attendances | Reward tally
    """
    
    await ctx.send('📊 Calculating reward distribution...')
    
    import io
    
    # Get configuration settings from database (with defaults)
    MAX_REWARD = int(await db.get_setting('reward_max_reward') or 7000)
    BASE_ROLE_REWARD = int(await db.get_setting('reward_base_role_reward') or 2000)
    SURVEY_BONUS = int(await db.get_setting('reward_survey_bonus') or 1000)
    SURVEY_PENALTY_NO_SUBMIT = int(await db.get_setting('reward_survey_penalty_no_submit') or 2000)
    EVENT_PORTION = int(await db.get_setting('reward_event_portion') or 3000)
    PVP_PORTION = int(await db.get_setting('reward_pvp_portion') or 1000)
    SURVEY_PENALTY_1 = int(await db.get_setting('reward_survey_penalty_1') or 500)
    SURVEY_PENALTY_2 = int(await db.get_setting('reward_survey_penalty_2') or 1000)
    
    # Get tracksurvey thresholds
    warning_seconds = await db.get_setting('track_warning_seconds')
    poop_seconds = await db.get_setting('track_poop_seconds')
    
    if not warning_seconds or not poop_seconds:
        await ctx.send('⚠️ Survey tracking not configured. Use `!tracksurvey <time1> <time2>` first.\nExample: `!tracksurvey 15D 30D`')
        return
    
    time1 = int(warning_seconds)
    time2 = int(poop_seconds)
    
    # Get member role (from !config)
    member_role_id = await db.get_setting('survey_role')
    if not member_role_id:
        await ctx.send('❌ Guild role not set. Use `!config` to configure the guild role first.')
        return
    
    member_role = ctx.guild.get_role(int(member_role_id))
    if not member_role:
        await ctx.send(f'❌ Guild role ID {member_role_id} not found in server.')
        return
    
    await ctx.send(f'✅ Guild Role: **{member_role.name}**')
    
    # Get PvP role
    pvp_role_id = await db.get_setting('pvp_role')
    pvp_role = None
    if pvp_role_id:
        pvp_role = ctx.guild.get_role(int(pvp_role_id))
        if pvp_role:
            await ctx.send(f'✅ PvP Role found: **{pvp_role.name}**')
        else:
            await ctx.send(f'⚠️ PvP Role ID {pvp_role_id} not found in server. Run `!config` to set it.')
    
    # Get all users from database
    users = await db.get_all_users()
    users_dict = {user['discord_id']: user for user in users}
    
    # Get all events (both !poll and !event)
    poll_events = await db.get_all_attendance_events()
    
    # Get reaction events from settings
    all_settings = await db.get_all_settings()
    event_reactions = {}
    for setting in all_settings:
        key = setting.get('key', '')
        if key.startswith('event_id_'):
            event_id = key.replace('event_id_', '')
            if event_id.isdigit():
                event_reactions[event_id] = True
    
    # Total number of events
    total_events = len(poll_events) + len(event_reactions)
    
    if total_events == 0:
        await ctx.send('ℹ️ No events found. Rewards will be calculated from base role, survey, and PvP role only.')
    
    # Calculate event share per event
    event_share = EVENT_PORTION / total_events if total_events > 0 else 0
    
    # Current time for survey age calculation
    current_time = datetime.utcnow()
    
    # Get all members with the !setrole role
    members_with_role = [member for member in ctx.guild.members if member_role in member.roles]
    
    if not members_with_role:
        await ctx.send('❌ No members found with the configured role.')
        return
    
    # Calculate rewards for each member with the role
    user_rewards = []
    pvp_bonus_count = 0  # Track how many users get PvP bonus
    
    for member in members_with_role:
        discord_id = str(member.id)
        nickname = member.display_name
        
        # Get user data from database (if exists)
        user = users_dict.get(discord_id, {})
        combat_power = user.get('combat_power', 0)
        attendances = user.get('attendances', {})
        survey_timestamp_str = user.get('survey_timestamp', None)
        
        # Step 1: Base Role Reward (always get 2,000 for having the role)
        base_reward = BASE_ROLE_REWARD
        
        # Step 2: Survey Bonus/Penalty
        survey_reward = 0
        penalty_applied = ""
        has_survey = False
        
        if survey_timestamp_str and survey_timestamp_str != 'N/A':
            # User completed survey - give bonus
            has_survey = True
            survey_reward = SURVEY_BONUS
            
            # Calculate survey age
            try:
                # Handle various timestamp formats
                clean_timestamp = survey_timestamp_str
                # Remove trailing Z if it exists along with timezone info
                if '+00:00Z' in clean_timestamp:
                    clean_timestamp = clean_timestamp.replace('+00:00Z', '+00:00')
                elif survey_timestamp_str.endswith('Z'):
                    clean_timestamp = survey_timestamp_str.replace('Z', '+00:00')
                
                survey_time = datetime.fromisoformat(clean_timestamp)
                
                # Remove timezone info for comparison
                if survey_time.tzinfo:
                    survey_time = survey_time.replace(tzinfo=None)
                
                survey_age_seconds = (current_time - survey_time).total_seconds()
                
                # Apply penalties based on survey age
                if survey_age_seconds > time2:
                    # Survey too old - treat as no survey (remove all survey value)
                    survey_reward = -SURVEY_PENALTY_NO_SUBMIT
                    penalty_applied = f" (survey expired, {int(survey_age_seconds/86400)}d old)"
                elif survey_age_seconds > time1:
                    survey_reward -= SURVEY_PENALTY_1
                    penalty_applied = f" (-{SURVEY_PENALTY_1} penalty, {int(survey_age_seconds/86400)}d old)"
            except Exception as e:
                # If parsing fails, give full survey bonus but log the error
                print(f"Warning: Failed to parse survey timestamp for {nickname}: {survey_timestamp_str}, error: {e}")
                survey_reward = SURVEY_BONUS
        else:
            # No survey completed - apply penalty
            survey_reward = -SURVEY_PENALTY_NO_SUBMIT
            penalty_applied = " (no survey penalty)"
        
        # Step 3: Event/Attendance Reward
        event_reward = 0
        attendance_count = 0
        
        # Count events user participated in
        for event_id in list(poll_events) + list(event_reactions.keys()):
            event_id_str = str(event_id) if isinstance(event_id, dict) else str(event_id)
            if isinstance(event_id, dict):
                event_id_str = str(event_id['event_id'])
            
            response = attendances.get(event_id_str, 'NO RESPONSE')
            
            if response == 'YES':
                # Full event share for YES
                event_reward += event_share
                attendance_count += 1
            elif response == 'NO':
                # 50% event share for NO
                event_reward += event_share * 0.5
            # 'NO RESPONSE' gets 0 reward (didn't answer yet)
        
        # Step 4: PvP Role Bonus
        pvp_reward = 0
        if pvp_role and pvp_role in member.roles:
            pvp_reward = PVP_PORTION
            pvp_bonus_count += 1
        
        # Step 5: Total Reward (capped at MAX_REWARD, but can be 0 or negative)
        total_reward = base_reward + survey_reward + event_reward + pvp_reward
        total_reward = min(total_reward, MAX_REWARD)
        total_reward = max(0, total_reward)  # Floor at 0
        total_reward = int(total_reward)  # Round to integer
        
        user_rewards.append({
            'nickname': nickname,
            'combat_power': combat_power,
            'attendances': attendance_count,
            'base_reward': int(base_reward),
            'survey_reward': int(survey_reward),
            'event_reward': int(event_reward),
            'pvp_reward': int(pvp_reward),
            'penalty_info': penalty_applied,
            'reward_tally': total_reward
        })
    
    # Sort by reward tally (highest first)
    user_rewards.sort(key=lambda x: -x['reward_tally'])
    
    # Send summary info
    await ctx.send(f'📊 **Members with role:** {len(members_with_role)} | **PvP Bonus:** {pvp_bonus_count} users')
    
    # Format message for channel display
    message = "**REWARD DISTRIBUTION**\n\n"
    message += "```\n"
    message += f"{'Member':<20} | {'Reward':>12}\n"
    message += "-" * 36 + "\n"
    
    for user_reward in user_rewards:
        nickname = user_reward['nickname'][:19]  # Truncate if too long
        reward = user_reward['reward_tally']
        message += f"{nickname:<20} | {reward:>12}\n"
    
    message += "```"
    
    # If message is too long for Discord (2000 char limit), split into multiple messages
    if len(message) > 1950:
        # Split into chunks
        lines = message.split('\n')
        current_msg = "**REWARD DISTRIBUTION**\n\n```\n"
        current_msg += f"{'Nickname':<20} | {'Reward Tally':>12}\n"
        current_msg += "-" * 36 + "\n"
        
        for line in lines[4:]:  # Skip header lines
            if line == "```":
                current_msg += "```"
                await ctx.send(current_msg)
                break
            
            if len(current_msg) + len(line) + 10 > 1950:
                current_msg += "```"
                await ctx.send(current_msg)
                current_msg = "```\n"
            
            current_msg += line + "\n"
    else:
        await ctx.send(message)
# Event command - Reaction-based attendance
@bot.command(name='event')
@commands.has_permissions(administrator=True)
async def create_event(ctx):
    """Create a reaction-based attendance event"""
    channel_id = await get_cached_setting('announcement_channel')
    if not channel_id:
        await ctx.send('Please set an announcement channel first using !setchannel')
        return
    
    modal = EventModal()
    await ctx.send('Please fill out the event form:', view=EventButtonView(modal))

class EventButtonView(View):
    def __init__(self, modal):
        super().__init__(timeout=300)
        self.modal = modal
        button = Button(label="Create Event", style=discord.ButtonStyle.primary)
        button.callback = self.open_modal
        self.add_item(button)
    
    async def open_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(self.modal)

class EventModal(Modal, title='Create Event'):
    event_message = TextInput(label='Event Message', style=discord.TextStyle.paragraph, required=True)
    datetime_input = TextInput(label='Event Date & Time', placeholder='10/30/2025 07:00 PM', required=True)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        datetime_str = self.datetime_input.value.strip()
        
        # Parse datetime
        parts = datetime_str.split()
        if len(parts) != 3:
            await interaction.followup.send(
                f'❌ Invalid format. You entered: "{datetime_str}"\n'
                f'✅ Required format: MM/DD/YYYY HH:MM AM/PM\n'
                f'📝 Example: 10/30/2025 07:00 PM',
                ephemeral=True
            )
            return
        
        date_str = parts[0]
        time_str = parts[1]
        am_pm_str = parts[2].upper()
        
        # Validate date
        try:
            datetime.strptime(date_str, '%m/%d/%Y')
        except ValueError:
            await interaction.followup.send(
                f'❌ Invalid date: "{date_str}"\n'
                f'✅ Required format: MM/DD/YYYY\n'
                f'📝 Example: 10/30/2025',
                ephemeral=True
            )
            return
        
        # Validate time
        try:
            if ':' not in time_str:
                raise ValueError("Missing colon")
            hour, minute = map(int, time_str.split(':'))
            if not (1 <= hour <= 12 and 0 <= minute <= 59):
                raise ValueError("Invalid time range")
        except ValueError:
            await interaction.followup.send(
                f'❌ Invalid time: "{time_str}"\n'
                f'✅ Required format: HH:MM (1-12 hours, 00-59 minutes)\n'
                f'📝 Example: 07:00 or 11:30',
                ephemeral=True
            )
            return
        
        # Validate AM/PM
        if am_pm_str not in ['AM', 'PM']:
            await interaction.followup.send(
                f'❌ Invalid AM/PM: "{am_pm_str}"\n'
                f'✅ Must be either AM or PM\n'
                f'📝 Example: 07:00 PM',
                ephemeral=True
            )
            return
        
        # Convert to 24-hour format for datetime parsing
        if am_pm_str == 'PM' and not time_str.startswith('12'):
            hour = int(time_str.split(':')[0]) + 12
            minute = time_str.split(':')[1]
            time_24 = f"{hour}:{minute}"
        elif am_pm_str == 'AM' and time_str.startswith('12'):
            minute = time_str.split(':')[1]
            time_24 = f"00:{minute}"
        else:
            time_24 = time_str
        
        # Create datetime objects for PST and EST
        pst_tz = pytz.timezone('US/Pacific')
        est_tz = pytz.timezone('US/Eastern')
        
        event_dt = datetime.strptime(f"{date_str} {time_24}", '%m/%d/%Y %H:%M')
        event_dt_pst = pst_tz.localize(event_dt)
        event_dt_est = event_dt_pst.astimezone(est_tz)
        
        pst_display = event_dt_pst.strftime('%m/%d/%Y %I:%M %p PST')
        est_display = event_dt_est.strftime('%m/%d/%Y %I:%M %p EST')
        
        # Get the configured channel
        channel_id = await db.get_setting('announcement_channel')
        if not channel_id:
            await interaction.followup.send('No announcement channel configured!', ephemeral=True)
            return
        
        channel = interaction.guild.get_channel(int(channel_id))
        if not channel:
            await interaction.followup.send('Configured channel not found!', ephemeral=True)
            return
        
        # Build the event message with countdown
        message_content = await build_event_message(
            self.event_message.value,
            date_str,
            time_str,
            am_pm_str,
            {},
            {}
        )
        
        # Generate Event ID
        event_id = await db.get_next_event_id()
        
        # Build the event message with Event ID
        message_content = await build_event_message(
            self.event_message.value,
            date_str,
            time_str,
            am_pm_str,
            {},
            {},
            event_id
        )
        
        # Post the message
        message = await channel.send(message_content)
        
        # Add reactions
        await message.add_reaction('✅')
        await message.add_reaction('❌')
        
        # Store event data in database
        event_data = {
            'event_id': event_id,
            'message_id': str(message.id),
            'channel_id': str(channel.id),
            'event_message': self.event_message.value,
            'date': date_str,
            'time': time_str,
            'am_pm': am_pm_str,
            'yes_reactions': {},
            'no_reactions': {}
        }
        await db.set_setting(f'event_{message.id}', json.dumps(event_data))
        await db.set_setting(f'event_id_{event_id}', str(message.id))
        
        # Start countdown updater
        task = asyncio.create_task(event_countdown_updater(interaction.guild, str(message.id)))
        countdown_tasks[f'event_{message.id}'] = task
        
        await interaction.followup.send(f'✅ Event created in {channel.mention} with Event ID: {event_id}!', ephemeral=True)

@bot.command(name='deleteevent')
@commands.has_permissions(administrator=True)
async def delete_event(ctx, event_id: int):
    """Delete a reaction-based event by Event ID"""
    # Get message ID from event ID
    message_id = await db.get_setting(f'event_id_{event_id}')
    if not message_id:
        await ctx.send(f'❌ Event ID {event_id} not found.')
        return
    
    # Get event data
    event_data_json = await db.get_setting(f'event_{message_id}')
    if not event_data_json:
        await ctx.send(f'❌ Event data not found for Event ID {event_id}.')
        return
    
    event_data = json.loads(event_data_json)
    channel_id = event_data.get('channel_id')
    
    # Delete the Discord message
    deleted_message = False
    if channel_id:
        channel = ctx.guild.get_channel(int(channel_id))
        if channel:
            try:
                message = await channel.fetch_message(int(message_id))
                await message.delete()
                deleted_message = True
                print(f'Deleted event message {message_id} for Event ID {event_id}')
            except discord.NotFound:
                print(f'Event message {message_id} not found (already deleted)')
            except discord.Forbidden:
                print(f'Missing permissions to delete message {message_id}')
            except Exception as e:
                print(f'Error deleting event message: {e}')
    
    # Cancel countdown task if it exists
    if f'event_{message_id}' in countdown_tasks:
        countdown_tasks[f'event_{message_id}'].cancel()
        del countdown_tasks[f'event_{message_id}']
    
    # Delete from database
    await db.set_setting(f'event_{message_id}', None)
    await db.set_setting(f'event_id_{event_id}', None)
    
    if deleted_message:
        await ctx.send(f'✅ Event {event_id} deleted (message removed, countdown stopped, database cleared).')
    else:
        await ctx.send(f'✅ Event {event_id} deleted from database (message was not found or already removed).')

async def build_event_message(event_msg, date_str, time_str, am_pm_str, yes_reactions, no_reactions, event_id=None):
    """Build the formatted event message with countdown"""
    lines = ["Attendance"]
    
    # Build comma-separated lists
    yes_list = list(yes_reactions.values())
    no_list = list(no_reactions.values())
    
    yes_names = ", ".join(yes_list) if yes_list else ""
    no_names = ", ".join(no_list) if no_list else ""
    
    lines.append(f"Yes: {yes_names}")
    lines.append("")
    lines.append(f"No: {no_names}")
    lines.append("")
    
    # Calculate PST and EST times
    if am_pm_str == 'PM' and not time_str.startswith('12'):
        hour = int(time_str.split(':')[0]) + 12
        minute = time_str.split(':')[1]
        time_24 = f"{hour}:{minute}"
    elif am_pm_str == 'AM' and time_str.startswith('12'):
        minute = time_str.split(':')[1]
        time_24 = f"00:{minute}"
    else:
        time_24 = time_str
    
    pst_tz = pytz.timezone('US/Pacific')
    est_tz = pytz.timezone('US/Eastern')
    
    event_dt = datetime.strptime(f"{date_str} {time_24}", '%m/%d/%Y %H:%M')
    event_dt_pst = pst_tz.localize(event_dt)
    event_dt_est = event_dt_pst.astimezone(est_tz)
    
    pst_display = event_dt_pst.strftime('%m/%d/%Y %I:%M %p PST')
    est_display = event_dt_est.strftime('%I:%M %p EST')  # Only time for EST
    
    # Calculate countdown
    now = datetime.now(pst_tz)
    time_diff = event_dt_pst - now
    total_minutes = time_diff.total_seconds() / 60
    
    countdown_text = ""
    if total_minutes > 0:
        days = int(total_minutes // 1440)
        hours = int((total_minutes % 1440) // 60)
        minutes = int(total_minutes % 60)
        
        if days > 0:
            countdown_text = f"{days}d {hours}h"
        elif hours > 0:
            countdown_text = f"{hours}h {minutes}m"
        else:
            countdown_text = f"{minutes}m"
    
    lines.append(f"Event: {event_msg}")
    lines.append("")  # Blank line after event message
    if countdown_text:
        event_id_text = f"  |  Event ID {event_id}" if event_id else ""
        lines.append(f"When: {pst_display} | {est_display}")
        lines.append(f"Event is in: {countdown_text}{event_id_text}")
    else:
        event_id_text = f"  |  Event ID {event_id}" if event_id else ""
        lines.append(f"When: {pst_display} | {est_display}{event_id_text}")
    
    return "\n".join(lines)

@bot.event
async def on_raw_reaction_add(payload):
    """Handle reaction additions for event attendance"""
    if payload.user_id == bot.user.id:
        return
    
    # Check if this is an event message
    event_data_json = await db.get_setting(f'event_{payload.message_id}')
    if not event_data_json:
        return
    
    event_data = json.loads(event_data_json)
    
    # Get the member's nickname
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    
    member = guild.get_member(payload.user_id)
    if not member:
        return
    
    nickname = member.display_name
    
    # Update reactions
    yes_reactions = event_data.get('yes_reactions', {})
    no_reactions = event_data.get('no_reactions', {})
    
    response = None
    if str(payload.emoji) == '✅':
        yes_reactions[str(payload.user_id)] = nickname
        no_reactions.pop(str(payload.user_id), None)
        response = "YES"
    elif str(payload.emoji) == '❌':
        no_reactions[str(payload.user_id)] = nickname
        yes_reactions.pop(str(payload.user_id), None)
        response = "NO"
    else:
        return
    
    event_data['yes_reactions'] = yes_reactions
    event_data['no_reactions'] = no_reactions
    await db.set_setting(f'event_{payload.message_id}', json.dumps(event_data))
    
    # Also save to user's attendances field for consistent tracking
    event_id = event_data.get('event_id')
    if event_id and response:
        user_data = await db.get_user(str(payload.user_id))
        if user_data:
            attendances = user_data['attendances']
            attendances[str(event_id)] = response
            await db.save_user(
                user_data['discord_id'],
                user_data['nickname'],
                user_data['characters'],
                user_data['combat_power'],
                attendances,
                update_timestamp=False
            )
        else:
            await db.save_user(
                str(payload.user_id),
                nickname,
                [],
                0,
                {str(event_id): response},
                update_timestamp=False
            )
    
    # Update the message
    channel = guild.get_channel(payload.channel_id)
    if not channel:
        return
    
    try:
        message = await channel.fetch_message(payload.message_id)
        new_content = await build_event_message(
            event_data['event_message'],
            event_data['date'],
            event_data['time'],
            event_data['am_pm'],
            yes_reactions,
            no_reactions,
            event_data.get('event_id')
        )
        await message.edit(content=new_content)
    except Exception as e:
        print(f'Error updating event message: {e}')

@bot.event
async def on_raw_reaction_remove(payload):
    """Handle reaction removals for event attendance"""
    if payload.user_id == bot.user.id:
        return
    
    # Check if this is an event message
    event_data_json = await db.get_setting(f'event_{payload.message_id}')
    if not event_data_json:
        return
    
    event_data = json.loads(event_data_json)
    
    # Update reactions
    yes_reactions = event_data.get('yes_reactions', {})
    no_reactions = event_data.get('no_reactions', {})
    
    if str(payload.emoji) == '✅':
        yes_reactions.pop(str(payload.user_id), None)
    elif str(payload.emoji) == '❌':
        no_reactions.pop(str(payload.user_id), None)
    else:
        return
    
    event_data['yes_reactions'] = yes_reactions
    event_data['no_reactions'] = no_reactions
    await db.set_setting(f'event_{payload.message_id}', json.dumps(event_data))
    
    # Also update user's attendances field to "No Response" when reaction removed
    event_id = event_data.get('event_id')
    if event_id:
        user_data = await db.get_user(str(payload.user_id))
        if user_data:
            attendances = user_data['attendances']
            attendances[str(event_id)] = "No Response"
            await db.save_user(
                user_data['discord_id'],
                user_data['nickname'],
                user_data['characters'],
                user_data['combat_power'],
                attendances,
                update_timestamp=False
            )
    
    # Update the message
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    
    channel = guild.get_channel(payload.channel_id)
    if not channel:
        return
    
    try:
        message = await channel.fetch_message(payload.message_id)
        new_content = await build_event_message(
            event_data['event_message'],
            event_data['date'],
            event_data['time'],
            event_data['am_pm'],
            yes_reactions,
            no_reactions,
            event_data.get('event_id')
        )
        await message.edit(content=new_content)
    except Exception as e:
        print(f'Error updating event message: {e}')

async def event_countdown_updater(guild, message_id):
    """Update event countdown every minute or 10 minutes"""
    try:
        while True:
            try:
                event_data_json = await db.get_setting(f'event_{message_id}')
                if not event_data_json:
                    break
                
                event_data = json.loads(event_data_json)
                
                date_str = event_data['date']
                time_str = event_data['time']
                am_pm_str = event_data['am_pm']
                
                # Convert to 24-hour format
                if am_pm_str == 'PM' and not time_str.startswith('12'):
                    hour = int(time_str.split(':')[0]) + 12
                    minute = time_str.split(':')[1]
                    time_24 = f"{hour}:{minute}"
                elif am_pm_str == 'AM' and time_str.startswith('12'):
                    minute = time_str.split(':')[1]
                    time_24 = f"00:{minute}"
                else:
                    time_24 = time_str
                
                pst_tz = pytz.timezone('US/Pacific')
                event_dt = datetime.strptime(f"{date_str} {time_24}", '%m/%d/%Y %H:%M')
                event_dt_pst = pst_tz.localize(event_dt)
                
                now = datetime.now(pst_tz)
                time_diff = event_dt_pst - now
                total_minutes = time_diff.total_seconds() / 60
                
                if total_minutes <= 0:
                    # Event has passed, delete message only
                    channel_id = event_data.get('channel_id')
                    event_id = event_data.get('event_id')
                    
                    if channel_id:
                        channel = guild.get_channel(int(channel_id))
                        if channel:
                            try:
                                message = await channel.fetch_message(int(message_id))
                                await message.delete()
                                print(f'Auto-deleted expired event {event_id} (message {message_id}) - data preserved in database')
                            except Exception as e:
                                print(f'Error deleting expired event message: {e}')
                    
                    # Data kept in database for historical record
                    break
                
                # Get the channel and update message
                channel_id = event_data.get('channel_id')
                if channel_id:
                    channel = guild.get_channel(int(channel_id))
                    if channel:
                        try:
                            message = await channel.fetch_message(int(message_id))
                            new_content = await build_event_message(
                                event_data['event_message'],
                                date_str,
                                time_str,
                                am_pm_str,
                                event_data.get('yes_reactions', {}),
                                event_data.get('no_reactions', {}),
                                event_data.get('event_id')
                            )
                            await message.edit(content=new_content)
                        except Exception as e:
                            print(f'Error updating event countdown: {e}')
                
                # Update interval: every minute if ≤30 minutes, else every 10 minutes
                if total_minutes <= 30:
                    await asyncio.sleep(60)
                else:
                    await asyncio.sleep(600)
                
            except asyncio.CancelledError:
                print(f'Event countdown task for {message_id} cancelled')
                break
            except Exception as e:
                print(f'Error in event countdown updater: {e}')
                break
    finally:
        # Clean up task from dictionary
        if f'event_{message_id}' in countdown_tasks:
            del countdown_tasks[f'event_{message_id}']

@bot.command(name='exportsurvey')
@commands.has_permissions(administrator=True)
async def export_survey(ctx):
    users = await db.get_all_users()
    
    if not users:
        await ctx.send('No survey data to export.')
        return
    
    filename = f'survey_export_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        slot_count = max(len(user['characters']) for user in users) if users else 1
        
        header = ['Nickname']
        for i in range(slot_count):
            header.append(f'Character {i+1}')
        header.append('Combat Power')
        writer.writerow(header)
        
        for user in users:
            # Get current server nickname
            member = ctx.guild.get_member(int(user['discord_id']))
            current_nickname = member.display_name if member else user['nickname']
            
            row = [current_nickname]
            
            for i in range(slot_count):
                if i < len(user['characters']):
                    char = user['characters'][i]
                    if char.get('subclass'):
                        char_str = f"{char['main']} > {char['subclass']}"
                    else:
                        char_str = char['main']
                    row.append(char_str)
                else:
                    row.append('')
            
            row.append(f"{user['combat_power']:,}")
            writer.writerow(row)
    
    await ctx.send(file=discord.File(filename))
    os.remove(filename)

@bot.command(name='exportpoll')
@commands.has_permissions(administrator=True)
async def export_attendance(ctx):
    users = await db.get_all_users()
    events = await db.get_all_attendance_events()
    
    if not events:
        await ctx.send('No attendance data to export.')
        return
    
    filename = f'attendance_export_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        attendance_title = await get_cached_setting('attendance_title') or 'Event'
        
        writer.writerow(['Event ID', 'Title', 'Nickname', 'Response', 'Event Time'])
        
        for event in events:
            event_id = event['event_id']
            event_time = f"{event['date']} {event['time']} {event['am_pm']} PST"
            
            for user in users:
                # Get current server nickname
                member = ctx.guild.get_member(int(user['discord_id']))
                current_nickname = (member.nick if member and member.nick else user['nickname']) if member else user['nickname']
                
                response = user['attendances'].get(str(event_id), 'No Response')
                writer.writerow([event_id, attendance_title, current_nickname, response, event_time])
    
    await ctx.send(file=discord.File(filename))
    os.remove(filename)

@bot.command(name='exportdatabase')
@commands.has_permissions(administrator=True)
async def export_database(ctx):
    users = await db.get_all_users()
    
    guildname = await get_cached_setting('guildname')
    attendance_title = await get_cached_setting('attendance_title')
    dmtitle = await get_cached_setting('dmtitle')
    
    export_data = {
        'guild_name': guildname,
        'attendance_title': attendance_title,
        'dmtitle': dmtitle,
        'users': users
    }
    
    filename = f'database_export_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.json'
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)
    
    await ctx.send(file=discord.File(filename))
    os.remove(filename)

@bot.command(name='deleteuser')
@commands.has_permissions(administrator=True)
async def delete_user(ctx, *, nickname: str):
    """Delete a user from the database by their nickname"""
    # Find user by nickname
    users = await db.get_all_users()
    user_to_delete = None
    
    for user in users:
        if user['nickname'].lower() == nickname.lower():
            user_to_delete = user
            break
    
    if not user_to_delete:
        await ctx.send(f'❌ User with nickname "{nickname}" not found in the database.')
        return
    
    # Delete the user
    await db.delete_user(user_to_delete['discord_id'])
    await ctx.send(f'✅ User "{user_to_delete["nickname"]}" has been deleted from the database.')

@bot.command(name='msg')
@commands.has_permissions(administrator=True)
async def message_all(ctx, *, text: str):
    # Check if a channel is mentioned
    mentioned_channels = ctx.message.channel_mentions
    
    if mentioned_channels:
        # Send to the mentioned channel(s)
        target_channel = mentioned_channels[0]
        # Remove channel mention from text
        clean_text = text
        for channel in mentioned_channels:
            clean_text = clean_text.replace(f'<#{channel.id}>', '')
        clean_text = clean_text.strip()
        
        if not clean_text:
            await ctx.send('Please provide a message to send to the channel.')
            return
        
        try:
            await target_channel.send(clean_text)
            await ctx.send(f'✅ Message sent to {target_channel.mention}')
        except discord.Forbidden:
            await ctx.send(f'❌ I do not have permission to send messages in {target_channel.mention}')
        except Exception as e:
            await ctx.send(f'❌ Failed to send message: {str(e)}')
        return
    
    # Original DM functionality
    role_id = await db.get_setting('survey_role')
    if not role_id:
        await ctx.send('Please set a role first using !setrole')
        return
    
    guild = ctx.guild
    role = guild.get_role(int(role_id))
    if not role:
        await ctx.send('Configured role not found.')
        return
    
    # Check if specific users are mentioned
    mentioned_users = ctx.message.mentions
    
    # Filter out bots from mentions
    target_members = []
    if mentioned_users:
        # Send only to mentioned users (excluding bots)
        target_members = [m for m in mentioned_users if not m.bot]
        # Remove mentions from the message text
        clean_text = text
        for mention in ctx.message.mentions:
            clean_text = clean_text.replace(f'<@{mention.id}>', '').replace(f'<@!{mention.id}>', '')
        clean_text = clean_text.strip()
        text = clean_text
    else:
        # Send to all role members (excluding bots)
        target_members = [m for m in role.members if not m.bot]
    
    if not target_members:
        await ctx.send('No valid members to send message to.')
        return
    
    sent_count = 0
    for member in target_members:
        try:
            msg = await member.send(text)
            await db.add_dm_message(msg.id, member.id)
            sent_count += 1
            await asyncio.sleep(0.5)
        except:
            pass
    
    if mentioned_users:
        await ctx.send(f'✅ Message sent to {sent_count} mentioned member(s).')
    else:
        await ctx.send(f'✅ Message sent to {sent_count} role member(s).')

@bot.command(name='editdatabase')
@commands.has_permissions(administrator=True)
async def edit_database(ctx, user: discord.Member, data_type: str, slot: str, field: str, *, value: str):
    if data_type.lower() != 'character':
        await ctx.send('Only "character" editing is supported currently.')
        return
    
    if field.lower() not in ['main', 'subclass']:
        await ctx.send('Field must be "main" or "subclass"')
        return
    
    try:
        slot_index = int(slot) - 1
    except:
        await ctx.send('Slot must be a number (1, 2, 3, etc.)')
        return
    
    user_data = await db.get_user(str(user.id))
    if not user_data:
        await ctx.send(f'No data found for {user.mention}')
        return
    
    if slot_index < 0 or slot_index >= len(user_data['characters']):
        await ctx.send(f'Invalid slot number. User has {len(user_data["characters"])} slots.')
        return
    
    user_data['characters'][slot_index][field.lower()] = value
    
    await db.save_user(
        user_data['discord_id'],
        user_data['nickname'],
        user_data['characters'],
        user_data['combat_power'],
        user_data['attendances']
    )
    
    await ctx.send(f'Updated {user.mention} slot {slot} {field} to: {value}')
    
    # Update leaderboards
    await update_all_leaderboards()

@bot.command(name='tracksurvey')
@commands.has_permissions(administrator=True)
async def track_survey(ctx, warning_time: str = None, poop_time: str = None):
    """Track survey age and auto-update leaderboards with emojis"""
    global leaderboard_tracker_task
    
    # If no arguments, show current status
    if not warning_time or not poop_time:
        warning_seconds = await db.get_setting('track_warning_seconds')
        poop_seconds = await db.get_setting('track_poop_seconds')
        
        if warning_seconds and poop_seconds:
            def format_time(seconds):
                seconds = int(seconds)
                if seconds >= 86400:
                    return f"{seconds // 86400}D"
                elif seconds >= 3600:
                    return f"{seconds // 3600}H"
                else:
                    return f"{seconds // 60}M"
            
            status = f"**Survey Tracking Status: ENABLED**\n"
            status += f"⚠️ Warning after: {format_time(warning_seconds)}\n"
            status += f"💩 Poop after: {format_time(poop_seconds)}\n"
            status += f"Auto-update: Every 24 hours (use !update to refresh manually)\n\n"
            status += f"Usage: `!tracksurvey <warning_time> <poop_time>`\n"
            status += f"Example: `!tracksurvey 15D 30D` or `!tracksurvey 2M 5M` for testing"
            await ctx.send(status)
        else:
            await ctx.send("**Survey Tracking: DISABLED**\n\nUsage: `!tracksurvey <warning_time> <poop_time>`\nExample: `!tracksurvey 15D 30D`\nFormats: M=minutes, H=hours, D=days")
        return
    
    # Parse time strings
    warning_seconds = parse_time_string(warning_time)
    poop_seconds = parse_time_string(poop_time)
    
    if warning_seconds is None:
        await ctx.send(f'Invalid warning time format: {warning_time}. Use format like 15D, 2H, or 30M')
        return
    
    if poop_seconds is None:
        await ctx.send(f'Invalid poop time format: {poop_time}. Use format like 30D, 4H, or 60M')
        return
    
    if warning_seconds >= poop_seconds:
        await ctx.send('Warning time must be less than poop time')
        return
    
    # Save settings
    await db.set_setting('track_warning_seconds', str(warning_seconds))
    await db.set_setting('track_poop_seconds', str(poop_seconds))
    await db.set_setting('track_update_interval', str(warning_seconds))
    clear_settings_cache()
    
    # Restart the tracker task
    if leaderboard_tracker_task and not leaderboard_tracker_task.done():
        leaderboard_tracker_task.cancel()
        try:
            await leaderboard_tracker_task
        except asyncio.CancelledError:
            pass
    
    leaderboard_tracker_task = asyncio.create_task(leaderboard_update_loop())
    
    # Format times for display
    def format_time(seconds):
        if seconds >= 86400:
            return f"{seconds // 86400}D"
        elif seconds >= 3600:
            return f"{seconds // 3600}H"
        else:
            return f"{seconds // 60}M"
    
    await ctx.send(f'✅ Survey tracking enabled:\n⚠️ Warning after: {format_time(warning_seconds)}\n💩 Poop after: {format_time(poop_seconds)}\nLeaderboards will auto-update every 24 hours (use !update to refresh manually)')
    
    # Immediately update all leaderboards
    await update_all_leaderboards()
    print(f"Tracking configured: Warning={warning_seconds}s, Poop={poop_seconds}s")

@bot.command(name='leaderboard')
@commands.has_permissions(administrator=True)
async def list_members(ctx, channel: discord.TextChannel):
    """Create a live-updating leaderboard in the specified channel"""
    try:
        # Format the initial leaderboard message
        message_content = await _format_leaderboard()
        
        # Send the message to the channel
        message = await channel.send(message_content)
        
        # Save the leaderboard message to database
        await db.save_leaderboard(str(channel.id), str(message.id))
        
        await ctx.send(f'Leaderboard created in {channel.mention}. It will automatically update when member data changes.')
    except discord.Forbidden:
        await ctx.send(f'I do not have permission to send messages in {channel.mention}')
    except Exception as e:
        await ctx.send(f'Error creating leaderboard: {str(e)}')

@bot.command(name='update')
@commands.has_permissions(administrator=True)
async def update_leaderboards(ctx):
    """Manually update all leaderboards immediately"""
    try:
        await update_all_leaderboards()
        await ctx.send('✅ All leaderboards have been updated!')
    except Exception as e:
        await ctx.send(f'Error updating leaderboards: {str(e)}')

@bot.command(name='addcharacter')
@commands.has_permissions(administrator=True)
async def add_character_slot(ctx):
    slot_count = int(await db.get_setting('survey_slot_count') or 2)
    new_count = slot_count + 1
    await db.set_setting('survey_slot_count', str(new_count))
    await ctx.send(f'Character slots increased to: {new_count}')

@bot.command(name='deletecharacter')
@commands.has_permissions(administrator=True)
async def remove_character_slot(ctx, slot: int):
    slot_count = int(await db.get_setting('survey_slot_count') or 2)
    
    if slot < 1 or slot > slot_count:
        await ctx.send(f'Invalid slot. Current slot count: {slot_count}')
        return
    
    users = await db.get_all_users()
    slot_index = slot - 1
    
    for user in users:
        if len(user['characters']) > slot_index:
            user['characters'].pop(slot_index)
            await db.save_user(
                user['discord_id'],
                user['nickname'],
                user['characters'],
                user['combat_power'],
                user['attendances']
            )
    
    new_count = slot_count - 1
    await db.set_setting('survey_slot_count', str(new_count))
    await ctx.send(f'Removed slot {slot}. New slot count: {new_count}')

@tasks.loop(hours=1)
async def cleanup_old_dms():
    """Optimized DM cleanup with parallel processing"""
    try:
        old_messages = await db.get_old_dm_messages(48)
        if not old_messages:
            return
        
        semaphore = asyncio.Semaphore(5)
        
        async def cleanup_message(message_id, user_id):
            async with semaphore:
                try:
                    user = await retry_with_backoff(lambda: bot.fetch_user(int(user_id)))
                    if user:
                        dm_channel = await retry_with_backoff(lambda: user.create_dm())
                        try:
                            message = await retry_with_backoff(lambda: dm_channel.fetch_message(int(message_id)))
                            await retry_with_backoff(lambda: message.delete())
                        except (discord.NotFound, discord.Forbidden):
                            pass
                except Exception:
                    pass
                finally:
                    await db.delete_dm_message(message_id)
        
        await asyncio.gather(*[cleanup_message(mid, uid) for mid, uid in old_messages], return_exceptions=True)
        print(f'Cleaned up {len(old_messages)} old DM messages')
    except Exception as e:
        print(f'Error in DM cleanup: {e}')

@cleanup_old_dms.before_loop
async def before_cleanup():
    await bot.wait_until_ready()

@tasks.loop(hours=24)
async def cleanup_old_events():
    """Optimized event cleanup with cached channel lookup"""
    try:
        events = await db.get_all_attendance_events()
        if not events:
            return
        
        current_time = datetime.utcnow()
        deleted_count = 0
        
        # Cache channel lookup
        channel_id = await get_cached_setting('announcement_channel')
        channel = None
        if channel_id:
            for guild in bot.guilds:
                channel = guild.get_channel(int(channel_id))
                if channel:
                    break
        
        events_to_delete = []
        
        for event in events:
            try:
                time_str = event['time']
                am_pm = event['am_pm']
                
                # Convert to 24-hour format
                if am_pm == 'PM' and not time_str.startswith('12'):
                    hour = int(time_str.split(':')[0]) + 12
                    time_24 = f"{hour}:{time_str.split(':')[1]}"
                elif am_pm == 'AM' and time_str.startswith('12'):
                    time_24 = f"00:{time_str.split(':')[1]}"
                else:
                    time_24 = time_str
                
                event_tz = pytz.timezone(event['timezone'])
                event_dt = datetime.strptime(f"{event['date']} {time_24}", '%m/%d/%Y %H:%M')
                event_dt = event_tz.localize(event_dt)
                event_dt_utc = event_dt.astimezone(pytz.UTC)
                
                # Delete events older than 7 days
                if (current_time - event_dt_utc.replace(tzinfo=None)).days > 7:
                    # Try to delete channel message
                    if event['channel_message_id'] and channel:
                        try:
                            message = await channel.fetch_message(int(event['channel_message_id']))
                            await message.delete()
                        except (discord.NotFound, discord.Forbidden):
                            pass
                    
                    events_to_delete.append(event['event_id'])
            except Exception:
                pass
        
        # Batch delete from database
        for event_id in events_to_delete:
            await db.delete_attendance_event(event_id)
            deleted_count += 1
        
        if deleted_count > 0:
            print(f'Cleaned up {deleted_count} old attendance events')
    except Exception as e:
        print(f'Error in event cleanup: {e}')

@cleanup_old_events.before_loop
async def before_event_cleanup():
    await bot.wait_until_ready()

@tasks.loop(hours=6)
async def cleanup_memory():
    """Periodic cleanup to prevent memory leaks"""
    try:
        # Clean up expired cache entries
        cache_cleaned = cleanup_expired_cache()
        if cache_cleaned > 0:
            print(f'Cleaned up {cache_cleaned} expired cache entries')
        
        # Clean up old user locks (inactive for 24+ hours)
        locks_cleaned = db.cleanup_old_locks(max_age_hours=24)
        if locks_cleaned > 0:
            print(f'Cleaned up {locks_cleaned} unused user locks')
    except Exception as e:
        print(f'Error in memory cleanup: {e}')

@cleanup_memory.before_loop
async def before_memory_cleanup():
    await bot.wait_until_ready()

# Bot startup is handled by main.py
# This allows for proper async/await handling and graceful shutdown
