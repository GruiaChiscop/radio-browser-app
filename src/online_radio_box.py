"""
OnlineRadioBox integration — HTML scraper + now-playing JSON API.

OnlineRadioBox has no official public API, so we scrape their website.
The URL layout is:
  Search  : https://onlineradiobox.com/search/?cs=on&q=<query>
  Station : https://onlineradiobox.com/<cc>/<slug>/
  Now playing JSON: https://onlineradiobox.com/json/?schedule_cs=<cc>.<slug>

The station's "cs" (channel-selector) code is derived directly from its page
path: /us/kexp/ → cs = us.kexp
"""

import re
import time
import threading
from typing import List, Optional

import requests

from radio_api import RadioStation

_BASE = "https://onlineradiobox.com"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Country code → readable country name (subset for filter UI)
_CC_TO_COUNTRY = {
    "us": "United States", "gb": "United Kingdom", "de": "Germany",
    "fr": "France", "ru": "Russia", "br": "Brazil", "au": "Australia",
    "ca": "Canada", "in": "India", "jp": "Japan", "es": "Spain",
    "it": "Italy", "nl": "Netherlands", "pl": "Poland", "ro": "Romania",
    "hu": "Hungary", "cz": "Czech Republic", "sk": "Slovakia",
    "ua": "Ukraine", "rs": "Serbia", "hr": "Croatia", "bg": "Bulgaria",
    "gr": "Greece", "pt": "Portugal", "se": "Sweden", "no": "Norway",
    "dk": "Denmark", "fi": "Finland", "be": "Belgium", "at": "Austria",
    "ch": "Switzerland", "tr": "Turkey", "cn": "China", "kr": "South Korea",
    "mx": "Mexico", "ar": "Argentina", "co": "Colombia", "cl": "Chile",
    "pe": "Peru", "za": "South Africa", "eg": "Egypt", "ng": "Nigeria",
    "nz": "New Zealand", "id": "Indonesia", "ph": "Philippines",
    "th": "Thailand",
}


def _cs_from_path(path: str) -> Optional[str]:
    """Convert /us/kexp/ → 'us.kexp'."""
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return None


