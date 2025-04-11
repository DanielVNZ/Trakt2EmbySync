import streamlit as st
import json
import os
import schedule
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sync_Trakt_to_emby import (
    get_trakt_device_code,
    poll_for_access_token,
    load_token,
    refresh_access_token,
    sync_trakt_list_to_emby,
    get_access_token,
    sync_all_trakt_lists,
    check_required_env_vars,
    get_config
)
import requests

# Add helper functions for date handling
def get_next_occurrence_date(day_of_week):
    """Calculate the next occurrence of a specific day of the week."""
    days = {
        'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
        'Friday': 4, 'Saturday': 5, 'Sunday': 6
    }
    today = datetime.now()
    target_day_index = days.get(day_of_week, 0)  # Default to Monday if invalid
    days_until = (target_day_index - today.weekday()) % 7
    if days_until == 0:  # If it's the same day, move to next week
        days_until = 7
    return today + timedelta(days=days_until)

def get_ordinal_suffix(n):
    """Return ordinal suffix for a number (1st, 2nd, 3rd, etc.)"""
    if 11 <= (n % 100) <= 13:
        return 'th'
    else:
        return {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')

# Enable Streamlit page config
st.set_page_config(page_title="Trakt to Emby Sync", page_icon="🎬")

# Main app title
def save_config():
    """Save configuration to .env file"""
    env_content = []
    try:
        # Read existing .env file
        if os.path.exists('.env'):
            with open('.env', 'r') as f:
                env_content = [line.strip() for line in f if line.strip()]
    except Exception as e:
        st.error(f"Error reading .env file: {str(e)}")
        return False

    # Update or add new values
    for key, value in st.session_state.config.items():
        key_prefix = f"{key}="
        if key == 'TRAKT_LISTS':
            new_line = f'{key}={json.dumps(value)}'
        else:
            new_line = f'{key}={value}'
        
        # Find and replace existing line or append new one
        found = False
        for i, line in enumerate(env_content):
            if line.startswith(key_prefix):
                env_content[i] = new_line
                found = True
                break
        if not found:
            env_content.append(new_line)
    
    try:
        with open('.env', 'w') as f:
            f.write('\n'.join(env_content) + '\n')
        # Force reload of environment variables
        load_dotenv(override=True)
        return True
    except Exception as e:
        st.error(f"Error saving configuration: {str(e)}")
        return False

def set_config(key, value):
    """Set configuration value in session state and save to file"""
    if 'config' not in st.session_state:
        st.session_state.config = {}
    st.session_state.config[key] = value
    save_config()

def create_default_env():
    """Create default .env file if it doesn't exist"""
    if not os.path.exists('.env'):
        default_env = """# Trakt API Credentials
TRAKT_CLIENT_ID=
TRAKT_CLIENT_SECRET=

# Emby Configuration
EMBY_API_KEY=
EMBY_SERVER=
EMBY_ADMIN_USER_ID=
EMBY_MOVIES_LIBRARY_ID=
EMBY_TV_LIBRARY_ID=

# Sync Configuration
SYNC_INTERVAL=6h
TRAKT_LISTS=[]
"""
        with open('.env', 'w') as f:
            f.write(default_env)
        print("Created default .env file")
        return True
    return False

def check_required_config():
    """Check if all required configuration is present"""
    required_vars = [
        'TRAKT_CLIENT_ID',
        'TRAKT_CLIENT_SECRET',
        'EMBY_API_KEY',
        'EMBY_SERVER',
        'EMBY_ADMIN_USER_ID',
        'EMBY_MOVIES_LIBRARY_ID',
        'EMBY_TV_LIBRARY_ID'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not get_config(var):
            missing_vars.append(var)
    
    if missing_vars:
        return {'Missing Configuration': missing_vars}
    return {}

# Create default .env if it doesn't exist
is_new_install = create_default_env()

# Load environment variables
load_dotenv()

# Initialize session state
if 'config' not in st.session_state:
    st.session_state.config = {}
    # Load configuration from environment variables
    for key in ['TRAKT_CLIENT_ID', 'TRAKT_CLIENT_SECRET', 'EMBY_API_KEY', 'EMBY_SERVER',
                'EMBY_ADMIN_USER_ID', 'EMBY_MOVIES_LIBRARY_ID', 'EMBY_TV_LIBRARY_ID']:
        st.session_state.config[key] = get_config(key)
    
    # Handle sync interval with default
    st.session_state.config['SYNC_INTERVAL'] = get_config('SYNC_INTERVAL') or '6h'
    
    # Handle Trakt lists
    try:
        st.session_state.config['TRAKT_LISTS'] = json.loads(get_config('TRAKT_LISTS') or '[]')
    except json.JSONDecodeError:
        st.session_state.config['TRAKT_LISTS'] = []

# Initialize trakt_lists in session state
if 'trakt_lists' not in st.session_state:
    try:
        trakt_lists_str = get_config('TRAKT_LISTS')
        if trakt_lists_str:
            st.session_state.trakt_lists = json.loads(trakt_lists_str)
        else:
            st.session_state.trakt_lists = []
    except json.JSONDecodeError:
        st.session_state.trakt_lists = []

# Initialize trakt authentication state
if 'trakt_auth_in_progress' not in st.session_state:
    st.session_state.trakt_auth_in_progress = False

if 'trakt_device_code' not in st.session_state:
    st.session_state.trakt_device_code = None

if 'trakt_user_code' not in st.session_state:
    st.session_state.trakt_user_code = None

if 'trakt_poll_interval' not in st.session_state:
    st.session_state.trakt_poll_interval = None

if 'page' not in st.session_state:
    st.session_state.page = 'settings' if is_new_install else 'main'

if 'sync_in_progress' not in st.session_state:
    st.session_state.sync_in_progress = False

if 'last_sync' not in st.session_state:
    st.session_state.last_sync = None

if 'sync_progress' not in st.session_state:
    st.session_state.sync_progress = {}

if 'sync_messages' not in st.session_state:
    st.session_state.sync_messages = []

if 'current_status' not in st.session_state:
    st.session_state.current_status = ""

if 'current_message' not in st.session_state:
    st.session_state.current_message = ""

if 'auth_complete' not in st.session_state:
    st.session_state.auth_complete = False

if 'auth_polling_started' not in st.session_state:
    st.session_state.auth_polling_started = False

# Initialize scheduler state
if 'scheduler_running' not in st.session_state:
    st.session_state.scheduler_running = False
    
if 'next_scheduled_run' not in st.session_state:
    st.session_state.next_scheduled_run = None

if 'last_check_time' not in st.session_state:
    st.session_state.last_check_time = datetime.now()

# Function to check and run scheduled jobs while Streamlit is active
def check_scheduler():
    """Check for scheduled jobs and run them if needed"""
    if not st.session_state.scheduler_running:
        return
    
    current_time = datetime.now()
    st.session_state.last_check_time = current_time
    
    # Check pending jobs
    schedule.run_pending()
    
    # Update next run time
    next_run = schedule.next_run()
    if next_run:
        st.session_state.next_scheduled_run = next_run

# Scheduler management functions
def start_streamlit_scheduler():
    """Start the scheduler within Streamlit"""
    # Check configuration
    env_valid, missing_vars = check_required_env_vars()
    if not env_valid:
        st.error("⚠️ Cannot start scheduler: Missing required configuration")
        return False
    
    # Clear existing jobs
    schedule.clear()
    
    # Get sync interval and time
    interval = get_config('SYNC_INTERVAL') or '6h'
    sync_time = get_config('SYNC_TIME') or '00:00'
    
    # Set up schedule based on interval
    if interval == '6h':
        schedule.every(6).hours.do(run_scheduled_sync)
        st.success("🕒 Scheduler set to run every 6 hours")
    elif interval == '1d':
        schedule.every().day.at(sync_time).do(run_scheduled_sync)
        st.success(f"🕒 Scheduler set to run daily at {sync_time}")
    elif interval == '1w':
        schedule.every().monday.at(sync_time).do(run_scheduled_sync)
        st.success(f"🕒 Scheduler set to run weekly on Mondays at {sync_time}")
    elif interval == '2w':
        schedule.every(14).days.at(sync_time).do(run_scheduled_sync)
        st.success(f"🕒 Scheduler set to run every 2 weeks at {sync_time}")
    elif interval == '1m':
        schedule.every(30).days.at(sync_time).do(run_scheduled_sync)
        st.success(f"🕒 Scheduler set to run monthly at {sync_time}")
    elif interval == '1min':
        # Testing interval - run every minute
        schedule.every(1).minute.do(run_scheduled_sync)
        st.success("🕒 TEST MODE: Scheduler set to run every minute")
    else:
        st.warning(f"⚠️ Invalid interval: {interval}. Using default 6 hours.")
        schedule.every(6).hours.do(run_scheduled_sync)
    
    # Mark scheduler as running
    st.session_state.scheduler_running = True
    
    # Update next run time
    st.session_state.next_scheduled_run = schedule.next_run()
    
    return True

def stop_streamlit_scheduler():
    """Stop the scheduler"""
    schedule.clear()
    st.session_state.scheduler_running = False
    st.session_state.next_scheduled_run = None
    st.success("Scheduler stopped")

def save_settings():
    """Save settings to .env file"""
    # First read existing lines that we don't manage
    env_lines = []
    managed_keys = {
        'SYNC_INTERVAL', 'TRAKT_LISTS',
        'TRAKT_CLIENT_ID', 'TRAKT_CLIENT_SECRET',
        'EMBY_API_KEY', 'EMBY_SERVER',
        'EMBY_ADMIN_USER_ID', 'EMBY_MOVIES_LIBRARY_ID',
        'EMBY_TV_LIBRARY_ID'
    }
    
    try:
        with open('.env', 'r') as f:
            for line in f:
                if not any(line.startswith(f"{key}=") for key in managed_keys):
                    env_lines.append(line.strip())
    except FileNotFoundError:
        pass

    # Add sync interval if it exists in session state
    if 'sync_interval' in st.session_state:
        env_lines.append(f'SYNC_INTERVAL={st.session_state.sync_interval}')
    
    # Add Trakt lists if they exist
    if hasattr(st.session_state, 'trakt_lists'):
        trakt_lists_json = json.dumps(st.session_state.trakt_lists)
        env_lines.append(f'TRAKT_LISTS={trakt_lists_json}')
    
    with open('.env', 'w') as f:
        f.write('\n'.join(env_lines))
    
    # Force reload of environment variables
    load_dotenv(override=True)

def save_config_value(key, value):
    """Save a single configuration value to .env file"""
    if not value:  # Don't save empty values
        return
        
    env_lines = []
    try:
        with open('.env', 'r') as f:
            for line in f:
                if not line.startswith(f"{key}="):
                    env_lines.append(line.strip())
    except FileNotFoundError:
        pass
    
    env_lines.append(f'{key}={value}')
    
    with open('.env', 'w') as f:
        f.write('\n'.join(env_lines))
    
    # Force reload of environment variables
    load_dotenv(override=True)

def save_trakt_lists():
    """Save Trakt lists to .env file"""
    env_lines = []
    with open('.env', 'r') as f:
        for line in f:
            if not line.startswith('TRAKT_LISTS='):
                env_lines.append(line.strip())
    
    trakt_lists_json = json.dumps(st.session_state.trakt_lists)
    env_lines.append(f'TRAKT_LISTS={trakt_lists_json}')
    
    with open('.env', 'w') as f:
        f.write('\n'.join(env_lines))

def check_token_status():
    """Check if we have a valid Trakt token"""
    token_data = load_token()
    if not token_data:
        return False, "No token found"
    
    # Try to refresh the token to verify it's still valid
    refresh_token = token_data.get('refresh_token')
    if refresh_token:
        access_token = refresh_access_token(refresh_token)
        if access_token:
            return True, "Token is valid"
    
    # If we get here, we need to re-authenticate
    return False, "Token needs refresh"

def update_progress(progress, collection_name, processed, total, message=None):
    """Update the progress and current message in session state"""
    st.session_state.sync_progress[collection_name] = {
        'progress': progress,
        'processed': processed,
        'total': total
    }
    if message:
        st.session_state.current_message = message

def run_scheduled_sync():
    """Run the sync operation and update last sync time"""
    sync_all_trakt_lists(update_progress)
    st.session_state.last_sync = datetime.now()

def check_configuration():
    """Test both Trakt and Emby configurations"""
    results = {
        'trakt': {'status': False, 'message': ''},
        'emby': {'status': False, 'message': ''}
    }
    
    # Check Trakt configuration
    trakt_client_id = get_config('TRAKT_CLIENT_ID')
    trakt_client_secret = get_config('TRAKT_CLIENT_SECRET')
    
    if not trakt_client_id or not trakt_client_secret:
        results['trakt']['message'] = "❌ Missing Trakt credentials"
    else:
        try:
            # Test Trakt API
            headers = {
                'Content-Type': 'application/json',
                'trakt-api-version': '2',
                'trakt-api-key': trakt_client_id
            }
            response = requests.get('https://api.trakt.tv/users/settings', headers=headers)
            if response.status_code == 401:  # Expected without OAuth
                results['trakt']['status'] = True
                results['trakt']['message'] = "✅ Trakt API credentials are valid"
            else:
                results['trakt']['message'] = f"❌ Unexpected Trakt API response: {response.status_code}"
        except Exception as e:
            results['trakt']['message'] = f"❌ Error testing Trakt API: {str(e)}"
    
    # Check Emby configuration
    required_emby = {
        'EMBY_API_KEY': get_config('EMBY_API_KEY'),
        'EMBY_SERVER': get_config('EMBY_SERVER'),
        'EMBY_ADMIN_USER_ID': get_config('EMBY_ADMIN_USER_ID'),
        'EMBY_MOVIES_LIBRARY_ID': get_config('EMBY_MOVIES_LIBRARY_ID'),
        'EMBY_TV_LIBRARY_ID': get_config('EMBY_TV_LIBRARY_ID')
    }
    
    missing_emby = [key for key, value in required_emby.items() if not value]
    
    if missing_emby:
        results['emby']['message'] = f"❌ Missing Emby configuration: {', '.join(missing_emby)}"
    else:
        try:
            # Test Emby connection
            emby_server = required_emby['EMBY_SERVER'].rstrip('/')  # Remove trailing slash if present
            
            # Use the header-based authentication
            headers = {
                'X-Emby-Token': required_emby['EMBY_API_KEY']
            }
            
            # Test System Info
            response = requests.get(f"{emby_server}/System/Info/Public", headers=headers)
            
            if response.status_code == 200:
                # Test library access
                movies_response = requests.get(
                    f"{emby_server}/Items",
                    headers=headers,
                    params={
                        "ParentId": required_emby['EMBY_MOVIES_LIBRARY_ID'],
                        "Limit": 1
                    }
                )
                shows_response = requests.get(
                    f"{emby_server}/Items",
                    headers=headers,
                    params={
                        "ParentId": required_emby['EMBY_TV_LIBRARY_ID'],
                        "Limit": 1
                    }
                )
                
                if movies_response.status_code == 200 and shows_response.status_code == 200:
                    results['emby']['status'] = True
                    server_info = response.json()
                    results['emby']['message'] = f"✅ Connected to Emby Server: {server_info.get('ServerName', '')}"
                else:
                    results['emby']['message'] = f"❌ Could not access libraries. Movies: {movies_response.status_code}, TV: {shows_response.status_code}"
                    if movies_response.status_code == 401 or shows_response.status_code == 401:
                        results['emby']['message'] += "\nInvalid API key. Please check your Emby API key."
            else:
                results['emby']['message'] = f"❌ Could not connect to Emby server: HTTP {response.status_code}"
                if response.status_code == 401:
                    results['emby']['message'] += "\nInvalid API key. Please check your Emby API key."
        except Exception as e:
            results['emby']['message'] = f"❌ Error connecting to Emby: {str(e)}"
    
    return results

# Check for missing configuration
missing_config = check_required_config()

# Navigation
st.sidebar.title("Navigation")

# Show configuration warning if needed
if missing_config:
    st.sidebar.error("⚠️ Configuration Required")
    st.sidebar.warning("Please complete the configuration in Settings:")
    for category, items in missing_config.items():
        for item in items:
            st.sidebar.info(f"• {item}")
    
    # Force settings page if configuration is missing
    page = "Settings"
    st.session_state.page = "Settings"
else:
    page = st.sidebar.radio("Go to", ["Main", "Settings"])

if page == "Settings":
    st.title("Settings")
    
    if missing_config:
        st.error("⚠️ Configuration Required")
        st.warning(
            "Please complete the configuration below to start using the application. "
            "All fields marked with ⚠️ are required."
        )
    
    # Create tabs for different settings categories
    tab1, tab2, tab3 = st.tabs(["Sync Schedule", "Trakt Configuration", "Emby Configuration"])
    
    with tab1:
        st.header("Sync Schedule")
        
        # Get current sync interval with default value
        current_interval = get_config('SYNC_INTERVAL') or '6h'
        
        interval_options = {
            '6h': 'Every 6 Hours',
            '1d': 'Daily',
            '1w': 'Weekly',
            '2w': 'Fortnightly',
            '1m': 'Monthly',
            '1min': 'Every Minute (TESTING)',
        }
        
        # Use default '6h' if current_interval is not in options
        if current_interval not in interval_options:
            current_interval = '6h'
        
        selected_interval = st.selectbox(
            "Sync Frequency",
            options=list(interval_options.keys()),
            format_func=lambda x: interval_options[x],
            index=list(interval_options.keys()).index(current_interval)
        )
        
        # Get current sync time if it exists
        current_time = get_config('SYNC_TIME') or '00:00'
        
        # Only show time selection for intervals that are daily or longer
        if selected_interval in ['1d', '1w', '2w', '1m']:
            sync_time = st.time_input(
                "Time of day to sync",
                datetime.strptime(current_time, '%H:%M').time(),
                help="Select the time of day when the sync should run"
            )
            # Convert time to string format HH:MM
            sync_time_str = sync_time.strftime('%H:%M')
            
            # Save time if changed
            if sync_time_str != current_time:
                set_config('SYNC_TIME', sync_time_str)
                st.success("✅ Sync time updated!")
        
        # Add day selection for weekly and fortnightly schedules
        if selected_interval in ['1w', '2w']:
            # Get current day setting or default to Monday
            current_day = get_config('SYNC_DAY') or 'Monday'
            days_of_week = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            
            selected_day = st.selectbox(
                "Day of the week",
                options=days_of_week,
                index=days_of_week.index(current_day) if current_day in days_of_week else 0,
                help="Select the day of the week when the sync should run"
            )
            
            # Save day if changed
            if selected_day != current_day:
                set_config('SYNC_DAY', selected_day)
                st.success("✅ Sync day updated!")
        
        # Add date selection for monthly schedule
        if selected_interval == '1m':
            # Get current date setting or default to 1
            try:
                current_date = int(get_config('SYNC_DATE') or '1')
            except ValueError:
                current_date = 1
            
            # Cap at 28 to be safe with February
            selected_date = st.slider(
                "Day of the month",
                min_value=1,
                max_value=28,
                value=current_date,
                help="Select the date of the month when the sync should run (1-28)"
            )
            
            # Save date if changed
            if selected_date != current_date:
                set_config('SYNC_DATE', str(selected_date))
                st.success("✅ Sync date updated!")
        
        if selected_interval != current_interval:
            set_config('SYNC_INTERVAL', selected_interval)
            st.success("✅ Sync schedule updated!")
        
        # Show next sync time based on schedule
        if selected_interval == '6h':
            st.info("🕒 Sync will run every 6 hours")
        elif selected_interval == '1d':
            st.info(f"🕒 Sync will run daily at {get_config('SYNC_TIME') or '00:00'}")
        elif selected_interval == '1w':
            sync_day = get_config('SYNC_DAY') or 'Monday'
            st.info(f"🕒 Sync will run weekly on {sync_day} at {get_config('SYNC_TIME') or '00:00'}")
        elif selected_interval == '2w':
            sync_day = get_config('SYNC_DAY') or 'Monday'
            next_date = get_next_occurrence_date(sync_day)
            st.info(f"🕒 Sync will run fortnightly on {sync_day} at {get_config('SYNC_TIME') or '00:00'}")
            st.info(f"🗓️ The next sync will be on {next_date.strftime('%Y-%m-%d')}")
        elif selected_interval == '1m':
            sync_date = get_config('SYNC_DATE') or '1'
            st.info(f"🕒 Sync will run monthly on the {sync_date}{get_ordinal_suffix(int(sync_date))} at {get_config('SYNC_TIME') or '00:00'}")
        elif selected_interval == '1min':
            st.info("🕒 Sync will run every minute (TESTING)")

        # Display static information about console mode
        st.markdown("""
        ### Console Runner Mode
        
        The scheduler runs automatically in the console runner, which can be started from:
        - **Windows**: Double-click on `run.bat`
        - **Command line**: Run `python console_runner.py`
        
        The console runner will continue syncing on schedule even when the web interface is closed.
        """)
        
        # Show scheduler status
        if st.session_state.next_scheduled_run:
            st.info(f"Next scheduled sync in the web interface: {st.session_state.next_scheduled_run.strftime('%Y-%m-%d %H:%M:%S')}")
            st.caption("Note: The console runner may have a different schedule if it was started separately.")

    with tab2:
        st.header("Trakt Configuration")
        
        if any(var for var in missing_config.get('Missing Configuration', []) if 'TRAKT' in var):
            st.error("⚠️ Required Trakt settings are missing")
        
        st.markdown("""
        ### How to get Trakt API Credentials:
        1. Visit [Trakt API Settings](https://trakt.tv/oauth/applications)
        2. Click "New Application"
        3. Fill in the application details:
           - Name: "Trakt2EmbySync" (or any name you prefer)
           - Redirect URI: urn:ietf:wg:oauth:2.0:oob
           - Javascript Origins: Leave blank
        4. Click "Save App"
        5. You'll see your Client ID and Client Secret
        """)
        
        # Trakt Client ID
        trakt_client_id = st.text_input(
            "Trakt Client ID ⚠️",
            value=get_config('TRAKT_CLIENT_ID'),
            help="The Client ID from your Trakt API application"
        )
        if trakt_client_id != get_config('TRAKT_CLIENT_ID'):
            set_config('TRAKT_CLIENT_ID', trakt_client_id)
            st.success("✅ Trakt Client ID updated!")
        
        # Trakt Client Secret
        trakt_client_secret = st.text_input(
            "Trakt Client Secret ⚠️",
            value=get_config('TRAKT_CLIENT_SECRET'),
            help="The Client Secret from your Trakt API application",
            type="password"
        )
        if trakt_client_secret != get_config('TRAKT_CLIENT_SECRET'):
            set_config('TRAKT_CLIENT_SECRET', trakt_client_secret)
            st.success("✅ Trakt Client Secret updated!")

        # Add Check Trakt Configuration button
        if st.button("Check Trakt Configuration"):
            with st.spinner("Testing Trakt configuration..."):
                results = check_configuration()
                st.write(results['trakt']['message'])

    with tab3:
        st.header("Emby Configuration")
        
        if any(var for var in missing_config.get('Missing Configuration', []) if 'EMBY' in var):
            st.error("⚠️ Required Emby settings are missing")
        
        st.markdown("""
        ### How to get Emby Configuration:
        
        #### API Key:
        1. Open Emby Dashboard
        2. Click on your username in the top right
        3. Select "Profile"
        4. Go to "API Keys" (or "Api Keys" in some versions)
        5. Click "+" to create a new key
        6. Enter a name like "Trakt2EmbySync" and click "Ok"
        7. Copy the generated API key
        
        #### Server URL:
        - Your Emby server URL (e.g., http://localhost:8096 or your remote URL)
        - Include http:// or https:// and any port numbers
        - Don't include trailing slashes
        
        #### Admin User ID:
        1. Go to Emby Dashboard
        2. Click on "Users"
        3. Click on your admin user
        4. The ID is in the URL (e.g., .../web/dashboard/users/edit?userId=**THIS_IS_YOUR_ID**)
        
        #### Library IDs:
        1. Go to Emby Dashboard
        2. Click "Libraries"
        3. Click on your Movies/TV Shows library
        4. The ID is in the URL (e.g., .../web/dashboard/library?parentId=**THIS_IS_YOUR_ID**)
        """)
        
        # Emby Server URL
        emby_server = st.text_input(
            "Emby Server URL ⚠️",
            value=get_config('EMBY_SERVER'),
            help="Your Emby server URL (e.g., http://localhost:8096)"
        )
        if emby_server != get_config('EMBY_SERVER'):
            set_config('EMBY_SERVER', emby_server)
            st.success("✅ Emby Server URL updated!")
        
        # Emby API Key
        emby_api_key = st.text_input(
            "Emby API Key ⚠️",
            value=get_config('EMBY_API_KEY'),
            help="Your Emby API key from your user profile",
            type="password"
        )
        if emby_api_key != get_config('EMBY_API_KEY'):
            set_config('EMBY_API_KEY', emby_api_key)
            st.success("✅ Emby API Key updated!")
            
            # Force environment refresh when API key changes
            load_dotenv(override=True)
        
        # Emby Admin User ID
        emby_admin_user_id = st.text_input(
            "Emby Admin User ID ⚠️",
            value=get_config('EMBY_ADMIN_USER_ID'),
            help="Your Emby admin user ID"
        )
        if emby_admin_user_id != get_config('EMBY_ADMIN_USER_ID'):
            set_config('EMBY_ADMIN_USER_ID', emby_admin_user_id)
            st.success("✅ Emby Admin User ID updated!")
        
        # Library IDs
        col1, col2 = st.columns(2)
        
        with col1:
            emby_movies_library_id = st.text_input(
                "Movies Library ID ⚠️",
                value=get_config('EMBY_MOVIES_LIBRARY_ID'),
                help="Your Emby movies library ID"
            )
            if emby_movies_library_id != get_config('EMBY_MOVIES_LIBRARY_ID'):
                set_config('EMBY_MOVIES_LIBRARY_ID', emby_movies_library_id)
                st.success("✅ Movies Library ID updated!")
        
        with col2:
            emby_tv_library_id = st.text_input(
                "TV Shows Library ID ⚠️",
                value=get_config('EMBY_TV_LIBRARY_ID'),
                help="Your Emby TV shows library ID"
            )
            if emby_tv_library_id != get_config('EMBY_TV_LIBRARY_ID'):
                set_config('EMBY_TV_LIBRARY_ID', emby_tv_library_id)
                st.success("✅ TV Shows Library ID updated!")

        # Add Check Emby Configuration button
        if st.button("Test Emby Connection"):
            with st.spinner("Testing Emby configuration..."):
                if not emby_server or not emby_api_key:
                    st.error("❌ Please enter Emby Server URL and API Key")
                else:
                    try:
                        # Force refresh environment variables
                        load_dotenv(override=True)
                        
                        # Test connection with current values
                        server_url = emby_server.rstrip('/')
                        headers = {'X-Emby-Token': emby_api_key}
                        
                        # Test basic connection
                        response = requests.get(f"{server_url}/System/Info", headers=headers)
                        
                        if response.status_code == 200:
                            server_info = response.json()
                            st.success(f"✅ Successfully connected to {server_info.get('ServerName', 'Emby Server')}")
                            
                            # Check if libraries are accessible
                            if emby_movies_library_id:
                                try:
                                    movies_resp = requests.get(
                                        f"{server_url}/Items", 
                                        headers=headers,
                                        params={"ParentId": emby_movies_library_id, "Limit": 1}
                                    )
                                    if movies_resp.status_code == 200:
                                        st.success("✅ Movies library is accessible")
                                    else:
                                        st.error(f"❌ Couldn't access movies library: {movies_resp.status_code}")
                                except Exception as e:
                                    st.error(f"❌ Error accessing movies library: {str(e)}")
                            
                            if emby_tv_library_id:
                                try:
                                    tv_resp = requests.get(
                                        f"{server_url}/Items", 
                                        headers=headers,
                                        params={"ParentId": emby_tv_library_id, "Limit": 1}
                                    )
                                    if tv_resp.status_code == 200:
                                        st.success("✅ TV Shows library is accessible")
                                    else:
                                        st.error(f"❌ Couldn't access TV Shows library: {tv_resp.status_code}")
                                except Exception as e:
                                    st.error(f"❌ Error accessing TV Shows library: {str(e)}")
                        else:
                            st.error(f"❌ Failed to connect to Emby: {response.status_code}")
                            if response.status_code == 401:
                                st.error("❌ Authentication failed. Please check your API key.")
                    except Exception as e:
                        st.error(f"❌ Error testing Emby connection: {str(e)}")

        # Add a "Check All Configuration" button at the bottom of the settings page
        st.markdown("---")
        if st.button("Check All Configuration", type="primary"):
            with st.spinner("Testing all configurations..."):
                results = check_configuration()
                st.subheader("Configuration Test Results:")
                st.write("**Trakt Configuration:**")
                st.write(results['trakt']['message'])
                st.write("**Emby Configuration:**")
                st.write(results['emby']['message'])
                
                if results['trakt']['status'] and results['emby']['status']:
                    st.success("✅ All configurations are valid!")
                else:
                    st.error("❌ Some configurations need attention. Please check the messages above.")

else:  # Main page
    st.title("Trakt to Emby Sync")
    
    if missing_config:
        st.error("⚠️ Configuration Required")
        st.warning(
            "The application needs to be configured before it can be used. "
            "Please complete the following settings:\n" + 
            "\n".join([f"• {item}" for item in missing_config.get('Missing Configuration', [])])
        )
        
        # Add a direct link to settings
        if st.button("Go to Settings", key="goto_settings"):
            st.session_state.page = "Settings"
            st.rerun()
    else:
        # Token Status and Sync Button
        token_valid, token_message = check_token_status()

        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"Trakt Status: {'🟢 Connected' if token_valid else '🔴 Not Connected'}")
            if st.session_state.last_sync:
                st.write(f"Last Sync: {st.session_state.last_sync.strftime('%Y-%m-%d %H:%M:%S')}")
        with col2:
            if not st.session_state.sync_in_progress:
                if st.button("Sync Now", key="sync_button"):
                    if token_valid:
                        st.session_state.sync_in_progress = True
                        st.session_state.sync_progress = {}
                        st.session_state.current_message = "Starting sync..."
                        st.rerun()
                    else:
                        with st.spinner("Starting Trakt authentication..."):
                            device_code, user_code, interval = get_trakt_device_code()
                            if device_code and user_code:
                                # Store authentication details in session state
                                st.session_state.trakt_auth_in_progress = True
                                st.session_state.trakt_device_code = device_code
                                st.session_state.trakt_user_code = user_code
                                st.session_state.trakt_poll_interval = interval
                                st.session_state.auth_polling_started = False
                                st.session_state.auth_complete = False
                                
                                st.rerun()  # Rerun to show the auth instructions

        # If authentication is in progress, create a container to show status
        if st.session_state.trakt_auth_in_progress and st.session_state.trakt_device_code:
            auth_container = st.container()
            
            with auth_container:
                st.info("Please authenticate with Trakt:")
                st.markdown("### [Click here to authorize](https://trakt.tv/activate)")
                
                # Make the code more prominent
                st.markdown("### Your Authorization Code:")
                st.code(st.session_state.trakt_user_code, language=None)
                
                # Add explicit instructions
                st.markdown("""
                1. Click the link above to open Trakt's activation page
                2. Enter the code shown above
                3. Authorize this application
                4. Return here and click 'Continue' when done
                """)
                
                # Add a button to confirm the user has completed authorization
                col1, col2 = st.columns([1, 1])
                with col1:
                    if st.button("Continue", key="start_polling"):
                        st.session_state.auth_polling_started = True
                        st.rerun()
                with col2:
                    if st.button("Cancel", key="cancel_auth"):
                        st.session_state.trakt_auth_in_progress = False
                        st.session_state.trakt_device_code = None
                        st.session_state.trakt_user_code = None
                        st.session_state.trakt_poll_interval = None
                        st.session_state.auth_polling_started = False
                        st.rerun()

                # Only start polling after the user clicks 'Continue'
                if st.session_state.auth_polling_started:
                    with st.spinner("Verifying authorization..."):
                        # Poll for access token
                        access_token = poll_for_access_token(
                            st.session_state.trakt_device_code, 
                            st.session_state.trakt_poll_interval
                        )
                        
                        if access_token:
                            # Authentication successful - reset auth state and continue with sync
                            st.session_state.trakt_auth_in_progress = False
                            st.session_state.trakt_device_code = None
                            st.session_state.trakt_user_code = None
                            st.session_state.trakt_poll_interval = None
                            st.session_state.auth_polling_started = False
                            st.session_state.auth_complete = True
                            
                            # Start the sync process
                            st.session_state.sync_in_progress = True
                            st.session_state.sync_progress = {}
                            st.session_state.current_message = "Authentication successful! Starting sync..."
                            st.success("✅ Successfully connected to Trakt!")
                            time.sleep(1)  # Brief pause to show success message
                            st.rerun()
                        else:
                            # Authentication failed or timed out
                            st.error("❌ Authentication failed or timed out. Please try again.")
                            st.session_state.trakt_auth_in_progress = False
                            st.session_state.auth_polling_started = False
                            time.sleep(2)  # Show error message for a moment
                            st.rerun()

        # Create placeholders for status and progress
        status_placeholder = st.empty()
        progress_placeholder = st.empty()

        # Handle sync if in progress
        if st.session_state.sync_in_progress:
            try:
                access_token = get_access_token()
                if access_token:
                    for trakt_list in st.session_state.trakt_lists:
                        sync_trakt_list_to_emby(trakt_list, access_token, update_progress)
                        
                        # Show current status and progress
                        status_placeholder.text(st.session_state.current_message)
                        
                        with progress_placeholder.container():
                            for collection_name, progress_data in st.session_state.sync_progress.items():
                                if collection_name:  # Only show progress for actual collections
                                    progress = progress_data['progress']
                                    processed = progress_data['processed']
                                    total = progress_data['total']
                                    
                                    st.write(f"**{collection_name}**")
                                    st.progress(progress)
                                    st.write(f"Processed {processed} of {total} items")
                
                    st.session_state.last_sync = datetime.now()
                    st.session_state.sync_in_progress = False
                    st.success("✅ Sync completed successfully!")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.error("Failed to sync with Trakt")
                    st.session_state.sync_in_progress = False
            except Exception as e:
                st.error(f"An error occurred during sync: {str(e)}")
                st.session_state.sync_in_progress = False
                st.session_state.sync_progress = {}
                st.session_state.current_message = ""

        # Show current status and progress if active
        if st.session_state.current_message:
            status_placeholder.text(st.session_state.current_message)

        if st.session_state.sync_progress:
            with progress_placeholder.container():
                for collection_name, progress_data in st.session_state.sync_progress.items():
                    if collection_name:  # Only show progress for actual collections
                        progress = progress_data['progress']
                        processed = progress_data['processed']
                        total = progress_data['total']
                        
                        st.write(f"**{collection_name}**")
                        st.progress(progress)
                        st.write(f"Processed {processed} of {total} items")

        # Trakt Lists Management
        st.header("Trakt Lists")

        # Display existing lists
        for i, list_data in enumerate(st.session_state.trakt_lists):
            with st.expander(f"List: {list_data['collection_name']}", expanded=True):
                col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
                
                with col1:
                    new_name = st.text_input("Collection Name", list_data['collection_name'], key=f"name_{i}")
                with col2:
                    new_list_id = st.text_input("List ID", list_data['list_id'], key=f"id_{i}")
                with col3:
                    new_type = st.selectbox("Type", ["movies", "shows"], 
                                          index=0 if list_data['type'] == "movies" else 1,
                                          key=f"type_{i}")
                with col4:
                    if st.button("Delete", key=f"delete_{i}"):
                        st.session_state.trakt_lists.pop(i)
                        save_trakt_lists()
                        st.rerun()
                
                # Update list if values changed
                if (new_name != list_data['collection_name'] or 
                    new_list_id != list_data['list_id'] or 
                    new_type != list_data['type']):
                    list_data.update({
                        'collection_name': new_name,
                        'list_id': new_list_id,
                        'type': new_type,
                        'library_id': list_data['library_id']  # Preserve existing library ID
                    })
                    save_trakt_lists()

        # Add new list
        st.header("Add New List")
        with st.form("new_list_form"):
            col1, col2, col3 = st.columns(3)
            with col1:
                new_name = st.text_input("Collection Name")
            with col2:
                new_list_id = st.text_input("List ID")
            with col3:
                new_type = st.selectbox("Type", ["movies", "shows"])
            
            if st.form_submit_button("Add List"):
                if new_name and new_list_id:
                    new_list = {
                        "list_id": new_list_id,
                        "collection_name": new_name,
                        "type": new_type,
                        "library_id": get_config('EMBY_MOVIES_LIBRARY_ID') if new_type == "movies" else get_config('EMBY_TV_LIBRARY_ID')
                    }
                    st.session_state.trakt_lists.append(new_list)
                    save_trakt_lists()
                    st.success("New list added!")
                    st.rerun()
                else:
                    st.error("Please fill in all fields")

        # Footer with sync status
        st.markdown("---")
        st.caption("Note: Click 'Sync Now' to manually sync your Trakt lists with Emby")

# Add this near the end of the file, outside all if/else blocks
# This ensures the scheduler check runs on each Streamlit rerun
if st.session_state.scheduler_running:
    check_scheduler()