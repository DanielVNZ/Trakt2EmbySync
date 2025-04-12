import requests
import time
import schedule
import json
import os
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import streamlit as st
from datetime import datetime, timedelta

# Add these global variables near the top of the file with other global variables
_library_cache = {}
_missing_items = []
_ignored_items = []  # New global variable for ignored items
_emby_id_mapping = {}
_verbose_logging = False  # Control the verbosity of logging

# Functions to manage Emby ID mappings
def save_emby_id_mappings():
    """Save Emby ID mappings to a JSON file"""
    global _emby_id_mapping
    try:
        # Create a copy of the dictionary to avoid modification during serialization
        mapping_copy = dict(_emby_id_mapping)
        with open('emby_id_mappings.json', 'w') as f:
            json.dump(mapping_copy, f, indent=2)
        print(f"Saved {len(mapping_copy)} Emby ID mappings to file")
        return True
    except Exception as e:
        print(f"Error saving Emby ID mappings: {e}")
        return False

def load_emby_id_mappings():
    """Load Emby ID mappings from JSON file"""
    global _emby_id_mapping
    try:
        if os.path.exists('emby_id_mappings.json'):
            with open('emby_id_mappings.json', 'r') as f:
                _emby_id_mapping = json.load(f)
            print(f"Loaded {len(_emby_id_mapping)} Emby ID mappings from file")
        else:
            _emby_id_mapping = {}
            print("No Emby ID mappings file found, starting with empty dictionary")
        return _emby_id_mapping
    except Exception as e:
        print(f"Error loading Emby ID mappings: {e}")
        _emby_id_mapping = {}
        return {}

def add_emby_id_mapping(trakt_id, emby_id, item_type, title):
    """Store a mapping between Trakt ID and Emby ID"""
    global _emby_id_mapping
    mapping_key = f"{item_type}_{trakt_id}"
    
    # Create or update the mapping
    _emby_id_mapping[mapping_key] = {
        "emby_id": emby_id,
        "type": item_type,
        "title": title,
        "last_updated": datetime.now().isoformat()
    }
    
    # Save to file after each update (can be optimized later if needed)
    try:
        save_emby_id_mappings()
        log_debug(f" Saved mapping for {title}")
    except Exception as e:
        log_error(f" Error saving ID mapping: {str(e)}")
    return True

def get_emby_id_from_mapping(item_type, trakt_id):
    """Get Emby ID from mapping if it exists"""
    global _emby_id_mapping
    key = f"{item_type}_{trakt_id}"
    mapping = _emby_id_mapping.get(key)
    if mapping:
        return mapping.get("emby_id")
    return None

def extract_emby_id_from_url(url):
    """Extract Emby item ID from a URL"""
    if not url or "id=" not in url:
        return None
    
    try:
        # Extract ID from URL 
        url_parts = url.split("id=")
        if len(url_parts) > 1:
            id_part = url_parts[1]
            if "&" in id_part:
                emby_id = id_part.split("&")[0]
            else:
                emby_id = id_part
            print(f"Extracted Emby ID from URL: {emby_id}")
            return emby_id
    except Exception as e:
        print(f"Could not extract ID from URL: {e}")
    
    return None

# Functions to manage missing items
def save_missing_items():
    """Save missing items to a JSON file"""
    global _missing_items
    try:
        with open('missing_items.json', 'w') as f:
            json.dump(_missing_items, f, indent=2)
        print(f"Saved {len(_missing_items)} missing items to file")
        return True
    except Exception as e:
        print(f"Error saving missing items: {e}")
        return False

def load_missing_items():
    """Load missing items from JSON file"""
    global _missing_items
    try:
        if os.path.exists('missing_items.json'):
            with open('missing_items.json', 'r') as f:
                _missing_items = json.load(f)
            print(f"Loaded {len(_missing_items)} missing items from file")
        else:
            _missing_items = []
            print("No missing items file found, starting with empty list")
        return _missing_items
    except Exception as e:
        print(f"Error loading missing items: {e}")
        _missing_items = []
        return []

def clear_missing_items_for_collection(collection_name):
    """Remove all missing items for a specific collection"""
    global _missing_items
    _missing_items = [item for item in _missing_items if item.get('collection_name') != collection_name]
    save_missing_items()
    return len(_missing_items)

def get_missing_items():
    """Get the list of missing items"""
    global _missing_items
    return _missing_items

# Functions to manage ignored items
def save_ignored_items():
    """Save ignored items to a JSON file"""
    global _ignored_items
    try:
        with open('ignored_items.json', 'w') as f:
            json.dump(_ignored_items, f, indent=2)
        print(f"Saved {len(_ignored_items)} ignored items to file")
        return True
    except Exception as e:
        print(f"Error saving ignored items: {e}")
        return False

def load_ignored_items():
    """Load ignored items from JSON file"""
    global _ignored_items
    try:
        if os.path.exists('ignored_items.json'):
            with open('ignored_items.json', 'r') as f:
                _ignored_items = json.load(f)
            print(f"Loaded {len(_ignored_items)} ignored items from file")
        else:
            _ignored_items = []
            print("No ignored items file found, starting with empty list")
        return _ignored_items
    except Exception as e:
        print(f"Error loading ignored items: {e}")
        _ignored_items = []
        return []

def get_ignored_items():
    """Get the list of ignored items"""
    global _ignored_items
    return _ignored_items

def ignore_missing_item(item_index):
    """Move an item from missing items to ignored items"""
    global _missing_items, _ignored_items
    
    if item_index < 0 or item_index >= len(_missing_items):
        return False, "Invalid item index"
    
    # Get the item to ignore
    item = _missing_items[item_index]
    
    # Add timestamp when it was ignored
    item['ignored_on'] = datetime.now().isoformat()
    
    # Add to ignored items
    _ignored_items.append(item)
    
    # Remove from missing items
    del _missing_items[item_index]
    
    # Save both lists
    save_missing_items()
    save_ignored_items()
    
    return True, f"Ignored item: {item.get('title')}"

def unignore_item(item_index):
    """Move an item from ignored items back to missing items"""
    global _missing_items, _ignored_items
    
    if item_index < 0 or item_index >= len(_ignored_items):
        return False, "Invalid item index"
    
    # Get the item to unignore
    item = _ignored_items[item_index]
    
    # Remove ignored_date if it exists
    if 'ignored_on' in item:
        del item['ignored_on']
    
    # Update last_checked date
    item['last_checked'] = datetime.now().isoformat()
    
    # Add to missing items
    _missing_items.append(item)
    
    # Remove from ignored items
    del _ignored_items[item_index]
    
    # Save both lists
    save_missing_items()
    save_ignored_items()
    
    return True, f"Unignored item: {item.get('title')}"

def ignore_missing_items(item_indices):
    """Move multiple items from missing items to ignored items"""
    global _missing_items, _ignored_items
    
    if not item_indices or not isinstance(item_indices, list):
        return False, "No valid items selected"
    
    # Sort indices in descending order to avoid index shifting when removing items
    sorted_indices = sorted(item_indices, reverse=True)
    
    success_count = 0
    failed_count = 0
    ignored_titles = []
    
    for index in sorted_indices:
        if index < 0 or index >= len(_missing_items):
            failed_count += 1
            continue
        
        # Get the item to ignore
        item = _missing_items[index]
        title = item.get('title', 'Unknown')
        
        # Add timestamp when it was ignored
        item['ignored_on'] = datetime.now().isoformat()
        
        # Add to ignored items
        _ignored_items.append(item)
        
        # Remove from missing items
        del _missing_items[index]
        
        success_count += 1
        ignored_titles.append(title)
    
    # Save both lists
    save_missing_items()
    save_ignored_items()
    
    if success_count > 0:
        titles_str = ", ".join(ignored_titles[:5])
        if len(ignored_titles) > 5:
            titles_str += f" and {len(ignored_titles) - 5} more"
        return True, f"Ignored {success_count} items: {titles_str}"
    else:
        return False, "No valid items were ignored"

