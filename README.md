# claude-usage-widget

Cross-platform Python script to monitor Claude AI usage limits and display them in your system tray (Windows) or menu bar (macOS).

<img width="447" height="105" alt="image" src="https://github.com/user-attachments/assets/ce92d374-2688-4c9a-919a-d9fb12b57c5d" />

## Features

- Real-time monitoring of Claude usage (5-hour session and 7-day weekly limits)
- System tray (Windows) / menu bar (macOS) integration
- Desktop notifications at usage thresholds (25%, 50%, 75%, 90%)
- Automatic updates every 3 minutes
- Manual update option
- Reset time display

## Platform Support

- **Windows 10/11**: System tray icon with Windows toast notifications
- **macOS**: Menu bar icon with native macOS notifications

## Prerequisites

1. **Python 3.8+** with pip

## Installation

1. Clone or download this repository

2. Navigate to the project directory:
   ```bash
   cd claude-usage-widget
   ```

3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
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
- **Next Update** - Shows the time of the next automatic update
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
- Check that `curl.txt` exists and contains a valid cURL command

### macOS

**Menu bar icon not appearing:**
- Ensure `rumps` installed correctly: `pip3 show rumps`
- Check for errors in terminal output
- Try running without `&` to see error messages

### Both Platforms

**"No cURL command found" error:**
- Ensure `curl.txt` exists in the same directory as the script
- Verify the file contains a complete cURL command from Claude's usage page
- Re-copy the cURL command from your browser

**Usage shows "N/A" or fetch error:**
- Your cURL token may have expired
- Get a fresh cURL command from Claude's usage page
- Replace the contents of `curl.txt` with the new command

## Auto-Start on Windows

To make the app start automatically when you log in to Windows:

### Option 1: Using Startup Folder (Recommended)

1. **Locate your Startup folder**:
   - Press `Win + R`
   - Type: `shell:startup`
   - Press Enter

2. **Create a shortcut**:
   - Right-click in the Startup folder
   - Select `New` → `Shortcut`
   - Browse to: `C:\claude_projects\claude_usage_widget\claude-usage-widget\start_claude_monitor_silent.vbs`
   - Click `Next`, name it "Claude Usage Monitor", and click `Finish`

3. **Done!** The app will now start automatically when you log in (no console window will appear).

### Option 2: Manual Start

If you prefer to start manually, simply run:
```bash
cd claude-usage-widget
python claude_usage_menubar.py
```

Or double-click `start_claude_monitor_silent.vbs` to run without a console window.

### Startup Files Included

- **`start_claude_monitor.bat`** - Batch file to start the app (shows console)
- **`start_claude_monitor_silent.vbs`** - VBScript to start silently (no console window) ⭐ Recommended

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

## How It Works

1. Parses your cURL command to extract the API URL and headers
2. Makes a direct HTTP request to the Claude usage API every 3 minutes
3. Parses the response to extract usage percentages
4. Displays data in system tray (Windows) or menu bar (macOS)
5. Sends notifications when usage crosses threshold percentages
6. Maintains notification state to prevent duplicate alerts

Happy Vibing!
