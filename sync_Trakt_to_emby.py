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
        'EMBY_ADMIN_USER_ID',
        'EMBY_MOVIES_LIBRARY_ID',
        'EMBY_TV_LIBRARY_ID'
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
    print("⚠️ Missing required configuration. Please complete setup in the Settings page.")
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
    load_dotenv(override=True)
    
    # Get fresh credentials
    client_id = get_TRAKT_CLIENT_ID()
    client_secret = get_TRAKT_CLIENT_SECRET()
    
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
    load_dotenv(override=True)
    
    # Get fresh credentials
    client_id = get_TRAKT_CLIENT_ID()
    
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
    load_dotenv(override=True)
    
    # Get fresh credentials
    client_id = get_TRAKT_CLIENT_ID()
    client_secret = get_TRAKT_CLIENT_SECRET()
    
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

def get_emby_library_items(item_type="Movie", force_refresh=False):
    """Get all items from Emby library with manual caching"""
    global _library_cache
    
    # Return cached results if available and not forcing refresh
    cache_key = f"library_{item_type}"
    if not force_refresh and cache_key in _library_cache:
        return _library_cache[cache_key]
    
    print(f"\n📚 Fetching {item_type} library data from Emby...")
    # Remove trailing slash from server URL
    server_url = get_EMBY_SERVER().rstrip('/')
        
    url = f'{server_url}/Items'
    headers = {
        'X-Emby-Token': get_EMBY_API_KEY()
    }
    params = {
        "IncludeItemTypes": item_type,
        "Recursive": "true",
        "Fields": "ProviderIds,ProductionYear,Path",
        "EnableImages": "false"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
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
        print(f"Response: {response.text}")
        return []
    except Exception as e:
        print(f"❌ Error fetching Emby library: {e}")
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
        print(f"✅ Found {'movie' if item.get("type") == "movie" else "TV show"}: {title}")
        return {"id": emby_id, "type": item.get("type")}
    else:
        print(f"❌ Could not find {'movie' if item.get("type") == "movie" else "TV show"}: {title}")
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
    
    # Test Emby connection first
    server_url = get_EMBY_SERVER().rstrip('/')
    headers = {'X-Emby-Token': get_EMBY_API_KEY()}
    try:
        test_response = requests.get(f"{server_url}/System/Info", headers=headers)
        if test_response.status_code != 200:
            error_msg = f"❌ Cannot connect to Emby server: HTTP {test_response.status_code}"
            if test_response.status_code == 401:
                error_msg += " - Authentication failed. Please check your API key."
            print(error_msg)
            if progress_callback:
                progress_callback(1.0, collection_name, 0, 0, error_msg)
            return
        else:
            print(f"✅ Connected to Emby server: {test_response.json().get('ServerName', 'Unknown')}")
    except Exception as e:
        error_msg = f"❌ Error connecting to Emby server: {str(e)}"
        print(error_msg)
        if progress_callback:
            progress_callback(1.0, collection_name, 0, 0, error_msg)
        return
    
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
        # Similar to weekly, but we need to determine if it's an even/odd week
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

def start_scheduler(interval='6h', sync_time='00:00'):
    """Start the scheduler with the specified interval and time"""
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
        print("🕒 Scheduler set to run every 6 hours")
    elif interval == '1d':
        schedule.every().day.at(sync_time).do(start_sync)
        print(f"🕒 Scheduler set to run daily at {sync_time}")
    elif interval == '1w':
        day_scheduler = day_methods.get(sync_day, schedule.every().monday)
        day_scheduler.at(sync_time).do(start_sync)
        print(f"🕒 Scheduler set to run weekly on {sync_day} at {sync_time}")
    elif interval == '2w':
        # For fortnightly, we use a week-based schedule but only run if it's the right week
        day_scheduler = day_methods.get(sync_day, schedule.every().monday)
        
        # Create a wrapper function that checks if it's the right week to run
        def fortnightly_sync():
            # Get the current week number of the year
            current_week = datetime.now().isocalendar()[1]
            # Run only on even or odd weeks depending on when we start
            if current_week % 2 == 0:
                print(f"🕒 Running fortnightly sync (even week: {current_week})")
                return start_sync()
            else:
                print(f"🕒 Skipping sync - not the right week (odd week: {current_week})")
                return False
        
        day_scheduler.at(sync_time).do(fortnightly_sync)
        print(f"🕒 Scheduler set to run fortnightly on {sync_day} at {sync_time}")
    elif interval == '1m':
        # For monthly sync on specific date
        def monthly_sync_on_date():
            # Check if today is the specified date
            if datetime.now().day == sync_date:
                print(f"🕒 Running monthly sync on day {sync_date}")
                return start_sync()
            else:
                print(f"🕒 Skipping sync - today is not day {sync_date}")
                return False
        
        # Check every day at the specified time
        schedule.every().day.at(sync_time).do(monthly_sync_on_date)
        print(f"🕒 Scheduler set to run monthly on day {sync_date} at {sync_time}")
    elif interval == '1min':
        # Testing interval - run every minute
        schedule.every(1).minute.do(start_sync)
        print("🕒 TEST MODE: Scheduler set to run every minute")
    else:
        print(f"⚠️ Invalid interval: {interval}. Using default 6 hours.")
        schedule.every(6).hours.do(start_sync)
        print("🕒 Scheduler set to run every 6 hours (default)")
    
    # Run initial sync
    print(f"🔄 Starting initial sync...")
    if start_sync():
        # Show when next sync will occur
        next_run = get_next_occurrence_date(interval, sync_time, sync_day, sync_date)
        if next_run:
            print(f"✅ Initial sync completed successfully")
            print(f"📅 Next sync scheduled for: {next_run}")
        return True
    else:
        print("❌ Initial sync failed - scheduler not started")
        return False

def run_scheduler_forever():
    """Run the scheduler in a loop forever - for console mode"""
    # Start the scheduler
    interval = os.getenv('SYNC_INTERVAL', '6h')
    if start_scheduler(interval):
        print("✅ Scheduler started successfully")
        print("📢 Running in continuous mode. Press Ctrl+C to exit.")
        
        try:
            # Keep the script running to execute scheduled jobs
            while True:
                schedule.run_pending()
                next_run = schedule.next_run()
                if next_run:
                    print(f"⏳ Next sync scheduled for: {next_run}")
                time.sleep(60)  # Check every minute
        except KeyboardInterrupt:
            print("\n🛑 Scheduler stopped by user")
        except Exception as e:
            print(f"❌ Scheduler error: {str(e)}")
    else:
        print("❌ Failed to start scheduler")

def clear_library_cache():
    """Clear the library cache"""
    global _library_cache
    _library_cache.clear()
    print("Cleared Emby library cache")

if __name__ == "__main__":
    # Default to 6 hour schedule if not specified
    interval = os.getenv('SYNC_INTERVAL', '6h')
    # Run in continuous console mode by default
    run_scheduler_forever()