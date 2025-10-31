import os
import asyncio
from bot import bot, shutdown_cleanup

async def main():
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        print("=" * 60)
        print("FATAL ERROR: DISCORD_BOT_TOKEN environment variable not set!")
        print("=" * 60)
        print("Please set your Discord bot token:")
        print("  - For Replit: Add DISCORD_BOT_TOKEN to Secrets")
        print("  - For Railway: Add DISCORD_BOT_TOKEN to Variables")
        print("=" * 60)
        return
    
    try:
        await bot.start(token)
    except KeyboardInterrupt:
        print("Received shutdown signal...")
    except Exception as e:
        print(f"Error starting bot: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await shutdown_cleanup()
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
