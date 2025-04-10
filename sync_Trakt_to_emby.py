import requests
import time
import schedule
import json
import urllib.parse
import os
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import re
import streamlit as st

# Initialize configuration if not already done
if 'config' not in st.session_state:
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

def get_config(key):
    """Get configuration value from session state"""
    return st.session_state.config.get(key, '')

def check_required_env_vars():
    """Check if all required configuration values are set"""
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
    
    return len(missing_vars) == 0, missing_vars

# Check environment variables before initializing
env_valid, missing_vars = check_required_env_vars()

# Initialize variables only if environment is properly configured
if env_valid:
    TRAKT_CLIENT_ID = get_config('TRAKT_CLIENT_ID')
    TRAKT_CLIENT_SECRET = get_config('TRAKT_CLIENT_SECRET')
    EMBY_API_KEY = get_config('EMBY_API_KEY')
    EMBY_SERVER = get_config('EMBY_SERVER')
    EMBY_ADMIN_USER_ID = get_config('EMBY_ADMIN_USER_ID')
    EMBY_MOVIES_LIBRARY_ID = get_config('EMBY_MOVIES_LIBRARY_ID')
    EMBY_TV_LIBRARY_ID = get_config('EMBY_TV_LIBRARY_ID')
else:
    print("⚠️ Missing required configuration. Please complete setup in the Settings page.")
    for var in missing_vars:
        print(f"  - Missing: {var}")
    # Set variables to None to prevent undefined variable errors
    TRAKT_CLIENT_ID = None
    TRAKT_CLIENT_SECRET = None
    EMBY_API_KEY = None
    EMBY_SERVER = None
    EMBY_ADMIN_USER_ID = None
    EMBY_MOVIES_LIBRARY_ID = None
    EMBY_TV_LIBRARY_ID = None

# File to store access token
TOKEN_FILE = 'trakt_token.json'

# List of Trakt lists - load from configuration
trakt_lists = get_config('TRAKT_LISTS') or []

# Add this near the top of the file with other global variables
_library_cache = {}

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
    load_env()
    
    # Get fresh credentials
    client_id = os.getenv('TRAKT_CLIENT_ID')
    client_secret = os.getenv('TRAKT_CLIENT_SECRET')
    
    if not client_id or not client_secret:
        print("❌ Missing Trakt credentials")
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
            return token_data.get('access_token')
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
    load_env()
    
    # Get fresh credentials
    client_id = os.getenv('TRAKT_CLIENT_ID')
    
    if not client_id:
        print("❌ Missing Trakt Client ID")
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
    load_env()
    
    # Get fresh credentials
    client_id = os.getenv('TRAKT_CLIENT_ID')
    client_secret = os.getenv('TRAKT_CLIENT_SECRET')
    
    if not client_id or not client_secret:
        print("❌ Missing Trakt credentials")
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
    
    max_wait = 600  # max wait time in seconds
    waited = 0
    while waited < max_wait:
        try:
            response = requests.post(url, json=data, headers=headers)
            print(f"Token Polling Response (after {waited}s): {response.status_code}")
            
            if response.status_code == 200:
                token_data = response.json()
                save_token(token_data)
                access_token = token_data.get('access_token')
                if access_token:
                    print("Access token obtained and saved.")
                    return access_token
            elif response.status_code == 404:
                print("Device code appears invalid. Breaking polling loop.")
                break
            elif response.status_code == 409:
                print("Authorization pending. Waiting for user to authorize...")
            elif response.status_code == 410:
                print("The tokens have expired. Please try again.")
                break
            elif response.status_code == 418:
                print("User denied the authentication.")
                break
            elif response.status_code == 400:
                print("The device code is incorrect or has expired.")
                break
        except Exception as e:
            print(f"Error in token polling: {str(e)}")
            break
            
        time.sleep(interval)
        waited += interval
    
    print("Failed to obtain access token after waiting.")
    return None

def get_trakt_list(list_id, access_token):
    url = f'https://api.trakt.tv/lists/{list_id}/items'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': TRAKT_CLIENT_ID
    }
    response = requests.get(url, headers=headers)
    print(f"Get Trakt List Response for list {list_id}: {response.status_code}")
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching Trakt list {list_id}: {response.status_code}")
        return []

# --- Emby Functions (modified) ---

