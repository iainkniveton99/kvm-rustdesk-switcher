#!/bin/bash
# KVM RustDesk Switcher - Linux installer
# Monitors keyboard/mouse input and notifies Windows to focus RustDesk window
# Usage: sudo ./install-kvm-notify.sh <WINDOWS_IP> <HOSTNAME>
# Example: sudo ./install-kvm-notify.sh 192.168.1.100 pc-1

set -e

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Please run as root (sudo)"
    exit 1
fi

if [ $# -ne 2 ]; then
    echo "Usage: sudo $0 <WINDOWS_IP> <HOSTNAME>"
    echo "Example: sudo $0 192.168.1.100 pc-1"
    exit 1
fi

WINDOWS_IP="$1"
HOSTNAME_ID="$2"
UDP_PORT=9999

echo "============================================"
echo " KVM RustDesk Switcher - Linux Installer"
echo "============================================"
echo " Windows IP:  $WINDOWS_IP"
echo " Hostname:    $HOSTNAME_ID"
echo " UDP Port:    $UDP_PORT"
echo ""

# Install dependencies
echo "[1/4] Checking dependencies..."

if ! command -v nc &>/dev/null; then
    echo "       Installing netcat..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq && apt-get install -y -qq netcat-openbsd
    elif command -v dnf &>/dev/null; then
        dnf install -y -q nmap-ncat
    elif command -v yum &>/dev/null; then
        yum install -y -q nmap-ncat
    elif command -v apk &>/dev/null; then
        apk add --quiet netcat-openbsd
    else
        echo "ERROR: Could not find a package manager to install netcat."
        exit 1
    fi
    echo "       netcat installed."
else
    echo "       netcat OK."
fi

if ! command -v python3 &>/dev/null; then
    echo "       Installing python3..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq && apt-get install -y -qq python3
    elif command -v dnf &>/dev/null; then
        dnf install -y -q python3
    elif command -v yum &>/dev/null; then
        yum install -y -q python3
    elif command -v apk &>/dev/null; then
        apk add --quiet python3
    else
        echo "ERROR: Could not find a package manager to install python3."
        exit 1
    fi
    echo "       python3 installed."
else
    echo "       python3 OK."
fi

# Create the input monitor daemon
echo "[2/4] Creating /usr/local/bin/kvm-input-monitor.py..."
cat > /usr/local/bin/kvm-input-monitor.py << 'SCRIPTEOF'
#!/usr/bin/env python3
"""
KVM input monitor daemon
Reads raw events from /dev/input/event* devices.
On any keyboard/mouse activity, sends UDP hostname notification with debounce.
Uses only stdlib — no pip packages needed.
"""

import glob
import os
import select
import socket
import struct
import syslog
import time

WINDOWS_IP = "__WINDOWS_IP__"
HOSTNAME_ID = "__HOSTNAME_ID__"
UDP_PORT = __UDP_PORT__
COOLDOWN = 3  # seconds between notifications

EVENT_SIZE = struct.calcsize("llHHi")

def send_notify(sock, last_sent):
    now = time.time()
    if now - last_sent < COOLDOWN:
        return last_sent
    try:
        sock.sendto(HOSTNAME_ID.encode(), (WINDOWS_IP, UDP_PORT))
        syslog.syslog(syslog.LOG_INFO, f"KVM switch detected, notified {WINDOWS_IP}")
    except Exception as e:
        syslog.syslog(syslog.LOG_ERR, f"Failed to send notification: {e}")
    return now

def open_input_devices():
    fds = {}
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            fds[fd] = path
        except OSError:
            pass
    return fds

def main():
    syslog.openlog("kvm-notify", syslog.LOG_PID, syslog.LOG_DAEMON)
    syslog.syslog(syslog.LOG_INFO, f"Starting input monitor for {HOSTNAME_ID}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    last_sent = 0.0

    while True:
        fds = open_input_devices()
        if not fds:
            time.sleep(5)
            continue

        syslog.syslog(syslog.LOG_INFO, f"Monitoring {len(fds)} input devices")

        try:
            while True:
                readable, _, _ = select.select(list(fds.keys()), [], [], 60.0)
                for fd in readable:
                    try:
                        data = os.read(fd, EVENT_SIZE * 64)
                        if data:
                            last_sent = send_notify(sock, last_sent)
                    except OSError:
                        raise StopIteration
        except (StopIteration, OSError):
            pass
        finally:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
        time.sleep(1)

if __name__ == "__main__":
    main()
SCRIPTEOF

# Replace placeholders
sed -i "s|__WINDOWS_IP__|$WINDOWS_IP|g" /usr/local/bin/kvm-input-monitor.py
sed -i "s|__HOSTNAME_ID__|$HOSTNAME_ID|g" /usr/local/bin/kvm-input-monitor.py
sed -i "s|__UDP_PORT__|$UDP_PORT|g" /usr/local/bin/kvm-input-monitor.py

chmod +x /usr/local/bin/kvm-input-monitor.py

# Create systemd service
echo "[3/4] Creating systemd service..."
cat > /etc/systemd/system/kvm-notify.service << 'SERVICEEOF'
[Unit]
Description=KVM RustDesk Window Switcher - Input Monitor
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/kvm-input-monitor.py
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICEEOF

# Clean up old files
echo "[4/4] Enabling and starting service..."
rm -f /etc/udev/rules.d/99-kvm-notify.rules 2>/dev/null
rm -f /usr/local/bin/kvm-notify.sh 2>/dev/null
rm -f /usr/local/bin/kvm-input-monitor.sh 2>/dev/null

systemctl daemon-reload
systemctl enable kvm-notify.service
systemctl restart kvm-notify.service

echo ""
echo "============================================"
echo " Installation complete!"
echo ""
echo " Files created:"
echo "   /usr/local/bin/kvm-input-monitor.py"
echo "   /etc/systemd/system/kvm-notify.service"
echo ""
echo " Service status:"
systemctl --no-pager status kvm-notify.service 2>&1 | head -5
echo ""
echo " Commands:"
echo "   systemctl status kvm-notify   # check status"
echo "   journalctl -u kvm-notify -f   # view logs"
echo ""
echo " Test manually:"
echo "   echo -n '$HOSTNAME_ID' | nc -u -w1 $WINDOWS_IP $UDP_PORT"
echo "============================================"
