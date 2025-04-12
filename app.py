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
    get_config,
    get_missing_items,
    recheck_missing_item,
    clear_missing_items_for_collection,
    load_missing_items,
    toggle_verbose_logging,
    # New imports for ignored items functionality
    get_ignored_items,
    ignore_missing_item,
    ignore_missing_items,  # New bulk ignore function
    unignore_item,
    load_ignored_items
)
import requests

# Define helper functions that will be used across the app
def process_sync_status(progress, collection_name, processed, total, message):
    """Display sync status in the main page"""
    if progress >= 1.0:  # When sync is completed
        st.success(f"✅ Sync completed for {collection_name}")
        st.write(message)
        
        # Get count of missing items for this collection
        missing_count = 0
        for item in get_missing_items():
            if item.get('collection_name') == collection_name:
                missing_count += 1
        
        # If there are missing items, inform the user
        if missing_count > 0:
            st.warning(f"⚠️ {missing_count} items could not be found in your Emby library. Check the **Missing Items** tab for details.")
    else:
        # Show progress bar
        st.progress(progress)
        st.info(f"Processing {collection_name}: {processed}/{total} items")
        st.text(message)

def perform_sync_all():
    """Start syncing all Trakt lists to Emby"""
    # Make sure trakt_lists is loaded
    if 'trakt_lists' not in st.session_state:
        st.session_state.trakt_lists = get_trakt_lists()
    
    # Initialize state variables
    st.session_state.sync_running = True
    st.session_state.current_progress = 0.0
    st.session_state.current_message = "Starting sync..."
    st.session_state.processed_items = 0
    st.session_state.total_items = 0
    
    # Get status placeholders
    progress_placeholder = st.empty()
    status_placeholder = st.empty()
    
    # Sync all lists
    with progress_placeholder, status_placeholder:
        # Create progress bar
        progress_bar = progress_placeholder.progress(0.0)
        
        # Initialize status
        status_placeholder.text("Starting sync...")
        
        # Start sync
        try:
            # Get access token first
            access_token = get_access_token()
            if access_token:
                for trakt_list in st.session_state.trakt_lists:
                    sync_trakt_list_to_emby(trakt_list, access_token, process_sync_status)
                    
                    # Show current status and progress
                    status_placeholder.text(st.session_state.current_message)
                    progress_bar.progress(st.session_state.current_progress)
                
                # Mark sync as complete
                progress_bar.progress(1.0)
                status_placeholder.success("Sync completed!")
                
                # Check for missing items
                missing_counts = {}
                for item in get_missing_items():
                    collection = item.get('collection_name', 'Unknown')
                    if collection not in missing_counts:
                        missing_counts[collection] = 0
                    missing_counts[collection] += 1
                
                if missing_counts:
                    warning_text = "⚠️ Some items could not be found in your Emby library:\n"
                    for collection, count in missing_counts.items():
                        warning_text += f"   • {collection}: {count} items\n"
                    warning_text += "\nCheck the **Missing Items** tab for details."
                    status_placeholder.warning(warning_text)
            else:
                status_placeholder.error("Failed to obtain access token. Please check Trakt configuration.")
        except Exception as e:
            status_placeholder.error(f"Error during sync: {str(e)}")
    
    # Mark sync as completed
    st.session_state.sync_running = False

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

def add_new_list(name, list_id, list_type, library_id):
    """Add a new Trakt list to the session state and save to .env file"""
    if name and list_id:
        new_list = {
            "list_id": list_id,
            "collection_name": name,
            "type": list_type,
            "library_id": library_id
        }
        st.session_state.trakt_lists.append(new_list)
        save_trakt_lists()
        return True
    else:
        return False

# Enable Streamlit page config
st.set_page_config(
    page_title="Trakt to Emby Sync",
    page_icon="🎬",
    layout="wide",  # Use the full width of the browser window
    initial_sidebar_state="expanded"
)

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
        'EMBY_ADMIN_USER_ID'
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

