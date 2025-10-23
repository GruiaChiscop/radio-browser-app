import wx
import wx.adv
import requests
from datetime import datetime
import threading
import urllib.request
from pathlib import Path
import zipfile
import tempfile
from packaging import version
import io
import time
import platform
import sys
import json
import os
import accessible_output2.outputs.auto as auto
from stream_recorder import StreamRecorder
from radio_api import RadioStation, RadioBrowserAPI
from SettingsDialog import SettingsDialog
from AddStationDialog import AddStationDialog
import Updater
o = auto.Auto()

APP_VERSION = "1.0.0"
UPDATE_URL = "https://gruiachiscop.dev/radio-browser-accessible/update.zip"
#We trick the app to believe that vlc is installed in the app's director
if getattr(sys, 'frozen', False):
    base_path = os.path.dirname(sys.executable)+"/internal/"
    os.environ['PATH'] = base_path + os.pathsep + os.environ.get('PATH', '')
    os.environ['VLC_PLUGIN_PATH'] = os.path.join(base_path, 'plugins')
#os.environ['PYTHON_VLC_LIB_PATH'] = os.path.join(base_path, 'libvlc.dll')

import vlc

class LiveRegion(wx.Accessible):
    def __init__(self, win):
        super().__init__(win)
        self.text = ""

    def GetName(self, childId):
        return self.text, wx.ACC_OK
    def SetText(self, text):
        self.text = text
        wx.Accessible.NotifyEvent(wx.ACC_EVENT_OBJECT_NAMECHANGE, self.GetWindow(), wx.OBJID_CLIENT, 0)


