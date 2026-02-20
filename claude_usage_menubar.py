#!/usr/bin/env python3

import os
import json
import subprocess
from datetime import datetime, timedelta
import shlex
import uuid
from urllib.parse import urlparse
import platform
import threading
from abc import ABC, abstractmethod

# Conditional imports based on platform
if platform.system() == "Darwin":  # macOS
    import rumps
elif platform.system() == "Windows":
    import pystray
    from PIL import Image, ImageDraw
    from win11toast import notify


# Config
COLLECTION_FILE = "MyCollection.postman_collection.json"
NEWMAN_OUTPUT_FILE = "output.json"
UPDATE_INTERVAL = 180  # seconds, 3 minutes
STATE_FILE = "notification_state.json"
DEBUG = False  # Set False to disable logs

# Read cURL command from file
CURL_FILE = "curl.txt"
if os.path.exists(CURL_FILE):
    with open(CURL_FILE, "r", encoding="utf-8") as f:
        CURL_COMMAND = f.read().strip()
else:
    debug_log(f"{CURL_FILE} not found!")
    CURL_COMMAND = ""

if not CURL_COMMAND:
    raise RuntimeError("No cURL command found in curl.txt")

# Notification thresholds
THRESHOLDS = [25, 50, 75, 90]

def debug_log(*args, **kwargs):
    if DEBUG:
        print("[DEBUG]", *args, **kwargs)


