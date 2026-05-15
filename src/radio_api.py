import json
import os
import random
import socket
import time
from typing import Dict, List, Optional

import requests
from platformdirs import user_cache_dir

_CACHE_DIR = user_cache_dir("RadioBrowserPlayer", "GruiaChiscop")
os.makedirs(_CACHE_DIR, exist_ok=True)
_CACHE_PATH = os.path.join(_CACHE_DIR, "server_cache.json")
_CACHE_TTL = 86400  # 24 hours


class RadioStation:
    def __init__(self, data, source="radiobrowser"):
        self.source = source
        data = data or {}

        if source == "radiobrowser":
            self.name = data.get("name", "Unknown")
            self.url = data.get("url_resolved", data.get("url", ""))
            self.country = data.get("country", "Unknown")
            self.countrycode = data.get("countrycode", "")
            self.state = data.get("state", "")
            self.language = data.get("language", "Unknown")
            self.tags = data.get("tags", "")
            self.favicon = data.get("favicon", "")
            self.bitrate = int(data.get("bitrate", 0) or 0)
            self.codec = data.get("codec", "Unknown")
            self.geo_lat = data.get("geo_lat")
            self.geo_long = data.get("geo_long")
            self.city = data.get("city", "")
            self.votes = int(data.get("votes", 0) or 0)

            location_parts = [p for p in [self.city, self.state, self.country] if p and p != "Unknown"]
            self.location = ", ".join(dict.fromkeys(location_parts)) if location_parts else "Unknown"

        elif source == "onlineradiobox":
            self.name = data.get("name", "Unknown")
            self.url = data.get("url", "")
            self.country = data.get("country", "Unknown")
            self.countrycode = data.get("countrycode", "")
            self.state = ""
            self.language = data.get("language", "Unknown")
            self.tags = ""
            self.favicon = data.get("favicon", "")
            self.bitrate = 0
            self.codec = "Unknown"
            self.geo_lat = None
            self.geo_long = None
            self.city = ""
            self.votes = 0
            self.location = data.get("location", self.country)
        else:
            self.name = data.get("name", "")
            self.url = data.get("url", "")
            self.country = "Unknown"
            self.countrycode = ""
            self.state = ""
            self.language = "Unknown"
            self.tags = ""
            self.favicon = ""
            self.bitrate = 0
            self.codec = "Unknown"
            self.geo_lat = None
            self.geo_long = None
            self.city = ""
            self.votes = 0
            self.location = "Unknown"

    def quality_score(self):
        return self.bitrate * 2 + self.votes

    def __str__(self):
        return f"{self.name} - {self.location}"


