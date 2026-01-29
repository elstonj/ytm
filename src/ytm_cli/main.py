# ytm-cli - YouTube Music CLI
# Created by Jack Elston
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
"""Main CLI entry point."""

import select
import sys
import termios
import tty
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ytm_cli.api import YouTubeMusicAPI
from ytm_cli.browser_auth import authenticate_from_browser
from ytm_cli.player import Player


class KeyReader:
    """Non-blocking key reader for Unix terminals."""

    def __init__(self):
        self.old_settings = None

    def __enter__(self):
        self.old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, *args):
        if self.old_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)

    def get_key(self, timeout: float = 0.1) -> str | None:
        """Get a keypress if available, or None if no key pressed."""
        if select.select([sys.stdin], [], [], timeout)[0]:
            key = sys.stdin.read(1)
            # Handle Ctrl+C
            if key == '\x03':
                return 'ctrl+c'
            return key
        return None

app = typer.Typer(
    name="ytm",
    help="YouTube Music CLI - Search, play, and manage your music from the terminal.",
)
console = Console()


def format_time(seconds: float) -> str:
    """Format seconds as MM:SS."""
    if seconds <= 0:
        return "0:00"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


def display_tracks(tracks: list, title: str = "Results") -> None:
    """Display a numbered list of tracks."""
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("#", style="cyan", width=4)
    table.add_column("Title", style="white")
    table.add_column("Artist", style="dim")
    table.add_column("Duration", style="dim", width=8)

    for i, track in enumerate(tracks, 1):
        table.add_row(
            str(i),
            track.get("title", "Unknown")[:50],
            track.get("artist", "Unknown")[:30],
            track.get("duration", ""),
        )

    console.print(table)


def play_with_progress(player: Player, track: dict, api: YouTubeMusicAPI, radio: bool = False) -> str | None:
    """Play a track with progress display. Returns 'search' if user wants to search, None otherwise."""
    video_id = track.get("videoId")
    if not video_id:
        console.print("[red]Invalid track[/red]")
        return None

    console.print(f"\n[green]▶ Now Playing:[/green] {track['title']} - {track.get('artist', 'Unknown')}")

    if radio:
        console.print("[dim]Loading radio (similar songs)...[/dim]")
        radio_tracks = api.get_radio(video_id, limit=50)
        queue = [track] + [t for t in radio_tracks if t.get("videoId") != video_id]
        console.print(f"[dim]Loaded {len(queue)} songs in queue[/dim]")
    else:
        queue = [track]

    queue_index = 0
    paused = False

    console.print("[dim]Controls: space=pause  n=next  p=prev  +=like  -=dislike  /=search  Ctrl+C=quit[/dim]")

    try:
        with KeyReader() as keys:
            while queue_index < len(queue):
                current = queue[queue_index]
                vid = current.get("videoId")

                console.print(f"\n[cyan]({queue_index + 1}/{len(queue)})[/cyan] {current['title']} - {current.get('artist', 'Unknown')}")

                player.play(vid)
                paused = False

                # Play loop with key handling
                while player.is_active():
                    # Check for keypress
                    key = keys.get_key(timeout=0.3)

                    if key == 'ctrl+c':
                        player.stop()
                        raise KeyboardInterrupt
                    elif key == ' ':
                        if paused:
                            player.resume()
                            paused = False
                        else:
                            player.pause()
                            paused = True
                    elif key == 'n':
                        player.stop()
                        queue_index += 1
                        console.print("\n[dim]>> Next[/dim]")
                        break
                    elif key == 'p':
                        player.stop()
                        queue_index = max(0, queue_index - 1)
                        console.print("\n[dim]<< Previous[/dim]")
                        break
                    elif key == '+':
                        if vid and api.rate_song(vid, "LIKE"):
                            console.print("\n[green]♥ Liked![/green]")
                        else:
                            console.print("\n[red]Failed to like[/red]")
                    elif key == '-':
                        if vid and api.rate_song(vid, "DISLIKE"):
                            console.print("\n[red]👎 Disliked - skipping[/red]")
                            # Remove from queue
                            queue = [t for t in queue if t.get("videoId") != vid]
                            player.stop()
                            # Adjust index if needed (don't increment since we removed current)
                            if queue_index >= len(queue):
                                queue_index = len(queue)  # Will exit while loop
                            break
                        else:
                            console.print("\n[red]Failed to dislike[/red]")
                    elif key == '/':
                        player.stop()
                        console.print("\n")
                        return 'search'

                    # Update progress display
                    position, duration = player.get_progress()
                    if duration > 0:
                        pct = int((position / duration) * 40)
                        bar = "█" * pct + "░" * (40 - pct)
                        icon = "⏸" if paused else "▶"
                        print(f"\r{icon} [{bar}] {format_time(position)}/{format_time(duration)}  ", end="", flush=True)
                else:
                    # Song finished naturally
                    print()  # New line after progress
                    queue_index += 1

    except Exception:
        player.stop()
        return None

    console.print("[green]Queue finished[/green]")
    return None


