"""
KVM-triggered RustDesk Window Switcher
Listens for UDP packets containing hostnames.
Connects to the matching RustDesk machine and closes other RustDesk sessions.
"""

import socket
import json
import ctypes
import ctypes.wintypes
import subprocess
import sys
import os
import time
import threading
from datetime import datetime

# Win32 constants
SW_RESTORE = 9
SW_MAXIMIZE = 3
WM_CLOSE = 0x0010
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1
SWP_NOZORDER = 0x0004

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("rcMonitor", ctypes.wintypes.RECT),
        ("rcWork", ctypes.wintypes.RECT),
        ("dwFlags", ctypes.wintypes.DWORD),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def load_config(config_path):
    with open(config_path, "r") as f:
        return json.load(f)


def send_alt_key():
    """Press and release Alt to allow SetForegroundWindow from background."""
    inputs = (INPUT * 2)()
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].union.ki.wVk = VK_MENU
    inputs[0].union.ki.dwFlags = 0
    inputs[1].type = INPUT_KEYBOARD
    inputs[1].union.ki.wVk = VK_MENU
    inputs[1].union.ki.dwFlags = KEYEVENTF_KEYUP
    user32.SendInput(2, ctypes.pointer(inputs[0]), ctypes.sizeof(INPUT))


def get_monitors():
    """Return list of monitor rects sorted by x position (left to right)."""
    monitors = []

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_longlong
    )

    def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))
        r = info.rcMonitor
        monitors.append({
            "left": r.left, "top": r.top,
            "right": r.right, "bottom": r.bottom,
            "width": r.right - r.left, "height": r.bottom - r.top,
        })
        return 1

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
    monitors.sort(key=lambda m: m["left"])
    return monitors


def move_to_monitor_and_maximize(hwnd, monitor_num):
    """Move a window to the specified monitor (1-indexed) and maximize it."""
    monitors = get_monitors()
    if monitor_num < 1 or monitor_num > len(monitors):
        log(f"  Warning: Monitor {monitor_num} not found, have {len(monitors)} monitors")
        return

    mon = monitors[monitor_num - 1]
    log(f"  Moving to monitor {monitor_num} ({mon['width']}x{mon['height']} at x={mon['left']})")

    user32.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.2)

    user32.SetWindowPos(
        hwnd, 0,
        mon["left"] + 100, mon["top"] + 100, 800, 600,
        SWP_NOZORDER
    )
    time.sleep(0.2)

    user32.ShowWindow(hwnd, SW_MAXIMIZE)
    time.sleep(0.3)

    send_alt_key()
    user32.SetForegroundWindow(hwnd)
    log(f"  Maximized on monitor {monitor_num}")