class OnlineRadioBoxAPI:
    """
    Scraper-based client for OnlineRadioBox.

    All network calls are synchronous (run them in threads from the UI layer).
    """

    def __init__(self):
        self.on_error = lambda msg: None
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        # Now-playing polling state
        self._now_playing_thread: Optional[threading.Thread] = None
        self._stop_np = threading.Event()

    # ------------------------------------------------------------------
    # Station search
    # ------------------------------------------------------------------

    def search_stations(
        self,
        query: str = "",
        country: str = "",
        limit: int = 100,
    ) -> List[RadioStation]:
        """Return up to *limit* stations matching *query* and/or *country*."""
        search_term = query or country or "radio"
        try:
            resp = self._session.get(
                f"{_BASE}/search/",
                params={"cs": "on", "q": search_term},
                timeout=12,
            )
            resp.raise_for_status()
            return self._parse_search_html(resp.text, limit)
        except Exception as exc:
            self.on_error(f"OnlineRadioBox search error: {exc}")
            return []

    def _parse_search_html(self, html: str, limit: int) -> List[RadioStation]:
        stations: List[RadioStation] = []
        seen: set = set()

        # Match station-page links: href="/cc/slug/"
        # OnlineRadioBox search results wrap each station in an <a> whose href
        # follows the pattern /<2-letter-cc>/<slug>/
        for m in re.finditer(
            r'href="(/[a-z]{2}/[^/"]+/)"[^>]*>([^<]*)</a>',
            html,
            re.IGNORECASE,
        ):
            if len(stations) >= limit:
                break
            path, name = m.group(1), m.group(2).strip()
            if not name or path in seen:
                continue
            # Skip obvious non-station links (top-level pages, etc.)
            parts = path.strip("/").split("/")
            if len(parts) != 2:
                continue
            seen.add(path)

            cc = parts[0].lower()
            country_name = _CC_TO_COUNTRY.get(cc, cc.upper())
            cs_code = _cs_from_path(path)

            station = RadioStation(
                {
                    "name": name,
                    "url": f"{_BASE}{path}",  # page URL; resolved to stream on play
                    "country": country_name,
                    "countrycode": cc.upper(),
                    "location": country_name,
                    "language": "",
                    "favicon": "",
                },
                source="onlineradiobox",
            )
            # Attach metadata for later use
            station._orb_page_url = f"{_BASE}{path}"
            station._orb_cs = cs_code
            stations.append(station)

        return stations

    # ------------------------------------------------------------------
    # Stream URL resolution (fetched on demand when user presses Play)
    # ------------------------------------------------------------------

    def get_stream_url(self, page_url: str) -> Optional[str]:
        """Fetch the station page and extract the live stream URL."""
        try:
            resp = self._session.get(page_url, timeout=12)
            resp.raise_for_status()
            return self._extract_stream_url(resp.text)
        except Exception as exc:
            self.on_error(f"Error resolving stream URL from {page_url}: {exc}")
            return None

    @staticmethod
    def _extract_stream_url(html: str) -> Optional[str]:
        """Try several known patterns to pull the stream URL from the page HTML."""

        # Pattern 1 – JSON blob with a "streams" key
        m = re.search(r'"streams"\s*:\s*\[([^\]]+)\]', html)
        if m:
            urls = re.findall(r'"(https?://[^"]+)"', m.group(1))
            if urls:
                return urls[0]

        # Pattern 2 – data-audio / data-src attribute
        for attr in ("data-audio", "data-src", "data-url"):
            m = re.search(rf'{attr}=["\']([^"\']+)["\']', html)
            if m:
                url = m.group(1)
                if url.startswith("http"):
                    return url

        # Pattern 3 – <audio src="...">
        m = re.search(r"<audio[^>]+src=[\"']([^\"']+)[\"']", html, re.IGNORECASE)
        if m:
            url = m.group(1)
            if url.startswith("http"):
                return url

        # Pattern 4 – JavaScript variable containing a stream URL
        m = re.search(
            r'(?:stream|src|url)\s*[=:]\s*["\']'
            r'(https?://[^\s"\'<>]+\.(?:mp3|aac|ogg|pls|m3u8)[^"\']*)["\']',
            html,
            re.IGNORECASE,
        )
        if m:
            return m.group(1)

        # Pattern 5 – any bare stream URL in the page
        m = re.search(
            r'(https?://[^\s"\'<>]+\.(?:mp3|aac|ogg|pls|m3u8)(?:\?[^\s"\'<>]*)?)',
            html,
        )
        if m:
            return m.group(1)

        return None

    # ------------------------------------------------------------------
    # Now-playing polling
    # ------------------------------------------------------------------

    def start_now_playing_poll(self, cs_code: str, callback) -> None:
        """
        Start a background thread that polls the now-playing API every 15 s
        and calls *callback(title: str)* when the track changes.
        """
        self.stop_now_playing_poll()
        self._stop_np = threading.Event()
        self._now_playing_thread = threading.Thread(
            target=self._np_worker,
            args=(cs_code, callback),
            daemon=True,
        )
        self._now_playing_thread.start()

    def stop_now_playing_poll(self) -> None:
        if self._now_playing_thread:
            self._stop_np.set()
            self._now_playing_thread.join(timeout=2)
            self._now_playing_thread = None

    def _np_worker(self, cs_code: str, callback) -> None:
        last_title = None
        while not self._stop_np.is_set():
            title = self._fetch_now_playing(cs_code)
            if title and title != last_title:
                last_title = title
                try:
                    callback(title)
                except Exception:
                    pass
            self._stop_np.wait(timeout=15)

    def _fetch_now_playing(self, cs_code: str) -> Optional[str]:
        try:
            resp = self._session.get(
                f"{_BASE}/json/",
                params={"schedule_cs": cs_code},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
            return (
                data.get("nowplaying")
                or data.get("title")
                or data.get("song")
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Filter helpers (used to populate UI dropdowns)
    # ------------------------------------------------------------------

    def get_countries(self) -> List[str]:
        return sorted(_CC_TO_COUNTRY.values())

    def get_languages(self) -> List[str]:
        return []  # OnlineRadioBox doesn't expose language data easily

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self):
        self.stop_now_playing_poll()
        self._session.close()
