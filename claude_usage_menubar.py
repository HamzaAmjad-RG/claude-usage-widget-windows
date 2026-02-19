#!/usr/bin/env python3

import os
import json
import re
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
import shlex
import platform
import threading
from abc import ABC, abstractmethod

# Conditional imports based on platform
if platform.system() == "Darwin":  # macOS
    import rumps
elif platform.system() == "Windows":
    import pystray
    from PIL import Image, ImageDraw, ImageFont


DEBUG = False  # Set False to disable logs

def debug_log(*args, **kwargs):
    if DEBUG:
        print("[DEBUG]", *args, **kwargs)


# Config
UPDATE_INTERVAL = 180  # seconds, 3 minutes
STATE_FILE = "notification_state.json"

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

PARSED_CURL = {}  # populated at startup after parse_curl_command is defined

# Notification thresholds
THRESHOLDS = [25, 50, 75, 90]


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
    """Check if we should send notifications for any thresholds that were crossed.
    Returns only the HIGHEST threshold to avoid notification spam."""
    sent_thresholds = state.get(usage_type, {}).get("sent", [])

    thresholds_to_send = [t for t in THRESHOLDS if current_utilization >= t and t not in sent_thresholds]

    if thresholds_to_send:
        return {
            'notify': [max(thresholds_to_send)],  # Only notify for highest
            'mark_sent': thresholds_to_send        # Mark all as sent
        }

    return None

def send_notification_macos(usage_type, threshold, current_utilization):
    """Send a macOS notification using both rumps and osascript"""
    title = "Claude Usage Alert"
    subtitle = f"{usage_type.replace('_', ' ').title()}"
    message = f"Usage reached {current_utilization}% (threshold: {threshold}%)"

    # Method 1: rumps (may not work if app is not signed/notarized)
    try:
        rumps.notification(title=title, subtitle=subtitle, message=message, sound=True)
    except Exception:
        pass

    # Method 2: osascript (more reliable)
    try:
        subprocess.run([
            'osascript', '-e',
            f'display notification "{message}" with title "{title}" subtitle "{subtitle}" sound name "default"'
        ], check=True, capture_output=True, text=True)
    except Exception:
        pass

def send_notification_windows(usage_type, threshold, current_utilization):
    """Send a Windows notification using win11toast"""
    title = "Claude Usage Alert"
    subtitle = f"{usage_type.replace('_', ' ').title()}"
    message = f"Usage reached {current_utilization}% (threshold: {threshold}%)"

    try:
        from win11toast import notify
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
    except Exception:
        return reset_time_str

def format_absolute_time(reset_time_str):
    """Format the reset time as an absolute local time"""
    try:
        reset_time = datetime.fromisoformat(reset_time_str.replace('Z', '+00:00'))
        local_time = reset_time.astimezone()
        return local_time.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return ""

def format_absolute_time_with_day(reset_time_str):
    """Format the reset time as an absolute local day + time"""
    try:
        reset_time = datetime.fromisoformat(reset_time_str.replace('Z', '+00:00'))
        local_time = reset_time.astimezone()
        return local_time.strftime("%a %I:%M %p").lstrip("0")
    except Exception:
        return ""

def parse_curl_command(curl_command: str) -> dict:
    """Parse a curl command and return url, method, and headers dict"""
    if platform.system() == "Windows":
        curl_command = re.sub(r'\^\s*\n\s*', ' ', curl_command)
        curl_command = curl_command.replace('^"', '"')
        curl_command = re.sub(r'\^(?=[^"])', '', curl_command)

    tokens = shlex.split(curl_command)
    method = "GET"
    url = ""
    headers = {}

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

        if token in ("-b", "--cookie"):
            headers["Cookie"] = tokens[i + 1]
            i += 2
            continue

        if not token.startswith("-") and url == "":
            url = token
            i += 1
            continue

        i += 1

    debug_log(f"Parsed curl: method={method}, url={url}, headers={list(headers.keys())}")
    return {"url": url, "method": method, "headers": headers}