# Load configuration into session state
for key in os.environ:
    st.session_state.config[key] = os.environ[key]

# Initialize Trakt lists
if 'trakt_lists' not in st.session_state:
    try:
        trakt_lists_json = get_config('TRAKT_LISTS')
        if trakt_lists_json:
            st.session_state.trakt_lists = json.loads(trakt_lists_json)
        else:
            st.session_state.trakt_lists = []
    except json.JSONDecodeError:
        st.session_state.trakt_lists = []
        print("Error parsing TRAKT_LISTS JSON")

# Initialize Emby libraries
if 'emby_libraries' not in st.session_state:
    try:
        libraries_json = get_config('EMBY_LIBRARIES') or '[]'
        st.session_state.emby_libraries = json.loads(libraries_json)
    except json.JSONDecodeError:
        st.session_state.emby_libraries = []
        print("Error parsing EMBY_LIBRARIES JSON")

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
    
    # Force reload of environment variables
    load_dotenv(override=True)
    
    # Update session state config to match
    st.session_state.config['TRAKT_LISTS'] = trakt_lists_json

def save_emby_libraries():
    """Save Emby libraries to .env file"""
    env_lines = []
    with open('.env', 'r') as f:
        for line in f:
            if not line.startswith('EMBY_LIBRARIES='):
                env_lines.append(line.strip())
    
    emby_libraries_json = json.dumps(st.session_state.emby_libraries)
    env_lines.append(f'EMBY_LIBRARIES={emby_libraries_json}')
    
    with open('.env', 'w') as f:
        f.write('\n'.join(env_lines))
    
    # Force reload of environment variables
    load_dotenv(override=True)
    
    # Update session state config to match
    st.session_state.config['EMBY_LIBRARIES'] = emby_libraries_json

def delete_library(index):
    """Delete a library from the session state and save to .env file"""
    st.session_state.emby_libraries.pop(index)
    save_emby_libraries()

def delete_trakt_list(index):
    """Delete a Trakt list from the session state and save to .env file"""
    # Get the collection name before deleting
    collection_name = st.session_state.trakt_lists[index]['collection_name']
    
    # Delete from session state
    st.session_state.trakt_lists.pop(index)
    save_trakt_lists()
    
    # Also clear any missing items for this collection
    clear_missing_items_for_collection(collection_name)

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

# Add function to check Emby connection status
def check_emby_status():
    """Check if Emby server is accessible"""
    server_url = get_config('EMBY_SERVER')
    api_key = get_config('EMBY_API_KEY')
    
    if not server_url or not api_key:
        return False
    
    try:
        headers = {'X-Emby-Token': api_key}
        response = requests.get(f"{server_url.rstrip('/')}/System/Info", headers=headers, timeout=5)
        return response.status_code == 200
    except Exception:
        return False