def recheck_missing_item(item_index, manual_emby_id=None):
    """Recheck a specific missing item to see if it can now be found in Emby"""
    global _missing_items
    
    if item_index < 0 or item_index >= len(_missing_items):
        return False, "Invalid item index"
    
    item = _missing_items[item_index]
    title = item.get('title', '')
    year = item.get('year')
    item_type = item.get('type', '')
    library_id = item.get('library_id', '')
    collection_name = item.get('collection_name', '')
    trakt_ids = item.get('trakt_ids', {})
    
    # Support both old and new format for collections
    collections = item.get('collections', [])
    if not collections and collection_name:
        # Old format, convert to new format
        collections = [{'name': collection_name, 'library_id': library_id}]
    
    log_info(f"Rechecking missing {item_type}: {title} ({year})")
    
    # If a manual Emby ID was provided, use it directly
    if manual_emby_id:
        log_info(f" Using manually provided Emby ID: {manual_emby_id}")
        
        # Check if we can actually get the item from Emby
        server_url = get_EMBY_SERVER().rstrip('/')
        headers = {'X-Emby-Token': get_EMBY_API_KEY()}
        try:
            response = requests.get(f"{server_url}/Items/{manual_emby_id}", headers=headers)
            if response.status_code == 200:
                # Store mapping if we have a Trakt ID
                if trakt_ids.get('trakt'):
                    add_emby_id_mapping(trakt_ids['trakt'], manual_emby_id, item_type, title)
                
                # Process for each collection
                success_count = 0
                for collection_info in collections:
                    coll_name = collection_info.get('name', '')
                    coll_library_id = collection_info.get('library_id', '')
                    
                    # Find or create collection
                    collection_id = find_collection_by_name(coll_name)
                    if collection_id:
                        # Add item to collection
                        if add_movie_to_emby_collection(manual_emby_id, collection_id):
                            log_info(f" Added {title} to collection {coll_name}")
                            success_count += 1
                    else:
                        log_info(f" Collection {coll_name} not found")
                
                # Remove from missing items if added to at least one collection
                if success_count > 0:
                    del _missing_items[item_index]
                    save_missing_items()
                    return True, f"Added {title} to {success_count} collections"
                else:
                    return False, "Found in Emby but could not add to any collections"
            else:
                return False, f"Invalid Emby ID: {response.status_code}"
        except Exception as e:
            return False, f"Error checking manual ID: {str(e)}"
    
    # No manual ID provided, try to find it in Emby
    if item_type == 'movie':
        emby_id = search_movie_in_emby(title, year, trakt_ids, library_id)
    else:
        emby_id = search_tv_show_in_emby(title, year, trakt_ids, library_id)
    
    if emby_id:
        log_info(f" Found in Emby: {title} - ID: {emby_id}")
        
        # Process for each collection
        success_count = 0
        for collection_info in collections:
            coll_name = collection_info.get('name', '')
            
            # Find or create collection
            collection_id = find_collection_by_name(coll_name)
            if collection_id:
                # Add item to collection
                if add_movie_to_emby_collection(emby_id, collection_id):
                    log_info(f" Added {title} to collection {coll_name}")
                    success_count += 1
            else:
                log_info(f" Collection {coll_name} not found")
        
        # Remove from missing items if added to at least one collection
        if success_count > 0:
            del _missing_items[item_index]
            save_missing_items()
            return True, f"Added {title} to {success_count} collections"
        else:
            _missing_items[item_index]['reason'] = "Found in Emby but collection doesn't exist"
            save_missing_items()
            return False, f"Found {title} but could not add to any collections"
    else:
        # Still missing
        log_info(f" Still cannot find {'movie' if item_type == 'movie' else 'TV show'}: {title}")
        # Update last checked time
        _missing_items[item_index]['last_checked'] = datetime.now().isoformat()
        save_missing_items()
        return False, f"Could not find {title} in Emby library"

def add_to_missing_items(item_data, item_type, collection_name, library_id=None, reason="No matching IDs found in Emby library"):
    """Add an item to missing_items list, preventing duplicates and handling multiple collections"""
    global _missing_items, _ignored_items
    
    # Check if we have enough data to identify the item
    trakt_id = item_data.get('ids', {}).get('trakt')
    title = item_data.get('title', 'Unknown')
    
    if not trakt_id:
        print(f"Warning: No Trakt ID for {title}, can't reliably track this item")
    
    # First check if this item is in the ignored items list
    # If so, we shouldn't add it to missing items again
    for ignored_item in _ignored_items:
        ignored_trakt_id = ignored_item.get('ids', {}).get('trakt')
        if ignored_trakt_id and ignored_trakt_id == trakt_id:
            # Item is already ignored, just update its collections if needed
            if 'collections' not in ignored_item:
                ignored_item['collections'] = []
                
            # Add this collection if not already present
            collection_exists = False
            for coll in ignored_item['collections']:
                if coll.get('name') == collection_name:
                    collection_exists = True
                    break
                    
            if not collection_exists:
                ignored_item['collections'].append({
                    'name': collection_name,
                    'library_id': library_id
                })
                save_ignored_items()
                
            print(f"Info: {title} is in ignored items list, not adding to missing items")
            return False
    
    # Check if this item is already in the missing items list
    existing_item = None
    existing_index = -1
    
    for i, item in enumerate(_missing_items):
        item_trakt_id = item.get('ids', {}).get('trakt')
        if trakt_id and item_trakt_id and trakt_id == item_trakt_id:
            existing_item = item
            existing_index = i
            break
    
    # Format item data for adding to the list
    item_to_add = {
        'title': title,
        'year': item_data.get('year'),
        'ids': item_data.get('ids', {}),
        'type': item_type,
        'reason': reason,
        'last_checked': datetime.now().isoformat()
    }
    
    # Add the collection information
    collection_info = {
        'name': collection_name,
        'library_id': library_id
    }
    
    if existing_item:
        # Item exists - update or add collection information
        if 'collections' not in existing_item:
            # Migration from old format to new
            existing_item['collections'] = []
            if 'collection_name' in existing_item:
                # Add the original collection
                existing_item['collections'].append({
                    'name': existing_item['collection_name'],
                    'library_id': existing_item.get('library_id')
                })
        
        # Check if this collection is already recorded
        collection_exists = False
        for coll in existing_item['collections']:
            if coll.get('name') == collection_name:
                collection_exists = True
                break
                
        if not collection_exists:
            # Add the new collection to the list
            existing_item['collections'].append(collection_info)
            
        # Update last checked time
        existing_item['last_checked'] = datetime.now().isoformat()
    else:
        # New item - add with collection info in the new format
        item_to_add['collections'] = [collection_info]
        _missing_items.append(item_to_add)
    
    # Save the missing items to file
    save_missing_items()
    
    return True

def get_config(key):
    """Get configuration value from environment variables - always load the most recent"""
    # Always reload dotenv to get the latest values
    load_dotenv(override=True)
    return os.environ.get(key, '')

