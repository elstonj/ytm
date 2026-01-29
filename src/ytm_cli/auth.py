# ytm-cli - YouTube Music CLI
# Created by Jack Elston
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
"""Authentication helpers for YouTube Music."""

import json
import re
import webbrowser
from pathlib import Path

from ytmusicapi.auth.browser import get_authorization, sapisid_from_cookie


def parse_chrome_headers(raw_headers: str) -> dict[str, str]:
    """Parse headers from Chrome DevTools format.

    Chrome DevTools shows headers as:
        Header-Name
        value
        Another-Header
        another value

    This function converts that to a dict.
    """
    headers: dict[str, str] = {}
    lines = raw_headers.strip().split("\n")

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines
        if not line:
            i += 1
            continue

        # Check if this looks like a header name (starts with letter/colon, no spaces in key part)
        # Chrome format: header names are on their own line, values on the next
        if line.startswith(":") or (
            re.match(r"^[A-Za-z][\w-]*$", line) and i + 1 < len(lines)
        ):
            header_name = line.lower().lstrip(":")
            i += 1
            if i < len(lines):
                header_value = lines[i].strip()
                headers[header_name] = header_value
            i += 1
        # Handle "Header: value" format (Firefox/standard)
        elif ": " in line:
            parts = line.split(": ", 1)
            if len(parts) == 2:
                headers[parts[0].lower()] = parts[1]
            i += 1
        else:
            i += 1

    return headers


def create_auth_headers(cookie: str, user_agent: str | None = None) -> dict[str, str]:
    """Create ytmusicapi-compatible headers from cookie string.

    Args:
        cookie: The cookie string from the browser
        user_agent: Optional user agent string

    Returns:
        Headers dict for ytmusicapi
    """
    sapisid = sapisid_from_cookie(cookie)
    if not sapisid:
        raise ValueError("Could not find SAPISID in cookies. Make sure you're logged in.")

    authorization = get_authorization(sapisid)

    return {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "authorization": authorization,
        "content-type": "application/json",
        "cookie": cookie,
        "origin": "https://music.youtube.com",
        "user-agent": user_agent
        or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "x-goog-authuser": "0",
        "x-origin": "https://music.youtube.com",
    }


def run_auth_flow(auth_file: Path) -> None:
    """Run the authentication flow.

    Opens browser to YouTube Music and prompts user to paste headers.
    """
    auth_file.parent.mkdir(parents=True, exist_ok=True)

    # Open browser
    webbrowser.open("https://music.youtube.com")

    print("\nPaste your browser headers below, then press Enter twice when done:")
    print("(Copy from DevTools Network tab → any music.youtube.com request → Request Headers)\n")

    # Read multiline input
    lines = []
    empty_count = 0
    while empty_count < 2:
        try:
            line = input()
            if line == "":
                empty_count += 1
            else:
                empty_count = 0
                lines.append(line)
        except EOFError:
            break

    raw_headers = "\n".join(lines)
    if not raw_headers.strip():
        raise ValueError("No headers provided")

    # Parse the headers
    headers = parse_chrome_headers(raw_headers)

    # Extract what we need
    cookie = headers.get("cookie", "")
    if not cookie:
        raise ValueError("No 'Cookie' header found. Make sure you copied the Request Headers.")

    user_agent = headers.get("user-agent")

    # Create auth headers
    auth_headers = create_auth_headers(cookie, user_agent)

    # Save to file
    with open(auth_file, "w") as f:
        json.dump(auth_headers, f, indent=2)