class RadioPlayerFrame(wx.Frame):
    def __init__(self):
        super().__init__(parent=None, title='Radio Browser Player', size=(1000, 700))
        
        self.api = RadioBrowserAPI()
        self.stations = []
        self.filtered_stations = []
        self.favorites = []
        self.current_station = None
        self.current_favorite_index = -1
        self.recorder = None
        self.recording = False
        self.current_offset = 0
        self.stations_per_page = 1000
        self.has_more_stations = False
        #continents
        self.continentmap = self.api.get_continents()
        # Settings
        self.settings = self.load_settings()
        
        self.is_playing = False
        self.is_muted = False
        self.volume = 0.7
        self.vlc_instance = vlc.Instance('--no-xlib')
        self.player = self.vlc_instance.media_player_new()

        self.stream_thread = None
        self.stop_stream = False
        
        # Load favorites
        self.load_favorites()
        
        # Setup UI
        self.setup_ui()
        self.api.on_servers_set = lambda message: self.set_status(message)
        self.api._get_base_url()
        #initialise the updater
        self.updater = Updater.AppUpdater(APP_VERSION, "https://gruiachiscop.dev/radio-browser-accessible/update", "radio-browser-accessible", self)
        if self.settings.get('check_updates', True):
            t = threading.Thread(target=self.updater.update)
            t.daemon = True
            t.start()
        # Load initial data
        self.load_countries_and_languages()
        
        self.Centre()
        self.Show()
        
    def setup_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Menu bar
        menubar = wx.MenuBar()
        
        file_menu = wx.Menu()
        settings_item = file_menu.Append(wx.ID_ANY, "Settings\tCtrl+S", "Open settings")
        self.Bind(wx.EVT_MENU, self.on_settings, settings_item)
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "Exit\tCtrl+Q", "Exit application")
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        menubar.Append(file_menu, "&File")
        
        help_menu = wx.Menu()
        about_item = help_menu.Append(wx.ID_ABOUT, "About", "About this application")
        self.Bind(wx.EVT_MENU, self.on_about, about_item)
        menubar.Append(help_menu, "&Help")
        
        self.SetMenuBar(menubar)
        
        # Filter section
        filter_box = wx.StaticBox(panel, label="Filters")
        filter_sizer = wx.StaticBoxSizer(filter_box, wx.HORIZONTAL)
        
        # Search
        filter_sizer.Add(wx.StaticText(panel, label="Search:"), 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
        self.search_ctrl = wx.TextCtrl(panel, size=(200, -1))
        self.search_ctrl.Bind(wx.EVT_TEXT, self.on_filter_change)
        filter_sizer.Add(self.search_ctrl, 0, wx.ALL, 5)
        
        # Country filter
        filter_sizer.Add(wx.StaticText(panel, label="Country:"), 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
        self.country_choice = wx.Choice(panel, size=(150, -1))
        self.country_choice.Bind(wx.EVT_CHOICE, self.on_filter_change)
        filter_sizer.Add(self.country_choice, 0, wx.ALL, 5)
        
        # Language filter
        filter_sizer.Add(wx.StaticText(panel, label="Language:"), 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
        self.language_choice = wx.Choice(panel, size=(150, -1))
        self.language_choice.Bind(wx.EVT_CHOICE, self.on_filter_change)
        filter_sizer.Add(self.language_choice, 0, wx.ALL, 5)
        
        # Continent filter
        filter_sizer.Add(wx.StaticText(panel, label="Continent:"), 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
        self.continent_choice = wx.Choice(panel, size=(150, -1))
        self.continent_choice.Bind(wx.EVT_CHOICE, self.on_filter_change)
        filter_sizer.Add(self.continent_choice, 0, wx.ALL, 5)
        
        # Clear filters button
        clear_btn = wx.Button(panel, label="Clear Filters")
        clear_btn.Bind(wx.EVT_BUTTON, self.on_clear_filters)
        filter_sizer.Add(clear_btn, 0, wx.ALL, 5)
        
        # Load More button
        self.load_more_btn = wx.Button(panel, label="Load More Stations")
        self.load_more_btn.Bind(wx.EVT_BUTTON, self.on_load_more_stations)
        self.load_more_btn.Enable(False)
        filter_sizer.Add(self.load_more_btn, 0, wx.ALL, 5)
        
        main_sizer.Add(filter_sizer, 0, wx.ALL|wx.EXPAND, 5)
        
        # Notebook for stations and favorites
        self.notebook = wx.Notebook(panel)
        
        # All stations tab
        self.stations_panel = wx.Panel(self.notebook)
        stations_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.stations_list = wx.ListCtrl(self.stations_panel, style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        self.stations_list.AppendColumn("Station Name", width=250)
        self.stations_list.AppendColumn("Location", width=150)
        self.stations_list.AppendColumn("Country", width=100)
        self.stations_list.AppendColumn("Language", width=100)
        self.stations_list.AppendColumn("Bitrate", width=80)
        self.stations_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_station_play)
        self.stations_list.Bind(wx.EVT_CONTEXT_MENU, self.on_station_context_menu)
        
        stations_sizer.Add(self.stations_list, 1, wx.ALL|wx.EXPAND, 5)
        self.stations_panel.SetSizer(stations_sizer)
        
        # Favorites tab
        self.favorites_panel = wx.Panel(self.notebook)
        favorites_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.favorites_list = wx.ListCtrl(self.favorites_panel, style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        self.favorites_list.AppendColumn("Station Name", width=250)
        self.favorites_list.AppendColumn("Location", width=150)
        self.favorites_list.AppendColumn("Country", width=100)
        self.favorites_list.AppendColumn("Language", width=100)
        self.favorites_list.AppendColumn("Bitrate", width=80)
        self.favorites_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_favorite_play)
        self.favorites_list.Bind(wx.EVT_CONTEXT_MENU, self.on_favorite_context_menu)
        
        favorites_sizer.Add(self.favorites_list, 1, wx.ALL|wx.EXPAND, 5)
        self.favorites_panel.SetSizer(favorites_sizer)
        
        self.notebook.AddPage(self.stations_panel, "All Stations")
        self.notebook.AddPage(self.favorites_panel, "Favorites")
        
        main_sizer.Add(self.notebook, 1, wx.ALL|wx.EXPAND, 5)
        
        # Now playing section
        now_playing_box = wx.StaticBox(panel, label="Now Playing")
        now_playing_sizer = wx.StaticBoxSizer(now_playing_box, wx.VERTICAL)
        
        self.now_playing_label = wx.StaticText(panel, label="No station playing")
        now_playing_sizer.Add(self.now_playing_label, 0, wx.ALL, 5)
        
        self.stream_url_label = wx.StaticText(panel, label="Stream URL: ")
        now_playing_sizer.Add(self.stream_url_label, 0, wx.ALL, 5)
        
        main_sizer.Add(now_playing_sizer, 0, wx.ALL|wx.EXPAND, 5)
        
        # Volume control
        volume_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.mute_btn = wx.Button(panel, label="🔊 Mute")
        self.mute_btn.Bind(wx.EVT_BUTTON, self.on_mute_toggle)
        volume_sizer.Add(self.mute_btn, 0, wx.ALL, 5)
        
        volume_sizer.Add(wx.StaticText(panel, label="&Volume:"), 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
        
        self.volume_slider = wx.Slider(panel, value=70, minValue=0, maxValue=100, 
                                       style=wx.SL_HORIZONTAL|wx.SL_LABELS)
        self.volume_slider.Bind(wx.EVT_SLIDER, self.on_volume_change)
        volume_sizer.Add(self.volume_slider, 1, wx.ALL|wx.EXPAND, 5)
        
        main_sizer.Add(volume_sizer, 0, wx.ALL|wx.EXPAND, 5)
        control_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.load_btn = wx.Button(panel, label="&Load Stations")
        self.load_btn.Bind(wx.EVT_BUTTON, self.on_load_stations)
        control_sizer.Add(self.load_btn, 0, wx.ALL, 5)
        
        self.play_stop_btn = wx.Button(panel, label="▶ &Play")
        self.play_stop_btn.Bind(wx.EVT_BUTTON, self.on_play_stop_toggle)
        control_sizer.Add(self.play_stop_btn, 0, wx.ALL, 5)
        # Zapping controls
        control_sizer.Add(wx.StaticLine(panel, style=wx.LI_VERTICAL), 0, wx.EXPAND|wx.ALL, 5)
        
        self.prev_btn = wx.Button(panel, label="◀ P&revious")
        self.prev_btn.Bind(wx.EVT_BUTTON, self.on_previous_favorite)
        control_sizer.Add(self.prev_btn, 0, wx.ALL, 5)
        self.next_btn = wx.Button(panel, label="&Next ▶")
        self.next_btn.Bind(wx.EVT_BUTTON, self.on_next_favorite)
        control_sizer.Add(self.next_btn, 0, wx.ALL, 5)
        
        # Recording button
        control_sizer.Add(wx.StaticLine(panel, style=wx.LI_VERTICAL), 0, wx.EXPAND|wx.ALL, 5)
        
        self.record_btn = wx.Button(panel, label="⏺ S&tart Recording")
        self.record_btn.Bind(wx.EVT_BUTTON, self.on_record)
        control_sizer.Add(self.record_btn, 0, wx.ALL, 5)
        #import new stations button
        self.import_btn = wx.Button(panel, label = "&Add new station")
        self.import_btn.Bind(wx.EVT_BUTTON, self.on_import_station)
        control_sizer.Add(self.import_btn, 0, wx.ALL, 5)
        main_sizer.Add(control_sizer, 0, wx.ALL|wx.CENTER, 5)
        
        # Status bar with live region support
        self.status_bar = self.CreateStatusBar()
        self.status_bar.SetStatusText("Ready")
        
        # Live region for screen readers
        self.live_region = wx.Panel(panel)
        self.live_region.SetSize((0, 0))
        self.status_text = wx.StaticText(self.live_region, label="Ready", style=wx.ST_NO_AUTORESIZE)
        self.accessibleLiveRegion = LiveRegion(self.status_text)
        self.status_text.SetAccessible(self.accessibleLiveRegion)
        # Set ARIA live region
        #if hasattr(self.status_text, 'SetName'):
            #self.status_text.SetName("status")
        main_sizer.Add(self.live_region, 0, wx.ALL, 0)
        
        panel.SetSizer(main_sizer)
    
    def set_status(self, message):
        """Set status bar text and announce to screen readers via live region"""
        self.status_bar.SetStatusText(message)
        # Update live region for screen readers
        self.status_text.SetLabel(message)
        self.accessibleLiveRegion.SetText(message)
        #since the accessible live regions doesn't seem to work, we'll use the accessible-output2 module for speech
        o.output(message)
    def on_settings(self, event):
        """Open settings dialog"""
        dlg = SettingsDialog(self, self.settings)
        if dlg.ShowModal() == wx.ID_OK:
            self.settings = dlg.settings
            self.save_settings()
            # Apply buffer size
            self.set_status("Settings saved")
        dlg.Destroy()
    
    def on_about(self, event):
        """Show about dialog"""
        info = wx.adv.AboutDialogInfo()
        info.SetName("Radio Browser Player")
        info.SetVersion(APP_VERSION)
        info.SetDescription("Accessible radio player with support for Radio Browser and Online Radio Box")
        info.SetWebSite("https://gruiachiscop.dev")
        wx.adv.AboutBox(info)
    
    def on_exit(self, event):
        """Exit application"""
        if self.is_playing:
            self.player.stop()
        if self.recording:
            self.stop_recording()
        self.Close()
    
    def load_settings(self):
        """Load settings from file"""
        settings_file = Path.home() / ".radio_settings.json"
        default_settings = {
            'recording_dir': str(Path.home() / "RadioRecordings"),
            'source': 'radiobrowser',
            'autoplay': False,
            'buffer_size': 1000,
            'check_updates': True,
            'volume': 0.7
        }
        
        if settings_file.exists():
            try:
                with open(settings_file, 'r') as f:
                    loaded = json.load(f)
                    default_settings.update(loaded)
            except Exception as e:
                print(f"Error loading settings: {e}")
        
        return default_settings
    
    def save_settings(self):
        """Save settings to file"""
        settings_file = Path.home() / ".radio_settings.json"
        try:
            with open(settings_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            print(f"Error saving settings: {e}")
    
    def load_countries_and_languages(self):
        """Load countries and languages into dropdowns"""
        self.set_status("Loading countries and languages...")
        
        def load_data():
            countries = self.api.get_countries()
            languages = self.api.get_languages()
            continents = self.api.get_continents()
            wx.CallAfter(self.populate_filters, countries, languages, continents)
            #self.populate_filters(countries, languages, continents)
        
        thread = threading.Thread(target=load_data)
        thread.daemon = True
        thread.start()
    
    def populate_filters(self, countries, languages, continents):
        """Populate filter dropdowns"""
        def populate():
            self.country_choice.Clear()
            self.country_choice.Append("All")
            for country in countries:
                self.country_choice.Append(country)
                self.country_choice.SetSelection(0)
        
            self.language_choice.Clear()
            self.language_choice.Append("All")
            for language in languages:
                self.language_choice.Append(language)
            self.language_choice.SetSelection(0)
        
            self.continent_choice.Clear()
            self.continent_choice.Append("All")
            for continent in self.api.get_continents_list():
                self.continent_choice.Append(continent)
            self.continent_choice.SetSelection(0)
        populate()
        self.set_status("Ready - Click 'Load Stations' to start")
    
    def on_load_stations(self, event):
        """Load stations from API"""
        self.set_status("Loading stations...")
        self.load_btn.Enable(False)
        self.current_offset = 0
        
        def load():
            self.stations = self.api.get_stations()
            wx.CallAfter(self.on_stations_loaded)
        
        thread = threading.Thread(target=load)
        thread.daemon = True
        thread.start()
    
    def on_load_more_stations(self, event):
        """Load more stations based on current filters"""
        if not self.has_more_stations:
            return
        
        self.set_status("Loading more stations...")
        self.load_more_btn.Enable(False)
        
        def load():
            search_text = self.search_ctrl.GetValue()
            country = self.country_choice.GetStringSelection()
            language = self.language_choice.GetStringSelection()
            
            search_name = search_text if search_text else ""
            search_country = country if country != "All" else ""
            search_language = language if language != "All" else ""
            
            self.current_offset += self.stations_per_page
            
            more_stations = self.api.search_stations(
                name=search_name,
                country=search_country,
                language=search_language,
                offset=self.current_offset,
                limit=self.stations_per_page
            )
            
            wx.CallAfter(self.on_more_stations_loaded, more_stations)
        
        thread = threading.Thread(target=load)
        thread.daemon = True
        thread.start()
    
    def on_stations_loaded(self):
        """Called when stations are loaded"""
        self.load_btn.Enable(True)
        self.current_offset = 0
        self.apply_filters()
        self.set_status(f"Loaded {len(self.stations)} stations")
    
    def on_more_stations_loaded(self, more_stations):
        """Called when more stations are loaded via pagination"""
        self.load_more_btn.Enable(True)
        
        if more_stations and len(more_stations) > 0:
            self.filtered_stations.extend(more_stations)
            self.has_more_stations = len(more_stations) >= self.stations_per_page
            self.update_stations_list()
            self.set_status(f"Loaded {len(more_stations)} more stations. Total: {len(self.filtered_stations)}")
        else:
            self.has_more_stations = False
            self.load_more_btn.Enable(False)
            self.set_status("No more stations available")
    
    def apply_filters(self):
        """Apply current filters to station list"""
        search_text = self.search_ctrl.GetValue()
        country = self.country_choice.GetStringSelection()
        language = self.language_choice.GetStringSelection()
        continent = self.continent_choice.GetStringSelection()
        
        self.current_offset = 0
        self.has_more_stations = False
        self.load_more_btn.Enable(False)
        
        if search_text or country != "All" or language != "All" or continent != "All":
            #self.set_status("Searching stations...")
            
            def search():
                search_name = search_text if search_text else ""
                search_country = country if country != "All" else ""
                search_language = language if language != "All" else ""
                
                results = self.api.search_stations(
                    name=search_name,
                    country=search_country,
                    language=search_language,
                    offset=0,
                    limit=self.stations_per_page
                )
                
                # Apply continent filter locally
                if continent != "All" and continent in self.continent_map:
                    continent_codes = self.continent_map[continent]
                    results = [s for s in results if s.countrycode in continent_codes]
                
                wx.CallAfter(self.on_filter_results_loaded, results)
            
            thread = threading.Thread(target=search)
            thread.daemon = True
            thread.start()
        else:
            self.filtered_stations = self.stations[:]
            self.update_stations_list()    
    
    def on_filter_results_loaded(self, results):
        """Called when filter search results are loaded"""
        self.filtered_stations = results
        self.has_more_stations = len(results) >= self.stations_per_page
        self.load_more_btn.Enable(self.has_more_stations)
        self.update_stations_list()
        
        status_msg = f"Found {len(self.filtered_stations)} stations"
        if self.has_more_stations:
            status_msg += " (more available)"
        self.set_status(status_msg)
    
    def update_stations_list(self):
        """Update the stations list control"""
        self.stations_list.DeleteAllItems()
        for i, station in enumerate(self.filtered_stations):
            index = self.stations_list.InsertItem(i, station.name)
            self.stations_list.SetItem(index, 1, station.country)
            self.stations_list.SetItem(index, 2, station.language)
            self.stations_list.SetItem(index, 3, f"{station.bitrate} kbps")
        
        status_msg = f"Showing {len(self.filtered_stations)} stations"
        if self.has_more_stations:
            status_msg += " (Load More available)"
        self.set_status(status_msg)
    
    def update_favorites_list(self):
        """Update the favorites list control"""
        self.favorites_list.DeleteAllItems()
        for i, station in enumerate(self.favorites):
            index = self.favorites_list.InsertItem(i, station.name)
            self.favorites_list.SetItem(index, 1, station.country)
            self.favorites_list.SetItem(index, 2, station.language)
            self.favorites_list.SetItem(index, 3, f"{station.bitrate} kbps")
    
    def on_filter_change(self, event):
        """Handle filter change"""
        if self.stations:
            self.apply_filters()
    
    def on_clear_filters(self, event):
        """Clear all filters"""
        self.search_ctrl.SetValue("")
        self.country_choice.SetSelection(0)
        self.language_choice.SetSelection(0)
        self.continent_choice.SetSelection(0)
        self.current_offset = 0
        self.has_more_stations = False
        self.load_more_btn.Enable(False)
        self.apply_filters()
    
    def on_station_play(self, event):
        """Play station from double-click"""
        index = event.GetIndex()
        if 0 <= index < len(self.filtered_stations):
            station = self.filtered_stations[index]
            self.play_station(station)
    
    def on_favorite_play(self, event):
        """Play favorite from double-click"""
        index = event.GetIndex()
        if 0 <= index < len(self.favorites):
            station = self.favorites[index]
            self.current_favorite_index = index
            self.play_station(station)
    
    def on_station_context_menu(self, event):
        """Show context menu for station"""
        index = self.stations_list.GetFirstSelected()
        if index == -1 or index >= len(self.filtered_stations):
            return
        
        station = self.filtered_stations[index]
        
        menu = wx.Menu()
        play_item = menu.Append(wx.ID_ANY, "Play")
        add_fav_item = menu.Append(wx.ID_ANY, "Add to Favorites")
        copy_url_item = menu.Append(wx.ID_ANY, "Copy Stream URL")
        
        def on_play(e):
            self.play_station(station)
        
        def on_add_fav(e):
            self.add_to_favorites(station)
        
        def on_copy_url(e):
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(station.url))
                wx.TheClipboard.Close()
                self.set_status(f"Copied URL to clipboard: {station.url}")
        
        self.Bind(wx.EVT_MENU, on_play, play_item)
        self.Bind(wx.EVT_MENU, on_add_fav, add_fav_item)
        self.Bind(wx.EVT_MENU, on_copy_url, copy_url_item)
        
        pos = event.GetPosition()
        if pos == wx.DefaultPosition:
            pos = self.stations_list.GetPosition()
        else:
            pos = self.stations_list.ScreenToClient(pos)
        
        self.stations_list.PopupMenu(menu, pos)
        menu.Destroy()
    
    def on_favorite_context_menu(self, event):
        """Show context menu for favorite"""
        index = self.favorites_list.GetFirstSelected()
        if index == -1 or index >= len(self.favorites):
            return
        
        station = self.favorites[index]
        fav_index = index
        
        menu = wx.Menu()
        play_item = menu.Append(wx.ID_ANY, "Play")
        remove_item = menu.Append(wx.ID_ANY, "Remove from Favorites")
        copy_url_item = menu.Append(wx.ID_ANY, "Copy Stream URL")
        
        def on_play(e):
            self.play_station(station)
        
        def on_remove(e):
            self.remove_from_favorites(fav_index)
        
        def on_copy_url(e):
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(station.url))
                wx.TheClipboard.Close()
                self.set_status(f"Copied URL to clipboard: {station.url}")
        
        self.Bind(wx.EVT_MENU, on_play, play_item)
        self.Bind(wx.EVT_MENU, on_remove, remove_item)
        self.Bind(wx.EVT_MENU, on_copy_url, copy_url_item)
        
        pos = event.GetPosition()
        if pos == wx.DefaultPosition:
            pos = self.favorites_list.GetPosition()
        else:
            pos = self.favorites_list.ScreenToClient(pos)
        
        self.favorites_list.PopupMenu(menu, pos)
        menu.Destroy()
    
    def on_play_stop_toggle(self, event):
        """Toggle play/stop"""
        if self.is_playing:
            self.stop_playback()
        else:
            # Play selected station
            current_page = self.notebook.GetSelection()
            
            if current_page == 0:
                index = self.stations_list.GetFirstSelected()
                if index >= 0 and index < len(self.filtered_stations):
                    self.play_station(self.filtered_stations[index])
            else:
                index = self.favorites_list.GetFirstSelected()
                if index >= 0 and index < len(self.favorites):
                    self.current_favorite_index = index
                    self.play_station(self.favorites[index])
    
    def play_station(self, station):
        try:
            # Stop current playback
            if self.is_playing:
                self.stop_playback()
            
            self.current_station = station
            self.now_playing_label.SetLabel(f"Playing: {station.name} ({station.location})")
            self.stream_url_label.SetLabel(f"Stream URL: {station.url}")
            
            media = self.vlc_instance.media_new(station.url)
            buffer_size = self.settings.get('buffer_size', 1000)
            media.add_option(f':network-caching={buffer_size}')
            self.player.set_media(media)
            self.player.play()
            self.is_playing = True
            self.play_stop_btn.SetLabel("⏹ &Stop")
            self.set_status(f"Playing {station.name}")
            
        except Exception as e:
            wx.MessageBox(f"Error playing stream: {e}\n\nStream URL: {station.url}", 
                         "Playback Error", wx.OK | wx.ICON_ERROR)
            self.set_status(f"Error playing {station.name}")
    
    def stop_playback(self):
        """Stop playback"""
        if self.is_playing:
            self.player.stop()
            self.is_playing = False
        self.is_playing = False
        
        self.play_stop_btn.SetLabel("▶ &Play")
        self.now_playing_label.SetLabel("No station playing")
        self.stream_url_label.SetLabel("Stream URL: ")
        self.set_status("Stopped")
        
        if self.recording:
            self.stop_recording()
    
    def on_volume_change(self, event):
        """Handle volume slider change"""
        if not self.is_muted:
            self.volume = self.volume_slider.GetValue()
            self.player.audio_set_volume(self.volume)
            self.set_status(f"Volume: {self.volume}%")


    def on_mute_toggle(self, event):
        """Toggle mute"""
        self.is_muted = not self.is_muted
        if self.is_muted:
            self.player.audio_set_volume(0)
            self.mute_btn.SetLabel("Un&mute")
            self.set_status("Muted")
        else:
            self.player.audio_set_volume(self.volume)
            self.mute_btn.SetLabel("&Mute")
            self.set_status(f"Unmuted - Volume: {self.volume}%")
    
    def on_previous_favorite(self, event):
        """Play previous favorite"""
        if not self.favorites:
            wx.MessageBox("No favorites added yet!", "Info", wx.OK | wx.ICON_INFORMATION)
            return
        
        self.current_favorite_index = (self.current_favorite_index - 1) % len(self.favorites)
        self.play_station(self.favorites[self.current_favorite_index])
        
        self.favorites_list.Select(self.current_favorite_index)
        self.favorites_list.EnsureVisible(self.current_favorite_index)
    
    def on_next_favorite(self, event):
        """Play next favorite"""
        if not self.favorites:
            wx.MessageBox("No favorites added yet!", "Info", wx.OK | wx.ICON_INFORMATION)
            return
        
        self.current_favorite_index = (self.current_favorite_index + 1) % len(self.favorites)
        self.play_station(self.favorites[self.current_favorite_index])
        
        self.favorites_list.Select(self.current_favorite_index)
        self.favorites_list.EnsureVisible(self.current_favorite_index)
    
    def on_record(self, event):
        """Start/stop recording"""
        if not self.current_station:
            wx.MessageBox("Please select a station to record!", "Error", wx.OK | wx.ICON_ERROR)
            return
        
        if not self.recording:
            self.start_recording()
        else:
            self.stop_recording()
    
    def start_recording(self):
        """Start recording current stream"""
        if not self.current_station:
            return
        
        recordings_dir = Path(self.settings.get('recording_dir', str(Path.home() / "RadioRecordings")))
        recordings_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c for c in self.current_station.name if c.isalnum() or c in (' ', '-', '_')).strip()
        filename = recordings_dir / f"{safe_name}_{timestamp}.mp3"
        
        self.recorder = StreamRecorder(self.current_station.url, str(filename))
        self.recorder.start()
        self.recording = True
        
        self.record_btn.SetLabel("⏹ Stop Recording")
        self.set_status(f"Recording to: {filename}")
    
    def stop_recording(self):
        """Stop recording"""
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
        
        self.recording = False
        self.record_btn.SetLabel("⏺ Start Recording")
        self.set_status("Recording stopped")
    
    def add_to_favorites(self, station):
        """Add station to favorites"""
        for fav in self.favorites:
            if fav.url == station.url:
                wx.MessageBox("Station already in favorites!", "Info", wx.OK | wx.ICON_INFORMATION)
                return
        
        self.favorites.append(station)
        self.update_favorites_list()
        self.save_favorites()
        self.set_status(f"Added {station.name} to favorites")
    
    def remove_from_favorites(self, index):
        """Remove station from favorites"""
        if 0 <= index < len(self.favorites):
            station = self.favorites.pop(index)
            self.update_favorites_list()
            self.save_favorites()
            self.set_status(f"Removed {station.name} from favorites")
    def on_import_station(self, event):
        dlg = AddStationDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            new_station = dlg.get_station()
            if new_station:
                self.favorites.append(new_station)
                self.update_favorites_list()
                self.save_favorites()
                self.set_status(f"Added new station: {new_station.name}")
        pass
    
    def save_favorites(self):
        """Save favorites to file"""
        favorites_file = Path.home() / ".radio_favorites.json"
        try:
            data = []
            for fav in self.favorites:
                data.append({
                    'name': fav.name,
                    'url': fav.url,
                    'country': fav.country,
                    'countrycode': fav.countrycode,
                    'state': fav.state,
                    'language': fav.language,
                    'bitrate': fav.bitrate,
                    'codec': fav.codec,
                    'tags': fav.tags,
                    'favicon': fav.favicon,
                    'geo_lat': fav.geo_lat,
                    'geo_long': fav.geo_long
                })
            
            with open(favorites_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving favorites: {e}")
    
    def load_favorites(self):
        """Load favorites from file"""
        favorites_file = Path.home() / ".radio_favorites.json"
        if favorites_file.exists():
            try:
                with open(favorites_file, 'r') as f:
                    data = json.load(f)
                    self.favorites = [RadioStation(item) for item in data]
                    if hasattr(self, 'favorites_list'):
                        self.update_favorites_list()
            except Exception as e:
                print(f"Error loading favorites: {e}")

if __name__ == '__main__':
    app = wx.App()
    frame = RadioPlayerFrame()
    app.MainLoop()