def fetch_usage() -> tuple:
    """Make a direct HTTP request and return (usage_data, error_msg).
    Returns (data_dict, None) on success, (None, error_str) on failure."""
    try:
        req = urllib.request.Request(
            PARSED_CURL["url"],
            method=PARSED_CURL["method"],
            headers=PARSED_CURL["headers"]
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            response_json = json.loads(response.read().decode("utf-8"))

        five_hour_data = response_json.get("five_hour", {})
        seven_day_data = response_json.get("seven_day", {})

        five_hour_raw = five_hour_data.get("utilization", "N/A")
        seven_day_raw = seven_day_data.get("utilization", "N/A")

        five_hour = round(five_hour_raw) if isinstance(five_hour_raw, (int, float)) else five_hour_raw
        seven_day = round(seven_day_raw) if isinstance(seven_day_raw, (int, float)) else seven_day_raw

        return {
            "five_hour": five_hour,
            "seven_day": seven_day,
            "five_hour_reset": five_hour_data.get("resets_at", ""),
            "seven_day_reset": seven_day_data.get("resets_at", "")
        }, None

    except urllib.error.URLError:
        debug_log("fetch_usage failed: no internet connection")
        return None, "No internet"
    except TimeoutError:
        debug_log("fetch_usage failed: request timed out")
        return None, "Timed out"
    except Exception as e:
        debug_log(f"fetch_usage failed: {e}")
        return None, "Fetch error"


class UsageMonitorApp(ABC):
    """Abstract base class for platform-specific implementations"""

    def __init__(self):
        self.notification_state = load_notification_state()
        self.next_update_time = None
        self.current_usage_text = "Loading..."
        self.current_usage_data = None
        self._update_lock = threading.Lock()

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
        if not self._update_lock.acquire(blocking=False):
            return  # another update is already in progress

        try:
            self._update_usage_inner()
        finally:
            self._update_lock.release()

    def _update_usage_inner(self):
        usage_data, error = fetch_usage()

        if usage_data:
            # Check and send notifications for five_hour
            if isinstance(usage_data["five_hour"], (int, float)):
                reset_notifications_if_needed("five_hour", usage_data["five_hour"], self.notification_state)
                result = should_send_notification("five_hour", usage_data["five_hour"], self.notification_state)

                if result:
                    for threshold in result['notify']:
                        send_notification("five_hour", threshold, usage_data["five_hour"])
                        time.sleep(0.5)
                    for threshold in result['mark_sent']:
                        if threshold not in self.notification_state["five_hour"]["sent"]:
                            self.notification_state["five_hour"]["sent"].append(threshold)

            # Check and send notifications for seven_day
            if isinstance(usage_data["seven_day"], (int, float)):
                reset_notifications_if_needed("seven_day", usage_data["seven_day"], self.notification_state)
                result = should_send_notification("seven_day", usage_data["seven_day"], self.notification_state)

                if result:
                    for threshold in result['notify']:
                        send_notification("seven_day", threshold, usage_data["seven_day"])
                        time.sleep(0.5)
                    for threshold in result['mark_sent']:
                        if threshold not in self.notification_state["seven_day"]["sent"]:
                            self.notification_state["seven_day"]["sent"].append(threshold)

            save_notification_state(self.notification_state)
            self.current_usage_data = usage_data
            five_hour = usage_data["five_hour"]
            seven_day = usage_data["seven_day"]
            self.current_usage_text = f"5h: {five_hour}% | 7d: {seven_day}%"
        else:
            # Keep last known values in the title, append the error reason
            base = self.current_usage_text if self.current_usage_text else "5h: ? | 7d: ?"
            # Strip any previously appended error suffix before adding the new one
            base = re.sub(r'\s*\([^)]*\)\s*$', '', base).strip()
            self.current_usage_text = f"{base} ({error})"

        self.next_update_time = datetime.now() + timedelta(seconds=UPDATE_INTERVAL)

        self.update_display(self.current_usage_text, usage_data)


class MacOSMenuBarApp(UsageMonitorApp):
    """macOS menu bar implementation using rumps"""

    def __init__(self):
        super().__init__()
        self.app = rumps.App("Usage")
        self._five_hour_item = rumps.MenuItem("5-Hour Reset: Loading...", callback=None)
        self._seven_day_item = rumps.MenuItem("7-Day Reset: Loading...", callback=None)
        self._next_update_item = rumps.MenuItem("Next Update: Loading...", callback=None)
        self.app.menu = [
            rumps.MenuItem("Update Now", callback=self.manual_update),
            rumps.MenuItem("Check Notification State", callback=self.check_state),
            rumps.MenuItem("Reset Notification History", callback=self.reset_notification_history),
            rumps.MenuItem("Test Notification", callback=self.send_test_notification),
            None,  # Separator
            self._five_hour_item,
            self._seven_day_item,
            self._next_update_item,
        ]

        self.update_timer = rumps.Timer(self.timer_update_usage, UPDATE_INTERVAL)
        self.countdown_timer = rumps.Timer(self.update_countdown, 1)

    def run(self):
        self.update_usage()
        self.update_timer.start()
        self.countdown_timer.start()
        self.app.run()

    def update_display(self, usage_text, usage_data):
        self.app.title = usage_text

        if usage_data:
            five_hour_reset_text = format_reset_time(usage_data["five_hour_reset"])
            seven_day_reset_text = format_reset_time(usage_data["seven_day_reset"])
            five_hour_abs = format_absolute_time(usage_data["five_hour_reset"])
            seven_day_abs = format_absolute_time_with_day(usage_data["seven_day_reset"])

            self._five_hour_item.title = f"5-Hour Reset: {five_hour_reset_text} ({five_hour_abs})"
            self._seven_day_item.title = f"7-Day Reset: {seven_day_reset_text} ({seven_day_abs})"

    def timer_update_usage(self, _):
        self.update_usage()

    def manual_update(self, _):
        threading.Thread(target=self.update_usage, daemon=True).start()

    def send_test_notification(self, _=None):
        try:
            rumps.notification(
                title="Claude Usage Monitor",
                subtitle="Test Notification",
                message="If you see this, notifications are working!",
                sound=True
            )
        except Exception:
            pass

        try:
            subprocess.run([
                'osascript', '-e',
                'display notification "If you see this, notifications are working!" with title "Claude Usage Monitor" subtitle "Test Notification" sound name "default"'
            ])
        except Exception:
            pass

    def check_state(self, _):
        rumps.alert(
            title="Notification State",
            message=f"5-Hour sent: {self.notification_state['five_hour']['sent']}\n7-Day sent: {self.notification_state['seven_day']['sent']}"
        )

    def reset_notification_history(self, _):
        self.notification_state = {
            "five_hour": {"sent": []},
            "seven_day": {"sent": []}
        }
        save_notification_state(self.notification_state)
        rumps.alert(title="Reset Complete", message="Notification history has been cleared")

    def update_countdown(self, _):
        if self.next_update_time:
            now = datetime.now()
            time_until_update = self.next_update_time - now

            if time_until_update.total_seconds() > 0:
                minutes = int(time_until_update.total_seconds() // 60)
                seconds = int(time_until_update.total_seconds() % 60)
                self._next_update_item.title = f"Next Update: {minutes}m {seconds}s"
            else:
                self._next_update_item.title = "Next Update: Updating..."
        else:
            self._next_update_item.title = "Next Update: Loading..."


class WindowsTrayApp(UsageMonitorApp):
    """Windows system tray implementation using pystray"""

    def __init__(self):
        super().__init__()
        self.icon = None
        self.update_thread = None
        self.stop_threads = threading.Event()
        self._timer_reset = threading.Event()
        self._five_hour_menu_text = "5-Hour Reset: Loading..."
        self._seven_day_menu_text = "7-Day Reset: Loading..."
        self._next_update_menu_text = "Next Update: Loading..."
        self._fonts = {}  # font size -> ImageFont, cached after first load

    def run(self):
        image = self.create_icon_image()

        # Callable menu items read from instance variables on open — no rebuilding needed
        menu = pystray.Menu(
            pystray.MenuItem("Update Now", self.manual_update),
            pystray.MenuItem("Check Notification State", self.check_state),
            pystray.MenuItem("Reset Notification History", self.reset_notification_history),
            pystray.MenuItem("Test Notification", self.send_test_notification),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: self._five_hour_menu_text, None, enabled=False),
            pystray.MenuItem(lambda item: self._seven_day_menu_text, None, enabled=False),
            pystray.MenuItem(lambda item: self._next_update_menu_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self.exit_app)
        )

        self.icon = pystray.Icon("claude_usage", image, "Usage", menu)

        self.update_usage()
        self.start_background_threads()
        self.icon.run()

    def _get_font(self, nchars):
        """Return a cached font sized for the given character count"""
        font_size = 50 if nchars == 1 else (42 if nchars == 2 else 30)
        if font_size not in self._fonts:
            font_paths = [
                "C:/Windows/Fonts/arialbd.ttf",
                "C:/Windows/Fonts/arial.ttf",
            ]
            font = None
            for fp in font_paths:
                try:
                    font = ImageFont.truetype(fp, font_size)
                    break
                except Exception:
                    continue
            self._fonts[font_size] = font or ImageFont.load_default()
        return self._fonts[font_size]

    def create_icon_image(self, usage_percent=None):
        """Create a color-coded tray icon with usage percentage"""
        width, height = 64, 64

        if usage_percent is None:
            fill_color = '#6c757d'
            outline_color = '#495057'
            text_color = 'white'
            display_text = "?"
        else:
            if usage_percent < 50:
                fill_color = '#28a745'
                outline_color = '#1e7e34'
                text_color = 'white'
            elif usage_percent < 75:
                fill_color = '#ffc107'
                outline_color = '#e0a800'
                text_color = '#1a1a1a'
            elif usage_percent < 90:
                fill_color = '#fd7e14'
                outline_color = '#d9650a'
                text_color = 'white'
            else:
                fill_color = '#dc3545'
                outline_color = '#bd2130'
                text_color = 'white'
            display_text = f"{int(usage_percent)}"

        image = Image.new('RGBA', (width, height), color=(0, 0, 0, 0))
        dc = ImageDraw.Draw(image)
        dc.rounded_rectangle([4, 4, 60, 60], radius=14, fill=fill_color, outline=outline_color, width=2)

        font = self._get_font(len(display_text))
        bbox = dc.textbbox((0, 0), display_text, font=font)
        text_x = (width - (bbox[2] - bbox[0])) // 2 - bbox[0]
        text_y = (height - (bbox[3] - bbox[1])) // 2 - bbox[1]
        dc.text((text_x, text_y), display_text, fill=text_color, font=font)

        return image

    def start_background_threads(self):
        self.update_thread = threading.Thread(target=self.recurring_update, daemon=True)
        self.update_thread.start()

    def recurring_update(self):
        while not self.stop_threads.is_set():
            self._timer_reset.clear()
            reset = self._timer_reset.wait(UPDATE_INTERVAL)
            if self.stop_threads.is_set():
                break
            if reset:
                continue  # manual update already ran, just restart the countdown
            self.update_usage()

    def update_display(self, usage_text, usage_data):
        """Update tooltip, icon image, and menu text variables"""
        if self.next_update_time:
            self._next_update_menu_text = "Next Update: " + self.next_update_time.strftime("%I:%M:%S %p").lstrip("0")

        if self.icon:
            self.icon.title = usage_text[:128]

            if usage_data:
                five_hour = usage_data.get("five_hour", 0)
                self.icon.icon = self.create_icon_image(five_hour if isinstance(five_hour, (int, float)) else None)

                five_hour_reset_text = format_reset_time(usage_data["five_hour_reset"])
                seven_day_reset_text = format_reset_time(usage_data["seven_day_reset"])
                five_hour_abs = format_absolute_time(usage_data["five_hour_reset"])
                seven_day_abs = format_absolute_time_with_day(usage_data["seven_day_reset"])

                self._five_hour_menu_text = f"5-Hour Reset: {five_hour_reset_text} ({five_hour_abs})"
                self._seven_day_menu_text = f"7-Day Reset: {seven_day_reset_text} ({seven_day_abs})"

            self.icon.update_menu()

    def manual_update(self, icon=None, item=None):
        self._timer_reset.set()  # reset the auto-update countdown
        threading.Thread(target=self._run_manual_update, daemon=True).start()

    def _run_manual_update(self):
        if not self._update_lock.acquire(blocking=False):
            return  # another update is already in progress; don't touch the text
        self._next_update_menu_text = "Next Update: Updating..."
        try:
            self._update_usage_inner()
        finally:
            self._update_lock.release()

    def send_test_notification(self, icon=None, item=None):
        try:
            from win11toast import notify
            notify(
                title="Claude Usage Monitor",
                body="Test Notification\nIf you see this, notifications are working!",
                app_id="Claude Usage Monitor",
                audio="ms-winsoundevent:Notification.Default"
            )
        except Exception as e:
            debug_log(f"Test notification failed: {e}")

    def check_state(self, icon=None, item=None):
        state_msg = f"5-Hour sent: {self.notification_state['five_hour']['sent']}\n7-Day sent: {self.notification_state['seven_day']['sent']}"
        try:
            from win11toast import notify
            notify(title="Notification State", body=state_msg, app_id="Claude Usage Monitor")
        except Exception as e:
            debug_log(f"Failed to show state: {e}")

    def reset_notification_history(self, icon=None, item=None):
        self.notification_state = {
            "five_hour": {"sent": []},
            "seven_day": {"sent": []}
        }
        save_notification_state(self.notification_state)
        try:
            from win11toast import notify
            notify(title="Reset Complete", body="Notification history has been cleared", app_id="Claude Usage Monitor")
        except Exception as e:
            debug_log(f"Failed to show reset confirmation: {e}")

    def exit_app(self, icon=None, item=None):
        self.stop_threads.set()
        if self.icon:
            self.icon.stop()


if __name__ == "__main__":
    PARSED_CURL.update(parse_curl_command(CURL_COMMAND))
    if not PARSED_CURL["url"]:
        raise RuntimeError("Could not parse URL from curl.txt")

    if platform.system() == "Darwin":
        app = MacOSMenuBarApp()
    elif platform.system() == "Windows":
        app = WindowsTrayApp()
    else:
        raise RuntimeError(f"Unsupported platform: {platform.system()}")

    app.run()
