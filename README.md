# Trakt2EmbySync

A Streamlit application that synchronizes your Trakt.tv lists with Emby collections.

## Features
- Sync Trakt lists to Emby collections
- Automatic synchronization at configurable intervals
- Support for both movies and TV shows
- User-friendly web interface
- Persistent configuration storage
- Missing Item Management
- Ignoring Item Management
- Custom Libraries

## Setup

### Local Development
1. Clone the repository:
```bash
git clone https://github.com/yourusername/Trakt2EmbySync.git
cd Trakt2EmbySync
```

2. Create a virtual environment and install dependencies:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Create `.streamlit/secrets.toml` with your configuration:
```toml
# Trakt API Credentials
trakt_client_id = "your_trakt_client_id"
trakt_client_secret = "your_trakt_client_secret"

# Emby Configuration
emby_api_key = "your_emby_api_key"
emby_server = "http://your.emby.server:8096"
emby_admin_user_id = "your_admin_user_id"
emby_movies_library_id = "your_movies_library_id"
emby_tv_library_id = "your_tv_library_id"

# Sync Configuration
sync_interval = "6h"
trakt_lists = "[]"
```

4. Run the application:
```bash
streamlit run app.py
```

### Streamlit Cloud Deployment
1. Fork this repository
2. Connect your fork to Streamlit Cloud
3. Add your secrets in the Streamlit Cloud dashboard
4. Deploy!

## Configuration

### Trakt.tv Setup
1. Go to [Trakt API Settings](https://trakt.tv/oauth/applications)
2. Create a new application
3. Set redirect URI to: urn:ietf:wg:oauth:2.0:oob
4. Copy Client ID and Client Secret

### Emby Setup
1. In Emby Dashboard, go to Advanced → API Keys
2. Create a new API key
3. Note your server URL and admin user ID
4. Get your library IDs from the library settings URLs

## Usage
1. Enter your Trakt and Emby credentials in the Settings page
2. Add your Trakt lists
3. Configure sync interval
4. Click "Sync Now" or wait for automatic sync

## Files
- `app.py`: Main Streamlit application
- `sync_Trakt_to_emby.py`: Synchronization logic
- `requirements.txt`: Python dependencies
- `.streamlit/secrets.toml`: Local configuration (not included in repo)

## Contributing
Pull requests are welcome! For major changes, please open an issue first.

## License
[MIT](https://choosealicense.com/licenses/mit/)