# Add function to quit the application
def quit_application():
    """Quit the application and any running console_runner.py process"""
    # Try to find and kill console_runner.py process
    try:
        import os
        import signal
        import subprocess
        
        # On Windows, use taskkill to forcefully terminate Python processes running console_runner.py
        if os.name == 'nt':  # Windows
            try:
                # Use tasklist to find Python processes
                result = subprocess.run(
                    ['tasklist', '/FI', 'IMAGENAME eq python.exe', '/FO', 'CSV'], 
                    capture_output=True, 
                    text=True, 
                    check=True
                )
                
                # Kill the Streamlit process
                subprocess.run(['taskkill', '/F', '/IM', 'streamlit.exe'], 
                               capture_output=True, 
                               check=False)
                
                # Kill Python processes
                subprocess.run(['taskkill', '/F', '/IM', 'python.exe'], 
                               capture_output=True, 
                               check=False)
                
                print("Terminated all Python processes")
            except subprocess.SubprocessError as e:
                print(f"Error terminating processes: {e}")
        else:  # Unix-like systems
            try:
                # Use ps and grep to find Python processes running console_runner.py
                ps_output = subprocess.check_output(
                    ['ps', '-ef'], 
                    text=True
                )
                
                for line in ps_output.splitlines():
                    if 'python' in line and 'console_runner.py' in line:
                        # Extract PID (second column in ps output)
                        pid = int(line.split()[1])
                        os.kill(pid, signal.SIGTERM)
                        print(f"Terminated console_runner.py process (PID: {pid})")
            except (subprocess.SubprocessError, ValueError) as e:
                print(f"Error terminating processes: {e}")
    except ImportError:
        # subprocess not available
        pass
    
    # Exit the current process
    import sys
    sys.exit(0)

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
    page = st.sidebar.radio("Go to", ["Main", "Settings", "Missing Items", "Ignored Items"])

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
        You can specify different Emby libraries for each Trakt list in the Main page.
        To find your library IDs:
        1. Go to Emby Dashboard
        2. Click "Libraries"
        3. Click on your library (Movies, TV Shows, Movies 4K, etc.)
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
        
        # Add Check Emby Configuration button
        if st.button("Check Emby Connection"):
            with st.spinner("Testing Emby connection..."):
                results = check_configuration()
                st.write(results['emby']['message'])
        
        # Library Management Section
        st.header("Library Management")
        st.markdown("Add your Emby libraries here with friendly names. These will be available for selection when adding Trakt lists.")
        
        # Display existing libraries
        for i, library in enumerate(st.session_state.emby_libraries):
            col1, col2, col3, col4 = st.columns([3, 3, 2, 1])
            
            with col1:
                st.write("Library Name")
                new_name = st.text_input("##", library['name'], key=f"lib_name_{i}", label_visibility="collapsed")
            with col2:
                st.write("Library ID")
                new_id = st.text_input("##", library['id'], key=f"lib_id_{i}", label_visibility="collapsed")
            with col3:
                st.write("Type")
                new_type = st.selectbox("##", ["movies", "shows"], 
                                       index=0 if library['type'] == "movies" else 1,
                                       key=f"lib_type_{i}",
                                       label_visibility="collapsed")
            with col4:
                st.write("Action")
                st.button("Delete", key=f"lib_delete_{i}", use_container_width=True, on_click=lambda i=i: delete_library(i))
            
            # Update library if values changed
            if (new_name != library['name'] or 
                new_id != library['id'] or 
                new_type != library['type']):
                library.update({
                    'name': new_name,
                    'id': new_id,
                    'type': new_type
                })
                save_emby_libraries()
        
        # Add new library
        with st.form("new_library_form"):
            st.subheader("Add New Library")
            col1, col2, col3 = st.columns([3, 3, 2])
            
            with col1:
                st.write("Library Name")
                new_lib_name = st.text_input("##", placeholder="Movies 4K", key="new_lib_name", label_visibility="collapsed")
            with col2:
                st.write("Library ID")
                new_lib_id = st.text_input("##", placeholder="Enter the Emby library ID", key="new_lib_id", label_visibility="collapsed")
            with col3:
                st.write("Type")
                new_lib_type = st.selectbox("##", ["movies", "shows"], key="new_lib_type", label_visibility="collapsed")
            
            submitted = st.form_submit_button("Add Library", use_container_width=True)
            if submitted:
                if new_lib_name and new_lib_id:
                    new_library = {
                        "name": new_lib_name,
                        "id": new_lib_id,
                        "type": new_lib_type
                    }
                    st.session_state.emby_libraries.append(new_library)
                    save_emby_libraries()
                    st.success("New library added!")
                    st.rerun()
                else:
                    st.error("Please fill in all fields")
        
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
        
        # Add option to control verbose logging
        st.markdown("---")
        st.subheader("Debugging Options")
        verbose_logging = st.toggle("Enable Verbose Logging", value=False, help="Enable detailed logs for debugging")
        if verbose_logging:
            st.info("Verbose logging is enabled. You will see detailed information during sync processes.")
            toggle_verbose_logging(True)
        else:
            toggle_verbose_logging(False)