def check_required_env_vars():
    """Check if all required configuration values are set - always from env file"""
    # Always reload dotenv to get the latest values
    load_dotenv(override=True)
    
    required_vars = [
        'TRAKT_CLIENT_ID',
        'TRAKT_CLIENT_SECRET',
        'EMBY_API_KEY',
        'EMBY_SERVER',
        'EMBY_ADMIN_USER_ID'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.environ.get(var):
            missing_vars.append(var)
    
    return len(missing_vars) == 0, missing_vars

# Always reload environment variables
load_dotenv(override=True)

# Check environment variables before initializing
env_valid, missing_vars = check_required_env_vars()

# Load missing items, ignored items, and Emby ID mappings from file
load_missing_items()
load_ignored_items()
load_emby_id_mappings()

# Initialize variables dynamically from the environment
if env_valid:
    # Use function to get real-time values
    def get_env_value(key):
        # Always reload dotenv to get the latest values
        load_dotenv(override=True)
        return os.environ.get(key)
    
    # These will be refreshed before each use
    def get_TRAKT_CLIENT_ID(): return get_env_value('TRAKT_CLIENT_ID')
    def get_TRAKT_CLIENT_SECRET(): return get_env_value('TRAKT_CLIENT_SECRET')
    def get_EMBY_API_KEY(): return get_env_value('EMBY_API_KEY')
    def get_EMBY_SERVER(): return get_env_value('EMBY_SERVER')
    def get_EMBY_ADMIN_USER_ID(): return get_env_value('EMBY_ADMIN_USER_ID')
    def get_EMBY_MOVIES_LIBRARY_ID(): return get_env_value('EMBY_MOVIES_LIBRARY_ID')
    def get_EMBY_TV_LIBRARY_ID(): return get_env_value('EMBY_TV_LIBRARY_ID')
else:
    print(" Missing required configuration. Please complete setup in the Settings page.")
    for var in missing_vars:
        print(f"  - Missing: {var}")
    # Set variables to None to prevent undefined variable errors
    def get_TRAKT_CLIENT_ID(): return None
    def get_TRAKT_CLIENT_SECRET(): return None
    def get_EMBY_API_KEY(): return None
    def get_EMBY_SERVER(): return None
    def get_EMBY_ADMIN_USER_ID(): return None
    def get_EMBY_MOVIES_LIBRARY_ID(): return None
    def get_EMBY_TV_LIBRARY_ID(): return None

# File to store access token
TOKEN_FILE = 'trakt_token.json'

# List of Trakt lists - load from configuration
def get_trakt_lists():
    try:
        return json.loads(get_config('TRAKT_LISTS') or '[]')
    except json.JSONDecodeError:
        return []

# --- Trakt Token Handling ---

def save_token(token_data):
    """Save token data to a file"""
    with open(TOKEN_FILE, 'w') as f:
        json.dump(token_data, f)
    print(f"Token saved to {TOKEN_FILE}")

def load_token():
    """Load token data from a file"""
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading token: {e}")
    return None

def refresh_access_token(refresh_token):
    """Use refresh token to get a new access token"""
    # Reload environment variables
    load_dotenv(override=True)
    
    # Get fresh credentials
    client_id = get_TRAKT_CLIENT_ID()
    client_secret = get_TRAKT_CLIENT_SECRET()
    
    if not client_id or not client_secret:
        print(" Missing Trakt credentials")
        return None
        
    url = 'https://api.trakt.tv/oauth/token'
    headers = {
        'Content-Type': 'application/json'
    }
    data = {
        'refresh_token': refresh_token,
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'refresh_token'
    }
    
    try:
        response = requests.post(url, json=data, headers=headers)
        print(f"Refresh Token Response: {response.status_code}")
        
        if response.status_code == 200:
            token_data = response.json()
            save_token(token_data)
            access_token = token_data.get('access_token')
            if access_token:
                print("Access token obtained and saved.")
                return access_token
        elif response.status_code == 400:
            print("Invalid refresh token, starting new device authentication")
            return None
        else:
            print(f"Unexpected response: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error refreshing token: {str(e)}")
        return None

# --- Trakt Authentication Functions ---

def get_trakt_device_code():
    """Get a device code for Trakt authentication"""
    # Reload environment variables
    load_dotenv(override=True)
    
    # Get fresh credentials
    client_id = get_TRAKT_CLIENT_ID()
    
    if not client_id:
        print(" Missing Trakt Client ID")
        return None, None, None
        
    url = 'https://api.trakt.tv/oauth/device/code'
    headers = {
        'Content-Type': 'application/json'
    }
    data = {
        'client_id': client_id
    }
    
    try:
        response = requests.post(url, json=data, headers=headers)
        print(f"Device Code Response: {response.status_code}")
        
        if response.status_code == 200:
            resp_json = response.json()
            device_code = resp_json.get('device_code')
            user_code = resp_json.get('user_code')
            verification_url = resp_json.get('verification_url')
            interval = resp_json.get('interval', 5)
            print(f"Please visit {verification_url} and enter code: {user_code}")
            print("Waiting for user authorization...")
            return (device_code, user_code, interval)
        else:
            print(f"Error obtaining device code: {response.status_code}")
            if response.status_code == 403:
                print("Invalid Trakt Client ID. Please check your configuration.")
            return (None, None, None)
    except Exception as e:
        print(f"Error in device code request: {str(e)}")
        return (None, None, None)

def poll_for_access_token(device_code, interval):
    """Poll for access token after user authorizes the device"""
    # Reload environment variables
    load_dotenv(override=True)
    
    # Get fresh credentials
    client_id = get_TRAKT_CLIENT_ID()
    client_secret = get_TRAKT_CLIENT_SECRET()
    
    if not client_id or not client_secret:
        print(" Missing Trakt credentials")
        return None
        
    url = 'https://api.trakt.tv/oauth/device/token'
    headers = {
        'Content-Type': 'application/json'
    }
    data = {
        'code': device_code,
        'client_id': client_id,
        'client_secret': client_secret
    }
    
    # For Streamlit, we do a single poll each time the app reruns
    try:
        print(f"Polling for Trakt token with device code: {device_code}")
        response = requests.post(url, json=data, headers=headers)
        print(f"Token Polling Response: {response.status_code}")
        
        if response.status_code == 200:
            token_data = response.json()
            save_token(token_data)
            access_token = token_data.get('access_token')
            if access_token:
                print("Access token obtained and saved.")
                return access_token
        elif response.status_code == 404:
            print("Device code appears invalid.")
        elif response.status_code == 409:
            print("Authorization pending. Waiting for user to authorize...")
        elif response.status_code == 410:
            print("The tokens have expired. Please try again.")
        elif response.status_code == 418:
            print("User denied the authentication.")
        elif response.status_code == 400:
            print("The device code is incorrect or has expired.")
    except Exception as e:
        print(f"Error in token polling: {str(e)}")
    
    # Return None if we didn't get a token
    return None

def get_trakt_list(list_id, access_token):
    url = f'https://api.trakt.tv/lists/{list_id}/items'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': get_TRAKT_CLIENT_ID()
    }
    response = requests.get(url, headers=headers)
    print(f"Get Trakt List Response for list {list_id}: {response.status_code}")
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching Trakt list {list_id}: {response.status_code}")
        return []

# --- Emby Functions (modified) ---

def get_emby_library_items(item_type="Movie", library_id=None, force_refresh=False):
    """Get all items from Emby library with manual caching"""
    global _library_cache
    cache_key = f"{item_type}_{library_id}"
    
    # Return cached data if available and not forced to refresh
    if not force_refresh and cache_key in _library_cache:
        print(f"Using cached {item_type} library data")
        return _library_cache[cache_key]
    
    # If no library ID provided, try to get from environment
    if not library_id:
        if item_type == "Movie":
            library_id = get_EMBY_MOVIES_LIBRARY_ID()
        elif item_type == "Series":
            library_id = get_EMBY_TV_LIBRARY_ID()
            
    if not library_id:
        print(f" No library ID provided for {item_type} items")
        return []
    
    # Remove trailing slash from server URL
    server_url = get_EMBY_SERVER().rstrip('/')
    
    try:
        # Fetch all items of the specified type from the library
        print(f"Fetching {item_type} items from Emby library {library_id}...")
        headers = {
            'X-Emby-Token': get_EMBY_API_KEY()
        }
        
        # Enhanced params to get ALL provider IDs and relevant metadata
        params = {
            "IncludeItemTypes": item_type,
            "ParentId": library_id,
            "Recursive": "true",
            "Fields": "ProviderIds,Path,ProductionYear",
            "EnableImages": "false"
        }
        
        response = requests.get(f"{server_url}/Items", headers=headers, params=params)
        
        if response.status_code == 200:
            items = response.json().get('Items', [])
            print(f" Found {len(items)} {item_type} items in Emby library")
            _library_cache[cache_key] = items
            return items
        else:
            print(f" Failed to fetch {item_type} items: HTTP {response.status_code}")
            return []
    except Exception as e:
        print(f" Error fetching {item_type} items: {str(e)}")
        return []

def create_collection_legacy_format(collection_name, movie_ids):
    """Create a collection using the legacy format for Emby 4.9"""
    if not movie_ids:
        print(f"No items to add to collection '{collection_name}'")
        return None

    # Format IDs as comma-separated string
    movie_ids_str = ",".join(str(movie_id) for movie_id in movie_ids)
    
    # Use the exact format from the provided example
    server_url = get_EMBY_SERVER().rstrip('/')
    api_key = get_EMBY_API_KEY()
    
    # URL format with query parameters including api_key
    url = f"{server_url}/Collections?api_key={api_key}&IsLocked=false&Name={collection_name}&Movies&Ids={movie_ids_str}"
    
    print(f"Creating collection '{collection_name}' with {len(movie_ids)} items using legacy format")
    try:
        # Send POST request without headers or body
        response = requests.post(url)
        print(f"Collection creation response: {response.status_code} - {response.text}")
        
        if response.status_code in (200, 201, 204):
            try:
                result = response.json()
                collection_id = result.get('Id')
                if collection_id:
                    print(f"Created collection with ID: {collection_id}")
                    return collection_id
            except Exception as e:
                print(f"Error parsing response: {str(e)}")
            
            # If we can't get ID from response, search for the collection
            time.sleep(1)
            collection_id = find_collection_by_name(collection_name)
            if collection_id:
                print(f"Created collection '{collection_name}' with ID: {collection_id}")
                return collection_id
            
        print(f"Failed to create collection: {response.status_code}")
        return None
    except Exception as e:
        print(f"Error creating collection: {str(e)}")
        return None

def create_emby_collection_with_movies(collection_name, movie_ids):
    """Create a collection and add movies in one operation"""
    if not movie_ids:
        print(f"No items to add to collection '{collection_name}'")
        return None
        
    # Check if collection already exists
    existing_id = find_collection_by_name(collection_name)
    if existing_id:
        print(f"Collection '{collection_name}' already exists with ID: {existing_id}")
        return existing_id
    
    # Try the legacy format first (exact format from the example)
    collection_id = create_collection_legacy_format(collection_name, movie_ids)
    if collection_id:
        return collection_id
        
    # If legacy format fails, try creating with the first item
    print("Legacy format failed. Trying alternative method...")
    server_url = get_EMBY_SERVER().rstrip('/')
    headers = {'X-Emby-Token': get_EMBY_API_KEY()}
    
    # Take the first item and create a collection with it
    first_movie_id = movie_ids[0]
    create_url = f"{server_url}/Items/{first_movie_id}/Collection"
    create_params = {
        "Name": collection_name,
        "IsLocked": "false"
    }
    
    try:
        create_response = requests.post(create_url, headers=headers, params=create_params)
        print(f"Alternative creation response: {create_response.status_code} - {create_response.text}")
        
        if create_response.status_code in (200, 201, 204):
            # Now find the collection ID
            time.sleep(1)
            collection_id = find_collection_by_name(collection_name)
            
            if collection_id:
                print(f"Created collection '{collection_name}' with ID: {collection_id}")
                
                # Add the rest of the items
                success_count = 1  # First item already added
                for movie_id in movie_ids[1:]:
                    if add_movie_to_emby_collection(movie_id, collection_id):
                        success_count += 1
                
                print(f"Added {success_count} of {len(movie_ids)} items to collection")
                return collection_id
        
        print("All collection creation methods failed")
        return None
    except Exception as e:
        print(f"Error in alternative creation method: {str(e)}")
        return None