class RadioBrowserAPI:
    def __init__(self):
        self.base_url: Optional[str] = None
        self.on_servers_set = lambda message: None
        self.on_error = lambda message: None
        self._load_cached_server()

    # ------------------------------------------------------------------
    # Server discovery with 24-hour cache so DNS lookup doesn't block UI
    # ------------------------------------------------------------------

    def _load_cached_server(self):
        try:
            if os.path.exists(_CACHE_PATH):
                with open(_CACHE_PATH, "r") as f:
                    data = json.load(f)
                if time.time() - data.get("timestamp", 0) < _CACHE_TTL:
                    self.base_url = data.get("url")
        except Exception:
            pass

    def _save_cached_server(self, url: str):
        try:
            with open(_CACHE_PATH, "w") as f:
                json.dump({"url": url, "timestamp": time.time()}, f)
        except Exception:
            pass

    def _get_radiobrowser_base_urls(self) -> List[str]:
        hosts = []
        try:
            ips = socket.getaddrinfo("all.api.radio-browser.info", 80, 0, 0, socket.IPPROTO_TCP)
            for ip_tuple in ips:
                ip = ip_tuple[4][0]
                try:
                    host_addr = socket.gethostbyaddr(ip)
                    if host_addr[0] not in hosts:
                        hosts.append(host_addr[0])
                except socket.herror:
                    continue
            hosts.sort()
            return ["https://" + host for host in hosts]
        except Exception as e:
            self.on_error(f"Error getting server list: {e}")
            return []

    def _get_base_url(self):
        if self.base_url:
            return self.base_url

        servers = self._get_radiobrowser_base_urls()
        if servers:
            self.base_url = random.choice(servers)
            self._save_cached_server(self.base_url)
            self.on_servers_set(f"Using server: {self.base_url}")
        else:
            self.base_url = "https://de1.api.radio-browser.info"
            self.on_error("Could not discover servers. Using fallback server.")
        return self.base_url

    def refresh_server(self):
        """Force a fresh server discovery, ignoring the cache."""
        self.base_url = None
        try:
            os.remove(_CACHE_PATH)
        except Exception:
            pass
        return self._get_base_url()

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _make_request(self, path, params=None, data=None):
        base_url = self._get_base_url()
        url = f"{base_url}{path}"
        headers = {
            "User-Agent": "RadioBrowserPlayer/1.2",
            "Content-Type": "application/json",
        }

        try:
            if data:
                response = requests.post(url, json=data, headers=headers, timeout=12)
            else:
                response = requests.get(url, params=params, headers=headers, timeout=12)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.on_error(f"Request error for {url}: {e}")
            return None

    # ------------------------------------------------------------------
    # De-duplication
    # ------------------------------------------------------------------

    def _remove_duplicates_keep_highest_bitrate(self, stations: List[RadioStation]) -> List[RadioStation]:
        best: Dict[str, RadioStation] = {}
        for station in stations:
            key = f"{station.name.strip().lower()}::{station.countrycode or station.country}"
            if key not in best or station.bitrate > best[key].bitrate:
                best[key] = station
        return sorted(best.values(), key=lambda s: (s.bitrate, s.votes), reverse=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_stations(self, limit=1000, best_bitrate_only=False):
        data = self._make_request(f"/json/stations/topvote/{limit}")
        if not data:
            return []
        stations = [RadioStation(station) for station in data]
        if best_bitrate_only:
            return self._remove_duplicates_keep_highest_bitrate(stations)
        return stations

    def search_stations(
        self,
        name="",
        country="",
        language="",
        offset=0,
        limit=1000,
        order="votes",
        reverse=True,
        hide_broken=True,
        best_bitrate_only=False,
    ):
        params = {
            "offset": offset,
            "limit": limit,
            "order": order,
            "reverse": str(reverse).lower(),
            "hidebroken": "true" if hide_broken else "false",
        }
        if name:
            params["name"] = name
        if country:
            params["country"] = country
        if language:
            params["language"] = language

        data = self._make_request("/json/stations/search", params=params)
        if not data:
            return []

        stations = [RadioStation(station) for station in data]
        if best_bitrate_only:
            stations = self._remove_duplicates_keep_highest_bitrate(stations)
        return stations

    def get_countries(self):
        data = self._make_request("/json/countries")
        if data:
            return sorted([c["name"] for c in data if c.get("name")])
        return []

    def get_languages(self):
        data = self._make_request("/json/languages")
        if data:
            return sorted([lang["name"] for lang in data if lang.get("name")])
        return []

    def get_continents(self):
        return {
            "Africa": ["DZ", "AO", "BJ", "BW", "BF", "BI", "CM", "CV", "CF", "TD", "KM", "CG", "CD", "CI", "DJ", "EG", "GQ", "ER", "ET", "GA", "GM", "GH", "GN", "GW", "KE", "LS", "LR", "LY", "MG", "MW", "ML", "MR", "MU", "YT", "MA", "MZ", "NA", "NE", "NG", "RE", "RW", "SH", "ST", "SN", "SC", "SL", "SO", "ZA", "SS", "SD", "SZ", "TZ", "TG", "TN", "UG", "EH", "ZM", "ZW"],
            "Asia": ["AF", "AM", "AZ", "BH", "BD", "BT", "BN", "KH", "CN", "GE", "HK", "IN", "ID", "IR", "IQ", "IL", "JP", "JO", "KZ", "KW", "KG", "LA", "LB", "MO", "MY", "MV", "MN", "MM", "NP", "KP", "OM", "PK", "PS", "PH", "QA", "SA", "SG", "KR", "LK", "SY", "TW", "TJ", "TH", "TL", "TR", "TM", "AE", "UZ", "VN", "YE"],
            "Europe": ["AX", "AL", "AD", "AT", "BY", "BE", "BA", "BG", "HR", "CY", "CZ", "DK", "EE", "FO", "FI", "FR", "DE", "GI", "GR", "GG", "HU", "IS", "IE", "IM", "IT", "JE", "XK", "LV", "LI", "LT", "LU", "MK", "MT", "MD", "MC", "ME", "NL", "NO", "PL", "PT", "RO", "RU", "SM", "RS", "SK", "SI", "ES", "SJ", "SE", "CH", "UA", "GB", "VA"],
            "North America": ["AI", "AG", "AW", "BS", "BB", "BZ", "BM", "BQ", "VG", "CA", "KY", "CR", "CU", "CW", "DM", "DO", "SV", "GL", "GD", "GP", "GT", "HT", "HN", "JM", "MQ", "MX", "MS", "NI", "PA", "PM", "PR", "BL", "KN", "LC", "MF", "VC", "SX", "TT", "TC", "US", "VI"],
            "South America": ["AR", "BO", "BR", "CL", "CO", "EC", "FK", "GF", "GY", "PY", "PE", "SR", "UY", "VE"],
            "Oceania": ["AS", "AU", "CK", "FJ", "PF", "GU", "KI", "MH", "FM", "NR", "NC", "NZ", "NU", "NF", "MP", "PW", "PG", "PN", "WS", "SB", "TK", "TO", "TV", "VU", "WF"],
            "Antarctica": ["AQ", "BV", "TF", "HM", "GS"],
        }

    def get_continents_list(self):
        return list(self.get_continents().keys())