@app.command()
def search(
    query: str,
    limit: int = typer.Option(10, "--limit", "-l", help="Number of results"),
    no_radio: bool = typer.Option(False, "--no-radio", help="Disable radio (similar songs)"),
):
    """Search for songs and play by number (radio enabled by default)."""
    radio = not no_radio
    api = YouTubeMusicAPI()
    player = Player()

    current_query = query

    try:
        while True:
            console.print(f"[dim]Searching for '{current_query}'...[/dim]")
            results = api.search(current_query, limit=limit)

            if not results:
                console.print("[yellow]No results found.[/yellow]")
                return

            display_tracks(results, f"Search: {current_query}")
            console.print("\n[dim]Enter a number to play, or press Enter to exit[/dim]")

            choice = console.input("[bold]Play #:[/bold] ").strip()
            if not choice:
                break

            try:
                num = int(choice)
                if 1 <= num <= len(results):
                    track = results[num - 1]
                    result = play_with_progress(player, track, api, radio=radio)
                    if result == 'search':
                        # User pressed / to search
                        new_query = console.input("[bold]Search:[/bold] ").strip()
                        if new_query:
                            current_query = new_query
                            continue
                    # Playback finished or stopped - exit
                    break
                else:
                    console.print(f"[red]Please enter a number between 1 and {len(results)}[/red]")
            except ValueError:
                console.print("[red]Please enter a valid number[/red]")
    except KeyboardInterrupt:
        pass
    finally:
        player.stop()


@app.command()
def play(query: str):
    """Play a song by search query."""
    api = YouTubeMusicAPI()
    player = Player()

    console.print(f"[dim]Searching for '{query}'...[/dim]")
    results = api.search(query, limit=1)
    if not results:
        console.print("[red]No results found.[/red]")
        raise typer.Exit(1)

    track = results[0]
    video_id = track.get("videoId")
    if not video_id:
        console.print("[red]Invalid track[/red]")
        raise typer.Exit(1)

    console.print(f"[green]▶ Playing:[/green] {track['title']} - {track.get('artist', 'Unknown')}")

    try:
        player.play(video_id)

        # Simple progress display with pause support
        with KeyReader() as keys:
            paused = False
            while player.is_active():
                key = keys.get_key(timeout=0.3)

                if key == 'ctrl+c':
                    break
                elif key == ' ':
                    if paused:
                        player.resume()
                        paused = False
                    else:
                        player.pause()
                        paused = True

                position, duration = player.get_progress()
                if duration > 0:
                    pct = int((position / duration) * 40)
                    bar = "█" * pct + "░" * (40 - pct)
                    icon = "⏸" if paused else "▶"
                    print(f"\r{icon} [{bar}] {format_time(position)}/{format_time(duration)}  ", end="", flush=True)

        print()  # New line after progress
    except Exception as e:
        console.print(f"[red]Playback error: {e}[/red]")
    finally:
        player.stop()