def find_collection_by_name(collection_name):
    """Find a collection by name - simplified version"""
    # Remove trailing slash from server URL
    server_url = get_EMBY_SERVER().rstrip('/')
        
    search_url = f'{server_url}/Items'
    headers = {
        'X-Emby-Token': get_EMBY_API_KEY()
    }
    params = {
        "IncludeItemTypes": "BoxSet",
        "Recursive": "true",
        "Fields": "Name,Id"
    }
    
    try:
        search_response = requests.get(search_url, headers=headers, params=params)
        
        if search_response.status_code == 200:
            results = search_response.json()
            items = results.get('Items', [])
            
            for item in items:
                if item.get('Name', '').lower() == collection_name.lower():
                    collection_id = item.get('Id')
                    print(f"Found collection '{item.get('Name')}' with ID: {collection_id}")
                    return collection_id
        else:
            print(f"Error searching for collection: HTTP {search_response.status_code}")
            print(f"Response: {search_response.text}")
        
        return None
    except Exception as e:
        print(f"Error finding collection: {e}")
        return None

def normalize_title(title):
    """Normalize title for comparison by removing common variations"""
    # Convert to lowercase
    title = title.lower()
    # Remove year in parentheses
    title = re.sub(r'\s*\(\d{4}\)\s*', '', title)
    # Remove special characters and extra spaces
    title = re.sub(r'[^\w\s]', '', title)
    # Remove common prefixes
    title = re.sub(r'^(the|a|an)\s+', '', title)
    # Remove "Marvel's" prefix
    title = re.sub(r'^marvel\'?s\s+', '', title)
    # Normalize spaces
    title = ' '.join(title.split())
    return title

def print_item_details(item_type, items):
    """Print detailed library contents for debugging"""
    print(f"\nEmby {item_type} Library Details:")
    for item in items:
        provider_ids = item.get('ProviderIds', {})
        print(f"\nTitle: {item.get('Name')}")
        if provider_ids.get('Imdb'): print(f"IMDB: {provider_ids['Imdb']}")
        if provider_ids.get('Tmdb'): print(f"TMDB: {provider_ids['Tmdb']}")
        if provider_ids.get('Tvdb'): print(f"TVDB: {provider_ids['Tvdb']}")

def search_movie_in_emby(title, year, provider_ids=None, library_id=None):
    """Search for a movie in Emby using provider IDs and stored mappings"""
    if not provider_ids:
        print(f" No provider IDs available for movie: {title}")
        return None

    # First, check if we have a stored mapping for this movie
    trakt_id = None
    if provider_ids.get('trakt'):
        trakt_id = provider_ids['trakt']
        # Check if we have a stored Emby ID for this Trakt ID
        emby_id = get_emby_id_from_mapping("movie", trakt_id)
        if emby_id:
            print(f" Found Emby ID from stored mapping for {title}: {emby_id}")
            return emby_id

    # Get cached library items
    library_items = get_emby_library_items("Movie", library_id)
    
    print(f"\n Searching for movie: {title} ({year})")
    print(f" Provider IDs from Trakt: {provider_ids}")
    
    # Try IMDB ID (most reliable)
    if provider_ids.get('imdb'):
        imdb_id = provider_ids['imdb']
        print(f"Checking IMDB ID: {imdb_id}")
        for item in library_items:
            item_provider_ids = item.get('ProviderIds', {})
            emby_imdb_id = item_provider_ids.get('Imdb', '').strip()
            if emby_imdb_id and emby_imdb_id == imdb_id:
                emby_id = item.get('Id')
                print(f" Found IMDB match: {item.get('Name')} (Emby ID: {emby_id})")
                # Store this mapping for future use
                if trakt_id:
                    add_emby_id_mapping(trakt_id, emby_id, "movie", title)
                return emby_id
                
            # Check for IMDB ID in file path
            path = item.get('Path', '')
            if path:
                path_imdb_id = extract_imdb_from_path(path)
                if path_imdb_id and path_imdb_id == imdb_id:
                    emby_id = item.get('Id')
                    print(f" Found IMDB match in path: {item.get('Name')} (Emby ID: {emby_id})")
                    # Store this mapping for future use
                    if trakt_id:
                        add_emby_id_mapping(trakt_id, emby_id, "movie", title)
                    return emby_id
    else:
        print(" No IMDB ID available")
    
    # Try TMDB ID
    if provider_ids.get('tmdb'):
        tmdb_id = provider_ids['tmdb']
        print(f"Checking TMDB ID: {tmdb_id}")
        for item in library_items:
            item_provider_ids = item.get('ProviderIds', {})
            emby_tmdb_id = item_provider_ids.get('Tmdb', '').strip()
            if emby_tmdb_id and emby_tmdb_id == tmdb_id:
                emby_id = item.get('Id')
                print(f" Found TMDB match: {item.get('Name')} (Emby ID: {emby_id})")
                # Store this mapping for future use
                if trakt_id:
                    add_emby_id_mapping(trakt_id, emby_id, "movie", title)
                return emby_id
    else:
        print(" No TMDB ID available")
    
    # If no provider ID match found, try fuzzy title matching as last resort
    print(f" Trying fuzzy title matching for: {title}")
    normalized_title = normalize_title(title)
    best_match = None
    best_score = 0
    
    for item in library_items:
        item_title = item.get('Name', '')
        item_year = item.get('ProductionYear')
        
        # Skip items with significantly different years if both years are available
        if year and item_year and abs(int(year) - int(item_year)) > 1:
            continue
            
        # Normalize both titles for comparison
        normalized_item_title = normalize_title(item_title)
        
        # Calculate similarity using different methods
        # 1. Direct equality after normalization
        if normalized_title == normalized_item_title:
            best_match = item
            best_score = 1.0
            break
            
        # 2. Check if one title is contained within the other
        if normalized_title in normalized_item_title or normalized_item_title in normalized_title:
            score = 0.9
            if not best_match or score > best_score:
                best_match = item
                best_score = score
                
        # 3. Check for word overlap percentage
        title_words = set(normalized_title.split())
        item_words = set(normalized_item_title.split())
        if title_words and item_words:  # Avoid division by zero
            common_words = title_words.intersection(item_words)
            overlap_score = len(common_words) / max(len(title_words), len(item_words))
            if overlap_score > 0.6 and overlap_score > best_score:  # At least 60% word overlap
                best_match = item
                best_score = overlap_score
    
    # If we found a good match
    if best_match and best_score >= 0.6:  # Threshold for accepting matches
        emby_id = best_match.get('Id')
        print(f" Found title match: {best_match.get('Name')} (score: {best_score:.2f}, Emby ID: {emby_id})")
        # Store this mapping for future use
        if trakt_id:
            add_emby_id_mapping(trakt_id, emby_id, "movie", title)
        return emby_id
    
    # If no match found, print some debug info
    print(f" No matches found for: {title}")
    print("Debug info for first few library items:")
    for item in library_items[:3]:
        print(f"  Library item: {item.get('Name')}")
        print(f"  Provider IDs: {item.get('ProviderIds', {})}")
    return None

