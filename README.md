# KVM RustDesk Switcher

Automatically switches RustDesk remote desktop windows when a physical KVM switch changes to a different PC.

When you flip your KVM to a machine, that machine detects the keyboard/mouse input and sends a UDP notification to your Windows PC, which then connects to (or focuses) the corresponding RustDesk session — maximized on your chosen monitor.

## How It Works

```
[Linux PC] ──KVM input detected──> [UDP packet with hostname] ──> [Windows listener] ──> [Focus/connect RustDesk window]
```

1. KVM switches keyboard/mouse to a PC
2. A systemd service on that PC detects the input activity
3. The service sends a UDP packet containing its hostname to the Windows PC
4. The Windows listener receives the packet and:
   - If already connected: focuses the RustDesk window
   - If not connected: closes other sessions, connects to the right machine, and maximizes the window on the configured monitor

## Requirements

- **Windows PC**: Python 3.x, RustDesk client installed
- **Linux machines**: Python 3, netcat (installed automatically by the script)
- **Network**: All machines on the same LAN

## Setup

### 1. Windows (listener)

1. Copy the `windows/` folder to your desired location (e.g., `C:\kvm-switcher\`)

2. Copy `kvm-config.example.json` to `kvm-config.json` and edit it:

```json
{
  "listen_port": 9999,
  "rustdesk_path": "C:\\Path\\To\\rustdesk.exe",
  "target_monitor": 1,
  "machines": [
    {
      "hostname": "my-pc",
      "rustdesk_id": "123456789"
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `listen_port` | UDP port to listen on (default: 9999) |
| `rustdesk_path` | Full path to your RustDesk executable |
| `target_monitor` | Which monitor to show RustDesk on (1 = leftmost, 2 = next, etc.) |
| `hostname` | Identifier sent by the Linux machine (must match) |
| `rustdesk_id` | The RustDesk ID of the remote machine (shown in RustDesk UI) |

3. Run `install.bat` as Administrator to:
   - Add a Windows Firewall rule for the UDP port
   - Install a startup shortcut so the listener runs on login

4. Test: `python kvm_listener.py`

### 2. Linux (each remote machine)

Copy `linux/install-kvm-notify.sh` to each Linux machine and run:

```bash
chmod +x install-kvm-notify.sh
sudo ./install-kvm-notify.sh <WINDOWS_IP> <HOSTNAME>
```

Example:
```bash
sudo ./install-kvm-notify.sh 192.168.1.100 my-pc
```

The `HOSTNAME` must match the `hostname` field in your `kvm-config.json`.

The installer:
- Installs dependencies (netcat, python3) if missing
- Creates a systemd service that monitors `/dev/input/` for keyboard/mouse activity
- Sends a UDP packet with the hostname when input is detected
- Includes a 3-second cooldown to avoid spamming

### 3. Test

From any Linux machine:
```bash
echo -n 'my-pc' | nc -u -w1 <WINDOWS_IP> 9999
```

The matching RustDesk window should appear on your Windows PC.

## Adding a New Machine

1. Add an entry to `kvm-config.json` on Windows
2. Run `install-kvm-notify.sh` on the new Linux machine
3. Done — no restart of the Windows listener needed (it reads config per-switch)

Wait — the listener reads config at startup. Restart the listener after editing the config.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Window doesn't appear | Check RustDesk is running and the ID is correct |
| No UDP packets arriving | Check Windows Firewall rule, verify port matches |
| Wrong monitor | Change `target_monitor` in config (monitors are numbered left-to-right) |
| Multiple machines fire at once | The listener has a 0.25s debounce + 10s duplicate cooldown |
| Service not running on Linux | `systemctl status kvm-notify` / `journalctl -u kvm-notify -f` |

## Uninstall

**Windows:**
- Delete the project folder
- Remove `start_kvm_listener.vbs` from `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`
- Run: `netsh advfirewall firewall delete rule name="KVM RustDesk Switcher"`

**Linux:**
```bash
sudo systemctl stop kvm-notify
sudo systemctl disable kvm-notify
sudo rm /etc/systemd/system/kvm-notify.service
sudo rm /usr/local/bin/kvm-input-monitor.py
sudo systemctl daemon-reload
```

## License

MIT
