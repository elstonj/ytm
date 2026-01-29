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
"""Browser cookie extraction for YouTube Music authentication."""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import browser_cookie3

ORIGIN = "https://music.youtube.com"


def get_sapisid_hash(sapisid: str) -> str:
    """Generate SAPISIDHASH for YouTube authentication.

    Args:
        sapisid: The SAPISID cookie value

    Returns:
        SAPISIDHASH string for the authorization header
    """
    timestamp = int(time.time())
    hash_input = f"{timestamp} {sapisid} {ORIGIN}"
    sha1_hash = hashlib.sha1(hash_input.encode()).hexdigest()
    return f"SAPISIDHASH {timestamp}_{sha1_hash}"


def get_youtube_cookies(browser: str = "chrome") -> dict[str, str]:
    """Extract YouTube cookies from a browser.

    Args:
        browser: Browser to extract from ('chrome', 'firefox', 'chromium')

    Returns:
        Dictionary of cookie name -> value for youtube.com
    """
    browser_funcs = {
        "chrome": browser_cookie3.chrome,
        "firefox": browser_cookie3.firefox,
        "chromium": browser_cookie3.chromium,
    }

    if browser not in browser_funcs:
        raise ValueError(f"Unsupported browser: {browser}. Use: {list(browser_funcs.keys())}")

    cj = browser_funcs[browser](domain_name=".youtube.com")

    cookies = {}
    for cookie in cj:
        cookies[cookie.name] = cookie.value

    return cookies


def create_headers_file(cookies: dict[str, str], filepath: Path) -> None:
    """Create a ytmusicapi headers file from cookies.

    Args:
        cookies: Dictionary of cookie name -> value
        filepath: Path to save the headers JSON file
    """
    # Get SAPISID for authorization header (try both regular and secure versions)
    sapisid = cookies.get("SAPISID") or cookies.get("__Secure-3PAPISID")

    if not sapisid:
        raise ValueError(
            "Could not find SAPISID cookie. "
            "Make sure you're logged into YouTube Music in your browser."
        )

    # Build cookie string
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())

    # Generate SAPISIDHASH for authorization
    auth_hash = get_sapisid_hash(sapisid)

    # Create headers dict for ytmusicapi
    headers: dict[str, Any] = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "authorization": auth_hash,
        "content-type": "application/json",
        "cookie": cookie_str,
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "x-origin": ORIGIN,
    }

    # Save to file
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(headers, f, indent=2)


def authenticate_from_browser(browser: str, filepath: Path) -> None:
    """Extract cookies from browser and create auth file.

    Args:
        browser: Browser to extract from ('chrome', 'firefox', 'chromium')
        filepath: Path to save the headers JSON file
    """
    cookies = get_youtube_cookies(browser)
    create_headers_file(cookies, filepath)
