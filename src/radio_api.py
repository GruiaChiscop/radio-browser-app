import requests
import socket
import json
import urllib.request
import random
import math
class RadioStation:
    def __init__(self, data, source="radiobrowser"):
        self.source = source
        if source == "radiobrowser":
            self.name = data.get('name', 'Unknown')
            self.url = data.get('url_resolved', data.get('url', ''))
            self.country = data.get('country', 'Unknown')
            self.countrycode = data.get('countrycode', '')
            self.state = data.get('state', '')
            self.language = data.get('language', 'Unknown')
            self.tags = data.get('tags', '')
            self.favicon = data.get('favicon', '')
            self.bitrate = data.get('bitrate', 0)
            self.codec = data.get('codec', 'Unknown')
            self.geo_lat = data.get('geo_lat', None)
            self.geo_long = data.get('geo_long', None)
            
            # Build location string
            location_parts = []
            if self.state:
                location_parts.append(self.state)
            if self.country and self.country != 'Unknown':
                location_parts.append(self.country)
            self.location = ', '.join(location_parts) if location_parts else 'Unknown'
            
        else:  # onlineradiobox
            self.name = data.get('name', 'Unknown')
            self.url = data.get('url', '')
            self.country = data.get('country', 'Unknown')
            self.countrycode = ''
            self.state = ''
            self.language = data.get('language', 'Unknown')
            self.tags = ''
            self.favicon = ''
            self.bitrate = 0
            self.codec = 'Unknown'
            self.geo_lat = None
            self.geo_long = None
            self.location = self.country
        
    def __str__(self):
        return f"{self.name} - {self.country}"