elif page == "Missing Items":
    st.title("Missing Items")
    st.markdown("This page shows items from your Trakt lists that are missing from your Emby libraries.")
    
    # Add instructions
    st.markdown("""
    ### Instructions
    
    Items listed here couldn't be automatically matched with content in your Emby library.
    
    - To manually match an item: Paste the full Emby URL to the movie/show in the 'Manual Emby URL' field and click **Recheck**
    - You can find this URL by opening the movie/show in Emby and copying the address from your browser
    - If you've added new content to your library, click **Recheck All** to try matching everything again
    - Items that were manually matched will be removed from this list
    """)
    
    # Load missing items
    missing_items = get_missing_items()
    
    if not missing_items:
        st.info("No missing items. All Trakt items have been found in Emby!")
    else:
        # Group items by collection
        collections = {}
        for i, item in enumerate(missing_items):
            # Handle both old and new format
            if 'collections' in item and item['collections']:
                for collection_info in item['collections']:
                    collection = collection_info.get('name', 'Unknown')
                    if collection not in collections:
                        collections[collection] = []
                    # Only add the item once per collection
                    if not any(idx == i for idx, _ in collections[collection]):
                        collections[collection].append((i, item))
            else:  # Fallback to old format
                collection = item.get('collection_name', 'Unknown')
                if collection not in collections:
                    collections[collection] = []
                collections[collection].append((i, item))
        
        # Action buttons at the top
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("Recheck All", type="primary"):
                recheck_results = []
                with st.spinner("Rechecking all missing items..."):
                    for i in range(len(missing_items)):
                        success, message = recheck_missing_item(i)
                        if success:
                            recheck_results.append(f"✅ {missing_items[i]['title']}: {message}")
                        else:
                            recheck_results.append(f"❌ {missing_items[i]['title']}: {message}")
                
                # Show results in an expander
                with st.expander("Recheck Results", expanded=True):
                    for result in recheck_results:
                        st.write(result)
                
                # Refresh the page to show updated list
                st.rerun()
        
        # Button to ignore all selected items
        selected_items = []
        st.subheader("Bulk Actions")
        with st.expander("Select items to ignore", expanded=False):
            
            # Create a selectbox for each collection
            for collection, items in collections.items():
                st.write(f"**{collection}** ({len(items)} items)")
                
                # Create three columns for more compact UI
                cols = st.columns(3)
                
                # Create checkboxes for all items in this collection
                for i, (index, item) in enumerate(items):
                    col_idx = i % 3  # Distribute across 3 columns
                    title = item.get('title', 'Unknown')
                    year = item.get('year', '')
                    with cols[col_idx]:
                        if st.checkbox(f"{title} ({year})", key=f"select_{collection}_{index}"):
                            selected_items.append(index)
            
            # Show selected count and Add ignore button if items are selected
            if selected_items:
                st.write(f"{len(selected_items)} items selected")
                if st.button("Ignore All Selected Items"):
                    with st.spinner("Ignoring selected items..."):
                        success, message = ignore_missing_items(selected_items)
                        if success:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)
        
        # Display items by collection in collapsible expanders
        st.subheader("Missing Items by Collection")
        for collection, items in collections.items():
            with st.expander(f"{collection} ({len(items)} items)", expanded=False):
                for i, (index, item) in enumerate(items):
                    with st.container():
                        col1, col2, col3 = st.columns([2, 2, 1])
                        
                        with col1:
                            title = item.get('title', 'Unknown')
                            year = item.get('year', '')
                            media_type = item.get('type', 'movie').capitalize()
                            st.subheader(f"{title} ({year})")
                            st.write(f"Type: {media_type}")
                            
                            # Show provider IDs
                            trakt_ids = item.get('ids', {})
                            if trakt_ids:
                                show_ids = st.toggle("Show Trakt IDs", key=f"show_ids_{index}", value=False)
                                if show_ids:
                                    st.write("**Trakt IDs:**")
                                    for id_type, id_value in trakt_ids.items():
                                        st.write(f"- **{id_type}**: {id_value}")
                    
                        with col2:
                            st.text(f"Last checked: {item.get('last_checked', 'Never')}")
                            st.text(f"Reason: {item.get('reason', 'Unknown')}")
                            
                            # Display collections the item belongs to
                            if 'collections' in item and len(item['collections']) > 0:
                                collections_list = [c.get('name', 'Unknown') for c in item.get('collections', [])]
                                if collections_list:
                                    st.write(f"**In collections:** {', '.join(collections_list)}")
                            
                            # Manual URL input
                            emby_url = st.text_input("Manual Emby URL", key=f"url_{index}", 
                                                   placeholder="Paste Emby URL here...")
                            
                            # Add ignore toggle
                            ignore = st.toggle("Ignore this item", key=f"ignore_{index}", value=False)
                            if ignore:
                                if st.button("Confirm Ignore", key=f"confirm_ignore_{index}"):
                                    with st.spinner(f"Ignoring {title}..."):
                                        success, message = ignore_missing_item(index)
                                        if success:
                                            st.success(message)
                                            st.rerun()
                                        else:
                                            st.error(message)
                    
                        with col3:
                            # Extract Emby ID from URL if provided
                            emby_id = None
                            if emby_url:
                                # Try to extract ID from URL - enhanced pattern matching for more URL formats
                                import re
                                # Handle multiple Emby URL patterns:
                                # 1. /item?id=XXX format
                                # 2. /item/XXX format
                                # 3. /Details/XXX format
                                # 4. /web/index.html#!/item?id=XXX format
                                # 5. /web/index.html#!/Details/XXX format
                                match = re.search(r'(?:item\?id=|item/|Details/|emby\.dll\?id=|\#!/item\?id=|\#!/Details/)([^&\s/#]+)', emby_url)
                                if match:
                                    emby_id = match.group(1)
                                    st.info(f"Extracted Emby ID: {emby_id}")
                                else:
                                    st.warning("Could not extract Emby ID from URL. Please make sure you're using the direct link to the item in Emby.")
                            
                            # Recheck button with extracted ID
                            if st.button("Recheck", key=f"recheck_{index}"):
                                with st.spinner(f"Rechecking {title}..."):
                                    success, message = recheck_missing_item(index, emby_id)
                            
                                if success:
                                    st.success(message)
                                    st.rerun()
                                else:
                                    st.error(message)
                    
                    st.divider()