def create_emby_collection_with_movies(collection_name, movie_ids):
    """Create a collection and add movies in one operation"""
    # Check if collection already exists
    existing_id = find_collection_by_name(collection_name)
    if existing_id:
        print(f"Collection '{collection_name}' already exists with ID: {existing_id}")
        return existing_id
    
    # Format the movie IDs as a comma-separated string
    movie_ids_str = ",".join(str(movie_id) for movie_id in movie_ids)
    
    # Use the exact format from the provided snippet
    url = f'{EMBY_SERVER}/emby/Collections'
    params = {
        "api_key": EMBY_API_KEY,
        "IsLocked": "false",
        "Name": collection_name,
        "Movies": None,  # Include as a flag parameter with no value
        "Ids": movie_ids_str
    }
    
    print(f"Creating collection '{collection_name}' with {len(movie_ids)} items")
    response = requests.post(url, params=params)
    print(f"Creation response: {response.status_code} - {response.text}")
    
    if response.status_code in (200, 201, 204):
        try:
            result = response.json()
            collection_id = result.get('Id')
            if collection_id:
                print(f"Created collection with ID: {collection_id}")
                return collection_id
        except:
            pass
        
        # If we can't get ID from response, search for the collection
        time.sleep(1)
        return find_collection_by_name(collection_name)
    else:
        print(f"Failed to create collection: {response.status_code}")
        return None

def find_collection_by_name(collection_name):
    """Find a collection by name - simplified version"""
    # Simplify the query to just search for collections
    search_url = f'{EMBY_SERVER}/emby/Items'
    params = {
        "api_key": EMBY_API_KEY,
        "IncludeItemTypes": "BoxSet",
        "Recursive": "true",
        "Fields": "Name,Id"
    }
    
    try:
        search_response = requests.get(search_url, params=params)
        
        if search_response.status_code == 200:
            results = search_response.json()
            items = results.get('Items', [])
            
            for item in items:
                if item.get('Name', '').lower() == collection_name.lower():
                    collection_id = item.get('Id')
                    print(f"Found collection '{item.get('Name')}' with ID: {collection_id}")
                    return collection_id
        
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

def get_emby_library_items(item_type="Movie", force_refresh=False):
    """Get all items from Emby library with manual caching"""
    global _library_cache
    
    # Return cached results if available and not forcing refresh
    cache_key = f"library_{item_type}"
    if not force_refresh and cache_key in _library_cache:
        return _library_cache[cache_key]
    
    print(f"\n📚 Fetching {item_type} library data from Emby...")
    url = f'{EMBY_SERVER}/emby/Items'
    params = {
        "api_key": EMBY_API_KEY,
        "IncludeItemTypes": item_type,
        "Recursive": "true",
        "Fields": "ProviderIds,ProductionYear,Path",
        "EnableImages": "false"
    }
    
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            items = response.json().get('Items', [])
            # Store in cache
            _library_cache[cache_key] = items
            
            # Print summary and sample of provider IDs
            print(f"📊 Found {len(items)} {item_type}s in Emby library")
            if items:
                sample_item = items[0]
                print(f"📝 Sample item format:")
                print(f"  Name: {sample_item.get('Name')}")
                print(f"  Provider IDs: {sample_item.get('ProviderIds', {})}")
            return items
        print(f"❌ Error fetching library: HTTP {response.status_code}")
        return []
    except Exception as e:
        print(f"❌ Error fetching Emby library: {e}")
        return []

def print_item_details(item_type, items):
    """Print detailed library contents for debugging"""
    print(f"\nEmby {item_type} Library Details:")
    for item in items:
        provider_ids = item.get('ProviderIds', {})
        print(f"\nTitle: {item.get('Name')}")
        if provider_ids.get('Imdb'): print(f"IMDB: {provider_ids['Imdb']}")
        if provider_ids.get('Tmdb'): print(f"TMDB: {provider_ids['Tmdb']}")
        if provider_ids.get('Tvdb'): print(f"TVDB: {provider_ids['Tvdb']}")

