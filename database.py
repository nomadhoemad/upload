import asyncpg  # type: ignore
import json
from datetime import datetime, timedelta
import asyncio
import os
from typing import Optional

class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self.user_locks = {}  # Per-user locks for fine-grained concurrency
        self.lock_timestamps = {}  # Track last use time for cleanup
        self.database_url = os.getenv('DATABASE_URL')
    
    def _require_pool(self):
        """Validate that the database pool is initialized"""
        if self.pool is None:
            raise RuntimeError(
                "Database pool not initialized. "
                "Ensure init_db() completed successfully before using database methods. "
                "Check that DATABASE_URL environment variable is set correctly."
            )
    
    def _get_user_lock(self, discord_id):
        """Get or create a lock for a specific user"""
        if discord_id not in self.user_locks:
            self.user_locks[discord_id] = asyncio.Lock()
        self.lock_timestamps[discord_id] = datetime.utcnow()
        return self.user_locks[discord_id]
    
    def cleanup_old_locks(self, max_age_hours=24):
        """Remove locks that haven't been used in max_age_hours to prevent memory leak"""
        if not self.lock_timestamps:
            return 0
        
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        to_remove = [
            discord_id for discord_id, timestamp in self.lock_timestamps.items()
            if timestamp < cutoff
        ]
        
        for discord_id in to_remove:
            if discord_id in self.user_locks:
                del self.user_locks[discord_id]
            if discord_id in self.lock_timestamps:
                del self.lock_timestamps[discord_id]
        
        return len(to_remove)
    
    async def init_db(self):
        if not self.database_url:
            raise ValueError(
                "DATABASE_URL environment variable is not set. "
                "Please configure your PostgreSQL database connection. "
                "For Railway: Add PostgreSQL database to your project. "
                "For Replit: Database should be auto-configured."
            )
        
        if not self.pool:
            try:
                # Increased pool size for high concurrency (100+ simultaneous users)
                self.pool = await asyncpg.create_pool(
                    self.database_url, 
                    min_size=5, 
                    max_size=30,
                    command_timeout=10,
                    max_inactive_connection_lifetime=300
                )
            except Exception as e:
                raise RuntimeError(
                    f"Failed to create database connection pool: {e}. "
                    "Check DATABASE_URL format and database availability."
                ) from e
        
        self._require_pool()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    discord_id TEXT PRIMARY KEY,
                    nickname TEXT NOT NULL,
                    characters JSONB NOT NULL,
                    combat_power BIGINT DEFAULT 0,
                    attendances JSONB DEFAULT '{}'::jsonb,
                    timestamp TIMESTAMPTZ,
                    survey_timestamp TIMESTAMPTZ
                )
            """)
            
            # Migration: Add survey_timestamp column if it doesn't exist
            try:
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS survey_timestamp TIMESTAMPTZ")
                # Copy existing timestamp to survey_timestamp for existing users
                await conn.execute("UPDATE users SET survey_timestamp = timestamp WHERE survey_timestamp IS NULL")
            except Exception:
                pass
            
            # Migration: Convert combat_power from INTEGER to BIGINT if needed
            try:
                await conn.execute("ALTER TABLE users ALTER COLUMN combat_power TYPE BIGINT")
            except Exception:
                pass
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS attendance_events (
                    event_id INTEGER PRIMARY KEY,
                    message TEXT NOT NULL,
                    time TEXT NOT NULL,
                    am_pm TEXT NOT NULL,
                    date TEXT NOT NULL,
                    channel_message_id TEXT,
                    timestamp TIMESTAMPTZ
                )
            """)
            
            # Clean up old columns (migration)
            try:
                await conn.execute("ALTER TABLE attendance_events DROP COLUMN IF EXISTS days_of_week")
                await conn.execute("ALTER TABLE attendance_events DROP COLUMN IF EXISTS recurring")
                await conn.execute("ALTER TABLE attendance_events DROP COLUMN IF EXISTS timezone")
            except Exception:
                pass
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS available_mains (
                    main_name TEXT PRIMARY KEY
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS available_subclasses (
                    main_name TEXT NOT NULL,
                    subclass_name TEXT NOT NULL,
                    PRIMARY KEY (main_name, subclass_name)
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dm_messages (
                    message_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS event_metadata (
                    event_id INTEGER PRIMARY KEY,
                    metadata JSONB NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS leaderboards (
                    channel_id TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL
                )
            """)
            
            # Create indexes for better query performance
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_dm_timestamp ON dm_messages(timestamp)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_attendance_event_id ON attendance_events(event_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id)")
    
    async def get_setting(self, key):
        self._require_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM settings WHERE key = $1", key)
            return row['value'] if row else None
    
    async def set_setting(self, key, value):
        self._require_pool()
        # No lock needed - ON CONFLICT is atomic at database level
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2",
                key, value
            )
    
    async def delete_setting(self, key):
        self._require_pool()
        # No lock needed - DELETE is atomic
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM settings WHERE key = $1", key)
    
    async def get_all_settings(self):
        self._require_pool()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT key, value FROM settings")
            return [{"key": row['key'], "value": row['value']} for row in rows]
    
    async def get_user(self, discord_id):
        self._require_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT discord_id, nickname, characters, combat_power, attendances, timestamp FROM users WHERE discord_id = $1",
                discord_id
            )
            if row:
                return {
                    "discord_id": row['discord_id'],
                    "nickname": row['nickname'],
                    "characters": json.loads(row['characters']) if isinstance(row['characters'], str) else row['characters'],
                    "combat_power": row['combat_power'],
                    "attendances": json.loads(row['attendances']) if isinstance(row['attendances'], str) else row['attendances'],
                    "timestamp": row['timestamp'].isoformat() + 'Z' if row['timestamp'] else None
                }
            return None
    
    async def save_user(self, discord_id, nickname, characters, combat_power, attendances, update_survey_timestamp=False, update_timestamp=True):
        self._require_pool()
        # Use per-user lock to prevent race conditions for same user
        async with self._get_user_lock(discord_id):
            async with self.pool.acquire() as conn:
                timestamp = datetime.utcnow()
                
                if update_survey_timestamp:
                    # Update both timestamp and survey_timestamp (for survey completion)
                    await conn.execute(
                        """INSERT INTO users (discord_id, nickname, characters, combat_power, attendances, timestamp, survey_timestamp) 
                           VALUES ($1, $2, $3::jsonb, $4, $5::jsonb, $6, $6) 
                           ON CONFLICT (discord_id) DO UPDATE 
                           SET nickname = $2, characters = $3::jsonb, combat_power = $4, attendances = $5::jsonb, timestamp = $6, survey_timestamp = $6""",
                        discord_id, nickname, json.dumps(characters), combat_power, json.dumps(attendances), timestamp
                    )
                elif update_timestamp:
                    # Update timestamp only (for activity tracking)
                    await conn.execute(
                        """INSERT INTO users (discord_id, nickname, characters, combat_power, attendances, timestamp, survey_timestamp) 
                           VALUES ($1, $2, $3::jsonb, $4, $5::jsonb, $6, $6) 
                           ON CONFLICT (discord_id) DO UPDATE 
                           SET nickname = $2, characters = $3::jsonb, combat_power = $4, attendances = $5::jsonb, timestamp = $6""",
                        discord_id, nickname, json.dumps(characters), combat_power, json.dumps(attendances), timestamp
                    )
                else:
                    # Don't update any timestamps (for poll responses)
                    await conn.execute(
                        """INSERT INTO users (discord_id, nickname, characters, combat_power, attendances, timestamp, survey_timestamp) 
                           VALUES ($1, $2, $3::jsonb, $4, $5::jsonb, $6, $6) 
                           ON CONFLICT (discord_id) DO UPDATE 
                           SET nickname = $2, characters = $3::jsonb, combat_power = $4, attendances = $5::jsonb""",
                        discord_id, nickname, json.dumps(characters), combat_power, json.dumps(attendances), timestamp
                    )
    
    async def get_all_users(self):
        self._require_pool()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT discord_id, nickname, characters, combat_power, attendances, timestamp, survey_timestamp FROM users")
            return [
                {
                    "discord_id": row['discord_id'],
                    "nickname": row['nickname'],
                    "characters": json.loads(row['characters']) if isinstance(row['characters'], str) else row['characters'],
                    "combat_power": row['combat_power'],
                    "attendances": json.loads(row['attendances']) if isinstance(row['attendances'], str) else row['attendances'],
                    "timestamp": row['timestamp'].isoformat() + 'Z' if row['timestamp'] else None,
                    "survey_timestamp": row['survey_timestamp'].isoformat() + 'Z' if row['survey_timestamp'] else None
                }
                for row in rows
            ]
    
    async def delete_user(self, discord_id):
        self._require_pool()
        # No lock needed - DELETE is atomic
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE discord_id = $1", discord_id)
    
    async def clear_all_surveys(self):
        self._require_pool()
        # No lock needed - DELETE is atomic
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM users")
    
    async def save_attendance_event(self, event_id, message, time, am_pm, date, channel_message_id=None):
        self._require_pool()
        # No lock needed - ON CONFLICT is atomic
        async with self.pool.acquire() as conn:
            timestamp = datetime.utcnow()
            await conn.execute(
                """INSERT INTO attendance_events (event_id, message, time, am_pm, date, channel_message_id, timestamp) 
                   VALUES ($1, $2, $3, $4, $5, $6, $7) 
                   ON CONFLICT (event_id) DO UPDATE 
                   SET message = $2, time = $3, am_pm = $4, date = $5, channel_message_id = $6, timestamp = $7""",
                event_id, message, time, am_pm, date, channel_message_id, timestamp
            )
    
    async def get_attendance_event(self, event_id):
        self._require_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT event_id, message, time, am_pm, date, channel_message_id, timestamp FROM attendance_events WHERE event_id = $1",
                event_id
            )
            if row:
                return {
                    "event_id": row['event_id'],
                    "message": row['message'],
                    "time": row['time'],
                    "am_pm": row['am_pm'],
                    "date": row['date'],
                    "channel_message_id": row['channel_message_id'],
                    "timestamp": row['timestamp'].isoformat() + 'Z' if row['timestamp'] else None
                }
            return None
    
    async def get_all_attendance_events(self):
        self._require_pool()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT event_id, message, time, am_pm, date, channel_message_id, timestamp FROM attendance_events")
            return [
                {
                    "event_id": row['event_id'],
                    "message": row['message'],
                    "time": row['time'],
                    "am_pm": row['am_pm'],
                    "date": row['date'],
                    "channel_message_id": row['channel_message_id'],
                    "timestamp": row['timestamp'].isoformat() + 'Z' if row['timestamp'] else None
                }
                for row in rows
            ]
    
    async def delete_attendance_event(self, event_id):
        self._require_pool()
        # No lock needed - DELETE is atomic
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM attendance_events WHERE event_id = $1", event_id)
    
    async def clear_all_attendance_events(self):
        self._require_pool()
        # No lock needed - DELETE is atomic
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM attendance_events")
    
    async def clear_all_user_attendances(self):
        self._require_pool()
        # No lock needed - UPDATE is atomic
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET attendances = '{}'::jsonb")
    
    async def update_channel_message_id(self, event_id, channel_message_id):
        self._require_pool()
        # No lock needed - UPDATE is atomic
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE attendance_events SET channel_message_id = $1 WHERE event_id = $2",
                channel_message_id, event_id
            )
    
    async def get_next_event_id(self):
        self._require_pool()
        async with self.pool.acquire() as conn:
            # Get IDs from !poll events (attendance_events table)
            rows = await conn.fetch("SELECT event_id FROM attendance_events ORDER BY event_id")
            used_ids = {row['event_id'] for row in rows}
            
            # Also get IDs from !event events (stored in settings as event_id_{id})
            setting_rows = await conn.fetch("SELECT key FROM settings WHERE key LIKE 'event_id_%'")
            for row in setting_rows:
                key = row['key']
                if key.startswith('event_id_'):
                    try:
                        event_id_from_setting = int(key.replace('event_id_', ''))
                        used_ids.add(event_id_from_setting)
                    except ValueError:
                        pass
            
            # Find the next available ID
            event_id = 1
            while event_id in used_ids:
                event_id += 1
            return event_id
    
    async def add_main(self, main_name):
        self._require_pool()
        # No lock needed - ON CONFLICT is atomic
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO available_mains (main_name) VALUES ($1) ON CONFLICT DO NOTHING", main_name)
    
    async def remove_main(self, main_name):
        self._require_pool()
        # No lock needed - DELETE is atomic
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM available_mains WHERE main_name = $1", main_name)
            await conn.execute("DELETE FROM available_subclasses WHERE main_name = $1", main_name)
    
    async def get_all_mains(self):
        self._require_pool()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT main_name FROM available_mains ORDER BY main_name")
            return [row['main_name'] for row in rows]
    
    async def add_subclass(self, main_name, subclass_name):
        self._require_pool()
        # No lock needed - ON CONFLICT is atomic
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO available_subclasses (main_name, subclass_name) VALUES ($1, $2) ON CONFLICT DO NOTHING", main_name, subclass_name)
    
    async def remove_subclass(self, main_name, subclass_name):
        self._require_pool()
        # No lock needed - DELETE is atomic
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM available_subclasses WHERE main_name = $1 AND subclass_name = $2", main_name, subclass_name)
    
    async def get_subclasses_for_main(self, main_name):
        self._require_pool()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT subclass_name FROM available_subclasses WHERE main_name = $1 ORDER BY subclass_name", main_name)
            return [row['subclass_name'] for row in rows]
    
    async def add_dm_message(self, message_id, user_id):
        self._require_pool()
        # No lock needed - ON CONFLICT is atomic
        async with self.pool.acquire() as conn:
            timestamp = datetime.utcnow()
            await conn.execute(
                "INSERT INTO dm_messages (message_id, user_id, timestamp) VALUES ($1, $2, $3) ON CONFLICT (message_id) DO UPDATE SET timestamp = $3",
                str(message_id), str(user_id), timestamp
            )
    
    async def get_old_dm_messages(self, hours=48):
        self._require_pool()
        async with self.pool.acquire() as conn:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            rows = await conn.fetch(
                "SELECT message_id, user_id FROM dm_messages WHERE timestamp < $1",
                cutoff_time
            )
            return [(row['message_id'], row['user_id']) for row in rows]
    
    async def delete_dm_message(self, message_id):
        self._require_pool()
        # No lock needed - DELETE is atomic
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM dm_messages WHERE message_id = $1", str(message_id))
    
    async def set_event_metadata(self, event_id, metadata):
        self._require_pool()
        # No lock needed - ON CONFLICT is atomic
        async with self.pool.acquire() as conn:
            timestamp = datetime.utcnow()
            await conn.execute(
                """INSERT INTO event_metadata (event_id, metadata, timestamp) 
                   VALUES ($1, $2::jsonb, $3) 
                   ON CONFLICT (event_id) DO UPDATE 
                   SET metadata = $2::jsonb, timestamp = $3""",
                event_id, json.dumps(metadata), timestamp
            )
    
    async def get_event_metadata(self, event_id):
        self._require_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT metadata FROM event_metadata WHERE event_id = $1",
                event_id
            )
            if row:
                return json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']
            return None
    
    async def delete_event_metadata(self, event_id):
        self._require_pool()
        # No lock needed - DELETE is atomic
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM event_metadata WHERE event_id = $1", event_id)
    
    async def save_leaderboard(self, channel_id, message_id):
        self._require_pool()
        # No lock needed - ON CONFLICT is atomic
        async with self.pool.acquire() as conn:
            timestamp = datetime.utcnow()
            await conn.execute(
                """INSERT INTO leaderboards (channel_id, message_id, timestamp) 
                   VALUES ($1, $2, $3) 
                   ON CONFLICT (channel_id) DO UPDATE 
                   SET message_id = $2, timestamp = $3""",
                str(channel_id), str(message_id), timestamp
            )
    
    async def get_all_leaderboards(self):
        self._require_pool()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT channel_id, message_id FROM leaderboards")
            return [(row['channel_id'], row['message_id']) for row in rows]
    
    async def delete_leaderboard(self, channel_id):
        self._require_pool()
        # No lock needed - DELETE is atomic
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM leaderboards WHERE channel_id = $1", str(channel_id))
    
    async def close(self):
        if self.pool:
            await self.pool.close()
