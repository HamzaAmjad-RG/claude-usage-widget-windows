# claude-usage-widget

Cross-platform Python script to monitor Claude AI usage limits and display them in your system tray (Windows) or menu bar (macOS).

<img width="447" height="105" alt="image" src="https://github.com/user-attachments/assets/ce92d374-2688-4c9a-919a-d9fb12b57c5d" />

## Features

- Real-time monitoring of Claude usage (5-hour session and 7-day weekly limits)
- System tray (Windows) / menu bar (macOS) integration
- Desktop notifications at usage thresholds (25%, 50%, 75%, 90%)
- Automatic updates every 3 minutes
- Manual update option
- Reset time display with countdown

## Platform Support

- **Windows 10/11**: System tray icon with Windows toast notifications
- **macOS**: Menu bar icon with native macOS notifications

## Prerequisites

1. **Python 3.8+** with pip
2. **Node.js v16 or later** - [Download here](https://nodejs.org/)
3. **newman CLI tool**: Install globally with `npm install -g newman`

## Installation

1. Clone or download this repository

2. Navigate to the project directory:
   ```bash
   cd claude-usage-widget
   ```

3. Install Python dependencies (platform-specific packages install automatically):
   ```bash
   pip install -r requirements.txt
   ```

   Or with pip3:
   ```bash
   pip3 install -r requirements.txt
   ```

## Setup

1. Open Chrome DevTools (F12) in your browser

2. Go to the [Claude usage status page](https://claude.ai/settings/usage)

3. In the Network tab, filter for "usage"

4. Right-click the usage fetch request and select: **Copy > Copy as cURL**

   <img width="1640" height="1546" alt="image" src="https://github.com/user-attachments/assets/e5eab8af-c3a1-4e0d-9e19-e16d86862a8b" />

5. Create a file named `curl.txt` in the project directory (same location as `claude_usage_menubar.py`)

6. Paste the cURL command into `curl.txt` and save

## Running the App

### Windows
```bash
python claude_usage_menubar.py
```

The app will appear in your **system tray** (bottom-right corner of taskbar). Right-click the icon to access the menu.

### macOS
```bash
python3 claude_usage_menubar.py &
```

The app will appear in your **menu bar** (top-right corner). Click the icon to access the menu.

### First Run
- Windows may prompt for notification permissions - allow them for alerts to work
- The app will automatically start monitoring your Claude usage
- Initial data fetch may take a few seconds

## Usage

### Menu Options

- **Update Now** - Manually refresh usage data
- **Check Notification State** - View which notification thresholds have been triggered
- **Reset Notification History** - Clear notification history to re-enable alerts
- **Test Notification** - Verify notifications are working
- **5-Hour Reset** - Shows when your session limit resets
- **7-Day Reset** - Shows when your weekly limit resets
- **Next Update** - Countdown to next automatic update
- **Exit** (Windows only) - Close the application

### Understanding the Display

The tray/menu bar shows: `5h: XX% | 7d: YY%`
- **5h**: Current 5-hour session usage percentage
- **7d**: Current 7-day weekly usage percentage

### Notifications

You'll receive desktop notifications when usage crosses these thresholds:
- 25% - Early warning
- 50% - Halfway point
- 75% - Approaching limit
- 90% - Nearly at limit

Notifications are sent only once per threshold to avoid spam.

## Troubleshooting

### Windows

**Notifications not appearing:**
- Check Windows notification settings (Settings > System > Notifications)
- Ensure "Get notifications from apps and other senders" is enabled
- Click "Test Notification" to verify

**App not starting:**
- Verify Python 3.8+ is installed: `python --version`
- Verify newman is installed: `newman --version`
- Check that `curl.txt` exists and contains a valid cURL command

### macOS

**Menu bar icon not appearing:**
- Ensure `rumps` installed correctly: `pip3 show rumps`
- Check for errors in terminal output
- Try running without `&` to see error messages

### Both Platforms

**"Newman failed" error:**
- Verify Node.js is installed: `node --version`
- Verify newman is installed: `newman --version`
- Reinstall newman: `npm install -g newman`

**"No cURL command found" error:**
- Ensure `curl.txt` exists in the same directory as the script
- Verify the file contains a complete cURL command from Claude's usage page
- Re-copy the cURL command from your browser

**Usage shows "N/A":**
- Your cURL token may have expired
- Get a fresh cURL command from Claude's usage page
- Replace the contents of `curl.txt` with the new command

## Configuration

Edit `claude_usage_menubar.py` to customize:

- `UPDATE_INTERVAL`: Seconds between automatic updates (default: 180 = 3 minutes)
- `THRESHOLDS`: Notification thresholds (default: [25, 50, 75, 90])
- `DEBUG`: Set to `True` to enable debug logging

## Dependencies

### Windows
- `pystray` - System tray integration
- `Pillow` - Icon image generation
- `win11toast` - Windows notifications

### macOS
- `rumps` - Menu bar integration and notifications

### Both Platforms
- `newman` (Node.js) - API request handling

## How It Works

1. Converts your cURL command to a Postman collection
2. Uses newman to execute the API request every 3 minutes
3. Parses the response to extract usage percentages
4. Displays data in system tray (Windows) or menu bar (macOS)
5. Sends notifications when usage crosses threshold percentages
6. Maintains notification state to prevent duplicate alerts

Happy Vibing!
