import wx
import wx.adv
from datetime import datetime
import threading
from pathlib import Path
import platform
import json
import os

from stream_recorder import StreamRecorder
from radio_api import RadioStation, RadioBrowserAPI
from online_radio_box import OnlineRadioBoxAPI
from SettingsDialog import SettingsDialog
from AddStationDialog import AddStationDialog
import Updater as updater
import accessible_output2.outputs.auto as auto
from radio_player import RadioPlayer

_ao = auto.Auto()
if _ao.is_system_output():
    _ao = None

APP_VERSION = "1.2.0"
# GitHub Releases API — check_for_updates() in Updater.py parses this format
UPDATE_URL = "https://api.github.com/repos/GruiaChiscop/radio-browser-accessible-desktop-app/releases/latest"
APP_DATA_DIR = os.environ.get("APPDATA") if platform.system() == "Windows" else str(Path.home())


class RadioPlayerFrame(wx.Frame):
    def __init__(self):
        super().__init__(parent=None, title="Radio Browser Player", size=(1000, 700))

        self.rb_api = RadioBrowserAPI()
        self.orb_api = OnlineRadioBoxAPI()

        self.stations: list[RadioStation] = []
        self.filtered_stations: list[RadioStation] = []
        self.favorites: list[RadioStation] = []
        self.current_station: RadioStation | None = None
        self.current_favorite_index = -1
        self.recorder = None
        self.recording = False
        self.current_offset = 0
        self.stations_per_page = 1000
        self.has_more_stations = False

        self.continent_map = self.rb_api.get_continents()
        self.settings = self._load_settings()

        self.is_playing = False
        self.is_muted = False
        self.volume = self.settings.get("volume", 70) / 100.0

        self._load_favorites()
        self._setup_ui()

        self.radio = RadioPlayer()
        self.radio.set_metadata_callback(self._on_metadata)
        self.radio.set_volume(self.volume)

        self.rb_api.on_servers_set = lambda msg: self.set_status(msg)
        self.rb_api.on_error = lambda msg: self.set_status(msg)
        self.orb_api.on_error = lambda msg: self.set_status(msg)

        # Server discovery runs in background — no longer blocks the UI
        threading.Thread(target=self.rb_api._get_base_url, daemon=True).start()

        self.app_updater = updater.AppUpdater(APP_VERSION, UPDATE_URL, "radio-browser-accessible", self)
        if self.settings.get("check_updates", True):
            wx.CallAfter(self.app_updater.update)

        self._load_countries_and_languages()

        self.Centre()
        self.Show()

    # ------------------------------------------------------------------
    # Metadata callback (called from background thread → push to main thread)
    # ------------------------------------------------------------------

    def _on_metadata(self, title: str):
        wx.CallAfter(self.set_status, f"Now Playing: {title}")

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Menu bar
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        settings_item = file_menu.Append(wx.ID_ANY, "Settings\tCtrl+S", "Open settings")
        self.Bind(wx.EVT_MENU, self.on_settings, settings_item)
        file_menu.AppendSeparator()
        add_item = file_menu.Append(wx.ID_ADD, "Add Custom Station...\tCtrl+N", "Add a custom radio station")
        self.Bind(wx.EVT_MENU, self.on_import_station, add_item)
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "Exit\tCtrl+Q", "Exit application")
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        menubar.Append(file_menu, "&File")

        help_menu = wx.Menu()
        about_item = help_menu.Append(wx.ID_ABOUT, "About", "About this application")
        self.Bind(wx.EVT_MENU, self.on_about, about_item)
        help_item = help_menu.Append(wx.ID_HELP, "Keyboard Shortcuts", "Keyboard shortcut reference")
        self.Bind(wx.EVT_MENU, self.on_help, help_item)
        menubar.Append(help_menu, "&Help")

        self.SetMenuBar(menubar)

        # Filter section
        filter_box = wx.StaticBox(panel, label="Filters")
        filter_sizer = wx.StaticBoxSizer(filter_box, wx.HORIZONTAL)

        filter_sizer.Add(wx.StaticText(panel, label="Search:"), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.search_ctrl = wx.TextCtrl(panel, size=(200, -1))
        self.search_ctrl.Bind(wx.EVT_TEXT, self.on_filter_change)
        filter_sizer.Add(self.search_ctrl, 0, wx.ALL, 5)

        for label, attr in [("Country:", "country_choice"), ("Language:", "language_choice"), ("Continent:", "continent_choice")]:
            filter_sizer.Add(wx.StaticText(panel, label=label), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
            choice = wx.Choice(panel, size=(150, -1))
            setattr(self, attr, choice)
            choice.Bind(wx.EVT_CHOICE, self.on_filter_change)
            filter_sizer.Add(choice, 0, wx.ALL, 5)

        self.best_bitrate_only_cb = wx.CheckBox(panel, label="Best bitrate only")
        self.best_bitrate_only_cb.SetValue(self.settings.get("best_bitrate_only", True))
        self.best_bitrate_only_cb.Bind(wx.EVT_CHECKBOX, self.on_filter_change)
        filter_sizer.Add(self.best_bitrate_only_cb, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        self.clear_btn = wx.Button(panel, label="Clear Filters")
        self.clear_btn.Enable(False)
        self.clear_btn.Bind(wx.EVT_BUTTON, self.on_clear_filters)
        filter_sizer.Add(self.clear_btn, 0, wx.ALL, 5)

        self.load_more_btn = wx.Button(panel, label="Load More Stations")
        self.load_more_btn.Bind(wx.EVT_BUTTON, self.on_load_more_stations)
        self.load_more_btn.Enable(False)
        filter_sizer.Add(self.load_more_btn, 0, wx.ALL, 5)

        main_sizer.Add(filter_sizer, 0, wx.ALL | wx.EXPAND, 5)

        # Notebook
        self.notebook = wx.Notebook(panel)

        def create_list_tab(parent, label):
            p = wx.Panel(parent)
            sz = wx.BoxSizer(wx.VERTICAL)
            sz.Add(wx.StaticText(p, label=label), 0, wx.ALL, 5)
            lc = wx.ListCtrl(p, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            lc.AppendColumn("Station Name", width=250)
            lc.AppendColumn("Location", width=220)
            lc.AppendColumn("Language", width=120)
            lc.AppendColumn("Bitrate", width=90)
            sz.Add(lc, 1, wx.EXPAND | wx.ALL, 5)
            p.SetSizer(sz)
            return p, lc

        self.stations_panel, self.stations_list = create_list_tab(self.notebook, "Stations")
        self.stations_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_station_play)
        self.stations_list.Bind(wx.EVT_CONTEXT_MENU, self.on_station_context_menu)

        self.favorites_panel, self.favorites_list = create_list_tab(self.notebook, "Favourite Stations")
        self.favorites_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_favorite_play)
        self.favorites_list.Bind(wx.EVT_CONTEXT_MENU, self.on_favorite_context_menu)

        self.notebook.AddPage(self.stations_panel, "All Stations")
        self.notebook.AddPage(self.favorites_panel, "Favorites")
        main_sizer.Add(self.notebook, 1, wx.ALL | wx.EXPAND, 5)

        # Now Playing section
        now_playing_box = wx.StaticBox(panel, label="Now Playing")
        now_playing_sizer = wx.StaticBoxSizer(now_playing_box, wx.VERTICAL)

        self.now_playing_label = wx.StaticText(panel, label="No station playing")
        now_playing_sizer.Add(self.now_playing_label, 0, wx.ALL, 5)

        stream_url_row = wx.BoxSizer(wx.HORIZONTAL)
        stream_url_row.Add(wx.StaticText(panel, label="Stream URL:"), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.stream_url_box = wx.TextCtrl(panel, value="", style=wx.TE_READONLY)
        stream_url_row.Add(self.stream_url_box, 1, wx.ALL | wx.EXPAND, 5)
        now_playing_sizer.Add(stream_url_row, 0, wx.EXPAND)

        main_sizer.Add(now_playing_sizer, 0, wx.ALL | wx.EXPAND, 5)

        # Volume control
        volume_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.mute_btn = wx.Button(panel, label="&Mute")
        self.mute_btn.Bind(wx.EVT_BUTTON, self.on_mute_toggle)
        volume_sizer.Add(self.mute_btn, 0, wx.ALL, 5)

        volume_sizer.Add(wx.StaticText(panel, label="&Volume:"), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.volume_slider = wx.Slider(panel, value=self.settings.get("volume", 70), minValue=0, maxValue=100)
        self.volume_slider.Bind(wx.EVT_SLIDER, self.on_volume_change)
        volume_sizer.Add(self.volume_slider, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        main_sizer.Add(volume_sizer, 0, wx.ALL | wx.EXPAND, 5)

        # Control buttons
        control_sizer = wx.BoxSizer(wx.HORIZONTAL)
        buttons = [
            ("&Load Stations", "load_btn", self.on_load_stations),
            ("&Play", "play_stop_btn", self.on_play_stop_toggle),
            ("P&revious", "prev_btn", self.on_previous_favorite),
            ("&Next", "next_btn", self.on_next_favorite),
            ("S&tart Recording", "record_btn", self.on_record),
            ("&Add new station", "import_btn", self.on_import_station),
        ]

        for label, attr, handler in buttons:
            btn = wx.Button(panel, label=label)
            setattr(self, attr, btn)
            btn.Bind(wx.EVT_BUTTON, handler)
            control_sizer.Add(btn, 0, wx.ALL, 5)
            if label in ("&Play", "&Next"):
                control_sizer.Add(wx.StaticLine(panel, style=wx.LI_VERTICAL), 0, wx.EXPAND | wx.ALL, 5)

        main_sizer.Add(control_sizer, 0, wx.ALL | wx.CENTER, 5)

        self.status_bar = self.CreateStatusBar()
        self.status_bar.SetStatusText("Ready")

        panel.SetSizer(main_sizer)
        main_sizer.Fit(self)
        self.Layout()

        if _ao:
            self.Bind(wx.EVT_CHAR_HOOK, self.on_handle_key_press)

    # ------------------------------------------------------------------
    # Status / accessibility
    # ------------------------------------------------------------------

    def set_status(self, message: str):
        self.status_bar.SetStatusText(message)
        if _ao:
            try:
                _ao.output(message)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _load_settings(self) -> dict:
        settings_file = os.path.join(APP_DATA_DIR, ".radio_settings.json")
        defaults = {
            "recording_dir": str(Path.home() / "RadioRecordings"),
            "source": "radiobrowser",
            "autoplay": False,
            "buffer_size": 1000,
            "check_updates": True,
            "volume": 70,
            "best_bitrate_only": True,
        }
        if os.path.exists(settings_file):
            try:
                with open(settings_file, "r") as f:
                    defaults.update(json.load(f))
            except Exception as e:
                print(f"Error loading settings: {e}")
        return defaults

    def _save_settings(self):
        settings_file = os.path.join(APP_DATA_DIR, ".radio_settings.json")
        try:
            with open(settings_file, "w") as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            wx.MessageBox(f"Error saving settings: {e}", "Error", wx.OK | wx.ICON_ERROR)

    # ------------------------------------------------------------------
    # Favorites persistence
    # ------------------------------------------------------------------

    def _load_favorites(self):
        favorites_file = os.path.join(APP_DATA_DIR, ".radio_favorites.json")
        if os.path.exists(favorites_file):
            try:
                with open(favorites_file, "r") as f:
                    self.favorites = [RadioStation(item) for item in json.load(f)]
                if hasattr(self, "favorites_list"):
                    self._update_favorites_list()
            except Exception as e:
                print(f"Error loading favorites: {e}")

    def _save_favorites(self):
        favorites_file = os.path.join(APP_DATA_DIR, ".radio_favorites.json")
        try:
            data = []
            for fav in self.favorites:
                data.append({
                    "name": fav.name,
                    "url": fav.url,
                    "country": fav.country,
                    "countrycode": getattr(fav, "countrycode", ""),
                    "state": getattr(fav, "state", ""),
                    "language": fav.language,
                    "bitrate": getattr(fav, "bitrate", 0),
                    "codec": getattr(fav, "codec", ""),
                    "tags": getattr(fav, "tags", ""),
                    "favicon": getattr(fav, "favicon", ""),
                    "geo_lat": getattr(fav, "geo_lat", None),
                    "geo_long": getattr(fav, "geo_long", None),
                    "city": getattr(fav, "city", ""),
                    "location": fav.location,
                })
            with open(favorites_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving favorites: {e}")

    # ------------------------------------------------------------------
    # Source helper
    # ------------------------------------------------------------------

    @property
    def _active_source(self) -> str:
        return self.settings.get("source", "radiobrowser")

    # ------------------------------------------------------------------
    # Country / language loading
    # ------------------------------------------------------------------

    def _load_countries_and_languages(self):
        self.set_status("Loading filters…")

        def load():
            if self._active_source == "onlineradiobox":
                countries = self.orb_api.get_countries()
                languages = []
            else:
                countries = self.rb_api.get_countries()
                languages = self.rb_api.get_languages()
            continents = self.rb_api.get_continents()
            wx.CallAfter(self._populate_filters, countries, languages, continents)

        threading.Thread(target=load, daemon=True).start()

    def _populate_filters(self, countries, languages, continents):
        # Already on the main thread via wx.CallAfter — do NOT spawn another thread
        self.country_choice.Clear()
        self.country_choice.Append("All")
        for c in countries:
            self.country_choice.Append(c)
        self.country_choice.SetSelection(0)

        self.language_choice.Clear()
        self.language_choice.Append("All")
        for lang in languages:
            self.language_choice.Append(lang)
        self.language_choice.SetSelection(0)

        # Continent filter only applies to RadioBrowser
        self.continent_choice.Clear()
        self.continent_choice.Append("All")
        if self._active_source == "radiobrowser":
            for cont in self.rb_api.get_continents_list():
                self.continent_choice.Append(cont)
        self.continent_choice.SetSelection(0)
        self.continent_choice.Enable(self._active_source == "radiobrowser")

        self.set_status("Ready — click 'Load Stations' to start")

    # ------------------------------------------------------------------
    # Station loading
    # ------------------------------------------------------------------

    def on_load_stations(self, event):
        self.set_status("Loading stations…")
        self.load_btn.Enable(False)
        self.current_offset = 0

        def load():
            if self._active_source == "onlineradiobox":
                query = self.search_ctrl.GetValue().strip()
                country = self.country_choice.GetStringSelection()
                stations = self.orb_api.search_stations(
                    query=query,
                    country="" if country == "All" else country,
                    limit=200,
                )
            else:
                stations = self.rb_api.get_stations(
                    best_bitrate_only=self.best_bitrate_only_cb.GetValue()
                )
            wx.CallAfter(self._on_stations_loaded, stations)

        threading.Thread(target=load, daemon=True).start()

    def on_load_more_stations(self, event):
        if not self.has_more_stations:
            return
        self.set_status("Loading more stations…")
        self.load_more_btn.Enable(False)

        def load():
            search_text = self.search_ctrl.GetValue()
            country = self.country_choice.GetStringSelection()
            language = self.language_choice.GetStringSelection()
            self.current_offset += self.stations_per_page

            more = self.rb_api.search_stations(
                name=search_text if search_text else "",
                country="" if country == "All" else country,
                language="" if language == "All" else language,
                offset=self.current_offset,
                limit=self.stations_per_page,
                order="bitrate" if self.best_bitrate_only_cb.GetValue() else "votes",
                best_bitrate_only=self.best_bitrate_only_cb.GetValue(),
            )
            wx.CallAfter(self._on_more_stations_loaded, more)

        threading.Thread(target=load, daemon=True).start()

    def _on_stations_loaded(self, stations):
        self.load_btn.Enable(True)
        self.stations = stations
        self.current_offset = 0
        self._apply_filters()
        self._update_favorites_list()
        self.set_status(f"Loaded {len(stations)} stations")

    def _on_more_stations_loaded(self, more):
        self.load_more_btn.Enable(True)
        if more:
            self.filtered_stations.extend(more)
            self.has_more_stations = len(more) >= self.stations_per_page
            self._update_stations_list()
            self.set_status(f"Loaded {len(more)} more. Total: {len(self.filtered_stations)}")
        else:
            self.has_more_stations = False
            self.load_more_btn.Enable(False)
            self.set_status("No more stations available")

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def on_filter_change(self, event):
        self.settings["best_bitrate_only"] = self.best_bitrate_only_cb.GetValue()
        if self.stations:
            self._apply_filters()
            self.clear_btn.Enable(True)

    def on_clear_filters(self, event):
        self.search_ctrl.SetValue("")
        self.country_choice.SetSelection(0)
        self.language_choice.SetSelection(0)
        self.continent_choice.SetSelection(0)
        self.best_bitrate_only_cb.SetValue(self.settings.get("best_bitrate_only", True))
        self.current_offset = 0
        self.has_more_stations = False
        self.load_more_btn.Enable(False)
        self.clear_btn.Enable(False)
        self._apply_filters()

    def _apply_filters(self):
        search_text = self.search_ctrl.GetValue()
        country = self.country_choice.GetStringSelection()
        language = self.language_choice.GetStringSelection()
        continent = self.continent_choice.GetStringSelection()

        self.current_offset = 0
        self.has_more_stations = False
        self.load_more_btn.Enable(False)

        has_filter = bool(search_text or country != "All" or language != "All" or continent != "All")

        if has_filter and self._active_source == "radiobrowser":
            def search():
                results = self.rb_api.search_stations(
                    name=search_text if search_text else "",
                    country="" if country == "All" else country,
                    language="" if language == "All" else language,
                    offset=0,
                    limit=self.stations_per_page,
                    order="bitrate" if self.best_bitrate_only_cb.GetValue() else "votes",
                    best_bitrate_only=self.best_bitrate_only_cb.GetValue(),
                )
                if continent != "All" and continent in self.continent_map:
                    codes = self.continent_map[continent]
                    results = [s for s in results if s.countrycode in codes]
                wx.CallAfter(self._on_filter_results, results)

            threading.Thread(target=search, daemon=True).start()
        else:
            self.filtered_stations = self.stations[:]
            if continent != "All" and continent in self.continent_map and self._active_source == "radiobrowser":
                codes = self.continent_map[continent]
                self.filtered_stations = [s for s in self.filtered_stations if s.countrycode in codes]
            if self.best_bitrate_only_cb.GetValue() and self._active_source == "radiobrowser":
                self.filtered_stations = self.rb_api._remove_duplicates_keep_highest_bitrate(self.filtered_stations)
            self._update_stations_list()

    def _on_filter_results(self, results):
        self.filtered_stations = results
        self.has_more_stations = len(results) >= self.stations_per_page
        self.load_more_btn.Enable(self.has_more_stations)
        self._update_stations_list()
        msg = f"Found {len(results)} stations"
        if self.has_more_stations:
            msg += " (more available)"
        self.set_status(msg)

    # ------------------------------------------------------------------
    # List controls
    # ------------------------------------------------------------------

    def _update_stations_list(self):
        self.stations_list.DeleteAllItems()
        for i, s in enumerate(self.filtered_stations):
            idx = self.stations_list.InsertItem(i, s.name)
            self.stations_list.SetItem(idx, 1, s.location)
            self.stations_list.SetItem(idx, 2, s.language)
            bitrate_text = f"{s.bitrate} kbps" if s.bitrate else "—"
            self.stations_list.SetItem(idx, 3, bitrate_text)
        msg = f"Showing {len(self.filtered_stations)} stations"
        if self.has_more_stations:
            msg += " (Load More available)"
        self.set_status(msg)

    def _update_favorites_list(self):
        self.favorites_list.DeleteAllItems()
        for i, s in enumerate(self.favorites):
            idx = self.favorites_list.InsertItem(i, s.name)
            self.favorites_list.SetItem(idx, 1, s.location)
            self.favorites_list.SetItem(idx, 2, s.language)
            bitrate_text = f"{s.bitrate} kbps" if s.bitrate else "—"
            self.favorites_list.SetItem(idx, 3, bitrate_text)

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def on_station_play(self, event):
        idx = event.GetIndex()
        if 0 <= idx < len(self.filtered_stations):
            self.play_station(self.filtered_stations[idx])

    def on_favorite_play(self, event):
        idx = event.GetIndex()
        if 0 <= idx < len(self.favorites):
            self.current_favorite_index = idx
            self.play_station(self.favorites[idx])

    def on_play_stop_toggle(self, event):
        if self.is_playing:
            self.stop_playback()
            return
        page = self.notebook.GetSelection()
        if page == 0:
            idx = self.stations_list.GetFirstSelected()
            if 0 <= idx < len(self.filtered_stations):
                self.play_station(self.filtered_stations[idx])
        else:
            idx = self.favorites_list.GetFirstSelected()
            if 0 <= idx < len(self.favorites):
                self.current_favorite_index = idx
                self.play_station(self.favorites[idx])

    def play_station(self, station: RadioStation):
        """Start playing a station, resolving the stream URL first for ORB stations."""
        if station.source == "onlineradiobox" and hasattr(station, "_orb_page_url"):
            self.set_status(f"Resolving stream URL for {station.name}…")
            self.now_playing_label.SetLabel(f"Connecting: {station.name}…")

            def resolve():
                url = self.orb_api.get_stream_url(station._orb_page_url)
                if url:
                    station.url = url
                    wx.CallAfter(self._do_play_station, station)
                else:
                    wx.CallAfter(self.set_status, f"Could not find stream URL for {station.name}")
                    wx.CallAfter(self.now_playing_label.SetLabel, "No station playing")

            threading.Thread(target=resolve, daemon=True).start()
        else:
            self._do_play_station(station)

    def _do_play_station(self, station: RadioStation):
        self.current_station = station
        self.now_playing_label.SetLabel(f"Playing: {station.name} ({station.location})")
        self.stream_url_box.SetValue(station.url)

        if self.is_playing:
            self.radio.stop()
            if self._active_source == "onlineradiobox":
                self.orb_api.stop_now_playing_poll()

        self.radio.play(station.url)
        self.is_playing = True
        self.play_stop_btn.SetLabel("&Stop")
        self.set_status(f"Playing {station.name}")

        # Start OnlineRadioBox now-playing poll if applicable
        if station.source == "onlineradiobox" and hasattr(station, "_orb_cs") and station._orb_cs:
            self.orb_api.start_now_playing_poll(station._orb_cs, self._on_metadata)

    def stop_playback(self):
        if self.is_playing or self.radio:
            self.radio.stop()
            self.is_playing = False
            self.play_stop_btn.SetLabel("&Play")
            self.now_playing_label.SetLabel("No station playing")
            self.stream_url_box.SetValue("")
            self.set_status("Stopped")
            if self._active_source == "onlineradiobox":
                self.orb_api.stop_now_playing_poll()
        if self.recording:
            self._stop_recording()

    def on_previous_favorite(self, event):
        if not self.favorites:
            wx.MessageBox("No favorites added yet.", "Info", wx.OK | wx.ICON_INFORMATION)
            return
        self.current_favorite_index = (self.current_favorite_index - 1) % len(self.favorites)
        self.play_station(self.favorites[self.current_favorite_index])
        self.favorites_list.Select(self.current_favorite_index)
        self.favorites_list.EnsureVisible(self.current_favorite_index)

    def on_next_favorite(self, event):
        if not self.favorites:
            wx.MessageBox("No favorites added yet.", "Info", wx.OK | wx.ICON_INFORMATION)
            return
        self.current_favorite_index = (self.current_favorite_index + 1) % len(self.favorites)
        self.play_station(self.favorites[self.current_favorite_index])
        self.favorites_list.Select(self.current_favorite_index)
        self.favorites_list.EnsureVisible(self.current_favorite_index)

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------

    def on_volume_change(self, event):
        if not self.is_muted:
            self.volume = self.volume_slider.GetValue() / 100.0
            self.radio.set_volume(self.volume)

    def on_mute_toggle(self, event):
        self.is_muted = not self.is_muted
        if self.is_muted:
            self.radio.set_volume(0.0)
            self.mute_btn.SetLabel("Un&mute")
            self.set_status("Muted")
        else:
            self.radio.set_volume(self.volume)
            self.mute_btn.SetLabel("&Mute")
            self.set_status(f"Unmuted — Volume: {int(self.volume * 100)}%")

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def on_record(self, event):
        if not self.current_station:
            wx.MessageBox("Please select a station to record.", "Error", wx.OK | wx.ICON_ERROR)
            return
        if not self.recording:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        recordings_dir = Path(self.settings.get("recording_dir", str(Path.home() / "RadioRecordings")))
        recordings_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c for c in self.current_station.name if c.isalnum() or c in " -_").strip()
        filename = recordings_dir / f"{safe_name}_{timestamp}.mp3"

        self.recorder = StreamRecorder(self.current_station.url, str(filename))
        self.recorder.start()
        self.recording = True
        self.record_btn.SetLabel("Stop Recording")
        self.set_status(f"Recording to: {filename}")

    def _stop_recording(self):
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
        self.recording = False
        self.record_btn.SetLabel("S&tart Recording")
        self.set_status(f"Recording saved to {self.settings.get('recording_dir', str(Path.home() / 'RadioRecordings'))}")

    # ------------------------------------------------------------------
    # Favorites management
    # ------------------------------------------------------------------

    def add_to_favorites(self, station: RadioStation):
        if any(f.url == station.url for f in self.favorites):
            wx.MessageBox("Station already in Favourites.", "Info", wx.OK | wx.ICON_INFORMATION)
            return
        self.favorites.append(station)
        self._update_favorites_list()
        self._save_favorites()
        self.set_status(f"Added {station.name} to Favorites")

    def remove_from_favorites(self, index: int):
        if 0 <= index < len(self.favorites):
            station = self.favorites.pop(index)
            self._update_favorites_list()
            self._save_favorites()
            self.set_status(f"Removed {station.name} from Favorites")

    def on_import_station(self, event):
        dlg = AddStationDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            new_station = dlg.get_station()
            if new_station:
                self.favorites.append(new_station)
                self._update_favorites_list()
                self._save_favorites()
                self.set_status(f"Added custom station: {new_station.name}")
        dlg.Destroy()

    # ------------------------------------------------------------------
    # Context menus
    # ------------------------------------------------------------------

    def on_station_context_menu(self, event):
        idx = self.stations_list.GetFirstSelected()
        if idx == -1 or idx >= len(self.filtered_stations):
            return
        station = self.filtered_stations[idx]

        menu = wx.Menu()
        play_item = menu.Append(wx.ID_ANY, "Play")
        add_fav_item = menu.Append(wx.ID_ANY, "Add to Favourites")
        copy_url_item = menu.Append(wx.ID_ANY, "Copy Stream URL")

        self.Bind(wx.EVT_MENU, lambda e: self.play_station(station), play_item)
        self.Bind(wx.EVT_MENU, lambda e: self.add_to_favorites(station), add_fav_item)
        self.Bind(wx.EVT_MENU, lambda e: self._copy_url(station.url), copy_url_item)

        pos = event.GetPosition()
        if pos == wx.DefaultPosition:
            pos = self.stations_list.GetPosition()
        else:
            pos = self.stations_list.ScreenToClient(pos)
        self.stations_list.PopupMenu(menu, pos)
        menu.Destroy()

    def on_favorite_context_menu(self, event):
        idx = self.favorites_list.GetFirstSelected()
        if idx == -1 or idx >= len(self.favorites):
            return
        station = self.favorites[idx]

        menu = wx.Menu()
        play_item = menu.Append(wx.ID_ANY, "Play")
        remove_item = menu.Append(wx.ID_ANY, "Remove from Favorites")
        copy_url_item = menu.Append(wx.ID_ANY, "Copy Stream URL")

        self.Bind(wx.EVT_MENU, lambda e: self.play_station(station), play_item)
        self.Bind(wx.EVT_MENU, lambda e: self.remove_from_favorites(idx), remove_item)
        self.Bind(wx.EVT_MENU, lambda e: self._copy_url(station.url), copy_url_item)

        pos = event.GetPosition()
        if pos == wx.DefaultPosition:
            pos = self.favorites_list.GetPosition()
        else:
            pos = self.favorites_list.ScreenToClient(pos)
        self.favorites_list.PopupMenu(menu, pos)
        menu.Destroy()

    def _copy_url(self, url: str):
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(url))
            wx.TheClipboard.Close()
            self.set_status(f"Copied URL: {url}")

    # ------------------------------------------------------------------
    # Menu handlers
    # ------------------------------------------------------------------

    def on_settings(self, event):
        dlg = SettingsDialog(self, self.settings)
        if dlg.ShowModal() == wx.ID_OK:
            old_source = self._active_source
            self.settings = dlg.settings
            self.settings["best_bitrate_only"] = self.best_bitrate_only_cb.GetValue()
            self._save_settings()
            self.set_status("Settings saved")
            # Reload filter dropdowns if the data source changed
            if self._active_source != old_source:
                self.stations = []
                self.filtered_stations = []
                self._update_stations_list()
                self._load_countries_and_languages()
        dlg.Destroy()

    def on_about(self, event):
        info = wx.adv.AboutDialogInfo()
        info.SetName("Radio Browser Player")
        info.SetVersion(APP_VERSION)
        info.SetDescription(
            "Accessible radio player with Radio Browser and Online Radio Box support.\n\n"
            "Now Playing metadata, ICY stream tags, and screen reader integration."
        )
        info.SetWebSite("https://github.com/GruiaChiscop/radio-browser-accessible-desktop-app")
        wx.adv.AboutBox(info)

    def on_help(self, event):
        help_text = (
            "Keyboard Shortcuts\n\n"
            "Ctrl+S  — Open Settings\n"
            "Ctrl+N  — Add Custom Station\n"
            "Ctrl+Q  — Exit\n"
            "F1      — About\n"
            "F2      — Announce favourite count\n"
            "F3      — Announce current status\n"
            "Enter   — Play selected station (double-click also works)\n"
            "Space   — Play / Stop toggle\n"
        )
        wx.MessageBox(help_text, "Keyboard Shortcuts", wx.OK | wx.ICON_INFORMATION)

    def on_exit(self, event):
        if self.is_playing:
            self.radio.stop()
        if self.recording:
            self._stop_recording()
        self.orb_api.close()
        self.Close()

    # ------------------------------------------------------------------
    # Accessibility key hook
    # ------------------------------------------------------------------

    def on_handle_key_press(self, event: wx.KeyEvent):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_F1:
            self.on_about(None)
        elif keycode == wx.WXK_F2:
            if _ao:
                _ao.output(f"{len(self.favorites)} stations are in Favourites")
        elif keycode == wx.WXK_F3:
            if _ao:
                _ao.output(self.GetStatusBar().GetStatusText())
        else:
            event.Skip()


if __name__ == "__main__":
    app = wx.App()
    frame = RadioPlayerFrame()
    app.MainLoop()
