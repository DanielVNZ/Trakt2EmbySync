import streamlit as st
import json
import os
import schedule
import threading
import time
from datetime import datetime
from dotenv import load_dotenv
from sync_Trakt_to_emby import (
    get_trakt_device_code,
    poll_for_access_token,
    load_token,
    refresh_access_token,
    sync_trakt_list_to_emby,
    get_access_token,
    sync_all_trakt_lists,
    check_required_env_vars
)
import requests
import pickle
import hashlib

# Enable Streamlit authentication
st.set_page_config(page_title="Trakt to Emby Sync")

# Add authentication
def get_user_hash():
    """Get a unique hash for the current user"""
    if not st.session_state.get("user_hash"):
        # Create a random session ID if not exists
        st.session_state.user_hash = hashlib.sha256(str(time.time()).encode()).hexdigest()[:16]
    return st.session_state.user_hash

def get_user_config_path():
    """Get the path to the user's configuration file"""
    user_hash = get_user_hash()
    config_dir = "user_configs"
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    return os.path.join(config_dir, f"config_{user_hash}.pkl")

def load_user_config():
    """Load user configuration from file"""
    config_path = get_user_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            st.error(f"Error loading configuration: {str(e)}")
    return None

def save_user_config():
    """Save user configuration to file"""
    config_path = get_user_config_path()
    try:
        with open(config_path, 'wb') as f:
            pickle.dump(st.session_state.config, f)
        return True
    except Exception as e:
        st.error(f"Error saving configuration: {str(e)}")
        return False

# Initialize session state for user configuration
if 'config' not in st.session_state:
    # Try to load existing configuration
    saved_config = load_user_config()
    if saved_config:
        st.session_state.config = saved_config
    else:
        # Initialize with empty values
        st.session_state.config = {
            'TRAKT_CLIENT_ID': '',
            'TRAKT_CLIENT_SECRET': '',
            'EMBY_API_KEY': '',
            'EMBY_SERVER': '',
            'EMBY_ADMIN_USER_ID': '',
            'EMBY_MOVIES_LIBRARY_ID': '',
            'EMBY_TV_LIBRARY_ID': '',
            'SYNC_INTERVAL': '6h',
            'TRAKT_LISTS': []
        }

# Load configuration from secrets if available (for production)
if hasattr(st, 'secrets'):
    for key in st.session_state.config.keys():
        if key in st.secrets:
            st.session_state.config[key] = st.secrets[key]

def save_config():
    """Save configuration to session state"""
    # In production, configuration is stored in session state
    # In development, you might want to save to .env file
    if not hasattr(st, 'secrets'):  # We're in development
        env_content = []
        for key, value in st.session_state.config.items():
            if key == 'TRAKT_LISTS':
                env_content.append(f'{key}={json.dumps(value)}')
            else:
                env_content.append(f'{key}={value}')
        
        with open('.env', 'w') as f:
            f.write('\n'.join(env_content))

def get_config(key):
    """Get configuration value from session state"""
    return st.session_state.config.get(key, '')

def set_config(key, value):
    """Set configuration value in session state and save to file"""
    st.session_state.config[key] = value
    save_user_config()

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

# Create default .env if it doesn't exist and force settings page if it was just created
is_new_install = create_default_env()

# Load environment variables
load_dotenv()

# Initialize session state
if 'page' not in st.session_state:
    st.session_state.page = 'settings' if is_new_install else 'main'

if 'config_checked' not in st.session_state:
    st.session_state.config_checked = False

if 'trakt_lists' not in st.session_state:
    trakt_lists_env = get_config('TRAKT_LISTS')
    if trakt_lists_env:
        try:
            st.session_state.trakt_lists = json.loads(trakt_lists_env)
        except json.JSONDecodeError:
            st.session_state.trakt_lists = []
    else:
        st.session_state.trakt_lists = []

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
            response = requests.get(
                f"{emby_server}/emby/System/Info/Public",
                params={"api_key": required_emby['EMBY_API_KEY']}
            )
            
            if response.status_code == 200:
                # Test library access
                movies_response = requests.get(
                    f"{emby_server}/emby/Items",
                    params={
                        "api_key": required_emby['EMBY_API_KEY'],
                        "ParentId": required_emby['EMBY_MOVIES_LIBRARY_ID'],
                        "Limit": 1
                    }
                )
                shows_response = requests.get(
                    f"{emby_server}/emby/Items",
                    params={
                        "api_key": required_emby['EMBY_API_KEY'],
                        "ParentId": required_emby['EMBY_TV_LIBRARY_ID'],
                        "Limit": 1
                    }
                )
                
                if movies_response.status_code == 200 and shows_response.status_code == 200:
                    results['emby']['status'] = True
                    server_info = response.json()
                    results['emby']['message'] = f"✅ Connected to Emby Server: {server_info.get('ServerName', '')}"
                else:
                    results['emby']['message'] = "❌ Could not access movie or TV show libraries"
            else:
                results['emby']['message'] = f"❌ Could not connect to Emby server: HTTP {response.status_code}"
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
        
        # Get current sync interval
        current_interval = get_config('SYNC_INTERVAL')
        
        interval_options = {
            '6h': 'Every 6 Hours',
            '1d': 'Daily',
            '1w': 'Weekly',
            '2w': 'Fortnightly',
            '1m': 'Monthly'
        }
        
        selected_interval = st.selectbox(
            "Sync Frequency",
            options=list(interval_options.keys()),
            format_func=lambda x: interval_options[x],
            index=list(interval_options.keys()).index(current_interval)
        )
        
        if selected_interval != current_interval:
            set_config('SYNC_INTERVAL', selected_interval)
            st.success("✅ Sync schedule updated!")
        
        # Show next sync time based on schedule
        if selected_interval == '6h':
            st.info("🕒 Sync will run every 6 hours")
        elif selected_interval == '1d':
            st.info("🕒 Sync will run daily at midnight")
        elif selected_interval == '1w':
            st.info("🕒 Sync will run weekly")
        elif selected_interval == '2w':
            st.info("🕒 Sync will run every two weeks")
        else:  # monthly
            st.info("🕒 Sync will run monthly")
    
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
        1. Open Emby Server Dashboard
        2. Go to "Advanced" → "Security"
        3. Scroll to "API Keys"
        4. Click "+" to create a new key
        5. Copy the generated key
        
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
            help="Your Emby API key",
            type="password"
        )
        if emby_api_key != get_config('EMBY_API_KEY'):
            set_config('EMBY_API_KEY', emby_api_key)
            st.success("✅ Emby API Key updated!")
        
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
        if st.button("Check Emby Configuration"):
            with st.spinner("Testing Emby configuration..."):
                results = check_configuration()
                st.write(results['emby']['message'])

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
                                st.info("Please visit the URL shown below and enter the code to authorize")
                                st.markdown("### [Click here to authorize](https://trakt.tv/activate)")
                                st.code(user_code, language=None)
                                
                                with st.spinner("Waiting for authorization..."):
                                    access_token = poll_for_access_token(device_code, interval)
                                    if access_token:
                                        st.success("✅ Successfully connected to Trakt!")
                                        st.session_state.sync_in_progress = True
                                        st.session_state.sync_progress = {}
                                        st.session_state.current_message = "Starting sync..."
                                        st.rerun()
                                    else:
                                        st.error("❌ Failed to connect to Trakt. Please try again.")

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