@app.command()
def auth(
    browser: Optional[str] = typer.Option(
        None, "--browser", "-b", help="Browser to extract cookies from (chrome, firefox, chromium)"
    ),
    manual: bool = typer.Option(False, "--manual", "-m", help="Use manual header paste method"),
):
    """Authenticate with YouTube Music to access your library."""
    from ytm_cli.api import YouTubeMusicAPI

    auth_file = YouTubeMusicAPI.AUTH_FILE

    # Remove existing auth file to avoid loading stale credentials
    if auth_file.exists():
        auth_file.unlink()

    if manual:
        console.print("[bold]YouTube Music Authentication (Manual)[/bold]\n")
        console.print("To authenticate, you need to copy request headers from your browser:")
        console.print("1. Open https://music.youtube.com in your browser")
        console.print("2. Open Developer Tools (F12) → Network tab")
        console.print("3. Click on any request to music.youtube.com")
        console.print("4. Find 'Request Headers' and copy everything")
        console.print("5. Paste below when prompted\n")
        api = YouTubeMusicAPI()
        api.authenticate()
    else:
        # Auto-detect browser if not specified
        if not browser:
            for b in ["chrome", "firefox", "chromium"]:
                try:
                    console.print(f"[dim]Trying {b}...[/dim]")
                    authenticate_from_browser(b, auth_file)
                    browser = b
                    break
                except Exception:
                    continue

            if not browser:
                console.print("[red]Could not extract cookies from any browser.[/red]")
                console.print("Make sure you're logged into YouTube Music, or use --manual")
                raise typer.Exit(1)
        else:
            try:
                authenticate_from_browser(browser, auth_file)
            except Exception as e:
                console.print(f"[red]Failed to extract cookies from {browser}: {e}[/red]")
                raise typer.Exit(1)

        console.print(f"[green]Extracted cookies from {browser}[/green]")

    console.print("[green]Authentication successful![/green]")
    console.print(f"Credentials saved to: {auth_file}")


@app.command()
def library():
    """Browse your YouTube Music library and play playlists."""
    api = YouTubeMusicAPI()
    player = Player()

    if not api.is_authenticated():
        console.print("[red]Please run 'ytm auth' first to authenticate.[/red]")
        raise typer.Exit(1)

    console.print("[dim]Loading library...[/dim]")
    playlists = api.get_library_playlists()

    def show_library():
        table = Table(title="Your Library", show_header=True, header_style="bold cyan")
        table.add_column("#", style="cyan", width=4)
        table.add_column("Playlist", style="white")
        table.add_column("Tracks", style="dim", width=8)
        table.add_row("1", "♥ Liked Songs", "")
        for i, p in enumerate(playlists, 2):
            table.add_row(str(i), p["title"], str(p.get("count", "?")))
        console.print(table)
        console.print("\n[dim]Enter a number to select, or press Enter to exit[/dim]")

    try:
        show_library()

        while True:
            choice = console.input("[bold]Select #:[/bold] ").strip()
            if not choice:
                break

            try:
                num = int(choice)
                if num == 1:
                    console.print("[dim]Loading liked songs...[/dim]")
                    tracks = api.get_liked_songs(limit=100)
                    if tracks:
                        display_tracks(tracks, "♥ Liked Songs")
                        _play_playlist_interactive(player, api, tracks, "Liked Songs")
                    else:
                        console.print("[yellow]No liked songs found.[/yellow]")
                elif 2 <= num <= len(playlists) + 1:
                    playlist = playlists[num - 2]
                    console.print(f"[dim]Loading {playlist['title']}...[/dim]")
                    tracks = api.get_playlist(playlist["playlistId"])
                    if tracks:
                        display_tracks(tracks, playlist["title"])
                        _play_playlist_interactive(player, api, tracks, playlist["title"])
                    else:
                        console.print("[yellow]Playlist is empty.[/yellow]")
                else:
                    console.print(f"[red]Please enter a number between 1 and {len(playlists) + 1}[/red]")
                    continue

                show_library()

            except ValueError:
                console.print("[red]Please enter a valid number[/red]")
    except KeyboardInterrupt:
        pass
    finally:
        player.stop()


