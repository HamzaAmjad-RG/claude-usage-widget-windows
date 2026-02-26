#!/usr/bin/env python3

import os
import sys
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
import queue
from abc import ABC, abstractmethod

# Conditional imports based on platform
if platform.system() == "Darwin":  # macOS
    import rumps
elif platform.system() == "Windows":
    import ctypes
    import pystray
    from PIL import Image, ImageDraw, ImageFont

    # Module-level ctypes structures — defined once, not re-created on every _push() call
    class _BIH(ctypes.Structure):
        _fields_ = [
            ('biSize',          ctypes.c_uint32),
            ('biWidth',         ctypes.c_int32),
            ('biHeight',        ctypes.c_int32),
            ('biPlanes',        ctypes.c_uint16),
            ('biBitCount',      ctypes.c_uint16),
            ('biCompression',   ctypes.c_uint32),
            ('biSizeImage',     ctypes.c_uint32),
            ('biXPelsPerMeter', ctypes.c_int32),
            ('biYPelsPerMeter', ctypes.c_int32),
            ('biClrUsed',       ctypes.c_uint32),
            ('biClrImportant',  ctypes.c_uint32),
        ]

    class _BF(ctypes.Structure):
        _fields_ = [
            ('BlendOp',             ctypes.c_ubyte),
            ('BlendFlags',          ctypes.c_ubyte),
            ('SourceConstantAlpha', ctypes.c_ubyte),
            ('AlphaFormat',         ctypes.c_ubyte),
        ]

    class _PT(ctypes.Structure):
        _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]

    class _SZ(ctypes.Structure):
        _fields_ = [('cx', ctypes.c_long), ('cy', ctypes.c_long)]


DEBUG = False  # Set False to disable logs

def debug_log(*args, **kwargs):
    if DEBUG:
        print("[DEBUG]", *args, **kwargs)


# Config
UPDATE_INTERVAL = 180  # seconds, 3 minutes
# When running as a PyInstaller --onefile exe, __file__ points to a temp
# extraction dir.  Use the exe's directory instead so curl.txt etc. are
# found next to the installed executable.
if getattr(sys, 'frozen', False):
    _SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(_SCRIPT_DIR, "notification_state.json")
WIDGET_STATE_FILE = os.path.join(_SCRIPT_DIR, "widget_state.json")

# Read cURL command from file
CURL_FILE = os.path.join(_SCRIPT_DIR, "curl.txt")
if not os.path.exists(CURL_FILE):
    debug_log(f"{CURL_FILE} not found, creating empty file")
    with open(CURL_FILE, "w", encoding="utf-8") as f:
        f.write("")

with open(CURL_FILE, "r", encoding="utf-8") as f:
    CURL_COMMAND = f.read().strip()

if not CURL_COMMAND:
    _msg = (
        "curl.txt is empty — setup is required.\n\n"
        "To get your cURL command:\n"
        "1. Open Chrome and go to claude.ai/settings/usage\n"
        "2. Open DevTools (F12) → Network tab\n"
        "3. Refresh the page\n"
        "4. Find the request to \"usage\" → right-click → Copy as cURL\n"
        "5. Paste it into curl.txt and save\n\n"
        "6. Run the App again from deskop icon or wherever you installed.\n\n"
        "The file will now open in Notepad for you to paste into."
    )
    if platform.system() == "Windows":
        ctypes.windll.user32.MessageBoxW(
            0, _msg, "Claude Usage Widget - Setup Required", 0x40  # MB_ICONINFORMATION
        )
        subprocess.Popen(["notepad", CURL_FILE])
    else:
        print(_msg)
    sys.exit(1)

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


