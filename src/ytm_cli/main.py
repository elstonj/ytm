# ytm-cli - YouTube Music CLI
# Created by Jack Elston
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
"""Main CLI entry point."""

import os
import select
import sys
import termios
import tty

import typer
from rich.console import Console
from rich.table import Table

from ytm_cli.api import YouTubeMusicAPI
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
            if key == "\x03":
                return "ctrl+c"
            return key
        return None


app = typer.Typer(
    name="ytm",
    help="YouTube Music CLI - Search, play, and manage your music from the terminal.",
)
console = Console()

_tray_mode: bool = False


def format_time(seconds: float) -> str:
    """Format seconds as MM:SS."""
    if seconds <= 0:
        return "0:00"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


def _launch_tray(
    queue: list,
    api: YouTubeMusicAPI,
    radio_mode: bool = False,
) -> None:
    """Launch tray mode with lazy import, forking to background."""
    try:
        from ytm_cli.tray import run_tray_mode
    except ImportError:
        console.print(
            "[red]PySide6 required for tray mode. Install with: pip install 'ytm-cli[tray]'[/red]"
        )
        raise typer.Exit(1)

    pid = os.fork()
    if pid > 0:
        console.print(f"[green]Tray started[/green] [dim](PID {pid})[/dim]")
        raise typer.Exit(0)

    # Child: detach from terminal
    os.setsid()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)

    run_tray_mode(queue=queue, api=api, radio_mode=radio_mode)
    os._exit(0)


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


def _handle_output_device(player: Player, keys: KeyReader) -> None:
    """Show audio output device list and let user pick one."""
    devices = player.get_audio_devices()
    if not devices:
        console.print("\n[red]No audio devices available[/red]")
        return

    current = player.get_audio_device()
    console.print("\n[bold] Audio Output:[/bold]")
    for i, dev in enumerate(devices, 1):
        marker = " ◄" if dev["name"] == current else ""
        label = dev["description"] if dev["name"] != "auto" else "Autoselect device"
        console.print(f"  [cyan]{i}.[/cyan] {label}{marker}")
    console.print("[dim] Select [1-9]:[/dim]", end=" ")

    key = keys.get_key(timeout=5.0)
    if key and key.isdigit():
        idx = int(key) - 1
        if 0 <= idx < len(devices):
            dev = devices[idx]
            if player.set_audio_device(dev["name"]):
                label = dev["description"] if dev["name"] != "auto" else "Autoselect device"
                console.print(f"\n[green]Switched to: {label}[/green]")
            else:
                console.print("\n[red]Failed to switch device[/red]")
            return
    console.print()


