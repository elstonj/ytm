# ytm-cli

A command-line interface for YouTube Music.

**Created by Jack Elston**

## Features

- Search for songs and artists
- Play music directly from the terminal
- Radio mode - play similar songs automatically
- Browse your YouTube Music library and playlists
- Like/dislike songs during playback
- Vim-style controls
- System tray mode - rich media player popup with equalizer, volume, and output device selection
- Remote control via `ytm ctl` - bind hardware media keys to control the tray
- Unified PulseAudio volume - tray slider and hardware keys control the same volume

## Requirements

- Python 3.10+
- mpv (for audio playback)

## Installation

### Quick Install

```bash
curl -sSL https://raw.githubusercontent.com/elstonj/ytm/main/install.sh | bash
```

### Manual Install

```bash
# Install mpv (required for playback)
# Ubuntu/Debian:
sudo apt install mpv
# macOS:
brew install mpv

# Clone and install
git clone https://github.com/elstonj/ytm.git
cd ytm
pip install .

# Optional: install with system tray support
pip install '.[tray]'
```

## Usage

```bash
# Search for music (interactive)
ytm search "artist or song name"

# Search with radio mode (play similar songs after selection)
ytm search -r "artist or song name"

# Play a song directly
ytm play "song name"

# Play with radio (similar songs)
ytm radio "song name"

# Browse your library (auto-authenticates via OAuth if needed)
ytm library

# System tray mode (--tray / -t is a global flag, works before or after the command)
ytm --tray play "song name"
ytm -t radio "song name"
ytm play -t "song name"

# Control the running tray instance
ytm ctl toggle-pause
ytm ctl next
ytm ctl prev
ytm ctl seek-fwd
ytm ctl seek-back
ytm ctl vol-up
ytm ctl vol-down
ytm ctl mute
ytm ctl quit
```

## Playback Controls

### Terminal Mode

- `space` - Pause/unpause
- `n` - Next track
- `p` - Previous track
- `+` - Like song
- `-` - Dislike song (skips to next)
- `/` - New search (in search mode)
- `o` - Switch audio output device
- `Ctrl+C` - Quit

### System Tray Mode (`--tray`)

Add `--tray` or `-t` as a global flag to any command to run playback as a system tray icon. The process automatically backgrounds itself, returning the terminal immediately. Requires PySide6 (`pip install '.[tray]'`).

Click the tray icon to open the media player popup with:

- Track info and queue position
- Seekable progress slider
- Transport controls (previous, seek back, play/pause, seek forward, next)
- Volume slider
- 10-band equalizer with reset
- Audio output device selector
- Like/Dislike, Search, and Quit buttons

Re-running `ytm --tray` automatically replaces the existing instance.

### Media Key Integration (i3)

Add these bindings to your i3 config to control the tray with hardware media keys:

```
bindsym XF86AudioPlay exec --no-startup-id ytm ctl toggle-pause
bindsym XF86AudioPause exec --no-startup-id ytm ctl toggle-pause
bindsym XF86AudioNext exec --no-startup-id ytm ctl next
bindsym XF86AudioPrev exec --no-startup-id ytm ctl prev
bindsym XF86AudioRewind exec --no-startup-id ytm ctl seek-back
bindsym XF86AudioForward exec --no-startup-id ytm ctl seek-fwd
```

Volume keys already control PulseAudio directly, and the tray slider stays in sync.

## Authentication

Authentication is only needed for library features (liked songs, playlists, rating). Search and playback work without auth.

Authentication happens automatically via OAuth when you first use `ytm library`. You'll need a Google Cloud OAuth client ID:

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a project (or select an existing one)
3. Enable the **YouTube Data API v3**
4. Create an **OAuth 2.0 Client ID** (type: TV / Limited Input)
5. Run `ytm library` — enter your client ID and secret when prompted, then authorize in the browser

Your client credentials are saved so you only enter them once. OAuth tokens refresh automatically.

Credentials are stored in `~/.config/ytm-cli/`.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.