def search_tv_show_in_emby(title, year, provider_ids=None, library_id=None):
    """Search for a TV show in Emby using provider IDs and stored mappings"""
    if not provider_ids:
        print(f" No provider IDs available for TV show: {title}")
        return None

    # First, check if we have a stored mapping for this TV show
    trakt_id = None
    if provider_ids.get('trakt'):
        trakt_id = provider_ids['trakt']
        # Check if we have a stored Emby ID for this Trakt ID
        emby_id = get_emby_id_from_mapping("show", trakt_id)
        if emby_id:
            print(f" Found Emby ID from stored mapping for {title}: {emby_id}")
            return emby_id

    # Get cached library items
    library_items = get_emby_library_items("Series", library_id)
    
    print(f"\n Searching for TV show: {title} ({year})")
    print(f" Provider IDs from Trakt: {provider_ids}")
    
    # Try TVDB ID (most reliable for TV shows)
    if provider_ids.get('tvdb'):
        tvdb_id = provider_ids['tvdb']
        print(f"Checking TVDB ID: {tvdb_id}")
        for item in library_items:
            item_provider_ids = item.get('ProviderIds', {})
            emby_tvdb_id = item_provider_ids.get('Tvdb', '').strip()
            if emby_tvdb_id and emby_tvdb_id == tvdb_id:
                emby_id = item.get('Id')
                print(f" Found TVDB match: {item.get('Name')} (Emby ID: {emby_id})")
                # Store this mapping for future use
                if trakt_id:
                    add_emby_id_mapping(trakt_id, emby_id, "show", title)
                return emby_id
    else:
        print(" No TVDB ID available")
    
    # Try TMDB ID
    if provider_ids.get('tmdb'):
        tmdb_id = provider_ids['tmdb']
        print(f"Checking TMDB ID: {tmdb_id}")
        for item in library_items:
            item_provider_ids = item.get('ProviderIds', {})
            emby_tmdb_id = item_provider_ids.get('Tmdb', '').strip()
            if emby_tmdb_id and emby_tmdb_id == tmdb_id:
                emby_id = item.get('Id')
                print(f" Found TMDB match: {item.get('Name')} (Emby ID: {emby_id})")
                # Store this mapping for future use
                if trakt_id:
                    add_emby_id_mapping(trakt_id, emby_id, "show", title)
                return emby_id
    else:
        print(" No TMDB ID available")
    
    # Try IMDB ID as last resort
    if provider_ids.get('imdb'):
        imdb_id = provider_ids['imdb']
        print(f"Checking IMDB ID: {imdb_id}")
        for item in library_items:
            item_provider_ids = item.get('ProviderIds', {})
            emby_imdb_id = item_provider_ids.get('Imdb', '').strip()
            if emby_imdb_id and emby_imdb_id == imdb_id:
                emby_id = item.get('Id')
                print(f" Found IMDB match: {item.get('Name')} (Emby ID: {emby_id})")
                # Store this mapping for future use
                if trakt_id:
                    add_emby_id_mapping(trakt_id, emby_id, "show", title)
                return emby_id
                
            # Check for IMDB ID in file path
            path = item.get('Path', '')
            if path:
                path_imdb_id = extract_imdb_from_path(path)
                if path_imdb_id and path_imdb_id == imdb_id:
                    emby_id = item.get('Id')
                    print(f" Found IMDB match in path: {item.get('Name')} (Emby ID: {emby_id})")
                    # Store this mapping for future use
                    if trakt_id:
                        add_emby_id_mapping(trakt_id, emby_id, "show", title)
                    return emby_id
    else:
        print(" No IMDB ID available")
    
    # If no provider ID match found, try fuzzy title matching as last resort
    print(f" Trying fuzzy title matching for: {title}")
    normalized_title = normalize_title(title)
    best_match = None
    best_score = 0
    
    for item in library_items:
        item_title = item.get('Name', '')
        item_year = item.get('ProductionYear')
        
        # Skip items with significantly different years if both years are available
        if year and item_year and abs(int(year) - int(item_year)) > 1:
            continue
            
        # Normalize both titles for comparison
        normalized_item_title = normalize_title(item_title)
        
        # Calculate similarity using different methods
        # 1. Direct equality after normalization
        if normalized_title == normalized_item_title:
            best_match = item
            best_score = 1.0
            break
            
        # 2. Check if one title is contained within the other
        if normalized_title in normalized_item_title or normalized_item_title in normalized_title:
            score = 0.9
            if not best_match or score > best_score:
                best_match = item
                best_score = score
                
        # 3. Check for word overlap percentage
        title_words = set(normalized_title.split())
        item_words = set(normalized_item_title.split())
        if title_words and item_words:  # Avoid division by zero
            common_words = title_words.intersection(item_words)
            overlap_score = len(common_words) / max(len(title_words), len(item_words))
            if overlap_score > 0.6 and overlap_score > best_score:  # At least 60% word overlap
                best_match = item
                best_score = overlap_score
    
    # If we found a good match
    if best_match and best_score >= 0.6:  # Threshold for accepting matches
        emby_id = best_match.get('Id')
        print(f" Found title match: {best_match.get('Name')} (score: {best_score:.2f}, Emby ID: {emby_id})")
        # Store this mapping for future use
        if trakt_id:
            add_emby_id_mapping(trakt_id, emby_id, "show", title)
        return emby_id
    
    # If no match found, print some debug info
    print(f" No matches found for: {title}")
    print("Debug info for first few library items:")
    for item in library_items[:3]:
        print(f"  Library item: {item.get('Name')}")
        print(f"  Provider IDs: {item.get('ProviderIds', {})}")
    return None

def add_movie_to_emby_collection(movie_id, collection_id):
    """Add a movie to a collection in Emby 4.9"""
    # Remove trailing slash from server URL
    server_url = get_EMBY_SERVER().rstrip('/')
        
    # Try first API format - direct add to collection
    url = f'{server_url}/Collections/{collection_id}/Items'
    headers = {
        'X-Emby-Token': get_EMBY_API_KEY()
    }
    params = {
        "Ids": movie_id
    }
    
    try:
        response = requests.post(url, headers=headers, params=params)
        print(f"Add movie response: {response.status_code}")
        
        if response.status_code in (200, 201, 204):
            print(f"Successfully added movie ID {movie_id} to collection ID {collection_id}")
            return True
        else:
            print(f"Failed to add movie ID {movie_id} to collection ID {collection_id}")
            print(f"Response: {response.text}")
            
            # Try alternative method - updating the item directly
            alt_url = f'{server_url}/Items/{movie_id}'
            alt_headers = {
                'X-Emby-Token': get_EMBY_API_KEY(),
                'Content-Type': 'application/json'
            }
            
            # Get the current item data first
            get_response = requests.get(
                alt_url, 
                headers={'X-Emby-Token': get_EMBY_API_KEY()}
            )
            
            if get_response.status_code == 200:
                try:
                    # Try to add collection ID to the item
                    print(f"Trying alternative method to add movie {movie_id} to collection {collection_id}")
                    
                    # Use the POST to Collection/{Id}/Items endpoint with IDs in querystring
                    post_url = f'{server_url}/Collections/{collection_id}/Items'
                    post_params = {
                        "Ids": movie_id
                    }
                    post_response = requests.post(post_url, headers=headers, params=post_params)
                    
                    if post_response.status_code in (200, 201, 204):
                        print(f"Successfully added movie ID {movie_id} to collection ID {collection_id} using alternative method")
                        return True
                    else:
                        print(f"Failed with alternative method too: {post_response.status_code} - {post_response.text}")
                        return False
                except Exception as e:
                    print(f"Error in alternative add method: {str(e)}")
                    return False
            else:
                print(f"Failed to retrieve item data: {get_response.status_code}")
                return False
    except Exception as e:
        print(f"Exception adding movie: {e}")
        return False