elif page == "Ignored Items":
    st.title("Ignored Items")
    st.markdown("This page shows items from your Trakt lists that you've chosen to ignore.")
    
    # Load ignored items
    ignored_items = get_ignored_items()
    
    if not ignored_items:
        st.info("No ignored items.")
    else:
        # Group items by collection
        collections = {}
        for i, item in enumerate(ignored_items):
            # Get collection name - handle both old and new format
            if 'collections' in item and item['collections']:
                # New format - use first collection in the list
                collection = item['collections'][0].get('name', 'Unknown')
            else:
                # Old format or fallback
                collection = item.get('collection_name', 'Unknown')
                
            if collection not in collections:
                collections[collection] = []
            collections[collection].append((i, item))
        
        # Display items by collection in collapsible expanders
        for collection, items in collections.items():
            with st.expander(f"{collection} ({len(items)} items)", expanded=False):
                for i, (index, item) in enumerate(items):
                    with st.container():
                        col1, col2, col3 = st.columns([2, 2, 1])
                        
                        with col1:
                            title = item.get('title', 'Unknown')
                            year = item.get('year', '')
                            media_type = item.get('type', 'movie').capitalize()
                            st.subheader(f"{title} ({year})")
                            st.write(f"Type: {media_type}")
                            
                            # Show provider IDs
                            trakt_ids = item.get('ids', {})
                            if trakt_ids:
                                show_ids = st.toggle("Show Trakt IDs", key=f"show_ids_{index}", value=False)
                                if show_ids:
                                    st.write("**Trakt IDs:**")
                                    for id_type, id_value in trakt_ids.items():
                                        st.write(f"- **{id_type}**: {id_value}")
                    
                        with col2:
                            st.text(f"Ignored reason: {item.get('reason', 'Unknown')}")
                            st.text(f"Ignored on: {item.get('ignored_on', 'Unknown')}")
                            
                            # Display all collections the item belongs to
                            if 'collections' in item and len(item['collections']) > 0:
                                collections_list = [c.get('name', 'Unknown') for c in item.get('collections', [])]
                                if collections_list:
                                    st.write(f"**In collections:** {', '.join(collections_list)}")
                    
                        with col3:
                            # Unignore button
                            if st.button("Unignore", key=f"unignore_{index}"):
                                unignore_item(index)
                                st.success(f"{title} has been unignored.")
                                st.rerun()
                    
                    st.divider()

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
        # Status indicators and action buttons in a row
        col1, col2, col3 = st.columns([4, 1, 1])
        
        with col1:
            # Status indicators in a row
            status_col1, status_col2 = st.columns(2)
            
            with status_col1:
                # Check Trakt status
                token_valid, token_message = check_token_status()
                if token_valid:
                    st.markdown("Trakt Status: 🟢 Connected")
                else:
                    st.markdown("Trakt Status: 🔴 Disconnected")
            
            with status_col2:
                # Check Emby status
                emby_status = check_emby_status()
                if emby_status:
                    st.markdown("Emby Status: 🟢 Connected")
                else:
                    st.markdown("Emby Status: 🔴 Disconnected")
            
            # Display last sync time if available
            if st.session_state.last_sync:
                st.caption(f"Last Sync: {st.session_state.last_sync.strftime('%Y-%m-%d %H:%M:%S')}")
        
        with col2:
            # Sync button
            if not st.session_state.sync_in_progress:
                if st.button("Sync Now", type="primary", use_container_width=True):
                    if token_valid:
                        perform_sync_all()
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
        
        with col3:
            # Quit button
            if st.button("Quit", type="secondary", use_container_width=True):
                quit_application()
        
        # Token Status and Sync Button
        token_valid, token_message = check_token_status()

        # Create placeholders for status and progress
        status_placeholder = st.empty()
        progress_placeholder = st.empty()

        # Handle sync if in progress
        if st.session_state.sync_in_progress:
            try:
                access_token = get_access_token()
                if access_token:
                    for trakt_list in st.session_state.trakt_lists:
                        sync_trakt_list_to_emby(trakt_list, access_token, process_sync_status)
                        
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
                    st.success("👍 Sync completed successfully!")
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
                            st.success("👍 Successfully connected to Trakt!")
                            time.sleep(1)  # Brief pause to show success message
                            st.rerun()
                        else:
                            # Authentication failed or timed out
                            st.error("🚫 Authentication failed or timed out. Please try again.")
                            st.session_state.trakt_auth_in_progress = False
                            st.session_state.auth_polling_started = False
                            time.sleep(2)  # Show error message for a moment
                            st.rerun()
        
        # Trakt Lists Management
        st.header("Trakt Lists")

        # Display existing lists
        for i, list_data in enumerate(st.session_state.trakt_lists):
            with st.expander(f"List: {list_data['collection_name']}", expanded=True):
                col1, col2, col3, col4, col5 = st.columns([3, 3, 2, 3, 1])
                
                with col1:
                    st.write("Collection Name")
                    new_name = st.text_input("##", list_data['collection_name'], key=f"name_{i}", label_visibility="collapsed")
                with col2:
                    st.write("List ID")
                    new_list_id = st.text_input("##", list_data['list_id'], key=f"id_{i}", label_visibility="collapsed")
                with col3:
                    st.write("Type")
                    new_type = st.selectbox("##", ["movies", "shows"], 
                                          index=0 if list_data['type'] == "movies" else 1,
                                          key=f"type_{i}", label_visibility="collapsed")
                with col4:
                    st.write("Library")
                    # Filter libraries by type
                    filtered_libraries = [lib for lib in st.session_state.emby_libraries 
                                         if lib['type'] == new_type]
                    
                    # Create options list with library name and ID
                    library_options = [f"{lib['name']} ({lib['id']})" for lib in filtered_libraries]
                    
                    # If no libraries available, show message
                    if not library_options:
                        st.warning(f"No {new_type} libraries configured. Please add libraries in Settings.")
                        new_library_id = ""
                    else:
                        # Find current library in options
                        current_library_id = list_data.get('library_id', '')
                        selected_index = 0  # Default to first option
                        
                        for idx, lib in enumerate(filtered_libraries):
                            if lib['id'] == current_library_id:
                                selected_index = idx
                                break
                        
                        library_selection = st.selectbox(
                            "##",
                            options=library_options,
                            index=min(selected_index, len(library_options)-1) if library_options else 0,
                            key=f"library_select_{i}",
                            label_visibility="collapsed"
                        )
                        
                        # Extract ID from selection
                        selected_lib_id = library_selection.split("(")[-1].split(")")[0]
                        new_library_id = selected_lib_id
                with col5:
                    st.write("Action")
                    st.button("Delete", key=f"delete_{i}", use_container_width=True, on_click=lambda i=i: delete_trakt_list(i))
                
                # Update list if values changed
                if (new_name != list_data['collection_name'] or 
                    new_list_id != list_data['list_id'] or 
                    new_type != list_data['type'] or
                    new_library_id != list_data.get('library_id', '')):
                    list_data.update({
                        'collection_name': new_name,
                        'list_id': new_list_id,
                        'type': new_type,
                        'library_id': new_library_id
                    })
                    save_trakt_lists()

        # Add new list
        st.header("Add New List")
        
        # Create form outside of columns for better reactivity
        new_name = st.text_input("Collection Name", placeholder="My Trakt List", key="new_name")
        new_list_id = st.text_input("List ID", placeholder="123456", key="new_list_id")
        
        # Type selection that will affect library options
        new_type = st.selectbox("Type", ["movies", "shows"], key="new_type")
        
        # Filter libraries by selected type
        filtered_libraries = [lib for lib in st.session_state.emby_libraries 
                             if lib['type'] == new_type]
        
        # Create options list with library name and ID
        library_options = [f"{lib['name']} ({lib['id']})" for lib in filtered_libraries]
        
        # Library selection
        if not library_options:
            st.warning(f"No {new_type} libraries configured. Please add libraries in Settings.")
            new_library_id = ""
        else:
            library_selection = st.selectbox(
                "Library",
                options=library_options,
                index=0,
                key=f"new_library_select_{new_type}"  # Key depends on type to force refresh
            )
            
            # Extract ID from selection
            selected_lib_id = library_selection.split("(")[-1].split(")")[0]
            new_library_id = selected_lib_id
        
        # Add button
        if st.button("Add List", type="primary", use_container_width=True):
            if new_name and new_list_id:
                if add_new_list(new_name, new_list_id, new_type, new_library_id):
                    st.success("New list added!")
                    st.rerun()
                else:
                    st.error("Please fill in all fields")
            else:
                st.error("Please fill in all fields")
        
        # Footer with sync status
        st.markdown("---")
        st.caption("Note: Click 'Sync Now' to manually sync your Trakt lists with Emby")
