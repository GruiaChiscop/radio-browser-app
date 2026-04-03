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
from SettingsDialog import SettingsDialog
from AddStationDialog import AddStationDialog
import Updater as updater
import accessible_output2.outputs.auto as auto
from radio_player import RadioPlayer
o = auto.Auto()
if o.is_system_output():
    o = None

APP_VERSION = "1.1.0"
UPDATE_URL = "https://gruiachiscop.dev/radio-browser-accessible/update/version.json"
APP_DATA_DIR = os.environ.get('APPDATA') if platform.system() == 'Windows' else str(Path.home())

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
        self.continent_map = self.api.get_continents()
        # Settings
        self.settings = self.load_settings()
        
        self.is_playing = False
        self.is_muted = False
        self.volume = 1.0
        self.stop_stream = False
        # Load favorites
        self.load_favorites()
        
        # Setup UI
        self.setup_ui()
        self.radio = RadioPlayer()
        self.radio.metadata_callback=lambda title: self.set_status(f"Now Playing: {title}"), 
        self.api.on_servers_set = lambda message: self.set_status(message)
        self.api.on_error = lambda message: self.set_status(message)
        self.radio.set_metadata_callback(lambda title: self.set_status(f"Now Playing: {title}"))
        self.api._get_base_url()
        #initialise the updater
        self.updater = updater.AppUpdater(APP_VERSION, UPDATE_URL, "radio-browser-accessible", self)
        if self.settings.get('check_updates', True):
            wx.CallAfter(self.updater.update)
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
        add_item = file_menu.Append(wx.ID_ADD, "Add Custom Station...\tCtrl+N", "Add a custom radio station")
        self.Bind(wx.EVT_MENU, self.on_import_station, add_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        menubar.Append(file_menu, "&File")
        
        help_menu = wx.Menu()
        about_item = help_menu.Append(wx.ID_ABOUT, "About", "About this application")
        help_item = help_menu.Append(wx.ID_HELP, "Help", "Help topics")
        self.Bind(wx.EVT_MENU, None, help_item) # Note: Ensure you have a handler for this
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
        
        # Choice Filters (Country, Language, Continent)
        for label, attr in [("Country:", "country_choice"), ("Language:", "language_choice"), ("Continent:", "continent_choice")]:
            filter_sizer.Add(wx.StaticText(panel, label=label), 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
            choice = wx.Choice(panel, size=(150, -1))
            setattr(self, attr, choice)
            choice.Bind(wx.EVT_CHOICE, self.on_filter_change)
            filter_sizer.Add(choice, 0, wx.ALL, 5)

        self.best_bitrate_only_cb = wx.CheckBox(panel, label="Best bitrate only")
        self.best_bitrate_only_cb.SetValue(self.settings.get('best_bitrate_only', True))
        self.best_bitrate_only_cb.Bind(wx.EVT_CHECKBOX, self.on_filter_change)
        filter_sizer.Add(self.best_bitrate_only_cb, 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)

        # Buttons
        self.clear_btn = wx.Button(panel, label="Clear Filters")
        self.clear_btn.Enable(False)
        self.clear_btn.Bind(wx.EVT_BUTTON, self.on_clear_filters)
        filter_sizer.Add(self.clear_btn, 0, wx.ALL, 5)
        
        self.load_more_btn = wx.Button(panel, label="Load More Stations")
        self.load_more_btn.Bind(wx.EVT_BUTTON, self.on_load_more_stations)
        self.load_more_btn.Enable(False)
        filter_sizer.Add(self.load_more_btn, 0, wx.ALL, 5)
        
        main_sizer.Add(filter_sizer, 0, wx.ALL|wx.EXPAND, 5)
        
        # Notebook
        self.notebook = wx.Notebook(panel)
        
        # Helper to create list tabs
        def create_list_tab(parent, label):
            p = wx.Panel(parent)
            sz = wx.BoxSizer(wx.VERTICAL)
            sz.Add(wx.StaticText(p, label=label), 0, wx.ALL, 5)
            lc = wx.ListCtrl(p, style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
            lc.AppendColumn("Station Name", width=250)
            lc.AppendColumn("Location", width=220)
            lc.AppendColumn("Language", width=120)
            lc.AppendColumn("Bitrate", width=90)
            sz.Add(lc, 1, wx.EXPAND|wx.ALL, 5)
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
        main_sizer.Add(self.notebook, 1, wx.ALL|wx.EXPAND, 5)
        
        # Now playing section
        now_playing_box = wx.StaticBox(panel, label="Now Playing")
        now_playing_sizer = wx.StaticBoxSizer(now_playing_box, wx.VERTICAL)
        
        self.now_playing_label = wx.StaticText(panel, label="No station playing")
        now_playing_sizer.Add(self.now_playing_label, 0, wx.ALL, 5)
        
        self.stream_url_label = wx.StaticText(panel, label="Stream URL: ")
        self.stream_url_box = wx.TextCtrl(panel, value="", style=wx.TE_READONLY)
        now_playing_sizer.Add(self.stream_url_label, 0, wx.ALL, 5)
        now_playing_sizer.Add(self.stream_url_box, 0, wx.ALL|wx.EXPAND, 5)
        
        main_sizer.Add(now_playing_sizer, 0, wx.ALL|wx.EXPAND, 5)
        
        # Volume control
        volume_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.mute_btn = wx.Button(panel, label="&Mute")
        self.mute_btn.Bind(wx.EVT_BUTTON, self.on_mute_toggle)
        volume_sizer.Add(self.mute_btn, 0, wx.ALL, 5)
        
        volume_sizer.Add(wx.StaticText(panel, label="&Volume:"), 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
        self.volume_slider = wx.Slider(panel, value=70, minValue=0, maxValue=100)
        self.volume_slider.Bind(wx.EVT_SLIDER, self.on_volume_change)
        volume_sizer.Add(self.volume_slider, 1, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
        
        main_sizer.Add(volume_sizer, 0, wx.ALL|wx.EXPAND, 5)
    
        # Control Buttons
        control_sizer = wx.BoxSizer(wx.HORIZONTAL)
        buttons = [
            ("&Load Stations", "load_btn", self.on_load_stations),
            ("&Play", "play_stop_btn", self.on_play_stop_toggle),
            (" P&revious", "prev_btn", self.on_previous_favorite),
            ("&Next", "next_btn", self.on_next_favorite),
            ("S&tart Recording", "record_btn", self.on_record),
            ("&Add new station", "import_btn", self.on_import_station)
        ]
        
        for label, attr, handler in buttons:
            btn = wx.Button(panel, label=label)
            setattr(self, attr, btn)
            btn.Bind(wx.EVT_BUTTON, handler)
            control_sizer.Add(btn, 0, wx.ALL, 5)
            # Add a visual separator after 'Play' and 'Next'
            if label in ["&Play", "&Next"]:
                control_sizer.Add(wx.StaticLine(panel, style=wx.LI_VERTICAL), 0, wx.EXPAND|wx.ALL, 5)
    
        main_sizer.Add(control_sizer, 0, wx.ALL|wx.CENTER, 5)
        
        # Status bar
        self.status_bar = self.CreateStatusBar()
        self.status_bar.SetStatusText("Ready")
        
        # Finalise Layout
        panel.SetSizer(main_sizer)
        main_sizer.Fit(self)
        self.Layout()
        if o:
            self.Bind(wx.EVT_CHAR_HOOK, self.on_handle_key_press)

    def set_status(self, message):
        """Set status bar text and announce to screen readers via live region"""
        self.status_bar.SetStatusText(message)
        # Update live region for screen readers
        #self.status_text.SetLabel(message)
        #since the accessible live regions don't seem to work, we'll use the accessible-output2 module for speech, if available
        try:
            o.output(message)
        except Exception   :
            pass
    
    def on_settings(self, event):
        """Open settings dialog"""
        dlg = SettingsDialog(self, self.settings)
        if dlg.ShowModal() == wx.ID_OK:
            self.settings = dlg.settings
            self.settings['best_bitrate_only'] = self.best_bitrate_only_cb.GetValue()
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
            self.radio.stop()
        if self.recording:
            self.stop_recording()
        self.Close()
    
    def load_settings(self):
        """Load settings from file"""
        settings_file = APP_DATA_DIR+"/.radio_settings.json"
        default_settings = {
            'recording_dir': str(Path.home() / "RadioRecordings"),
            'source': 'radiobrowser',
            'autoplay': False,
            'buffer_size': 1000,
            'check_updates': True,
            'volume': 70,
            'best_bitrate_only': True
        }
        
        if os.path.exists(settings_file):
            try:
                with open(settings_file, 'r') as f:
                    loaded = json.load(f)
                    default_settings.update(loaded)
            except Exception as e:
                print(f"Error loading settings: {e}")
        
        return default_settings
    
    def save_settings(self):
        """Save settings to file"""
        settings_file = os.path.join(APP_DATA_DIR, ".radio_settings.json")
        try:
            with open(settings_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            wx.MessageBox(f"Error saving settings: {e}", "Error", wx.OK | wx.ICON_ERROR)
    
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
        # make it async
        t = threading.Thread(target=populate)
        t.daemon = True
        t.start()
        self.set_status("Ready - Click 'Load Stations' to start")
    
    def on_load_stations(self, event):
        """Load stations from API"""
        self.set_status("Loading stations...")
        self.load_btn.Enable(False)
        self.current_offset = 0
        
        def load():
            self.stations = self.api.get_stations(best_bitrate_only=self.best_bitrate_only_cb.GetValue())
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
                limit=self.stations_per_page,
                order='bitrate' if self.best_bitrate_only_cb.GetValue() else 'votes',
                best_bitrate_only=self.best_bitrate_only_cb.GetValue(),
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
        self.update_favorites_list()
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
                    limit=self.stations_per_page,
                    order='bitrate' if self.best_bitrate_only_cb.GetValue() else 'votes',
                    best_bitrate_only=self.best_bitrate_only_cb.GetValue(),
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
            if continent != "All" and continent in self.continent_map:
                continent_codes = self.continent_map[continent]
                self.filtered_stations = [s for s in self.filtered_stations if s.countrycode in continent_codes]
            if self.best_bitrate_only_cb.GetValue():
                self.filtered_stations = self.api._remove_duplicates_keep_highest_bitrate(self.filtered_stations)
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
            self.stations_list.SetItem(index, 1, station.location)
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
            self.favorites_list.SetItem(index, 1, station.location)
            self.favorites_list.SetItem(index, 2, station.language)
            self.favorites_list.SetItem(index, 3, f"{station.bitrate} kbps")
    
    def on_filter_change(self, event):
        """Handle filter change"""
        self.settings['best_bitrate_only'] = self.best_bitrate_only_cb.GetValue()
        if self.stations:
            self.apply_filters()
            self.clear_btn.Enable(True)
    
    def on_clear_filters(self, event):
        """Clear all filters"""
        self.search_ctrl.SetValue("")
        self.country_choice.SetSelection(0)
        self.language_choice.SetSelection(0)
        self.continent_choice.SetSelection(0)
        self.best_bitrate_only_cb.SetValue(self.settings.get('best_bitrate_only', True))
        self.current_offset = 0
        self.has_more_stations = False
        self.load_more_btn.Enable(False)
        self.clear_btn.Enable(False)
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
        add_fav_item = menu.Append(wx.ID_ANY, "Add to Favourites")
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
            self.current_station = station
            self.now_playing_label.SetLabel(f"Playing: {station.name} ({station.location})")
            self.stream_url_box.SetValue(station.url)
            if self.is_playing:
                self.stop_playback()
                
            self.radio.play(station.url)
            self.is_playing = True
            self.play_stop_btn.SetLabel("&Stop")
            self.set_status(f"Playing {station.name}")
        
    def stop_playback(self):
        """Stop playback"""
        if self.radio or self.is_playing:
            self.radio.stop()
            self.is_playing = False
            self.play_stop_btn.SetLabel("&Play")
            self.now_playing_label.SetLabel("No station playing")
            self.stream_url_box.SetValue("")
            self.set_status("Stopped")
        
        if self.recording:
            self.stop_recording()
    
    def on_volume_change(self, event):
        """Handle volume slider change"""
        if not self.is_muted:
            self.volume = self.volume_slider.GetValue()/100.0
            self.radio.set_volume(self.volume)
            #self.set_status(f"Volume: {self.volume}%")


    def on_mute_toggle(self, event):
        """Toggle mute"""
        self.is_muted = not self.is_muted
        if self.is_muted:
            self.radio.set_volume(0.0)
            self.mute_btn.SetLabel("Un&mute")
            self.set_status("Muted")
        else:
            self.radio.set_volume(self.volume)
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
        
        self.record_btn.SetLabel("Stop Recording")
        self.set_status(f"Recording to: {filename}")
    
    def stop_recording(self):
        """Stop recording"""
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
        
        self.recording = False
        self.record_btn.SetLabel("Start Recording")
        self.set_status(f"Recording stopped and saved to {self.settings.get('recording_dir', str(Path.home() / 'RadioRecordings'))}")
    
    def add_to_favorites(self, station):
        """Add station to favorites"""
        for fav in self.favorites:
            if fav.url == station.url:
                wx.MessageBox("Station already in favourites!", "Info", wx.OK | wx.ICON_INFORMATION)
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
            self.set_status(f"Removed {station.name} from favourites")
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
        favorites_file = APP_DATA_DIR+"/.radio_favorites.json"
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
                    'geo_long': fav.geo_long,
                    'city': getattr(fav, 'city', ''),
                    'location': fav.location
                })
            
            with open(favorites_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving favorites: {e}")
    
    def load_favorites(self):
        """Load favorites from file"""
        favorites_file = APP_DATA_DIR+"/.radio_favorites.json"
        if os.path.exists(favorites_file):
            try:
                with open(favorites_file, 'r') as f:
                    data = json.load(f)
                    self.favorites = [RadioStation(item) for item in data]
                    if hasattr(self, 'favorites_list'):
                        self.update_favorites_list()
            except Exception as e:
                print(f"Error loading favorites: {e}")
    def on_handle_key_press(self, event: wx.KeyEvent):
        """Handle key press events for accessibility"""
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_F1:
            self.on_about(None)
        elif keycode==wx.WXK_F2:
            o.output(f"{len(self.favorites)} stations are in favourites")
        elif keycode == wx.WXK_F3:
            o.output(self.GetStatusBar().GetStatusText())
        else:
            event.Skip()

if __name__ == '__main__':
    app = wx.App()
    frame = RadioPlayerFrame()
    app.MainLoop()