class DesktopWidget:
    """Floating widget using a Win32 layered window with per-pixel alpha.
    The background is semi-transparent while text remains fully opaque."""

    def __init__(self):
        self._queue      = queue.Queue()
        self._thread     = None
        self._hwnd       = None
        self._usage_data = None
        self._usage_text = ""
        self._font_cache = {}
        self._font_scale = None
        self._cached_dpi = None
        state = self._load_state()
        self._x = state.get("x", 100)
        self._y = state.get("y", 100)
        self.visible = state.get("visible", False)

    def _load_state(self):
        if os.path.exists(WIDGET_STATE_FILE):
            try:
                with open(WIDGET_STATE_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_state(self):
        try:
            with open(WIDGET_STATE_FILE, "w") as f:
                json.dump({"x": self._x, "y": self._y, "visible": self.visible}, f)
        except Exception:
            pass

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _dpi_scale(self):
        if self._cached_dpi is None:
            try:
                self._cached_dpi = ctypes.windll.user32.GetDpiForSystem() / 96.0
            except Exception:
                self._cached_dpi = 1.0
        return self._cached_dpi

    def _pct_color(self, pct):
        if not isinstance(pct, (int, float)):
            return (136, 136, 136, 255)
        if pct < 50: return (40,  167,  69, 255)
        if pct < 75: return (255, 193,   7, 255)
        if pct < 90: return (253, 126,  20, 255)
        return (220, 53, 69, 255)

    def _render(self):
        """Render widget content to a PIL RGBA image with per-pixel alpha."""
        s = self._dpi_scale()
        if self._font_scale != s:
            self._font_cache = {}
            self._font_scale = s
        W = round(130 * s)
        H = round(35  * s)
        R = round(10  * s)

        img  = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Semi-transparent background, opaque border
        draw.rounded_rectangle(
            [0, 0, W - 1, H - 1], radius=R,
            fill=(13, 17, 23, 200),     # #0d1117 @ ~80 % opacity
            outline=(48, 54, 61, 220),  # #30363d @ ~86 % opacity
        )

        sz_lbl = round(13 * s)
        sz_val = round(15 * s)
        font_lbl = self._font_cache.get(("lbl", sz_lbl))
        font_val = self._font_cache.get(("val", sz_val))
        if font_lbl is None:
            font_lbl = None
            for fp in ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"]:
                try:
                    font_lbl = ImageFont.truetype(fp, sz_lbl)
                    break
                except Exception:
                    pass
            font_lbl = font_lbl or ImageFont.load_default()
            self._font_cache[("lbl", sz_lbl)] = font_lbl
        if font_val is None:
            font_val = None
            for fp in ["C:/Windows/Fonts/seguibl.ttf", "C:/Windows/Fonts/segoeuib.ttf",
                       "C:/Windows/Fonts/arialbd.ttf",  "C:/Windows/Fonts/arial.ttf"]:
                try:
                    font_val = ImageFont.truetype(fp, sz_val)
                    break
                except Exception:
                    pass
            font_val = font_val or font_lbl
            self._font_cache[("val", sz_val)] = font_val

        fh = self._usage_data.get("five_hour", None) if self._usage_data else None
        sd = self._usage_data.get("seven_day", None) if self._usage_data else None
        fh_txt = f"{int(fh)}%" if isinstance(fh, (int, float)) else "-"
        sd_txt = f"{int(sd)}%" if isinstance(sd, (int, float)) else "-"

        MUTED = (180, 188, 199, 255)
        SEP   = (33,  38,  45,  255)
        DIM   = (68,  76,  86,  255)

        pieces = [
            ("5h ",   font_lbl, MUTED),
            (fh_txt,  font_val, self._pct_color(fh) if isinstance(fh, (int, float)) else DIM),
            ("  |  ", font_lbl, SEP),
            ("7d ",   font_lbl, MUTED),
            (sd_txt,  font_val, self._pct_color(sd) if isinstance(sd, (int, float)) else DIM),
        ]

        metrics = []
        total_w = 0
        for t, f, c in pieces:
            bb = draw.textbbox((0, 0), t, font=f)
            metrics.append((t, f, c, bb))
            total_w += bb[2] - bb[0]
        x  = (W - total_w) // 2
        cy = H // 2
        for text, font, color, bb in metrics:
            tw = bb[2] - bb[0]
            th = bb[3] - bb[1]
            draw.text((x - bb[0], cy - th // 2 - bb[1]), text, fill=color, font=font)
            x += tw

        return img, W, H

    def _push(self, img, W, H):
        """Upload a PIL RGBA image to the Win32 layered window via UpdateLayeredWindow."""
        if not self._hwnd:
            debug_log("_push: no hwnd, skipping")
            return
        try:
            u32 = ctypes.windll.user32
            g32 = ctypes.windll.gdi32

            # Set return types — must be c_void_p so 64-bit handles are not truncated
            u32.GetDC.restype              = ctypes.c_void_p
            g32.CreateCompatibleDC.restype = ctypes.c_void_p
            g32.CreateDIBSection.restype   = ctypes.c_void_p
            g32.SelectObject.restype       = ctypes.c_void_p

            # Reorder channels RGBA → BGRA and pre-multiply alpha (required by UpdateLayeredWindow)
            r, g, b, a = img.split()
            raw = bytearray(Image.merge('RGBA', (b, g, r, a)).tobytes())
            for i in range(0, len(raw), 4):
                al = raw[i + 3]
                raw[i]     = raw[i]     * al // 255
                raw[i + 1] = raw[i + 1] * al // 255
                raw[i + 2] = raw[i + 2] * al // 255

            bmi = _BIH(biSize=ctypes.sizeof(_BIH), biWidth=W, biHeight=-H, biPlanes=1, biBitCount=32)
            pv  = ctypes.c_void_p()
            # Cast all handles to c_void_p so 64-bit values are not truncated
            sdc = ctypes.c_void_p(u32.GetDC(None))
            mdc = ctypes.c_void_p(g32.CreateCompatibleDC(sdc))
            hbm = ctypes.c_void_p(g32.CreateDIBSection(sdc, ctypes.byref(bmi), 0, ctypes.byref(pv), None, 0))

            if not hbm.value:
                debug_log("_push: CreateDIBSection failed")
                g32.DeleteDC(mdc)
                u32.ReleaseDC(None, sdc)
                return

            old = None
            try:
                ctypes.memmove(pv, bytes(raw), len(raw))
                old = ctypes.c_void_p(g32.SelectObject(mdc, hbm))
                u32.UpdateLayeredWindow(
                    ctypes.c_void_p(self._hwnd), sdc,
                    ctypes.byref(_PT(self._x, self._y)),
                    ctypes.byref(_SZ(W, H)),
                    mdc, ctypes.byref(_PT(0, 0)),
                    0, ctypes.byref(_BF(0, 0, 255, 1)),  # AC_SRC_OVER, 0, 255, AC_SRC_ALPHA
                    2,                                    # ULW_ALPHA
                )
            finally:
                if old is not None:
                    g32.SelectObject(mdc, old)
                g32.DeleteObject(hbm)
                g32.DeleteDC(mdc)
                u32.ReleaseDC(None, sdc)
        except Exception as e:
            import traceback
            traceback.print_exc()

    def _run(self):
        """Create a Win32 layered window and run its message loop."""
        try:
            self._run_inner()
        except Exception:
            import traceback
            traceback.print_exc()

    def _run_inner(self):
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass

        # Set restypes before any calls — without this, 64-bit handles are truncated to 32-bit
        k32.GetModuleHandleW.restype = ctypes.c_void_p
        u32.CreateWindowExW.restype  = ctypes.c_void_p
        u32.LoadCursorW.restype      = ctypes.c_void_p
        hInst = k32.GetModuleHandleW(None)
        debug_log(f"hInst = {hInst}")

        WM_DESTROY       = 0x0002
        WM_MOUSEACTIVATE = 0x0021
        WM_TIMER         = 0x0113
        WM_LBUTTONDOWN   = 0x0201
        WM_MOUSEMOVE     = 0x0200
        WM_LBUTTONUP     = 0x0202
        WM_APP_UPDATE    = 0x8001
        WM_APP_SHOW      = 0x8002
        WM_APP_HIDE      = 0x8003
        WM_APP_DESTROY   = 0x8004
        MA_NOACTIVATE    = 3
        TOPMOST_TIMER_ID = 1
        # SetWindowPos flags: no move, no size, no activate
        SWP_FLAGS        = 0x0001 | 0x0002 | 0x0010

        drag = [False, 0, 0]   # [is_dragging, offset_x, offset_y]

        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_void_p, ctypes.c_void_p,
        )

        def wnd_proc(hwnd, msg, wp, lp):
            lp = lp or 0
            if msg == WM_MOUSEACTIVATE:
                return MA_NOACTIVATE
            if msg == WM_TIMER and wp == TOPMOST_TIMER_ID:
                # Re-assert topmost — keeps widget above the taskbar after it's clicked
                u32.SetWindowPos(
                    ctypes.c_void_p(hwnd),
                    ctypes.c_ssize_t(-1),  # HWND_TOPMOST
                    0, 0, 0, 0, SWP_FLAGS,
                )
                return 0
            if msg == WM_LBUTTONDOWN:
                drag[0] = True
                drag[1] = lp & 0xFFFF
                drag[2] = (lp >> 16) & 0xFFFF
                u32.SetCapture(hwnd)
                return 0
            if msg == WM_MOUSEMOVE and drag[0]:
                pt = _PT(ctypes.c_int16(lp & 0xFFFF).value,
                         ctypes.c_int16((lp >> 16) & 0xFFFF).value)
                u32.ClientToScreen(hwnd, ctypes.byref(pt))
                self._x = pt.x - drag[1]
                self._y = pt.y - drag[2]
                img, W, H = self._render()
                self._push(img, W, H)
                return 0
            if msg == WM_LBUTTONUP:
                drag[0] = False
                u32.ReleaseCapture()
                self._save_state()
                return 0
            if msg == WM_APP_UPDATE:
                img, W, H = self._render()
                self._push(img, W, H)
                return 0
            if msg == WM_APP_SHOW:
                # Push content before ShowWindow so the window is never shown blank
                img, W, H = self._render()
                self._push(img, W, H)
                u32.ShowWindow(ctypes.c_void_p(hwnd), 5)
                u32.SetTimer(ctypes.c_void_p(hwnd), TOPMOST_TIMER_ID, 2000, None)
                return 0
            if msg == WM_APP_HIDE:
                u32.KillTimer(ctypes.c_void_p(hwnd), TOPMOST_TIMER_ID)
                u32.ShowWindow(hwnd, 0)
                return 0
            if msg == WM_APP_DESTROY:
                u32.KillTimer(ctypes.c_void_p(hwnd), TOPMOST_TIMER_ID)
                u32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                u32.PostQuitMessage(0)
                return 0
            return u32.DefWindowProcW(hwnd, msg, wp, lp)

        wpc = WNDPROC(wnd_proc)

        class WNDCLSEX(ctypes.Structure):
            _fields_ = [
                ('cbSize',        ctypes.c_uint),
                ('style',         ctypes.c_uint),
                ('lpfnWndProc',   WNDPROC),
                ('cbClsExtra',    ctypes.c_int),
                ('cbWndExtra',    ctypes.c_int),
                ('hInstance',     ctypes.c_void_p),
                ('hIcon',         ctypes.c_void_p),
                ('hCursor',       ctypes.c_void_p),
                ('hbrBackground', ctypes.c_void_p),
                ('lpszMenuName',  ctypes.c_wchar_p),
                ('lpszClassName', ctypes.c_wchar_p),
                ('hIconSm',       ctypes.c_void_p),
            ]

        cls_name = "ClaudeUsageWidget"
        wc = WNDCLSEX(
            cbSize        = ctypes.sizeof(WNDCLSEX),
            lpfnWndProc   = wpc,
            hInstance     = hInst,
            hCursor       = u32.LoadCursorW(None, 32512),  # IDC_ARROW
            lpszClassName = cls_name,
        )
        reg_result = u32.RegisterClassExW(ctypes.byref(wc))
        if not reg_result:
            err = k32.GetLastError()
            if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS
                debug_log(f"RegisterClassExW failed, GetLastError={err}")

        s = self._dpi_scale()
        W = round(130 * s)
        H = round(35  * s)

        # WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        hwnd = u32.CreateWindowExW(
            0x00080000 | 0x00000008 | 0x00000080 | 0x08000000,
            cls_name, "Claude Usage",
            0x80000000,   # WS_POPUP
            self._x, self._y, W, H,
            None, None, ctypes.c_void_p(hInst), None,
        )
        debug_log(f"CreateWindowExW hwnd = {hwnd}")
        if not hwnd:
            print("DesktopWidget: CreateWindowExW failed — widget will not show", flush=True)
            return
        self._hwnd = hwnd

        if self.visible:
            # Push content before ShowWindow so the window is never shown blank
            img, W2, H2 = self._render()
            self._push(img, W2, H2)
            u32.ShowWindow(ctypes.c_void_p(hwnd), 5)
            u32.SetTimer(ctypes.c_void_p(hwnd), TOPMOST_TIMER_ID, 2000, None)

        def proc_queue():
            while True:
                try:
                    cmd, args = self._queue.get(timeout=0.1)
                    if cmd == 'update':
                        self._usage_text = args[0]
                        self._usage_data = args[1]
                        u32.PostMessageW(hwnd, WM_APP_UPDATE, 0, 0)
                    elif cmd == 'show':
                        u32.PostMessageW(hwnd, WM_APP_SHOW, 0, 0)
                    elif cmd == 'hide':
                        u32.PostMessageW(hwnd, WM_APP_HIDE, 0, 0)
                    elif cmd == 'destroy':
                        u32.PostMessageW(hwnd, WM_APP_DESTROY, 0, 0)
                        return
                except queue.Empty:
                    pass

        threading.Thread(target=proc_queue, daemon=True).start()

        class MSG(ctypes.Structure):
            _fields_ = [
                ('hwnd',    ctypes.c_void_p),
                ('message', ctypes.c_uint),
                ('wParam',  ctypes.c_void_p),
                ('lParam',  ctypes.c_void_p),
                ('time',    ctypes.c_ulong),
                ('ptX',     ctypes.c_long),
                ('ptY',     ctypes.c_long),
            ]

        msg = MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))

    def update(self, usage_text, usage_data):
        self._queue.put(('update', (usage_text, usage_data)))

    def show(self):
        self.visible = True
        self._save_state()
        self._queue.put(('show', ()))

    def hide(self):
        self.visible = False
        self._save_state()
        self._queue.put(('hide', ()))

    def toggle(self):
        if self.visible:
            self.hide()
        else:
            self.show()

    def destroy(self):
        self._queue.put(('destroy', ()))


