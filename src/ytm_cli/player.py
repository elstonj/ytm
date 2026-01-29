#   __  __ ____ ___ ___        _____/ /(_)
#  / / / // __ `__ `__ \ ____ / ___/ / / /
# / /_/ // / / / / / / //___ // /__/ / / /
# \__, //_/ /_/ /_/ /_/      \___/_/_/_/
#/____/
#
# ytm-cli - YouTube Music CLI
# Created by Jack Elston
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
"""Audio playback using yt-dlp and mpv with IPC control."""

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import yt_dlp

# Ensure deno is in PATH for yt-dlp JS challenge solving
_deno_path = Path.home() / ".deno" / "bin"
if _deno_path.exists() and str(_deno_path) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{_deno_path}:{os.environ.get('PATH', '')}"


class Player:
    """Handle audio playback for YouTube Music tracks with IPC control."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._socket_path: Path | None = None
        self._socket: socket.socket | None = None
        self._duration: float = 0
        self._audio_file: Path | None = None
        self._last_error: str = ""
        self._check_dependencies()

    def _check_dependencies(self) -> None:
        """Check that required external tools are available."""
        if not shutil.which("mpv"):
            raise RuntimeError(
                "mpv is required for audio playback. "
                "Install it with: sudo apt install mpv (Ubuntu/Debian) "
                "or brew install mpv (macOS)"
            )

    def _download_audio(self, video_id: str) -> tuple[Path | None, float]:
        """Download audio for a video ID using yt-dlp with cookies.

        Returns:
            Tuple of (audio_file_path, duration) or (None, 0) on failure.
        """
        url = f"https://www.youtube.com/watch?v={video_id}"

        # Create temp file for audio
        audio_file = Path(tempfile.mktemp(suffix=".mp4", prefix="ytm-"))

        # Check for cookies file in config directory
        cookies_file = Path.home() / ".config" / "ytm-cli" / "cookies.txt"

        ydl_opts: dict[str, Any] = {
            "format": "18/bestaudio/best",  # Format 18 has audio, fallback to bestaudio
            "outtmpl": str(audio_file),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,  # Suppress download progress
            # Enable downloading JS challenge solver from GitHub
            "allow_remote_component_download": "ejs:github",
        }

        last_error: str = ""

        # Try with cookies file first if it exists
        if cookies_file.exists():
            ydl_opts["cookiefile"] = str(cookies_file)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                duration = info.get("duration", 0) if info else 0

                if audio_file.exists() and audio_file.stat().st_size > 0:
                    return audio_file, duration
        except Exception as e:
            last_error = str(e)

        # Try with browser cookies as fallback
        try:
            ydl_opts.pop("cookiefile", None)
            ydl_opts["cookiesfrombrowser"] = ("chrome",)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                duration = info.get("duration", 0) if info else 0
                if audio_file.exists() and audio_file.stat().st_size > 0:
                    return audio_file, duration
        except Exception as e:
            last_error = str(e)

        # Try without any cookies as last resort
        try:
            ydl_opts.pop("cookiesfrombrowser", None)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                duration = info.get("duration", 0) if info else 0
                if audio_file.exists() and audio_file.stat().st_size > 0:
                    return audio_file, duration
        except Exception as e:
            last_error = str(e)

        # Clean up empty file if it exists
        if audio_file.exists() and audio_file.stat().st_size == 0:
            audio_file.unlink()

        # Store last error for debugging
        self._last_error = last_error
        return None, 0

    def _connect_ipc(self) -> bool:
        """Connect to mpv IPC socket."""
        if not self._socket_path or not self._socket_path.exists():
            return False

        try:
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._socket.settimeout(1.0)
            self._socket.connect(str(self._socket_path))
            return True
        except (socket.error, OSError):
            self._socket = None
            return False

    def _send_command(self, command: list[Any]) -> dict[str, Any] | None:
        """Send a command to mpv via IPC and get response."""
        if not self._socket:
            if not self._connect_ipc():
                return None

        try:
            msg = json.dumps({"command": command}) + "\n"
            self._socket.sendall(msg.encode())  # type: ignore

            response = b""
            while True:
                chunk = self._socket.recv(4096)  # type: ignore
                if not chunk:
                    break
                response += chunk
                if b"\n" in chunk:
                    break

            if response:
                return json.loads(response.decode().strip())
        except (socket.error, json.JSONDecodeError, OSError):
            self._socket = None
        return None

    def _get_property(self, name: str) -> Any:
        """Get an mpv property value."""
        result = self._send_command(["get_property", name])
        if result and "data" in result:
            return result["data"]
        return None

    def _set_property(self, name: str, value: Any) -> bool:
        """Set an mpv property value."""
        result = self._send_command(["set_property", name, value])
        return result is not None and result.get("error") == "success"

    def play(self, video_id: str) -> float:
        """Play audio for a given video ID.

        Returns:
            Duration of the track in seconds.
        """
        self.stop()

        # Download audio first
        audio_file, self._duration = self._download_audio(video_id)
        if not audio_file:
            error_detail = f" ({self._last_error})" if self._last_error else ""
            raise RuntimeError(f"Could not download audio for video: {video_id}{error_detail}")

        self._audio_file = audio_file

        # Create IPC socket path
        self._socket_path = Path(tempfile.mktemp(suffix=".sock", prefix="ytm-mpv-"))

        # Play with mpv
        self._process = subprocess.Popen(
            [
                "mpv",
                "--no-video",
                "--no-terminal",
                f"--input-ipc-server={self._socket_path}",
                str(audio_file),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for socket to be created
        for _ in range(20):
            if self._socket_path.exists():
                time.sleep(0.1)
                self._connect_ipc()
                break
            time.sleep(0.1)

        return self._duration

    def stop(self) -> None:
        """Stop current playback."""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

        if self._socket_path and self._socket_path.exists():
            try:
                self._socket_path.unlink()
            except Exception:
                pass
            self._socket_path = None

        # Clean up audio file
        if self._audio_file and self._audio_file.exists():
            try:
                self._audio_file.unlink()
            except Exception:
                pass
            self._audio_file = None

        self._duration = 0

    def is_playing(self) -> bool:
        """Check if audio is currently playing (not paused and process running)."""
        if self._process and self._process.poll() is None:
            paused = self._get_property("pause")
            return paused is False
        return False

    def is_active(self) -> bool:
        """Check if player process is running (playing or paused)."""
        return self._process is not None and self._process.poll() is None

    def toggle_pause(self) -> bool:
        """Toggle pause state. Returns new pause state."""
        current = self._get_property("pause")
        if current is not None:
            new_state = not current
            self._set_property("pause", new_state)
            return new_state
        return False

    def pause(self) -> None:
        """Pause playback."""
        self._set_property("pause", True)

    def resume(self) -> None:
        """Resume playback."""
        self._set_property("pause", False)

    def get_position(self) -> float:
        """Get current playback position in seconds."""
        pos = self._get_property("time-pos")
        return float(pos) if pos is not None else 0.0

    def get_duration(self) -> float:
        """Get track duration in seconds."""
        # Try to get from mpv first (more accurate)
        dur = self._get_property("duration")
        if dur is not None:
            return float(dur)
        return self._duration

    def get_progress(self) -> tuple[float, float]:
        """Get current position and duration.

        Returns:
            Tuple of (position, duration) in seconds.
        """
        return self.get_position(), self.get_duration()

    def seek(self, seconds: float, relative: bool = True) -> None:
        """Seek in the current track.

        Args:
            seconds: Seconds to seek (positive = forward, negative = backward)
            relative: If True, seek relative to current position
        """
        mode = "relative" if relative else "absolute"
        self._send_command(["seek", seconds, mode])

    def set_volume(self, volume: int) -> None:
        """Set volume (0-100)."""
        self._set_property("volume", max(0, min(100, volume)))

    def get_volume(self) -> int:
        """Get current volume (0-100)."""
        vol = self._get_property("volume")
        return int(vol) if vol is not None else 100

    def wait(self) -> None:
        """Wait for current track to finish playing."""
        if self._process:
            self._process.wait()