def search_movie_in_emby(title, year, provider_ids=None):
    """Search for a movie in Emby using provider IDs"""
    if not provider_ids:
        print(f"❌ No provider IDs available for movie: {title}")
        return None

    # Get cached library items
    library_items = get_emby_library_items("Movie")
    
    print(f"\n🔍 Searching for movie: {title} ({year})")
    print(f"🔑 Provider IDs from Trakt: {provider_ids}")
    
    # Try IMDB ID (most reliable)
    if provider_ids.get('imdb'):
        imdb_id = provider_ids['imdb']
        print(f"Checking IMDB ID: {imdb_id}")
        for item in library_items:
            item_provider_ids = item.get('ProviderIds', {})
            emby_imdb_id = item_provider_ids.get('Imdb', '').strip()
            if emby_imdb_id and emby_imdb_id == imdb_id:
                print(f"✅ Found IMDB match: {item.get('Name')} (Emby ID: {item.get('Id')})")
                return item.get('Id')
    else:
        print("❌ No IMDB ID available")
    
    # Try TMDB ID
    if provider_ids.get('tmdb'):
        tmdb_id = provider_ids['tmdb']
        print(f"Checking TMDB ID: {tmdb_id}")
        for item in library_items:
            item_provider_ids = item.get('ProviderIds', {})
            emby_tmdb_id = item_provider_ids.get('Tmdb', '').strip()
            if emby_tmdb_id and emby_tmdb_id == tmdb_id:
                print(f"✅ Found TMDB match: {item.get('Name')} (Emby ID: {item.get('Id')})")
                return item.get('Id')
    else:
        print("❌ No TMDB ID available")
    
    # If no match found, print some debug info
    print(f"❌ No provider ID matches found for: {title}")
    print("Debug info for first few library items:")
    for item in library_items[:3]:
        print(f"  Library item: {item.get('Name')}")
        print(f"  Provider IDs: {item.get('ProviderIds', {})}")
    return None

def search_tv_show_in_emby(title, year, provider_ids=None):
    """Search for a TV show in Emby using provider IDs"""
    if not provider_ids:
        print(f"❌ No provider IDs available for TV show: {title}")
        return None

    # Get cached library items
    library_items = get_emby_library_items("Series")
    
    print(f"\n🔍 Searching for TV show: {title} ({year})")
    print(f"🔑 Provider IDs from Trakt: {provider_ids}")
    
    # Try TVDB ID (most reliable for TV shows)
    if provider_ids.get('tvdb'):
        tvdb_id = provider_ids['tvdb']
        print(f"Checking TVDB ID: {tvdb_id}")
        for item in library_items:
            item_provider_ids = item.get('ProviderIds', {})
            emby_tvdb_id = item_provider_ids.get('Tvdb', '').strip()
            if emby_tvdb_id and emby_tvdb_id == tvdb_id:
                print(f"✅ Found TVDB match: {item.get('Name')} (Emby ID: {item.get('Id')})")
                return item.get('Id')
    else:
        print("❌ No TVDB ID available")
    
    # Try TMDB ID
    if provider_ids.get('tmdb'):
        tmdb_id = provider_ids['tmdb']
        print(f"Checking TMDB ID: {tmdb_id}")
        for item in library_items:
            item_provider_ids = item.get('ProviderIds', {})
            emby_tmdb_id = item_provider_ids.get('Tmdb', '').strip()
            if emby_tmdb_id and emby_tmdb_id == tmdb_id:
                print(f"✅ Found TMDB match: {item.get('Name')} (Emby ID: {item.get('Id')})")
                return item.get('Id')
    else:
        print("❌ No TMDB ID available")
    
    # Try IMDB ID as last resort
    if provider_ids.get('imdb'):
        imdb_id = provider_ids['imdb']
        print(f"Checking IMDB ID: {imdb_id}")
        for item in library_items:
            item_provider_ids = item.get('ProviderIds', {})
            emby_imdb_id = item_provider_ids.get('Imdb', '').strip()
            if emby_imdb_id and emby_imdb_id == imdb_id:
                print(f"✅ Found IMDB match: {item.get('Name')} (Emby ID: {item.get('Id')})")
                return item.get('Id')
    else:
        print("❌ No IMDB ID available")
    
    # If no match found, print some debug info
    print(f"❌ No provider ID matches found for: {title}")
    print("Debug info for first few library items:")
    for item in library_items[:3]:
        print(f"  Library item: {item.get('Name')}")
        print(f"  Provider IDs: {item.get('ProviderIds', {})}")
    return None