def process_item(item, access_token, library_id=None, collection_name=None):
    """Process a single item from Trakt list using multiple ID types for robust matching"""
    global _missing_items, _library_cache
    
    if item.get("type") == "movie":
        media = item.get("movie", {})
    else:
        media = item.get("show", {})
    
    title = media.get("title", "")
    year = media.get("year")
    ids = media.get("ids", {})
    
    log_info(f"\n Processing item: {title} ({year})")
    
    # Check if we have any usable IDs
    if not ids or not (ids.get('imdb') or ids.get('tmdb') or ids.get('trakt')):
        log_info(f" No usable IDs found for: {title}")
        # Add to missing items
        add_to_missing_items(media, item.get("type"), collection_name, library_id, "No usable IDs available")
        return None
    
    # Extract and normalize all available IDs
    imdb_id = ids.get('imdb', '').strip() if ids.get('imdb') else None
    tmdb_id = str(ids.get('tmdb')).strip() if ids.get('tmdb') else None
    trakt_id = str(ids.get('trakt')).strip() if ids.get('trakt') else None
    tvdb_id = str(ids.get('tvdb')).strip() if ids.get('tvdb') else None
    
    # First check if we have a stored mapping for the Trakt ID
    if trakt_id:
        item_type = "movie" if item.get("type") == "movie" else "show"
        emby_id = get_emby_id_from_mapping(item_type, trakt_id)
        if emby_id:
            log_debug(f" Found stored mapping for {title}: {emby_id}")
            return {"id": emby_id, "type": item.get("type")}
    
    # Get appropriate library items based on type
    if item.get("type") == "movie":
        library_items = get_emby_library_items("Movie", library_id)
    else:
        library_items = get_emby_library_items("Series", library_id)
    
    # Create lookup dictionaries for all ID types
    imdb_lookup = {}
    tmdb_lookup = {}
    tvdb_lookup = {}
    path_imdb_lookup = {}
    
    # Build comprehensive lookup tables
    for lib_item in library_items:
        lib_id = lib_item.get('Id')
        provider_ids = lib_item.get('ProviderIds', {})
        
        # IMDB ID from metadata - normalize by removing any prefix and ensuring lowercase
        emby_imdb_id = provider_ids.get('Imdb', '').strip()
        if emby_imdb_id:
            # Sometimes Emby stores IMDB IDs with 'tt' prefix removed, so check both formats
            imdb_lookup[emby_imdb_id] = lib_id
            # If it doesn't start with tt, add it as an alternative
            if not emby_imdb_id.startswith('tt') and len(emby_imdb_id) > 5:
                imdb_lookup[f"tt{emby_imdb_id}"] = lib_id
            # If it does start with tt, add version without it
            elif emby_imdb_id.startswith('tt'):
                imdb_lookup[emby_imdb_id[2:]] = lib_id
        
        # TMDB ID from metadata - similar normalization
        emby_tmdb_id = provider_ids.get('Tmdb', '').strip()
        if emby_tmdb_id:
            tmdb_lookup[emby_tmdb_id] = lib_id
        
        # TVDB ID from metadata
        emby_tvdb_id = provider_ids.get('Tvdb', '').strip()
        if emby_tvdb_id:
            tvdb_lookup[emby_tvdb_id] = lib_id
        
        # Check file path for IMDB ID
        path = lib_item.get('Path', '')
        if path:
            path_imdb_id = extract_imdb_from_path(path)
            if path_imdb_id:
                path_imdb_lookup[path_imdb_id] = lib_id
    
    # Normalize Trakt IDs the same way Emby might store them
    normalized_imdb_id = imdb_id
    if imdb_id and imdb_id.startswith('tt'):
        normalized_imdb_id_no_prefix = imdb_id[2:]
    else:
        normalized_imdb_id_no_prefix = imdb_id
        if imdb_id and not imdb_id.startswith('tt'):
            normalized_imdb_id = f"tt{imdb_id}"
    
    # Try matching with each available ID type in order of reliability
    matched_emby_id = None
    match_source = None
    
    # 1. Try direct IMDB ID match from metadata (most reliable) - using both formats
    if normalized_imdb_id and normalized_imdb_id in imdb_lookup:
        matched_emby_id = imdb_lookup[normalized_imdb_id]
        match_source = "IMDB metadata"
    elif normalized_imdb_id_no_prefix and normalized_imdb_id_no_prefix in imdb_lookup:
        matched_emby_id = imdb_lookup[normalized_imdb_id_no_prefix]
        match_source = "IMDB metadata (no prefix)"
    
    # 2. Try IMDB ID from file path as fallback
    elif normalized_imdb_id and normalized_imdb_id in path_imdb_lookup:
        matched_emby_id = path_imdb_lookup[normalized_imdb_id]
        match_source = "IMDB in filename"
    
    # 3. Try TMDB ID
    elif tmdb_id and tmdb_id in tmdb_lookup:
        matched_emby_id = tmdb_lookup[tmdb_id]
        match_source = "TMDB"
    
    # 4. Try TVDB ID (for TV shows)
    elif tvdb_id and tvdb_id in tvdb_lookup and item.get("type") == "show":
        matched_emby_id = tvdb_lookup[tvdb_id]
        match_source = "TVDB"
    
    # 5. Try fuzzy name match with year if nothing else works
    if not matched_emby_id and year:
        for lib_item in library_items:
            lib_name = lib_item.get('Name', '')
            lib_year = lib_item.get('ProductionYear')
            
            # Extremely strict matching to avoid false positives
            if lib_name.lower() == title.lower() and lib_year == year:
                matched_emby_id = lib_item.get('Id')
                match_source = "Name and year exact match"
                break
    
    # If a match was found with any method
    if matched_emby_id:
        log_info(f" Match found: {title} ({match_source})")
        # Store mapping for future using Trakt ID if available
        if trakt_id:
            item_type = "movie" if item.get("type") == "movie" else "show"
            add_emby_id_mapping(trakt_id, matched_emby_id, item_type, title)
        return {"id": matched_emby_id, "type": item.get("type")}
    
    # If we get here, no match was found with any ID
    log_info(f" Could not find {item.get('type')}: {title} - No matching IDs in Emby library")
    # Add to missing items with minimal debug info
    add_to_missing_items(media, item.get("type"), collection_name, library_id, "No matching IDs found in Emby library")
    return None

def log_provider_ids(lib_item, title=None):
    """Helper function to log all provider IDs for a library item for debugging"""
    if not _verbose_logging:
        return
    
    item_title = title or lib_item.get('Name', 'Unknown')
    provider_ids = lib_item.get('ProviderIds', {})
    
    if not provider_ids:
        log_debug(f" {item_title} has no provider IDs")
        return
    
    log_debug(f" Provider IDs for {item_title}:")
    for provider, id_value in provider_ids.items():
        log_debug(f"   {provider}: {id_value}")

def sync_trakt_list_to_emby(trakt_list, access_token, progress_callback=None):
    # Check if environment is properly configured
    env_valid, missing_vars = check_required_env_vars()
    if not env_valid:
        msg = " Cannot sync: Missing required configuration. Please complete setup in Settings."
        print(msg)
        if progress_callback:
            progress_callback(1.0, "Configuration Error", 0, 0, msg)
        return

    trakt_list_id = trakt_list["list_id"]
    collection_name = trakt_list["collection_name"]
    library_id = trakt_list.get("library_id", "")
    list_type = trakt_list.get("type", "movies")
    
    # Validate library ID
    if not library_id:
        msg = f" No library ID specified for list: {collection_name}. Please add a library ID in the UI."
        print(msg)
        if progress_callback:
            progress_callback(1.0, collection_name, 0, 0, msg)
        return
    
    start_msg = f"\n Starting sync for list: {collection_name} (Library ID: {library_id})"
    print(start_msg)
    if progress_callback:
        progress_callback(0.0, collection_name, 0, 0, start_msg)
    
    # Test Emby connection first
    server_url = get_EMBY_SERVER().rstrip('/')
    headers = {'X-Emby-Token': get_EMBY_API_KEY()}
    
    try:
        test_response = requests.get(f"{server_url}/System/Info", headers=headers)
        if test_response.status_code != 200:
            error_msg = f" Cannot connect to Emby server: HTTP {test_response.status_code}"
            if test_response.status_code == 401:
                error_msg += " - Authentication failed. Please check your API key."
            print(error_msg)
            if progress_callback:
                progress_callback(1.0, collection_name, 0, 0, error_msg)
            return
        else:
            print(f" Connected to Emby server: {test_response.json().get('ServerName', 'Unknown')}")
    except Exception as e:
        error_msg = f" Error connecting to Emby server: {str(e)}"
        print(error_msg)
        if progress_callback:
            progress_callback(1.0, collection_name, 0, 0, error_msg)
        return
    
    # Get items from Trakt
    trakt_items = get_trakt_list(trakt_list_id, access_token)
    if not trakt_items:
        msg = f" No items found in Trakt list: {collection_name}"
        print(msg)
        if progress_callback:
            progress_callback(1.0, collection_name, 0, 0, msg)
        return
    
    total_items = len(trakt_items)
    msg = f" Found {total_items} items in Trakt list"
    print(msg)
    if progress_callback:
        progress_callback(0.0, collection_name, 0, total_items, msg)
    
    # Process items concurrently
    emby_items = []
    media_counts = {"movie": 0, "show": 0}
    processed_count = 0
    
    # Pre-fetch library data
    msg = " Loading Emby library data..."
    print(msg)
    if progress_callback:
        progress_callback(0.0, collection_name, 0, total_items, msg)
    
    if list_type == "movies":
        movies = get_emby_library_items("Movie", library_id)
        msg = f" Loaded {len(movies)} movies from Emby library"
        print(msg)
        if progress_callback:
            progress_callback(0.0, collection_name, 0, total_items, msg)
    else:
        shows = get_emby_library_items("Series", library_id)
        msg = f" Loaded {len(shows)} TV shows from Emby library"
        print(msg)
        if progress_callback:
            progress_callback(0.0, collection_name, 0, total_items, msg)
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all tasks
        future_to_item = {executor.submit(process_item, item, access_token, library_id, collection_name): item for item in trakt_items}
        
        # Process completed tasks
        for future in as_completed(future_to_item):
            try:
                result = future.result()
                if result:
                    emby_items.append(result["id"])
                    media_counts[result["type"]] += 1
            except Exception as e:
                error_msg = f" Error processing item: {str(e)}"
                print(error_msg)
                if progress_callback:
                    progress_callback(processed_count / total_items, collection_name, 
                                   processed_count, total_items, error_msg)
            
            # Update progress
            processed_count += 1
            if progress_callback:
                progress = processed_count / total_items
                msg = f" Processing items from {collection_name} ({processed_count}/{total_items})"
                progress_callback(progress, collection_name, processed_count, total_items, msg)
    
    if not emby_items:
        msg = f" No matching items found in Emby for {collection_name}"
        print(msg)
        if progress_callback:
            progress_callback(1.0, collection_name, total_items, total_items, msg)
        return
    
    # Create the collection with all found items
    msg = f" Creating/updating Emby collection: {collection_name}"
    print(msg)
    if progress_callback:
        progress_callback(0.95, collection_name, processed_count, total_items, msg)
    
    collection_id = create_emby_collection_with_movies(collection_name, emby_items)
    
    if collection_id:
        msg = f" Successfully created/updated collection '{collection_name}' (ID: {collection_id})"
        print(msg)
        if progress_callback:
            progress_callback(1.0, collection_name, total_items, total_items, msg)
        
        summary_msg = f" Added to {collection_name}: {media_counts['movie']} movies, {media_counts['show']} TV shows"
        print(summary_msg)
        if progress_callback:
            progress_callback(1.0, collection_name, total_items, total_items, summary_msg)
        
        # Save missing items to file
        save_missing_items()
    else:
        msg = f" Failed to create/update collection: {collection_name}"
        print(msg)
        if progress_callback:
            progress_callback(1.0, collection_name, processed_count, total_items, msg)