class RadioBrowserAPI:
    def __init__(self):
        self.base_url = None
        self._get_base_url()
    
    def _get_radiobrowser_base_urls(self):
        """Get all base urls of all currently available radiobrowser servers"""
        hosts = []
        try:
            ips = socket.getaddrinfo('all.api.radio-browser.info', 80, 0, 0, socket.IPPROTO_TCP)
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
            print(f"Error getting server list: {e}")
            return []
    
    def _get_base_url(self):
        """Get a random server from available servers"""
        servers = self._get_radiobrowser_base_urls()
        if servers:
            self.base_url = random.choice(servers)
            print(f"Using server: {self.base_url}")
        else:
            self._get_base_url()
    
    def _make_request(self, path, params=None, data=None):
        """Make a request to the API with proper headers"""
        url = f"{self.base_url}{path}"
        headers = {
            'User-Agent': 'RadioBrowserPlayer/1.0',
            'Content-Type': 'application/json'
        }
        
        try:
            if data:
                response = requests.post(url, json=data, headers=headers, timeout=10)
            else:
                response = requests.get(url, params=params, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"Request error for {url}: {e}")
        return None
    
    def _remove_duplicates_keep_highest_bitrate(self, stations):
        """Keep only one station per name — the one with the highest bitrate"""
        best = {}
        for s in stations:
            if s.name not in best or s.bitrate > best[s.name].bitrate:
                best[s.name] = s
        return list(best.values())

    def get_stations(self, limit=1000):
        """Get top stations by vote count"""
        try:
            data = self._make_request(f"/json/stations/topvote/{limit}")
            if data:
                stations = [RadioStation(station) for station in data]
                return self._remove_duplicates_keep_highest_bitrate(stations)
        except Exception as e:
            print(f"Error fetching stations: {e}")
        return []
    
    def search_stations(self, name="", country="", language="", offset=0, limit=1000):
        """Search stations by name, country, or language with pagination"""
        try:
            params = {
                'offset': offset,
                'limit': limit,
                'order': 'votes',
                'reverse': 'true'
            }
            if name:
                params['name'] = name
            if country:
                params['country'] = country
            if language:
                params['language'] = language
            
            data = self._make_request("/json/stations/search", params=params)
            if data:
                return self._remove_duplicates_keep_highest_bitrate([RadioStation(station) for station in data])
        except Exception as e:
            print(f"Error searching stations: {e}")
        return []
    
    def get_countries(self):
        """Get list of countries"""
        try:
            data = self._make_request("/json/countries")
            if data:
                return sorted([c['name'] for c in data if c.get('name')])
        except Exception as e:
            print(f"Error fetching countries: {e}")
        return []
    
    def get_languages(self):
        """Get list of languages"""
        try:
            data = self._make_request("/json/languages")
            if data:
                return sorted([l['name'] for l in data if l.get('name')])
        except Exception as e:
            print(f"Error fetching languages: {e}")
        return []
    
    def get_continents(self):
        """Get list of continents based on country codes"""
        # Map continents to country codes
        continents = {
            'Africa': ['DZ', 'AO', 'BJ', 'BW', 'BF', 'BI', 'CM', 'CV', 'CF', 'TD', 'KM', 'CG', 'CD', 'CI', 'DJ', 'EG', 'GQ', 'ER', 'ET', 'GA', 'GM', 'GH', 'GN', 'GW', 'KE', 'LS', 'LR', 'LY', 'MG', 'MW', 'ML', 'MR', 'MU', 'YT', 'MA', 'MZ', 'NA', 'NE', 'NG', 'RE', 'RW', 'SH', 'ST', 'SN', 'SC', 'SL', 'SO', 'ZA', 'SS', 'SD', 'SZ', 'TZ', 'TG', 'TN', 'UG', 'EH', 'ZM', 'ZW'],
            'Asia': ['AF', 'AM', 'AZ', 'BH', 'BD', 'BT', 'BN', 'KH', 'CN', 'GE', 'HK', 'IN', 'ID', 'IR', 'IQ', 'IL', 'JP', 'JO', 'KZ', 'KW', 'KG', 'LA', 'LB', 'MO', 'MY', 'MV', 'MN', 'MM', 'NP', 'KP', 'OM', 'PK', 'PS', 'PH', 'QA', 'SA', 'SG', 'KR', 'LK', 'SY', 'TW', 'TJ', 'TH', 'TL', 'TR', 'TM', 'AE', 'UZ', 'VN', 'YE'],
            'Europe': ['AX', 'AL', 'AD', 'AT', 'BY', 'BE', 'BA', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FO', 'FI', 'FR', 'DE', 'GI', 'GR', 'GG', 'HU', 'IS', 'IE', 'IM', 'IT', 'JE', 'XK', 'LV', 'LI', 'LT', 'LU', 'MK', 'MT', 'MD', 'MC', 'ME', 'NL', 'NO', 'PL', 'PT', 'RO', 'RU', 'SM', 'RS', 'SK', 'SI', 'ES', 'SJ', 'SE', 'CH', 'UA', 'GB', 'VA'],
            'North America': ['AI', 'AG', 'AW', 'BS', 'BB', 'BZ', 'BM', 'BQ', 'VG', 'CA', 'KY', 'CR', 'CU', 'CW', 'DM', 'DO', 'SV', 'GL', 'GD', 'GP', 'GT', 'HT', 'HN', 'JM', 'MQ', 'MX', 'MS', 'NI', 'PA', 'PM', 'PR', 'BL', 'KN', 'LC', 'MF', 'VC', 'SX', 'TT', 'TC', 'US', 'VI'],
            'South America': ['AR', 'BO', 'BR', 'CL', 'CO', 'EC', 'FK', 'GF', 'GY', 'PY', 'PE', 'SR', 'UY', 'VE'],
            'Oceania': ['AS', 'AU', 'CK', 'FJ', 'PF', 'GU', 'KI', 'MH', 'FM', 'NR', 'NC', 'NZ', 'NU', 'NF', 'MP', 'PW', 'PG', 'PN', 'WS', 'SB', 'TK', 'TO', 'TV', 'VU', 'WF'],
            'Antarctica': ['AQ', 'BV', 'TF', 'HM', 'GS']
        }
        return list(continents.keys())