def find_rustdesk_windows():
    """Find all RustDesk remote desktop windows. Returns list of (hwnd, title)."""
    results = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )

    def callback(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if "rustdesk" in title.lower() and "remote desktop" in title.lower():
            results.append((hwnd, title))
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return results


def close_rustdesk_windows(except_id=None):
    """Close all RustDesk remote windows, optionally except one matching an ID."""
    windows = find_rustdesk_windows()
    for hwnd, title in windows:
        if except_id and except_id in title:
            continue
        log(f"  Closing: {title}")
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def focus_window(hwnd, title):
    """Bring a window to the foreground, restoring if minimized."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    send_alt_key()
    result = user32.SetForegroundWindow(hwnd)

    if result:
        log(f"  Focused: {title}")
    else:
        foreground_hwnd = user32.GetForegroundWindow()
        foreground_tid = user32.GetWindowThreadProcessId(foreground_hwnd, None)
        current_tid = kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(current_tid, foreground_tid, True)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(current_tid, foreground_tid, False)
        log(f"  Focused (fallback): {title}")


def find_window_by_id(rustdesk_id):
    """Find a RustDesk window matching a specific ID."""
    windows = find_rustdesk_windows()
    for hwnd, title in windows:
        if rustdesk_id in title:
            return hwnd, title
    return None, None


def connect_rustdesk(rustdesk_path, rustdesk_id):
    """Launch a RustDesk connection to the given ID."""
    log(f"  Connecting to RustDesk ID: {rustdesk_id}")
    subprocess.Popen(
        [rustdesk_path, "--connect", rustdesk_id],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


_pending_switch = None
_pending_timer = None
_pending_lock = threading.Lock()
_last_executed = 0
_last_executed_host = None

DEBOUNCE_DELAY = 0.25  # seconds to wait for packets to settle
DUPLICATE_COOLDOWN = 10  # seconds to ignore duplicate switches


def _execute_switch(hostname, machines, rustdesk_path, target_monitor):
    """Actually perform the switch after the debounce delay."""
    global _last_executed, _last_executed_host

    now = time.time()
    if hostname == _last_executed_host and now - _last_executed < DUPLICATE_COOLDOWN:
        log(f"  Skipping duplicate execution for '{hostname}'")
        return True
    _last_executed = now
    _last_executed_host = hostname

    match_entry = None
    for machine in machines:
        if machine["hostname"].lower() == hostname.lower():
            match_entry = machine
            break

    if not match_entry:
        log(f"  Unknown hostname: {hostname}")
        return False

    rustdesk_id = match_entry["rustdesk_id"]

    # Check if already connected to this machine
    hwnd, title = find_window_by_id(rustdesk_id)
    if hwnd:
        if user32.GetForegroundWindow() == hwnd and user32.IsZoomed(hwnd):
            log(f"  Already connected and focused: {hostname}, skipping")
            return True
        log(f"  Already connected to {hostname}")
        move_to_monitor_and_maximize(hwnd, target_monitor)
        return True

    # Close other RustDesk sessions
    close_rustdesk_windows()
    time.sleep(0.5)

    # Connect to the target machine
    connect_rustdesk(rustdesk_path, rustdesk_id)

    # Wait for the window to appear and focus it
    for _ in range(10):
        time.sleep(1)
        hwnd, title = find_window_by_id(rustdesk_id)
        if hwnd:
            if user32.IsZoomed(hwnd):
                log(f"  Window already maximized, focusing")
                send_alt_key()
                user32.SetForegroundWindow(hwnd)
            else:
                move_to_monitor_and_maximize(hwnd, target_monitor)
            return True

    log(f"  Warning: Connected but couldn't find window for {rustdesk_id}")
    return False


def handle_switch(hostname, machines, rustdesk_path, target_monitor):
    """Debounced switch — waits for the last hostname to settle before acting."""
    global _pending_switch, _pending_timer

    with _pending_lock:
        if _pending_timer is not None:
            _pending_timer.cancel()

        _pending_switch = hostname

        def do_switch():
            global _pending_switch
            with _pending_lock:
                final_hostname = _pending_switch
                _pending_switch = None
            log(f"  Executing switch to '{final_hostname}'")
            _execute_switch(final_hostname, machines, rustdesk_path, target_monitor)

        _pending_timer = threading.Timer(DEBOUNCE_DELAY, do_switch)
        _pending_timer.start()
        log(f"  Queued switch to '{hostname}' (waiting {DEBOUNCE_DELAY}s)")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "kvm-config.json")

    if not os.path.exists(config_path):
        print(f"ERROR: Config file not found: {config_path}")
        print(f"Copy kvm-config.example.json to kvm-config.json and edit it.")
        sys.exit(1)

    config = load_config(config_path)
    port = config["listen_port"]
    machines = config["machines"]
    rustdesk_path = config["rustdesk_path"]
    target_monitor = config.get("target_monitor", 1)

    if not os.path.exists(rustdesk_path):
        print(f"ERROR: RustDesk not found: {rustdesk_path}")
        sys.exit(1)

    monitors = get_monitors()
    log(f"KVM RustDesk Switcher starting")
    log(f"Listening on UDP port {port}")
    log(f"RustDesk: {rustdesk_path}")
    log(f"Target monitor: {target_monitor} of {len(monitors)}")
    for i, mon in enumerate(monitors, 1):
        marker = " <--" if i == target_monitor else ""
        log(f"  Monitor {i}: {mon['width']}x{mon['height']} at x={mon['left']}{marker}")
    log(f"Configured machines:")
    for m in machines:
        log(f"  {m['hostname']} -> RustDesk ID {m['rustdesk_id']}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", port))

    try:
        while True:
            data, addr = sock.recvfrom(1024)

            try:
                hostname = data.decode("utf-8").strip()
            except UnicodeDecodeError:
                log(f"  Ignoring non-UTF8 data from {addr[0]}:{addr[1]}")
                continue

            if not hostname:
                continue

            log(f"KVM switch detected: '{hostname}' (from {addr[0]}:{addr[1]})")
            handle_switch(hostname, machines, rustdesk_path, target_monitor)

    except KeyboardInterrupt:
        log("Shutting down")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