def sync_all_trakt_lists(progress_callback=None):
    # Check if environment is properly configured
    env_valid, missing_vars = check_required_env_vars()
    if not env_valid:
        msg = " Cannot sync: Missing required configuration. Please complete setup in Settings."
        print(msg)
        if progress_callback:
            progress_callback(1.0, "Configuration Error", 0, 0, msg)
        return

    access_token = get_access_token()
    if access_token:
        for trakt_list in get_trakt_lists():
            sync_trakt_list_to_emby(trakt_list, access_token, progress_callback)
    else:
        msg = "Failed to obtain access token. Please check Trakt configuration in Settings."
        print(msg)
        if progress_callback:
            progress_callback(1.0, "Authentication Error", 0, 0, msg)

# --- Main Sync Job ---

def get_access_token():
    """Get a valid access token, using saved token if available"""
    # Reload environment variables
    load_dotenv(override=True)
    
    # Try to load saved token
    token_data = load_token()
    
    if token_data:
        print("Found saved token")
        # Check if token is expired (conservatively assume it might be)
        refresh_token = token_data.get('refresh_token')
        if refresh_token:
            print("Attempting to refresh the token")
            access_token = refresh_access_token(refresh_token)
            if access_token:
                return access_token
    
    # If no saved token or refresh failed, start device code auth
    print("Starting new device authentication")
    device_code, user_code, interval = get_trakt_device_code()
    if device_code:
        return poll_for_access_token(device_code, interval)
    
    return None