def add_movie_to_emby_collection(movie_id, collection_id):
    """Add a movie to a collection using simplest possible approach for Emby 4.9"""
    url = f'{EMBY_SERVER}/emby/Collections/{collection_id}/Items'
    
    # Use query parameters only, include admin user ID
    params = {
        "api_key": EMBY_API_KEY,
        "UserId": EMBY_ADMIN_USER_ID,
        "Ids": movie_id
    }
    
    try:
        response = requests.post(url, params=params)
        print(f"Add movie response: {response.status_code}")
        
        if response.status_code in (200, 201, 204):
            print(f"Successfully added movie ID {movie_id} to collection ID {collection_id}")
            return True
        else:
            # Try alternative method
            alt_url = f'{EMBY_SERVER}/emby/Items/{movie_id}/Collection'
            alt_params = {
                "api_key": EMBY_API_KEY,
                "UserId": EMBY_ADMIN_USER_ID,
                "CollectionId": collection_id
            }
            
            alt_response = requests.post(alt_url, params=alt_params)
            print(f"Alternative add movie response: {alt_response.status_code}")
            
            if alt_response.status_code in (200, 201, 204):
                print(f"Successfully added movie ID {movie_id} using alternative method")
                return True
                
            return False
    except Exception as e:
        print(f"Exception adding movie: {e}")
        return False

def process_item(item, access_token):
    """Process a single item from Trakt list"""
    if item.get("type") == "movie":
        media = item.get("movie", {})
    else:
        media = item.get("show", {})
    
    title = media.get("title", "")
    year = media.get("year")
    ids = media.get("ids", {})
    
    print(f"\n📦 Processing Trakt item: {title} ({year})")
    print(f"🔑 Trakt IDs: {ids}")
    
    if not ids:
        print(f"❌ No provider IDs found for: {title}")
        return None
    
    # Convert IDs to strings and normalize format
    normalized_ids = {}
    if ids.get('imdb'):
        normalized_ids['imdb'] = str(ids['imdb']).strip()
    if ids.get('tmdb'):
        normalized_ids['tmdb'] = str(ids['tmdb']).strip()
    if ids.get('tvdb'):
        normalized_ids['tvdb'] = str(ids['tvdb']).strip()
    
    if item.get("type") == "movie":
        emby_id = search_movie_in_emby(title, year, normalized_ids)
    else:
        emby_id = search_tv_show_in_emby(title, year, normalized_ids)
    
    if emby_id:
        print(f"✅ Found {'movie' if item.get('type') == 'movie' else 'TV show'}: {title}")
        return {"id": emby_id, "type": item.get("type")}
    else:
        print(f"❌ Could not find {'movie' if item.get('type') == 'movie' else 'TV show'}: {title}")
        return None

def sync_trakt_list_to_emby(trakt_list, access_token, progress_callback=None):
    # Check if environment is properly configured
    env_valid, missing_vars = check_required_env_vars()
    if not env_valid:
        msg = "⚠️ Cannot sync: Missing required configuration. Please complete setup in Settings."
        print(msg)
        if progress_callback:
            progress_callback(1.0, "Configuration Error", 0, 0, msg)
        return

    trakt_list_id = trakt_list["list_id"]
    collection_name = trakt_list["collection_name"]
    
    start_msg = f"\n🔄 Starting sync for list: {collection_name}"
    print(start_msg)
    if progress_callback:
        progress_callback(0.0, collection_name, 0, 0, start_msg)
    
    # Get items from Trakt
    trakt_items = get_trakt_list(trakt_list_id, access_token)
    if not trakt_items:
        msg = f"❌ No items found in Trakt list: {collection_name}"
        print(msg)
        if progress_callback:
            progress_callback(1.0, collection_name, 0, 0, msg)
        return
    
    total_items = len(trakt_items)
    msg = f"📋 Found {total_items} items in Trakt list"
    print(msg)
    if progress_callback:
        progress_callback(0.0, collection_name, 0, total_items, msg)
    
    # Process items concurrently
    emby_items = []
    media_counts = {"movie": 0, "show": 0}
    processed_count = 0
    
    # Pre-fetch library data
    msg = "📚 Loading Emby library data..."
    print(msg)
    if progress_callback:
        progress_callback(0.0, collection_name, 0, total_items, msg)
    
    movies = get_emby_library_items("Movie")
    shows = get_emby_library_items("Series")
    msg = f"📚 Loaded {len(movies)} movies and {len(shows)} TV shows from Emby"
    print(msg)
    if progress_callback:
        progress_callback(0.0, collection_name, 0, total_items, msg)
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all tasks
        future_to_item = {executor.submit(process_item, item, access_token): item for item in trakt_items}
        
        # Process completed tasks
        for future in as_completed(future_to_item):
            try:
                result = future.result()
                if result:
                    emby_items.append(result["id"])
                    media_counts[result["type"]] += 1
            except Exception as e:
                error_msg = f"❌ Error processing item: {str(e)}"
                print(error_msg)
                if progress_callback:
                    progress_callback(processed_count / total_items, collection_name, 
                                   processed_count, total_items, error_msg)
            
            # Update progress
            processed_count += 1
            if progress_callback:
                progress = processed_count / total_items
                msg = f"⏳ Processing items from {collection_name} ({processed_count}/{total_items})"
                progress_callback(progress, collection_name, processed_count, total_items, msg)
    
    if not emby_items:
        msg = f"❌ No matching items found in Emby for {collection_name}"
        print(msg)
        if progress_callback:
            progress_callback(1.0, collection_name, total_items, total_items, msg)
        return
    
    # Create the collection with all found items
    msg = f"📁 Creating/updating Emby collection: {collection_name}"
    print(msg)
    if progress_callback:
        progress_callback(0.95, collection_name, processed_count, total_items, msg)
    
    collection_id = create_emby_collection_with_movies(collection_name, emby_items)
    
    if collection_id:
        msg = f"✅ Successfully created/updated collection '{collection_name}' (ID: {collection_id})"
        print(msg)
        if progress_callback:
            progress_callback(1.0, collection_name, total_items, total_items, msg)
        
        summary_msg = f"📊 Added to {collection_name}: {media_counts['movie']} movies, {media_counts['show']} TV shows"
        print(summary_msg)
        if progress_callback:
            progress_callback(1.0, collection_name, total_items, total_items, summary_msg)
    else:
        msg = f"❌ Failed to create/update collection: {collection_name}"
        print(msg)
        if progress_callback:
            progress_callback(1.0, collection_name, processed_count, total_items, msg)

