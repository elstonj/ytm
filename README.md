```
                 __                            _____
   __  __ ____ _/ /_   _____  ____ ___        / ___/
  / / / // __ `/ __/  / ___/ / __ `__ \ ____  \__ \
 / /_/ // /_/ / /_   / /__  / / / / / //___ / __/ /
 \__, / \__,_/\__/   \___/ /_/ /_/ /_/     /____/
/____/
```

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

## Requirements

- Python 3.10+
- mpv (for audio playback)

## Installation

```bash
# Install mpv (required for playback)
# Ubuntu/Debian:
sudo apt install mpv
# macOS:
brew install mpv

# Install the CLI
pip install -e .
```

## Usage

```bash
# Search for music (interactive)
ytm search "artist or song name"

# Play a song directly
ytm play "song name"

# Play with radio (similar songs)
ytm radio "song name"

# Browse your library
ytm library

# Authenticate to access your library
ytm auth
```

## Playback Controls

- `space` - Pause/unpause
- `n` - Next track
- `p` - Previous track
- `+` - Like song
- `-` - Dislike song (skips to next)
- `/` - New search (in search mode)
- `Ctrl+C` - Quit

## Authentication

To access your YouTube Music library and playlists, run `ytm auth`. The tool will attempt to extract cookies from your browser automatically. If that fails, use `ytm auth --manual` to paste request headers manually.

Credentials are stored in `~/.config/ytm-cli/`.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.