def get_next_occurrence_date(interval='6h', sync_time='00:00', sync_day='Monday', sync_date=1):
    """Calculate the next occurrence date based on schedule settings"""
    import calendar
    
    today = datetime.now()
    
    # For hourly intervals (e.g., 6h)
    if interval == '6h':
        # Calculate the next 6-hour mark
        current_hour = today.hour
        hours_until_next = 6 - (current_hour % 6)
        if hours_until_next == 0 and today.minute > 0:
            hours_until_next = 6
        next_date = today.replace(minute=0, second=0, microsecond=0) + timedelta(hours=hours_until_next)
        return next_date
    
    # For daily runs
    elif interval == '1d':
        # Parse the sync time
        hour, minute = map(int, sync_time.split(':'))
        next_date = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # If today's specified time has already passed, move to tomorrow
        if next_date <= today:
            next_date += timedelta(days=1)
        return next_date
    
    # For weekly runs
    elif interval == '1w':
        # Parse the sync time
        hour, minute = map(int, sync_time.split(':'))
        
        # Get the target day as an integer (0=Monday, 6=Sunday)
        target_day = list(calendar.day_name).index(sync_day)
        if target_day == 6:  # Adjust for calendar.day_name starting with Monday at index 0
            target_day = 0
        else:
            target_day += 1
            
        # Calculate days until the next occurrence
        days_ahead = target_day - today.weekday()
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
            
        next_date = today + timedelta(days=days_ahead)
        next_date = next_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return next_date
    
    # For bi-weekly runs
    elif interval == '2w':
        # Similar to weekly, but we need to determine if it's the right week
        hour, minute = map(int, sync_time.split(':'))
        
        # Get the target day as an integer (0=Monday, 6=Sunday)
        target_day = list(calendar.day_name).index(sync_day)
        if target_day == 6:  # Adjust for calendar.day_name starting with Monday at index 0
            target_day = 0
        else:
            target_day += 1
            
        # Calculate days until the next occurrence this week
        days_ahead = target_day - today.weekday()
        if days_ahead < 0:  # Target day already happened this week
            days_ahead += 7
            
        next_date = today + timedelta(days=days_ahead)
        next_date = next_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # Determine if we're in an even or odd week
        current_week = today.isocalendar()[1]
        next_week = next_date.isocalendar()[1]
        
        # If next occurrence week has wrong parity, add another week
        if (next_week % 2) != (current_week % 2):
            next_date += timedelta(days=7)
            
        return next_date
    
    # For monthly runs
    elif interval == '1m':
        # Parse the sync time
        hour, minute = map(int, sync_time.split(':'))
        
        # First, try this month
        try:
            next_date = today.replace(day=sync_date, hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:  # Day out of range for month
            # Go to the first of next month and then try to set the day
            next_date = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            # Now try to set the correct day
            try:
                next_date = next_date.replace(day=sync_date)
            except ValueError:  # Day out of range for month
                # Use the last day of the month
                last_day = calendar.monthrange(next_date.year, next_date.month)[1]
                next_date = next_date.replace(day=min(sync_date, last_day))
                
        # If the calculated date is in the past, move to next month
        if next_date <= today:
            next_date = (next_date.replace(day=1) + timedelta(days=32)).replace(day=1)
            try:
                next_date = next_date.replace(day=sync_date, hour=hour, minute=minute, second=0, microsecond=0)
            except ValueError:  # Day out of range for month
                last_day = calendar.monthrange(next_date.year, next_date.month)[1]
                next_date = next_date.replace(day=min(sync_date, last_day), hour=hour, minute=minute, second=0, microsecond=0)
                
        return next_date
    
    # For testing (1min)
    elif interval == '1min':
        next_date = today + timedelta(minutes=1)
        return next_date.replace(second=0, microsecond=0)
    
    # Default fallback
    else:
        return today + timedelta(hours=6)

def start_sync():
    """Start the sync process after checking configuration"""
    # Reload environment variables
    load_dotenv(override=True)
    
    env_valid, missing_vars = check_required_env_vars()
    if not env_valid:
        print(" Cannot start sync: Missing required configuration")
        for var in missing_vars:
            print(f"  - Missing: {var}")
        print("Please complete setup in the Settings page")
        return False
    
    try:
        sync_all_trakt_lists()
        return True
    except Exception as e:
        print(f" Sync failed with error: {str(e)}")
        return False

def start_scheduler(interval='6h', sync_time='00:00'):
    """Start the scheduler with the specified interval and time"""
    # Clear any existing jobs
    schedule.clear()
    
    # Check configuration before starting
    env_valid, missing_vars = check_required_env_vars()
    if not env_valid:
        print(" Cannot start scheduler: Missing required configuration")
        for var in missing_vars:
            print(f"  - Missing: {var}")
        print("Please complete setup in the Settings page")
        return False
    
    # Get additional schedule parameters
    sync_day = get_config('SYNC_DAY') or 'Monday'
    try:
        sync_date = int(get_config('SYNC_DATE') or '1')
        if sync_date < 1 or sync_date > 28:
            sync_date = 1  # Default to 1st if invalid
    except ValueError:
        sync_date = 1
    
    # Convert day name to schedule day
    day_methods = {
        'Monday': schedule.every().monday,
        'Tuesday': schedule.every().tuesday,
        'Wednesday': schedule.every().wednesday,
        'Thursday': schedule.every().thursday,
        'Friday': schedule.every().friday,
        'Saturday': schedule.every().saturday,
        'Sunday': schedule.every().sunday
    }
    
    # Set up schedule based on interval
    if interval == '6h':
        # Schedule every 6 hours
        schedule.every(6).hours.do(start_sync)
        print(" Scheduler set to run every 6 hours")
    elif interval == '1d':
        schedule.every().day.at(sync_time).do(start_sync)
        print(f" Scheduler set to run daily at {sync_time}")
    elif interval == '1w':
        day_scheduler = day_methods.get(sync_day, schedule.every().monday)
        day_scheduler.at(sync_time).do(start_sync)
        print(f" Scheduler set to run weekly on {sync_day} at {sync_time}")
    elif interval == '2w':
        # For fortnightly, we use a week-based schedule but only run if it's the right week
        day_scheduler = day_methods.get(sync_day, schedule.every().monday)
        
        # Create a wrapper function that checks if it's the right week to run
        def fortnightly_sync():
            # Get the current week number of the year
            current_week = datetime.now().isocalendar()[1]
            # Run only on even or odd weeks depending on when we start
            if current_week % 2 == 0:
                print(f" Running fortnightly sync (even week: {current_week})")
                return start_sync()
            else:
                print(f" Skipping sync - not the right week (odd week: {current_week})")
                return False
        
        day_scheduler.at(sync_time).do(fortnightly_sync)
        print(f" Scheduler set to run fortnightly on {sync_day} at {sync_time}")
    elif interval == '1m':
        # For monthly sync on specific date
        def monthly_sync_on_date():
            # Check if today is the specified date
            if datetime.now().day == sync_date:
                print(f" Running monthly sync on day {sync_date}")
                return start_sync()
            else:
                print(f" Skipping sync - today is not day {sync_date}")
                return False
        
        # Check every day at the specified time
        schedule.every().day.at(sync_time).do(monthly_sync_on_date)
        print(f" Scheduler set to run monthly on day {sync_date} at {sync_time}")
    elif interval == '1min':
        # Testing interval - run every minute
        schedule.every(1).minute.do(start_sync)
        print(" TEST MODE: Scheduler set to run every minute")
    else:
        print(f" Invalid interval: {interval}. Using default 6 hours.")
        schedule.every(6).hours.do(start_sync)
        print(" Scheduler set to run every 6 hours (default)")
    
    # Run initial sync
    print(f" Starting initial sync...")
    if start_sync():
        # Show when next sync will occur
        next_run = get_next_occurrence_date(interval, sync_time, sync_day, sync_date)
        if next_run:
            print(f" Initial sync completed successfully")
            print(f" Next sync scheduled for: {next_run}")
        return True
    else:
        print(" Initial sync failed - scheduler not started")
        return False

def run_scheduler_forever():
    """Run the scheduler in a loop forever - for console mode"""
    # Start the scheduler
    interval = os.getenv('SYNC_INTERVAL', '6h')
    if start_scheduler(interval):
        print(" Scheduler started successfully")
        print(" Running in continuous mode. Press Ctrl+C to exit.")
        
        try:
            # Keep the script running to execute scheduled jobs
            while True:
                schedule.run_pending()
                next_run = schedule.next_run()
                if next_run:
                    print(f" Next sync scheduled for: {next_run}")
                time.sleep(60)  # Check every minute
        except KeyboardInterrupt:
            print("\n Scheduler stopped by user")
        except Exception as e:
            print(f" Scheduler error: {str(e)}")
    else:
        print(" Failed to start scheduler")

def clear_library_cache():
    """Clear the library cache"""
    global _library_cache
    _library_cache.clear()
    print("Cleared Emby library cache")

def extract_imdb_from_path(path):
    """Extract IMDB ID from file path if present in [imdbid-ttXXXXXXX] format"""
    if not path or '[imdbid-' not in path:
        return None
        
    try:
        # Find the pattern [imdbid-ttXXXXXXX]
        match = re.search(r'\[imdbid-(tt\d+)\]', path)
        if match:
            imdb_id = match.group(1)
            log_debug(f"Extracted IMDB ID from path: {imdb_id}")
            return imdb_id
    except Exception as e:
        log_error(f"Error extracting IMDB ID from path: {e}")
        
    return None

def log_debug(message):
    """Print debug message only if verbose logging is enabled"""
    if _verbose_logging:
        print(message)

def log_info(message):
    """Print info message regardless of verbosity setting"""
    print(message)

def log_error(message):
    """Print error message regardless of verbosity setting"""
    print(f"ERROR: {message}")

def toggle_verbose_logging(enabled=None):
    """Toggle or set verbose logging"""
    global _verbose_logging
    if enabled is not None:
        _verbose_logging = enabled
    else:
        _verbose_logging = not _verbose_logging
    return _verbose_logging

def batch_match_by_provider_ids(items, library_items, item_type='movie'):
    """Batch match items against library using provider IDs"""
    # Create lookup dictionaries from library items for faster matching
    imdb_lookup = {}
    tmdb_lookup = {}
    tvdb_lookup = {}
    path_imdb_lookup = {}
    
    # Store matches
    matches = {}
    missing = []
    
    # Build lookup tables from library (do this only once for efficiency)
    log_info(f"Building lookup tables from {len(library_items)} library items...")
    for item in library_items:
        item_id = item.get('Id')
        # Get standard IMDB ID from metadata
        provider_ids = item.get('ProviderIds', {})
        emby_imdb_id = provider_ids.get('Imdb', '').strip()
        if emby_imdb_id:
            imdb_lookup[emby_imdb_id] = item_id
            
        # Get TMDB ID from metadata
        emby_tmdb_id = provider_ids.get('Tmdb', '').strip()
        if emby_tmdb_id:
            tmdb_lookup[emby_tmdb_id] = item_id
            
        # Get TVDB ID from metadata
        emby_tvdb_id = provider_ids.get('Tvdb', '').strip()
        if emby_tvdb_id:
            tvdb_lookup[emby_tvdb_id] = item_id
        
        # Check file path for IMDB ID
        path = item.get('Path', '')
        if path:
            path_imdb_id = extract_imdb_from_path(path)
            if path_imdb_id:
                path_imdb_lookup[path_imdb_id] = item_id
    
    log_info(f"Created lookups: IMDB({len(imdb_lookup)}), TMDB({len(tmdb_lookup)}), TVDB({len(tvdb_lookup)}), Path IMDB({len(path_imdb_lookup)})")
    
    # Match each item
    for item in items:
        matched = False
        title = item.get('title', '')
        year = item.get('year')
        ids = item.get('ids', {})
        
        # Try stored mapping first
        trakt_id = ids.get('trakt')
        if trakt_id:
            emby_id = get_emby_id_from_mapping(item_type, trakt_id)
            if emby_id:
                log_debug(f"Found stored mapping for {title}: {emby_id}")
                matches[title] = emby_id
                matched = True
                continue
                
        # Try IMDB ID
        if not matched and 'imdb' in ids and ids['imdb']:
            imdb_id = ids['imdb']
            if imdb_id in imdb_lookup:
                emby_id = imdb_lookup[imdb_id]
                matches[title] = emby_id
                # Store mapping for future
                if trakt_id:
                    add_emby_id_mapping(trakt_id, emby_id, item_type, title)
                matched = True
                continue
                
            # Try path IMDB lookup
            if imdb_id in path_imdb_lookup:
                emby_id = path_imdb_lookup[imdb_id]
                matches[title] = emby_id
                # Store mapping for future
                if trakt_id:
                    add_emby_id_mapping(trakt_id, emby_id, item_type, title)
                matched = True
                continue
        
        # Try TMDB ID
        if not matched and 'tmdb' in ids and ids['tmdb']:
            tmdb_id = str(ids['tmdb'])
            if tmdb_id in tmdb_lookup:
                emby_id = tmdb_lookup[tmdb_id]
                matches[title] = emby_id
                # Store mapping for future
                if trakt_id:
                    add_emby_id_mapping(trakt_id, emby_id, item_type, title)
                matched = True
                continue
                
        # Try TVDB ID
        if not matched and 'tvdb' in ids and ids['tvdb'] and item_type == 'show':
            tvdb_id = str(ids['tvdb'])
            if tvdb_id in tvdb_lookup:
                emby_id = tvdb_lookup[tvdb_id]
                matches[title] = emby_id
                # Store mapping for future
                if trakt_id:
                    add_emby_id_mapping(trakt_id, emby_id, item_type, title)
                matched = True
                continue
                
        # If we get here, no match was found for this item
        if not matched:
            missing.append({
                'title': title,
                'year': year,
                'ids': ids,
                'normalized_title': normalize_title(title)
            })
    
    # Try fuzzy title matching for remaining items
    if missing:
        log_info(f"Trying fuzzy title matching for {len(missing)} remaining items...")
        # Create normalized title lookup
        title_lookup = {}
        for item in library_items:
            item_title = item.get('Name', '')
            normalized = normalize_title(item_title)
            # Skip empty titles
            if not normalized:
                continue
            # Store with item ID
            title_lookup[normalized] = item.get('Id')
            
        # Process missing items with fuzzy matching
        for i, item in enumerate(missing[:]):
            title = item['title']
            normalized_title = item['normalized_title']
            trakt_id = item['ids'].get('trakt')
            
            # Direct normalized match
            if normalized_title in title_lookup:
                emby_id = title_lookup[normalized_title]
                matches[title] = emby_id
                # Store mapping for future
                if trakt_id:
                    add_emby_id_mapping(trakt_id, emby_id, item_type, title)
                missing.remove(item)
                continue
                
            # Try word overlap for the rest
            best_match = None
            best_score = 0.6  # Minimum threshold
            title_words = set(normalized_title.split())
            
            for lib_title, lib_id in title_lookup.items():
                # Skip single-word titles to avoid false matches
                if len(lib_title.split()) <= 1 or len(title_words) <= 1:
                    continue
                    
                # Check if one title is contained within the other
                if normalized_title in lib_title or lib_title in normalized_title:
                    score = 0.9
                    if not best_match or score > best_score:
                        best_match = lib_id
                        best_score = score
                        
                # Calculate word overlap
                lib_words = set(lib_title.split())
                common_words = title_words.intersection(lib_words)
                if common_words:
                    overlap = len(common_words) / max(len(title_words), len(lib_words))
                    if overlap > best_score:
                        best_match = lib_id
                        best_score = overlap
                        
            # Use best match if found
            if best_match:
                emby_id = best_match
                matches[title] = emby_id
                # Store mapping for future
                if trakt_id:
                    add_emby_id_mapping(trakt_id, emby_id, item_type, title)
                missing.remove(item)
    
    # Return results
    return matches, missing

if __name__ == "__main__":
    # Default to 6 hour schedule if not specified
    interval = os.getenv('SYNC_INTERVAL', '6h')
    # Run in continuous console mode by default
    run_scheduler_forever()