def _play_playlist_interactive(player: Player, api: YouTubeMusicAPI, tracks: list, name: str) -> None:
    """Play a playlist interactively with number selection."""
    console.print(f"\n[dim]Enter a track number to start from, 'a' to play all, or Enter to go back[/dim]")

    while True:
        choice = console.input("[bold]Play #:[/bold] ").strip().lower()
        if not choice:
            return

        if choice == "a":
            # Play all from start
            start_index = 0
        else:
            try:
                num = int(choice)
                if 1 <= num <= len(tracks):
                    start_index = num - 1
                else:
                    console.print(f"[red]Please enter a number between 1 and {len(tracks)}[/red]")
                    continue
            except ValueError:
                console.print("[red]Please enter a valid number or 'a' for all[/red]")
                continue

        # Play from selected track through end
        queue = list(tracks[start_index:])  # Copy to allow modification
        queue_index = 0
        paused = False

        console.print(f"\n[green]Playing {name}[/green] ({len(queue)} tracks)")
        console.print("[dim]Controls: space=pause  n=next  p=prev  +=like  -=dislike  Ctrl+C=quit[/dim]")

        with KeyReader() as keys:
            while queue_index < len(queue):
                current = queue[queue_index]
                video_id = current.get("videoId")

                console.print(
                    f"\n[cyan]({start_index + queue_index + 1}/{len(tracks)})[/cyan] "
                    f"{current['title']} - {current.get('artist', 'Unknown')}"
                )

                player.play(video_id)
                paused = False

                # Play loop with key handling
                while player.is_active():
                    key = keys.get_key(timeout=0.3)

                    if key == 'ctrl+c':
                        player.stop()
                        raise KeyboardInterrupt
                    elif key == ' ':
                        if paused:
                            player.resume()
                            paused = False
                        else:
                            player.pause()
                            paused = True
                    elif key == 'n':
                        player.stop()
                        queue_index += 1
                        console.print("\n[dim]>> Next[/dim]")
                        break
                    elif key == 'p':
                        player.stop()
                        queue_index = max(0, queue_index - 1)
                        console.print("\n[dim]<< Previous[/dim]")
                        break
                    elif key == '+':
                        if video_id and api.rate_song(video_id, "LIKE"):
                            console.print("\n[green]♥ Liked![/green]")
                        else:
                            console.print("\n[red]Failed to like[/red]")
                    elif key == '-':
                        if video_id and api.rate_song(video_id, "DISLIKE"):
                            console.print("\n[red]👎 Disliked - skipping[/red]")
                            # Remove from queue
                            queue = [t for t in queue if t.get("videoId") != video_id]
                            player.stop()
                            if queue_index >= len(queue):
                                queue_index = len(queue)
                            break
                        else:
                            console.print("\n[red]Failed to dislike[/red]")

                    # Update progress display
                    position, duration = player.get_progress()
                    if duration > 0:
                        pct = int((position / duration) * 40)
                        bar = "█" * pct + "░" * (40 - pct)
                        icon = "⏸" if paused else "▶"
                        print(f"\r{icon} [{bar}] {format_time(position)}/{format_time(duration)}  ", end="", flush=True)
                else:
                    # Song finished naturally
                    print()
                    queue_index += 1

        console.print("[green]Playlist finished[/green]")
        return


@app.command()
def radio(query: str):
    """Play a song and continue with similar songs (radio mode)."""
    api = YouTubeMusicAPI()
    player = Player()

    console.print(f"[dim]Searching for '{query}'...[/dim]")
    results = api.search(query, limit=1)
    if not results:
        console.print("[red]No results found.[/red]")
        raise typer.Exit(1)

    track = results[0]
    try:
        play_with_progress(player, track, api, radio=True)
    except KeyboardInterrupt:
        pass
    finally:
        player.stop()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """YouTube Music CLI."""
    if ctx.invoked_subcommand is None:
        console.print("[bold]YouTube Music CLI[/bold]")
        console.print()
        console.print("Commands:")
        console.print("  ytm search <query>  - Search for songs (interactive)")
        console.print("  ytm play <query>    - Play first match")
        console.print("  ytm radio <query>   - Play with radio (similar songs)")
        console.print("  ytm library         - Browse your library")
        console.print("  ytm auth            - Authenticate with YouTube Music")
        console.print("  ytm --help          - Show all commands")


if __name__ == "__main__":
    app()