class WindowsTrayApp(UsageMonitorApp):
    """Windows system tray implementation using pystray"""

    def __init__(self):
        super().__init__()
        self.icon = None
        self.stop_threads = threading.Event()
        self._next_update_at = None
        self._ui_queue = queue.Queue()
        self._five_hour_menu_text = "5-Hour Reset: Loading..."
        self._seven_day_menu_text = "7-Day Reset: Loading..."
        self._next_update_menu_text = "Next Update: Loading..."
        self._fonts = {}  # font size -> ImageFont, cached after first load
        self._widget = DesktopWidget()

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
            pystray.MenuItem("Desktop Widget", self.toggle_widget, checked=lambda item: self._widget.visible),
            pystray.MenuItem("Exit", self.exit_app)
        )

        self.icon = pystray.Icon("claude_usage", image, "Usage", menu)

        self._widget.start()
        self.update_usage()
        self._schedule_next_update()
        self.icon.run_detached()
        self._main_loop()

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

    def _schedule_next_update(self):
        self._next_update_at = time.monotonic() + UPDATE_INTERVAL

    def _main_loop(self):
        while not self.stop_threads.is_set():
            self._process_ui_queue(timeout=0.2)
            if self._next_update_at is not None and time.monotonic() >= self._next_update_at:
                self.update_usage()
                self._schedule_next_update()
        if self.icon:
            self.icon.stop()

    def _process_ui_queue(self, timeout=0.0):
        try:
            cmd, args = self._ui_queue.get(timeout=timeout)
        except queue.Empty:
            return
        if cmd == "manual_update":
            self._next_update_menu_text = "Next Update: Updating..."
            self.update_usage()
            self._schedule_next_update()
        elif cmd == "toggle_widget":
            if self._widget.visible:
                self._widget.hide()
            else:
                self._widget.show()
                self._widget.update(self.current_usage_text, self.current_usage_data)
            if self.icon:
                self.icon.update_menu()
        elif cmd == "check_state":
            state_msg = f"5-Hour sent: {self.notification_state['five_hour']['sent']}\n7-Day sent: {self.notification_state['seven_day']['sent']}"
            try:
                from win11toast import notify
                notify(title="Notification State", body=state_msg, app_id="Claude Usage Monitor")
            except Exception as e:
                debug_log(f"Failed to show state: {e}")
        elif cmd == "reset_notification_history":
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
        elif cmd == "send_test_notification":
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
        elif cmd == "exit":
            self.stop_threads.set()
            self._widget.destroy()

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

        self._widget.update(usage_text, usage_data)

    def toggle_widget(self, icon=None, item=None):
        self._ui_queue.put(("toggle_widget", None))

    def manual_update(self, icon=None, item=None):
        self._ui_queue.put(("manual_update", None))

    def send_test_notification(self, icon=None, item=None):
        self._ui_queue.put(("send_test_notification", None))

    def check_state(self, icon=None, item=None):
        self._ui_queue.put(("check_state", None))

    def reset_notification_history(self, icon=None, item=None):
        self._ui_queue.put(("reset_notification_history", None))

    def exit_app(self, icon=None, item=None):
        self._ui_queue.put(("exit", None))


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