def play_with_progress(
    player: Player,
    track: dict,
    api: YouTubeMusicAPI,
    radio: bool = False,
) -> str | None:
    """Play a track with progress display.

    Returns 'search' if user wants to search, None otherwise.
    """
    video_id = track.get("videoId")
    if not video_id:
        console.print("[red]Invalid track[/red]")
        return None

    artist = track.get("artist", "Unknown")
    console.print(f"\n[green]▶ Now Playing:[/green] {track['title']} - {artist}")

    if radio:
        console.print("[dim]Loading radio (similar songs)...[/dim]")
        radio_tracks = api.get_radio(video_id, limit=50)
        queue = [track] + [t for t in radio_tracks if t.get("videoId") != video_id]
        console.print(f"[dim]Loaded {len(queue)} songs in queue[/dim]")
    else:
        queue = [track]

    queue_index = 0
    paused = False

    console.print(
        "[dim]Controls: space=pause  n=next  p=prev  +=like"
        "  -=dislike  o=output  /=search  Ctrl+C=quit[/dim]"
    )

    try:
        with KeyReader() as keys:
            while queue_index < len(queue):
                current = queue[queue_index]
                vid = current.get("videoId")

                artist = current.get("artist", "Unknown")
                pos = f"{queue_index + 1}/{len(queue)}"
                console.print(f"\n[cyan]({pos})[/cyan] {current['title']} - {artist}")

                player.play(vid)
                paused = False

                # Play loop with key handling
                while player.is_active():
                    # Check for keypress
                    key = keys.get_key(timeout=0.3)

                    if key == "ctrl+c":
                        print()  # New line after progress bar
                        player.stop()
                        raise KeyboardInterrupt
                    elif key == " ":
                        if paused:
                            player.resume()
                            paused = False
                        else:
                            player.pause()
                            paused = True
                    elif key == "n":
                        player.stop()
                        queue_index += 1
                        console.print("\n[dim]>> Next[/dim]")
                        break
                    elif key == "p":
                        player.stop()
                        queue_index = max(0, queue_index - 1)
                        console.print("\n[dim]<< Previous[/dim]")
                        break
                    elif key == "+":
                        if vid and api.rate_song(vid, "LIKE"):
                            console.print("\n[green]♥ Liked![/green]")
                        else:
                            console.print("\n[red]Failed to like[/red]")
                    elif key == "-":
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
                    elif key == "/":
                        player.stop()
                        console.print("\n")
                        return "search"
                    elif key == "o":
                        _handle_output_device(player, keys)

                    # Update progress display
                    position, duration = player.get_progress()
                    if duration > 0:
                        pct = int((position / duration) * 40)
                        bar = "█" * pct + "░" * (40 - pct)
                        icon = "⏸" if paused else "▶"
                        elapsed = format_time(position)
                        total = format_time(duration)
                        print(f"\r{icon} [{bar}] {elapsed}/{total}  ", end="", flush=True)
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
    radio: bool = typer.Option(False, "--radio", "-r", help="Enable radio mode (similar songs)"),
):
    """Search for songs and play by number."""
    api = YouTubeMusicAPI()

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
                    if _tray_mode:
                        _launch_tray(queue=[track], api=api, radio_mode=radio)
                        return
                    player = Player()
                    try:
                        result = play_with_progress(player, track, api, radio=radio)
                        if result == "search":
                            # User pressed / to search
                            new_query = console.input("[bold]Search:[/bold] ").strip()
                            if new_query:
                                current_query = new_query
                                continue
                        # Playback finished or stopped - exit
                        break
                    finally:
                        player.stop()
                else:
                    console.print(f"[red]Please enter a number between 1 and {len(results)}[/red]")
            except ValueError:
                console.print("[red]Please enter a valid number[/red]")
    except KeyboardInterrupt:
        pass


@app.command()
def play(query: str):
    """Play a song by search query."""
    api = YouTubeMusicAPI()

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

    if _tray_mode:
        _launch_tray(queue=[track], api=api)
        return

    player = Player()
    console.print(f"[green]▶ Playing:[/green] {track['title']} - {track.get('artist', 'Unknown')}")

    try:
        player.play(video_id)
        console.print("[dim]Controls: space=pause  o=output  Ctrl+C=quit[/dim]")

        # Simple progress display with pause support
        with KeyReader() as keys:
            paused = False
            while player.is_active():
                key = keys.get_key(timeout=0.3)

                if key == "ctrl+c":
                    print()  # New line after progress bar
                    break
                elif key == " ":
                    if paused:
                        player.resume()
                        paused = False
                    else:
                        player.pause()
                        paused = True
                elif key == "o":
                    _handle_output_device(player, keys)

                position, duration = player.get_progress()
                if duration > 0:
                    pct = int((position / duration) * 40)
                    bar = "█" * pct + "░" * (40 - pct)
                    icon = "⏸" if paused else "▶"
                    elapsed = format_time(position)
                    total = format_time(duration)
                    print(f"\r{icon} [{bar}] {elapsed}/{total}  ", end="", flush=True)

        print()  # New line after progress
    except Exception as e:
        console.print(f"[red]Playback error: {e}[/red]")
    finally:
        player.stop()


