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
"""YouTube Music API wrapper using ytmusicapi."""

from pathlib import Path
from typing import Any

from ytmusicapi import YTMusic, setup


class YouTubeMusicAPI:
    """Wrapper around ytmusicapi for YouTube Music operations."""

    AUTH_FILE = Path.home() / ".config" / "ytm-cli" / "headers.json"

    def __init__(self) -> None:
        self._ytmusic: YTMusic | None = None
        self._authenticated = False
        self._load_client()

    def _load_client(self) -> None:
        """Load the YTMusic client, with auth if available."""
        if self.AUTH_FILE.exists():
            self._ytmusic = YTMusic(str(self.AUTH_FILE))
            self._authenticated = True
        else:
            self._ytmusic = YTMusic()

    def is_authenticated(self) -> bool:
        """Check if the user is authenticated."""
        return self._authenticated

    def authenticate(self) -> None:
        """Run browser headers auth flow to authenticate with YouTube Music.

        Prompts user to paste request headers from browser dev tools.
        """
        self.AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        setup(filepath=str(self.AUTH_FILE))
        self._load_client()

    def search(
        self, query: str, filter_type: str | None = "songs", limit: int = 10
    ) -> list[dict[str, Any]]:
        """Search for songs, albums, artists, or playlists."""
        if not self._ytmusic:
            return []

        results = self._ytmusic.search(query, filter=filter_type, limit=limit)

        return [
            {
                "videoId": item.get("videoId"),
                "title": item.get("title", "Unknown"),
                "artist": (
                    item["artists"][0]["name"]
                    if item.get("artists")
                    else "Unknown"
                ),
                "album": item.get("album", {}).get("name") if item.get("album") else None,
                "duration": item.get("duration"),
            }
            for item in results
            if item.get("videoId")
        ]

    def get_library_playlists(self) -> list[dict[str, Any]]:
        """Get user's library playlists (requires auth)."""
        if not self._ytmusic or not self._authenticated:
            return []

        playlists = self._ytmusic.get_library_playlists()

        return [
            {
                "playlistId": p.get("playlistId"),
                "title": p.get("title", "Untitled"),
                "count": p.get("count", 0),
            }
            for p in playlists
        ]

    def get_playlist(self, playlist_id: str) -> list[dict[str, Any]]:
        """Get tracks from a playlist (deduplicated)."""
        if not self._ytmusic:
            return []

        playlist = self._ytmusic.get_playlist(playlist_id)
        tracks = playlist.get("tracks", [])

        # Deduplicate by videoId
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for track in tracks:
            video_id = track.get("videoId")
            if video_id and video_id not in seen:
                seen.add(video_id)
                result.append({
                    "videoId": video_id,
                    "title": track.get("title", "Unknown"),
                    "artist": (
                        track["artists"][0]["name"]
                        if track.get("artists")
                        else "Unknown"
                    ),
                    "duration": track.get("duration"),
                })
        return result

    def get_song_info(self, video_id: str) -> dict[str, Any] | None:
        """Get detailed info about a song."""
        if not self._ytmusic:
            return None

        return self._ytmusic.get_song(video_id)

    def rate_song(self, video_id: str, rating: str) -> bool:
        """Rate a song (thumbs up/down).

        Args:
            video_id: The video ID to rate
            rating: 'LIKE', 'DISLIKE', or 'INDIFFERENT'

        Returns:
            True if successful
        """
        if not self._ytmusic or not self._authenticated:
            return False

        try:
            self._ytmusic.rate_song(video_id, rating)
            return True
        except Exception:
            return False

    def get_liked_songs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get user's liked songs (deduplicated)."""
        if not self._ytmusic or not self._authenticated:
            return []

        try:
            playlist = self._ytmusic.get_liked_songs(limit=limit)
            tracks = playlist.get("tracks", [])

            # Deduplicate by videoId
            seen: set[str] = set()
            result: list[dict[str, Any]] = []
            for track in tracks:
                video_id = track.get("videoId")
                if video_id and video_id not in seen:
                    seen.add(video_id)
                    result.append({
                        "videoId": video_id,
                        "title": track.get("title", "Unknown"),
                        "artist": (
                            track["artists"][0]["name"]
                            if track.get("artists")
                            else "Unknown"
                        ),
                        "duration": track.get("duration"),
                    })
            return result
        except Exception:
            return []

    def get_radio(self, video_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get radio/similar songs for a given video ID (deduplicated)."""
        if not self._ytmusic:
            return []

        try:
            watch_playlist = self._ytmusic.get_watch_playlist(videoId=video_id, limit=limit)
            tracks = watch_playlist.get("tracks", [])

            # Deduplicate by videoId
            seen: set[str] = set()
            result: list[dict[str, Any]] = []
            for track in tracks:
                vid = track.get("videoId")
                if vid and vid not in seen:
                    seen.add(vid)
                    result.append({
                        "videoId": vid,
                        "title": track.get("title", "Unknown"),
                        "artist": (
                            track["artists"][0]["name"]
                            if track.get("artists")
                            else "Unknown"
                        ),
                        "duration": track.get("length"),
                    })
            return result
        except Exception:
            return []