def sync_all_trakt_lists(progress_callback=None):
    # Check if environment is properly configured
    env_valid, missing_vars = check_required_env_vars()
    if not env_valid:
        msg = "⚠️ Cannot sync: Missing required configuration. Please complete setup in Settings."
        print(msg)
        if progress_callback:
            progress_callback(1.0, "Configuration Error", 0, 0, msg)
        return

    access_token = get_access_token()
    if access_token:
        for trakt_list in trakt_lists:
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
    load_env()
    
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

def start_sync():
    """Start the sync process after checking configuration"""
    # Reload environment variables
    load_env()
    
    env_valid, missing_vars = check_required_env_vars()
    if not env_valid:
        print("⚠️ Cannot start sync: Missing required configuration")
        for var in missing_vars:
            print(f"  - Missing: {var}")
        print("Please complete setup in the Settings page")
        return False
    
    try:
        sync_all_trakt_lists()
        return True
    except Exception as e:
        print(f"❌ Sync failed with error: {str(e)}")
        return False

def start_scheduler(interval='6h'):
    """Start the scheduler with the specified interval"""
    # Clear any existing jobs
    schedule.clear()
    
    # Check configuration before starting
    env_valid, missing_vars = check_required_env_vars()
    if not env_valid:
        print("⚠️ Cannot start scheduler: Missing required configuration")
        for var in missing_vars:
            print(f"  - Missing: {var}")
        print("Please complete setup in the Settings page")
        return False
    
    # Set up schedule based on interval
    if interval == '6h':
        schedule.every(6).hours.do(start_sync)
    elif interval == '1d':
        schedule.every().day.at("00:00").do(start_sync)
    elif interval == '1w':
        schedule.every().monday.at("00:00").do(start_sync)
    elif interval == '2w':
        schedule.every(14).days.at("00:00").do(start_sync)
    elif interval == '1m':
        schedule.every(30).days.at("00:00").do(start_sync)
    else:
        print(f"⚠️ Invalid interval: {interval}. Using default 6 hours.")
        schedule.every(6).hours.do(start_sync)
    
    # Run initial sync
    print(f"🔄 Starting initial sync...")
    if start_sync():
        print(f"✅ Initial sync completed successfully")
        print(f"📅 Next sync scheduled: {schedule.next_run()}")
        
        # Start the scheduler loop
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    else:
        print("❌ Initial sync failed - scheduler not started")
        return False

def clear_library_cache():
    """Clear the library cache"""
    global _library_cache
    _library_cache.clear()
    print("Cleared Emby library cache")

if __name__ == "__main__":
    # Default to 6 hour schedule if not specified
    interval = os.getenv('SYNC_INTERVAL', '6h')
    start_scheduler(interval)