def load_notification_state():
    """Load the state of which notifications have been sent"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {
        "five_hour": {"sent": []},
        "seven_day": {"sent": []}
    }

def save_notification_state(state):
    """Save the notification state to disk"""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def should_send_notification(usage_type, current_utilization, state):
    """Check if we should send notifications for any thresholds that were crossed
    Returns only the HIGHEST threshold to avoid notification spam"""
    sent_thresholds = state.get(usage_type, {}).get("sent", [])
    
    # Find all thresholds that should trigger
    thresholds_to_send = []
    for threshold in THRESHOLDS:
        if current_utilization >= threshold and threshold not in sent_thresholds:
            thresholds_to_send.append(threshold)
    
    # To avoid spam, only return the highest threshold
    # But mark all lower ones as sent
    if thresholds_to_send:
        return {
            'notify': [max(thresholds_to_send)],  # Only notify for highest
            'mark_sent': thresholds_to_send       # Mark all as sent
        }
    
    return None

def send_notification_macos(usage_type, threshold, current_utilization):
    """Send a macOS notification using both rumps and osascript"""
    title = f"Claude Usage Alert"
    subtitle = f"{usage_type.replace('_', ' ').title()}"
    message = f"Usage reached {current_utilization}% (threshold: {threshold}%)"

    # Method 1: rumps (may not work if app is not signed/notarized)
    try:
        rumps.notification(
            title=title,
            subtitle=subtitle,
            message=message,
            sound=True
        )
    except Exception as e:
        pass

    # Method 2: osascript (more reliable)
    try:
        subprocess.run([
            'osascript', '-e',
            f'display notification "{message}" with title "{title}" subtitle "{subtitle}" sound name "default"'
        ], check=True, capture_output=True, text=True)
    except Exception as e:
        pass

def send_notification_windows(usage_type, threshold, current_utilization):
    """Send a Windows notification using win11toast"""
    title = f"Claude Usage Alert"
    subtitle = f"{usage_type.replace('_', ' ').title()}"
    message = f"Usage reached {current_utilization}% (threshold: {threshold}%)"

    try:
        notify(
            title=title,
            body=f"{subtitle}\n{message}",
            app_id="Claude Usage Monitor",
            audio="ms-winsoundevent:Notification.Default"
        )
    except Exception as e:
        debug_log(f"Windows notification failed: {e}")

def send_notification(usage_type, threshold, current_utilization):
    """Platform-agnostic notification dispatcher"""
    if platform.system() == "Darwin":
        send_notification_macos(usage_type, threshold, current_utilization)
    elif platform.system() == "Windows":
        send_notification_windows(usage_type, threshold, current_utilization)

def reset_notifications_if_needed(usage_type, current_utilization, state):
    """Reset notification state for any thresholds that usage has fallen below"""
    sent_thresholds = state.get(usage_type, {}).get("sent", [])
    if sent_thresholds:
        # Keep only thresholds that are still at or below current utilization
        state[usage_type]["sent"] = [t for t in sent_thresholds if current_utilization >= t]

def format_reset_time(reset_time_str):
    """Format the reset time in a readable way"""
    try:
        reset_time = datetime.fromisoformat(reset_time_str.replace('Z', '+00:00'))
        now = datetime.now(reset_time.tzinfo)
        
        time_diff = reset_time - now
        
        if time_diff.total_seconds() < 0:
            return "Resetting soon"
        
        hours = int(time_diff.total_seconds() // 3600)
        minutes = int((time_diff.total_seconds() % 3600) // 60)
        
        if hours > 24:
            days = hours // 24
            hours = hours % 24
            return f"Resets in {days}d {hours}h"
        elif hours > 0:
            return f"Resets in {hours}h {minutes}m"
        else:
            return f"Resets in {minutes}m"
    except Exception as e:
        return reset_time_str

def format_absolute_time(reset_time_str):
    """Format the reset time as an absolute local time"""
    try:
        reset_time = datetime.fromisoformat(reset_time_str.replace('Z', '+00:00'))
        local_time = reset_time.astimezone()  # Convert to local timezone
        return local_time.strftime("%I:%M %p").lstrip("0")  # e.g., "3:45 PM"
    except Exception:
        return ""

def format_absolute_time_with_day(reset_time_str):
    """Format the reset time as an absolute local day + time"""
    try:
        reset_time = datetime.fromisoformat(reset_time_str.replace('Z', '+00:00'))
        local_time = reset_time.astimezone()
        # Example: "Wed 3:45 PM"
        return local_time.strftime("%a %I:%M %p").lstrip("0")
    except Exception:
        return ""

def run_newman():
    """Run Newman and export JSON output"""
    debug_log("Running Newman with collection:", COLLECTION_FILE)

    # Use newman.cmd on Windows, newman on other platforms
    newman_cmd = "newman.cmd" if platform.system() == "Windows" else "newman"

    try:
        result = subprocess.run([
            newman_cmd, "run", COLLECTION_FILE,
            "-r", "json",
            "--reporter-json-export", NEWMAN_OUTPUT_FILE
        ], check=True, capture_output=True, text=True)

        debug_log("Newman STDOUT:\n", result.stdout)
        debug_log("Newman STDERR:\n", result.stderr)
        return True
    except subprocess.CalledProcessError as e:
        debug_log("Newman failed with return code:", e.returncode)
        debug_log("Newman STDOUT:\n", e.stdout)
        debug_log("Newman STDERR:\n", e.stderr)
        return False


def get_usage_from_newman_json():
    """Parse the Newman JSON output and return usage info"""
    if not os.path.exists(NEWMAN_OUTPUT_FILE):
        return None, "No data"

    try:
        with open(NEWMAN_OUTPUT_FILE, "r") as f:
            data = json.load(f)

        executions = data.get("run", {}).get("executions", [])
        if not executions:
            return None, "No executions"

        response_stream = executions[0].get("response", {}).get("stream", {}).get("data", [])
        if not response_stream:
            return None, "No response stream"

        # Convert list of ints to string if needed
        if isinstance(response_stream, list):
            response_text = bytes(response_stream).decode("utf-8")
        else:
            response_text = str(response_stream)

        response_json = json.loads(response_text)

        # Extract both five_hour and seven_day usage
        five_hour_data = response_json.get("five_hour", {})
        seven_day_data = response_json.get("seven_day", {})
        
        five_hour_raw = five_hour_data.get("utilization", "N/A")
        seven_day_raw = seven_day_data.get("utilization", "N/A")

        # Round to whole numbers to conserve space
        five_hour = round(five_hour_raw) if isinstance(five_hour_raw, (int, float)) else five_hour_raw
        seven_day = round(seven_day_raw) if isinstance(seven_day_raw, (int, float)) else seven_day_raw

        five_hour_reset = five_hour_data.get("resets_at", "")
        seven_day_reset = seven_day_data.get("resets_at", "")

        # Concise display: e.g., "5h:56% | 7d:25%"
        display_text = f"5h: {five_hour}% | 7d: {seven_day}%"
        
        return {
            "five_hour": five_hour,
            "seven_day": seven_day,
            "five_hour_reset": five_hour_reset,
            "seven_day_reset": seven_day_reset
        }, display_text

    except Exception as e:
        return None, f"Error: {e}"

def parse_curl(curl_command: str):
    tokens = shlex.split(curl_command)

    method = "GET"
    url = ""
    headers = {}
    body = None

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token == "curl":
            i += 1
            continue

        if token in ("-X", "--request"):
            method = tokens[i + 1].upper()
            i += 2
            continue

        if token in ("-H", "--header"):
            key, value = tokens[i + 1].split(":", 1)
            headers[key.strip()] = value.strip()
            i += 2
            continue

        if token in ("-d", "--data", "--data-raw", "--data-binary"):
            body = tokens[i + 1]
            if method == "GET":
                method = "POST"
            i += 2
            continue

        if not token.startswith("-"):
            url = token
            i += 1
            continue

        i += 1

    return method, url, headers, body


def generate_postman_collection_from_curl(curl_command: str):
    debug_log("Generating Postman collection from cURL...")

    import shlex
    import uuid
    from urllib.parse import urlparse
    import re

    # Clean Windows batch-style cURL command
    # Remove ^ line continuation and escape characters
    if platform.system() == "Windows":
        # Remove ^ at end of lines (line continuation)
        curl_command = re.sub(r'\^\s*\n\s*', ' ', curl_command)
        # Remove ^ before quotes
        curl_command = curl_command.replace('^"', '"')
        # Remove any remaining standalone ^ characters
        curl_command = re.sub(r'\^(?=[^"])', '', curl_command)

    tokens = shlex.split(curl_command)
    method = "GET"
    url = ""
    headers = []
    cookie_header = None

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token == "curl":
            i += 1
            continue

        # HTTP method
        if token in ("-X", "--request"):
            method = tokens[i + 1].upper()
            debug_log("Detected method:", method)
            i += 2
            continue

        # Header
        if token in ("-H", "--header"):
            key, value = tokens[i + 1].split(":", 1)
            headers.append({"key": key.strip(), "value": value.strip()})
            debug_log(f"Added header: {key.strip()}: {value.strip()}")
            i += 2
            continue

        # Cookie shortcut
        if token in ("-b", "--cookie"):
            cookie_value = tokens[i + 1]
            cookie_header = {"key": "Cookie", "value": cookie_value}
            debug_log("Detected cookie:", cookie_value)
            i += 2
            continue

        # URL
        if not token.startswith("-") and url == "":
            url = token
            debug_log("Detected URL:", url)
            i += 1
            continue

        i += 1

    # If -b/--cookie exists, merge it as a Cookie header (overwrites existing if any)
    if cookie_header:
        # Remove any existing Cookie headers first
        headers = [h for h in headers if h["key"].lower() != "cookie"]
        headers.append(cookie_header)
        debug_log("Final Cookie header set:", cookie_header)

    parsed = urlparse(url)

    collection = {
        "info": {
            "_postman_id": str(uuid.uuid4()),
            "name": "My Collection",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
        },
        "item": [
            {
                "name": url,
                "request": {
                    "method": method,
                    "header": headers,
                    "url": {
                        "raw": url,
                        "protocol": parsed.scheme,
                        "host": parsed.netloc.split("."),
                        "path": parsed.path.strip("/").split("/")
                    },
                    "description": f"Generated from cURL: {curl_command.strip()[:60]}"
                },
                "response": []
            }
        ]
    }

    with open(COLLECTION_FILE, "w", encoding="utf-8") as f:
        json.dump(collection, f, indent=2)

    debug_log("Postman collection generated successfully:", COLLECTION_FILE)


class UsageMonitorApp(ABC):
    """Abstract base class for platform-specific implementations"""

    def __init__(self):
        self.notification_state = load_notification_state()
        self.next_update_time = None
        self.current_usage_text = "Loading..."
        self.current_usage_data = None

    @abstractmethod
    def run(self):
        """Start the application (blocking)"""
        pass

    @abstractmethod
    def update_display(self, usage_text, usage_data):
        """Update the UI with new usage information"""
        pass

    def update_usage(self):
        """Core update logic - same for all platforms"""
        usage_data = None
        usage_text = "Loading..."

        if run_newman():
            usage_data, usage_text = get_usage_from_newman_json()

            if usage_data:
                # Check and send notifications for five_hour
                if isinstance(usage_data["five_hour"], (int, float)):
                    reset_notifications_if_needed("five_hour", usage_data["five_hour"], self.notification_state)
                    result = should_send_notification("five_hour", usage_data["five_hour"], self.notification_state)

                    if result:
                        # Send notification only for highest threshold
                        for threshold in result['notify']:
                            send_notification("five_hour", threshold, usage_data["five_hour"])
                            import time
                            time.sleep(0.5)  # Small delay to ensure notification is processed

                        # Mark all thresholds as sent
                        for threshold in result['mark_sent']:
                            if threshold not in self.notification_state["five_hour"]["sent"]:
                                self.notification_state["five_hour"]["sent"].append(threshold)

                        save_notification_state(self.notification_state)

                # Check and send notifications for seven_day
                if isinstance(usage_data["seven_day"], (int, float)):
                    reset_notifications_if_needed("seven_day", usage_data["seven_day"], self.notification_state)
                    result = should_send_notification("seven_day", usage_data["seven_day"], self.notification_state)

                    if result:
                        # Send notification only for highest threshold
                        for threshold in result['notify']:
                            send_notification("seven_day", threshold, usage_data["seven_day"])
                            import time
                            time.sleep(0.5)  # Small delay to ensure notification is processed

                        # Mark all thresholds as sent
                        for threshold in result['mark_sent']:
                            if threshold not in self.notification_state["seven_day"]["sent"]:
                                self.notification_state["seven_day"]["sent"].append(threshold)

                        save_notification_state(self.notification_state)

                # Always save state to persist any threshold resets
                save_notification_state(self.notification_state)

                self.current_usage_data = usage_data
            else:
                usage_text = usage_text
        else:
            usage_text = "Newman failed"

        self.current_usage_text = usage_text
        self.next_update_time = datetime.now() + timedelta(seconds=UPDATE_INTERVAL)

        self.update_display(usage_text, usage_data if usage_data else None)


class MacOSMenuBarApp(UsageMonitorApp):
    """macOS menu bar implementation using rumps"""

    def __init__(self):
        super().__init__()
        self.app = rumps.App("Usage")
        self.app.menu = [
            rumps.MenuItem("Update Now", callback=self.manual_update),
            rumps.MenuItem("Check Notification State", callback=self.check_state),
            rumps.MenuItem("Reset Notification History", callback=self.reset_notification_history),
            rumps.MenuItem("Test Notification", callback=self.send_test_notification),
            None,  # Separator
            rumps.MenuItem("5-Hour Reset: Loading...", callback=None),
            rumps.MenuItem("7-Day Reset: Loading...", callback=None),
            rumps.MenuItem("Next Update: Loading...", callback=None)
        ]

        # Start timers
        self.update_timer = rumps.Timer(self.timer_update_usage, UPDATE_INTERVAL)
        self.countdown_timer = rumps.Timer(self.update_countdown, 1)

    def run(self):
        """Start the rumps application"""
        self.update_usage()  # Initial update
        self.update_timer.start()
        self.countdown_timer.start()
        self.app.run()

    def update_display(self, usage_text, usage_data):
        """Update menu bar title and menu items"""
        self.app.title = usage_text

        if usage_data:
            five_hour_reset_text = format_reset_time(usage_data["five_hour_reset"])
            seven_day_reset_text = format_reset_time(usage_data["seven_day_reset"])
            five_hour_abs = format_absolute_time(usage_data["five_hour_reset"])
            seven_day_abs = format_absolute_time_with_day(usage_data["seven_day_reset"])

            self.app.menu["5-Hour Reset: Loading..."].title = f"5-Hour Reset: {five_hour_reset_text} ({five_hour_abs})"
            self.app.menu["7-Day Reset: Loading..."].title = f"7-Day Reset: {seven_day_reset_text} ({seven_day_abs})"

    def timer_update_usage(self, _):
        """Wrapper for rumps.Timer callback"""
        self.update_usage()

    def manual_update(self, _):
        """Handle manual update menu item"""
        self.update_usage()

    def send_test_notification(self, _=None):
        """Send test notification"""
        try:
            rumps.notification(
                title="Claude Usage Monitor",
                subtitle="Test Notification",
                message="If you see this, notifications are working!",
                sound=True
            )
        except Exception as e:
            pass

        # Also try using osascript as a fallback
        try:
            subprocess.run([
                'osascript', '-e',
                'display notification "If you see this, notifications are working!" with title "Claude Usage Monitor" subtitle "Test Notification" sound name "default"'
            ])
        except Exception as e:
            pass

    def check_state(self, _):
        """Show notification state"""
        state_info = json.dumps(self.notification_state, indent=2)
        rumps.alert(
            title="Notification State",
            message=f"5-Hour sent: {self.notification_state['five_hour']['sent']}\n7-Day sent: {self.notification_state['seven_day']['sent']}"
        )

    def reset_notification_history(self, _):
        """Reset notification history"""
        self.notification_state = {
            "five_hour": {"sent": []},
            "seven_day": {"sent": []}
        }
        save_notification_state(self.notification_state)
        rumps.alert(title="Reset Complete", message="Notification history has been cleared")

    def update_countdown(self, _):
        """Update the countdown timer display"""
        if self.next_update_time:
            now = datetime.now()
            time_until_update = self.next_update_time - now

            if time_until_update.total_seconds() > 0:
                minutes = int(time_until_update.total_seconds() // 60)
                seconds = int(time_until_update.total_seconds() % 60)
                self.app.menu["Next Update: Loading..."].title = f"Next Update: {minutes}m {seconds}s"
            else:
                self.app.menu["Next Update: Loading..."].title = "Next Update: Updating..."
        else:
            self.app.menu["Next Update: Loading..."].title = "Next Update: Loading..."


class WindowsTrayApp(UsageMonitorApp):
    """Windows system tray implementation using pystray"""

    def __init__(self):
        super().__init__()
        self.icon = None
        self.update_thread = None
        self.countdown_thread = None
        self.stop_threads = threading.Event()

    def run(self):
        """Start the pystray application"""
        # Create icon image
        image = self.create_icon_image()

        # Create menu
        menu = pystray.Menu(
            pystray.MenuItem("Update Now", self.manual_update),
            pystray.MenuItem("Check Notification State", self.check_state),
            pystray.MenuItem("Reset Notification History", self.reset_notification_history),
            pystray.MenuItem("Test Notification", self.send_test_notification),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("5-Hour Reset: Loading...", None, enabled=False),
            pystray.MenuItem("7-Day Reset: Loading...", None, enabled=False),
            pystray.MenuItem("Next Update: Loading...", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self.exit_app)
        )

        # Create icon
        self.icon = pystray.Icon("claude_usage", image, "Usage", menu)

        # Start background threads
        self.start_background_threads()

        # Run initial update
        self.update_usage()

        # Run icon (blocking)
        self.icon.run()

    def create_icon_image(self, usage_percent=None):
        """Create a color-coded tray icon with usage percentage"""
        width = 64
        height = 64

        # Determine color based on usage level
        if usage_percent is None:
            # Default gray when loading
            fill_color = 'gray'
            outline_color = 'darkgray'
            text_color = 'white'
            display_text = "?"
        else:
            # Color coding based on usage
            if usage_percent < 50:
                fill_color = '#28a745'  # Green
                outline_color = '#1e7e34'
            elif usage_percent < 75:
                fill_color = '#ffc107'  # Yellow/Amber
                outline_color = '#e0a800'
            else:
                fill_color = '#dc3545'  # Red
                outline_color = '#bd2130'

            text_color = 'white'
            display_text = f"{int(usage_percent)}"

        # Create icon image with transparent background
        image = Image.new('RGBA', (width, height), color=(0, 0, 0, 0))
        dc = ImageDraw.Draw(image)

        # Draw colored circle
        dc.ellipse([4, 4, 60, 60], fill=fill_color, outline=outline_color, width=2)

        # Draw usage percentage text
        # Use a larger size for better readability
        try:
            from PIL import ImageFont
            # Try to use a larger font
            try:
                font = ImageFont.truetype("arial.ttf", 24)
            except:
                font = ImageFont.load_default()
        except:
            font = None

        # Calculate text position to center it
        if font:
            bbox = dc.textbbox((0, 0), display_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
        else:
            # Estimate for default font
            text_width = len(display_text) * 6
            text_height = 8

        text_x = (width - text_width) // 2
        text_y = (height - text_height) // 2 - 2

        dc.text((text_x, text_y), display_text, fill=text_color, font=font)

        return image

    def start_background_threads(self):
        """Start recurring timer threads"""
        self.update_thread = threading.Thread(target=self.recurring_update, daemon=True)
        self.countdown_thread = threading.Thread(target=self.recurring_countdown, daemon=True)
        self.update_thread.start()
        self.countdown_thread.start()

    def recurring_update(self):
        """Recurring update timer"""
        while not self.stop_threads.is_set():
            self.stop_threads.wait(UPDATE_INTERVAL)
            if not self.stop_threads.is_set():
                self.update_usage()

    def recurring_countdown(self):
        """Recurring countdown timer"""
        while not self.stop_threads.is_set():
            self.stop_threads.wait(1)
            if not self.stop_threads.is_set():
                self.update_countdown_display()

    def update_display(self, usage_text, usage_data):
        """Update system tray tooltip, icon, and menu items"""
        if self.icon:
            self.icon.title = usage_text

            # Update icon with 5-hour usage percentage and color
            if usage_data:
                five_hour = usage_data.get("five_hour", 0)

                # Use 5-hour usage for the icon
                if isinstance(five_hour, (int, float)):
                    self.icon.icon = self.create_icon_image(five_hour)
                else:
                    self.icon.icon = self.create_icon_image(None)

                five_hour_reset_text = format_reset_time(usage_data["five_hour_reset"])
                seven_day_reset_text = format_reset_time(usage_data["seven_day_reset"])
                five_hour_abs = format_absolute_time(usage_data["five_hour_reset"])
                seven_day_abs = format_absolute_time_with_day(usage_data["seven_day_reset"])

                # Rebuild menu with updated text
                menu = pystray.Menu(
                    pystray.MenuItem("Update Now", self.manual_update),
                    pystray.MenuItem("Check Notification State", self.check_state),
                    pystray.MenuItem("Reset Notification History", self.reset_notification_history),
                    pystray.MenuItem("Test Notification", self.send_test_notification),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(f"5-Hour Reset: {five_hour_reset_text} ({five_hour_abs})", None, enabled=False),
                    pystray.MenuItem(f"7-Day Reset: {seven_day_reset_text} ({seven_day_abs})", None, enabled=False),
                    pystray.MenuItem(self.get_countdown_text(), None, enabled=False),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Exit", self.exit_app)
                )
                self.icon.menu = menu

    def get_countdown_text(self):
        """Get countdown text for next update"""
        if self.next_update_time:
            now = datetime.now()
            time_until_update = self.next_update_time - now

            if time_until_update.total_seconds() > 0:
                minutes = int(time_until_update.total_seconds() // 60)
                seconds = int(time_until_update.total_seconds() % 60)
                return f"Next Update: {minutes}m {seconds}s"
            else:
                return "Next Update: Updating..."
        return "Next Update: Loading..."

    def update_countdown_display(self):
        """Update just the countdown timer menu item"""
        if self.icon and self.icon.menu:
            # Rebuild menu to update countdown (pystray limitation)
            self.update_display(self.current_usage_text, self.current_usage_data)

    def manual_update(self, icon=None, item=None):
        """Handle manual update menu item"""
        threading.Thread(target=self.update_usage, daemon=True).start()

    def send_test_notification(self, icon=None, item=None):
        """Send test notification"""
        try:
            notify(
                title="Claude Usage Monitor",
                body="Test Notification\nIf you see this, notifications are working!",
                app_id="Claude Usage Monitor",
                audio="ms-winsoundevent:Notification.Default"
            )
        except Exception as e:
            debug_log(f"Test notification failed: {e}")

    def check_state(self, icon=None, item=None):
        """Show notification state - Windows version"""
        # Use win11toast to show state
        state_msg = f"5-Hour sent: {self.notification_state['five_hour']['sent']}\n7-Day sent: {self.notification_state['seven_day']['sent']}"
        try:
            notify(
                title="Notification State",
                body=state_msg,
                app_id="Claude Usage Monitor"
            )
        except Exception as e:
            debug_log(f"Failed to show state: {e}")

    def reset_notification_history(self, icon=None, item=None):
        """Reset notification history"""
        self.notification_state = {
            "five_hour": {"sent": []},
            "seven_day": {"sent": []}
        }
        save_notification_state(self.notification_state)
        try:
            notify(
                title="Reset Complete",
                body="Notification history has been cleared",
                app_id="Claude Usage Monitor"
            )
        except Exception as e:
            debug_log(f"Failed to show reset confirmation: {e}")

    def exit_app(self, icon=None, item=None):
        """Exit the application"""
        self.stop_threads.set()
        if self.icon:
            self.icon.stop()


if __name__ == "__main__":
    # Generate Postman collection from curl BEFORE running
    generate_postman_collection_from_curl(CURL_COMMAND)

    # Create and run platform-specific app
    if platform.system() == "Darwin":
        app = MacOSMenuBarApp()
    elif platform.system() == "Windows":
        app = WindowsTrayApp()
    else:
        raise RuntimeError(f"Unsupported platform: {platform.system()}")

    app.run()

