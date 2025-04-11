import os
import sys
import time
import argparse
import schedule  # Add the missing schedule import
from datetime import datetime
from dotenv import load_dotenv
import pathlib

# Determine the script directory and .env file path
script_dir = pathlib.Path(__file__).parent.absolute()
env_path = script_dir / '.env'

# Ensure the script can find the sync module regardless of the working directory
sys.path.append(str(script_dir))

# Track the last modification time of the .env file
last_env_mtime = os.path.getmtime(env_path) if os.path.exists(env_path) else 0

# Function to check for and reload environment variables if changed
def check_env_changes():
    global last_env_mtime
    try:
        if os.path.exists(env_path):
            current_mtime = os.path.getmtime(env_path)
            if current_mtime > last_env_mtime:
                print(f"📝 Detected changes to .env file. Reloading configuration...")
                load_dotenv(dotenv_path=env_path, override=True)
                last_env_mtime = current_mtime
                return True
    except Exception as e:
        print(f"⚠️ Error checking .env file: {e}")
    return False

# Load environment variables from the correct path
load_dotenv(dotenv_path=env_path, override=True)

from sync_Trakt_to_emby import (
    check_required_env_vars,
    start_scheduler,
    run_scheduler_forever,
    start_sync,
    get_config
)

def main():
    """Main entry point for the console runner"""
    parser = argparse.ArgumentParser(description="Trakt to Emby Sync Console Runner")
    parser.add_argument(
        "--mode", 
        choices=["scheduler", "sync_once", "check_config"],
        default="scheduler",
        help="Run mode: scheduler (default), sync_once, or check_config"
    )
    parser.add_argument(
        "--interval",
        help="Override sync interval (e.g. 6h, 1d, 1w, 2w, 1m, 1min)"
    )
    
    args = parser.parse_args()
    
    # Load environment variables from the correct location
    load_dotenv(dotenv_path=env_path, override=True)
    
    # Display banner
    print("\n" + "="*50)
    print("🎬 Trakt to Emby Sync - Console Runner")
    print("="*50)
    print(f"📅 Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📂 Using .env file at: {env_path}")
    
    # Check configuration first
    env_valid, missing_vars = check_required_env_vars()
    if not env_valid:
        print("⚠️ Missing required configuration:")
        for var in missing_vars:
            print(f"  - {var}")
        print("\n❌ Please set up configuration before running")
        print("You can configure the application using the Streamlit interface.")
        return False
    
    # Get sync interval (command line takes precedence, then .env, then default)
    interval = args.interval or get_config('SYNC_INTERVAL') or '6h'
    print(f"🔄 Sync interval: {interval}")
    
    # Run in specified mode
    if args.mode == "scheduler":
        print("🕒 Starting scheduler in continuous mode...")
        # Use modified run_scheduler_forever that checks for env changes
        run_scheduler_with_env_monitoring(interval)
    elif args.mode == "sync_once":
        print("🔄 Running one-time sync...")
        # Check for any config changes before running
        check_env_changes()
        start_sync()
    elif args.mode == "check_config":
        print("🔍 Checking configuration...")
        print(f"✅ Configuration is valid")
        print("\nCurrent settings:")
        print(f"  - Sync interval: {interval}")
        print(f"  - Trakt client ID: {'Set' if get_config('TRAKT_CLIENT_ID') else 'Not set'}")
        print(f"  - Trakt client secret: {'Set' if get_config('TRAKT_CLIENT_SECRET') else 'Not set'}")
        print(f"  - Emby API key: {'Set' if get_config('EMBY_API_KEY') else 'Not set'}")
        print(f"  - Emby server: {get_config('EMBY_SERVER')}")
    
    return True

def run_scheduler_with_env_monitoring(interval):
    """Run the scheduler in a loop forever with environment file monitoring"""
    # Import these locally to ensure they've been properly loaded
    import schedule
    from sync_Trakt_to_emby import start_scheduler, get_config, get_next_occurrence_date

    # Start the scheduler with time and day settings
    sync_time = get_config('SYNC_TIME') or '00:00'
    sync_day = get_config('SYNC_DAY') or 'Monday'
    try:
        sync_date = int(get_config('SYNC_DATE') or '1')
    except ValueError:
        sync_date = 1
        
    if start_scheduler(interval, sync_time):
        print("✅ Scheduler started successfully")
        print("📢 Running in continuous mode. Press Ctrl+C to exit.")
        print("📝 Environment file will be checked every hour for changes")
        
        try:
            # Keep the script running to execute scheduled jobs
            while True:
                # Check for environment file changes
                if check_env_changes():
                    print("📝 Reloaded configuration from .env file")
                    # Reset scheduler with new settings if needed
                    new_interval = get_config('SYNC_INTERVAL') or interval
                    new_time = get_config('SYNC_TIME') or '00:00'
                    new_day = get_config('SYNC_DAY') or 'Monday'
                    try:
                        new_date = int(get_config('SYNC_DATE') or '1')
                    except ValueError:
                        new_date = 1
                        
                    if new_interval != interval or new_time != sync_time or new_day != sync_day or new_date != sync_date:
                        print(f"🔄 Sync schedule changed. Resetting scheduler...")
                        schedule.clear()
                        start_scheduler(new_interval, new_time)
                        interval = new_interval
                        sync_time = new_time
                        sync_day = new_day
                        sync_date = new_date
                
                schedule.run_pending()
                next_run = get_next_occurrence_date(interval, sync_time, sync_day, sync_date)
                if next_run:
                    print(f"⏳ Next sync scheduled for: {next_run}")
                else:
                    print("⚠️ No scheduled jobs found. Check your scheduler setup.")
                
                # Sleep for a minute
                time.sleep(3600)  # Check every minute
        except KeyboardInterrupt:
            print("\n🛑 Scheduler stopped by user")
        except Exception as e:
            print(f"❌ Scheduler error: {str(e)}")
            import traceback
            traceback.print_exc()
    else:
        print("❌ Failed to start scheduler")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Program stopped by user")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