@app.command()
def auth():
    """Authenticate with YouTube Music (required for library access)."""
    console.print("[bold]YouTube Music Authentication[/bold]\n")
    console.print(
        "[dim]Note: Auth is only needed for library features"
        " (liked songs, playlists, rating).[/dim]"
    )
    console.print("[dim]Search and playback work without auth.[/dim]")
    console.print("A browser will open. Then:")
    console.print("  1. Sign in to YouTube Music if needed")
    console.print("  2. Press [bold]F12[/bold] → [bold]Network[/bold] tab")
    console.print("  3. Refresh the page (F5)")
    console.print("  4. Click any request to [cyan]music.youtube.com[/cyan]")
    console.print("  5. Scroll to [bold]Request Headers[/bold], select all, copy")
    console.print("  6. Paste here and press Enter twice\n")

    try:
        YouTubeMusicAPI.authenticate()
        console.print("\n[green]Authentication successful![/green]")
        console.print(f"Credentials saved to: {YouTubeMusicAPI.AUTH_FILE}")
    except KeyboardInterrupt:
        console.print("\n[yellow]Authentication cancelled.[/yellow]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[red]Authentication failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def library():
    """Browse your YouTube Music library and play playlists."""
    api = YouTubeMusicAPI()

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

    player = None
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
                        _play_playlist_interactive(api, tracks, "Liked Songs")
                    else:
                        console.print("[yellow]No liked songs found.[/yellow]")
                elif 2 <= num <= len(playlists) + 1:
                    playlist = playlists[num - 2]
                    console.print(f"[dim]Loading {playlist['title']}...[/dim]")
                    tracks = api.get_playlist(playlist["playlistId"])
                    if tracks:
                        display_tracks(tracks, playlist["title"])
                        _play_playlist_interactive(api, tracks, playlist["title"])
                    else:
                        console.print("[yellow]Playlist is empty.[/yellow]")
                else:
                    max_num = len(playlists) + 1
                    console.print(f"[red]Please enter a number between 1 and {max_num}[/red]")
                    continue

                if _tray_mode:
                    return
                show_library()

            except ValueError:
                console.print("[red]Please enter a valid number[/red]")
    except KeyboardInterrupt:
        pass
    finally:
        if player:
            player.stop()


def _play_playlist_interactive(
    api: YouTubeMusicAPI,
    tracks: list,
    name: str,
) -> None:
    """Play a playlist interactively with number selection."""
    console.print(
        "\n[dim]Enter a track number to start from, 'a' to play all, or Enter to go back[/dim]"
    )

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

        queue = list(tracks[start_index:])

        if _tray_mode:
            _launch_tray(queue=queue, api=api)
            return

        # Play from selected track through end
        player = Player()
        queue_index = 0
        paused = False

        console.print(f"\n[green]Playing {name}[/green] ({len(queue)} tracks)")
        console.print(
            "[dim]Controls: space=pause  n=next  p=prev  +=like"
            "  -=dislike  o=output  Ctrl+C=quit[/dim]"
        )

        try:
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

                        if key == "ctrl+c":
                            print()  # New line after progress bar
                            player.stop()
                            raise KeyboardInterrupt
                        elif key == " ":
                            if paused:
                                player.resume()
                                paused = False
                            else:
                                player.pause()
                                paused = True
                        elif key == "n":
                            player.stop()
                            queue_index += 1
                            console.print("\n[dim]>> Next[/dim]")
                            break
                        elif key == "p":
                            player.stop()
                            queue_index = max(0, queue_index - 1)
                            console.print("\n[dim]<< Previous[/dim]")
                            break
                        elif key == "+":
                            if video_id and api.rate_song(video_id, "LIKE"):
                                console.print("\n[green]♥ Liked![/green]")
                            else:
                                console.print("\n[red]Failed to like[/red]")
                        elif key == "-":
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
                        elif key == "o":
                            _handle_output_device(player, keys)

                        # Update progress display
                        position, duration = player.get_progress()
                        if duration > 0:
                            pct = int((position / duration) * 40)
                            bar = "█" * pct + "░" * (40 - pct)
                            icon = "⏸" if paused else "▶"
                            elapsed = format_time(position)
                            total = format_time(duration)
                            print(f"\r{icon} [{bar}] {elapsed}/{total}  ", end="", flush=True)
                    else:
                        # Song finished naturally
                        print()
                        queue_index += 1
        finally:
            player.stop()

        console.print("[green]Playlist finished[/green]")
        return


@app.command()
def radio(query: str):
    """Play a song and continue with similar songs (radio mode)."""
    api = YouTubeMusicAPI()

    console.print(f"[dim]Searching for '{query}'...[/dim]")
    results = api.search(query, limit=1)
    if not results:
        console.print("[red]No results found.[/red]")
        raise typer.Exit(1)

    track = results[0]

    if _tray_mode:
        # Pre-fetch radio tracks for instant queue
        video_id = track.get("videoId")
        if video_id:
            console.print("[dim]Loading radio tracks...[/dim]")
            radio_tracks = api.get_radio(video_id, limit=50)
            queue = [track] + [t for t in radio_tracks if t.get("videoId") != video_id]
        else:
            queue = [track]
        _launch_tray(queue=queue, api=api, radio_mode=True)
        return

    player = Player()
    try:
        play_with_progress(player, track, api, radio=True)
    except KeyboardInterrupt:
        pass
    finally:
        player.stop()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    tray: bool = typer.Option(False, "--tray", "-t", help="Run in system tray mode"),
):
    """YouTube Music CLI."""
    global _tray_mode
    _tray_mode = tray
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
