# Trakt2EmbySync

A simple application to synchronize your Trakt.tv lists with your Emby collections.

## Features

- Connect to your Trakt.tv account via OAuth to access your lists
- Synchronize Trakt lists to Emby collections
- Support for movies and TV shows
- Scheduled automatic synchronization
- Easy-to-use web interface

## Requirements

- Python 3.8 or higher
- Emby server (version 4.9.0 or higher)
- Trakt.tv account
- Trakt API application (for API keys)

## One-Click Setup

### Windows Users

1. Download this project as a ZIP file
2. Extract all files to a folder
3. Double-click `setup.bat`
   - If you see an error or the window closes immediately, try right-clicking and select "Run as administrator"
4. Follow the instructions in the web interface

## Starting the Application (After Setup)

After you've completed the setup once, you can use the simpler run scripts to start the app:

- Windows: Double-click `run.bat`

## Manual Setup

If the one-click setup doesn't work for you:

1. Install Python 3.8 or higher
2. Create a virtual environment: `python -m venv .venv`
3. Activate the virtual environment:
   - Windows: `.venv\Scripts\activate`
   - Mac/Linux: `source .venv/bin/activate`
4. Install requirements: `pip install -r requirements.txt`
5. Run the app: `streamlit run app.py`
6. To run the scheduler `python console_runner.py`

## Configuration

In the Settings page of the application, you'll need to provide:

### Trakt Configuration
- Trakt Client ID and Client Secret (from your Trakt API application)
  - Visit [Trakt API Settings](https://trakt.tv/oauth/applications) to create an application
  - Use "urn:ietf:wg:oauth:2.0:oob" as the Redirect URI

### Emby Configuration
- Emby Server URL (e.g., http://localhost:8096 or https://your-emby-server.com)
- Emby API Key (found in your Emby user profile under API Keys)
- Emby Admin User ID
- Emby Movies Library ID
- Emby TV Library ID

## Troubleshooting

### Setup closes immediately
- Right-click on setup.bat and select "Run as administrator"
- Check if Python is installed and added to your PATH
- Look at setup_log.txt for error details

### Cannot connect to Emby
- Check that your Emby server is running
- Verify your API key is correct
- Ensure your server URL is formatted correctly (including http:// or https://)

### Cannot connect to Trakt
- Verify your Trakt API credentials
- Follow the OAuth authorization process

## License

MIT License - Feel free to use, modify, and distribute this code.

## Support

If you encounter any issues, please submit them on GitHub.
