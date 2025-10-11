import wx
import wx.adv
import requests
from datetime import datetime
import threading
import urllib.request
from pathlib import Path
import zipfile
import tempfile
import shutil
from packaging import version
import io
import time
import platform
import subprocess
import sys
import vlc
import accessible_output2.outputs.auto as auto
from stream_recorder import StreamRecorder
from radio_api import RadioStation, RadioBrowserAPI
o = auto.Auto()

APP_VERSION = "1.0.0"
UPDATE_URL = "https://gruiachiscop.dev/radio-browser-accessible/update.zip"


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, settings):
        super().__init__(parent, title="Settings", size=(500, 400))
        
        self.settings = settings.copy()
        
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Recording directory
        rec_box = wx.StaticBox(panel, label="Recording")
        rec_sizer = wx.StaticBoxSizer(rec_box, wx.VERTICAL)
        
        rec_dir_sizer = wx.BoxSizer(wx.HORIZONTAL)
        rec_dir_sizer.Add(wx.StaticText(panel, label="Directory:"), 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
        self.rec_dir_text = wx.TextCtrl(panel, value=self.settings.get('recording_dir', ''))
        rec_dir_sizer.Add(self.rec_dir_text, 1, wx.ALL, 5)
        
        browse_btn = wx.Button(panel, label="Browse...")
        browse_btn.Bind(wx.EVT_BUTTON, self.on_browse_dir)
        rec_dir_sizer.Add(browse_btn, 0, wx.ALL, 5)
        
        rec_sizer.Add(rec_dir_sizer, 0, wx.EXPAND)
        sizer.Add(rec_sizer, 0, wx.ALL|wx.EXPAND, 5)
        
        # Data source
        source_box = wx.StaticBox(panel, label="Data Source")
        source_sizer = wx.StaticBoxSizer(source_box, wx.VERTICAL)
        
        self.rb_radiobrowser = wx.RadioButton(panel, label="Radio Browser", style=wx.RB_GROUP)
        self.rb_onlineradiobox = wx.RadioButton(panel, label="Online Radio Box (experimental)")
        
        if self.settings.get('source', 'radiobrowser') == 'radiobrowser':
            self.rb_radiobrowser.SetValue(True)
        else:
            self.rb_onlineradiobox.SetValue(True)
        
        source_sizer.Add(self.rb_radiobrowser, 0, wx.ALL, 5)
        source_sizer.Add(self.rb_onlineradiobox, 0, wx.ALL, 5)
        sizer.Add(source_sizer, 0, wx.ALL|wx.EXPAND, 5)
        
        # Playback
        playback_box = wx.StaticBox(panel, label="Playback")
        playback_sizer = wx.StaticBoxSizer(playback_box, wx.VERTICAL)
        
        self.autoplay_cb = wx.CheckBox(panel, label="Auto-play on selection")
        self.autoplay_cb.SetValue(self.settings.get('autoplay', False))
        playback_sizer.Add(self.autoplay_cb, 0, wx.ALL, 5)
        
        buffer_sizer = wx.BoxSizer(wx.HORIZONTAL)
        buffer_sizer.Add(wx.StaticText(panel, label="Buffer size (ms):"), 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
        self.buffer_spin = wx.SpinCtrl(panel, value=str(self.settings.get('buffer_size', 1000)), 
                                        min=500, max=5000, initial=self.settings.get('buffer_size', 1000))
        buffer_sizer.Add(self.buffer_spin, 0, wx.ALL, 5)
        playback_sizer.Add(buffer_sizer, 0, wx.EXPAND)
        
        sizer.Add(playback_sizer, 0, wx.ALL|wx.EXPAND, 5)
        
        # Updates
        update_box = wx.StaticBox(panel, label="Updates")
        update_sizer = wx.StaticBoxSizer(update_box, wx.VERTICAL)
        
        self.check_updates_cb = wx.CheckBox(panel, label="Check for updates on startup")
        self.check_updates_cb.SetValue(self.settings.get('check_updates', True))
        update_sizer.Add(self.check_updates_cb, 0, wx.ALL, 5)
        
        check_now_btn = wx.Button(panel, label="Check for Updates Now")
        check_now_btn.Bind(wx.EVT_BUTTON, self.on_check_updates)
        update_sizer.Add(check_now_btn, 0, wx.ALL, 5)
        
        sizer.Add(update_sizer, 0, wx.ALL|wx.EXPAND, 5)
        
        # Buttons
        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(panel, wx.ID_OK)
        ok_btn.Bind(wx.EVT_BUTTON, self.on_ok)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL)
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        
        sizer.Add(btn_sizer, 0, wx.ALL|wx.EXPAND, 5)
        
        panel.SetSizer(sizer)
        self.Centre()
    
    def on_browse_dir(self, event):
        dlg = wx.DirDialog(self, "Choose recording directory", 
                          defaultPath=self.rec_dir_text.GetValue())
        if dlg.ShowModal() == wx.ID_OK:
            self.rec_dir_text.SetValue(dlg.GetPath())
        dlg.Destroy()
    
    def on_check_updates(self, event):
        self.GetParent().check_for_updates(manual=True)
    
    def on_ok(self, event):
        self.settings['recording_dir'] = self.rec_dir_text.GetValue()
        self.settings['source'] = 'radiobrowser' if self.rb_radiobrowser.GetValue() else 'onlineradiobox'
        self.settings['autoplay'] = self.autoplay_cb.GetValue()
        self.settings['buffer_size'] = self.buffer_spin.GetValue()
        self.settings['check_updates'] = self.check_updates_cb.GetValue()
        self.EndModal(wx.ID_OK)

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
        
        # Country code to continent mapping
        self.continent_map = {
            'Africa': ['DZ', 'AO', 'BJ', 'BW', 'BF', 'BI', 'CM', 'CV', 'CF', 'TD', 'KM', 'CG', 'CD', 'CI', 'DJ', 'EG', 'GQ', 'ER', 'ET', 'GA', 'GM', 'GH', 'GN', 'GW', 'KE', 'LS', 'LR', 'LY', 'MG', 'MW', 'ML', 'MR', 'MU', 'YT', 'MA', 'MZ', 'NA', 'NE', 'NG', 'RE', 'RW', 'SH', 'ST', 'SN', 'SC', 'SL', 'SO', 'ZA', 'SS', 'SD', 'SZ', 'TZ', 'TG', 'TN', 'UG', 'EH', 'ZM', 'ZW'],
            'Asia': ['AF', 'AM', 'AZ', 'BH', 'BD', 'BT', 'BN', 'KH', 'CN', 'GE', 'HK', 'IN', 'ID', 'IR', 'IQ', 'IL', 'JP', 'JO', 'KZ', 'KW', 'KG', 'LA', 'LB', 'MO', 'MY', 'MV', 'MN', 'MM', 'NP', 'KP', 'OM', 'PK', 'PS', 'PH', 'QA', 'SA', 'SG', 'KR', 'LK', 'SY', 'TW', 'TJ', 'TH', 'TL', 'TR', 'TM', 'AE', 'UZ', 'VN', 'YE'],
            'Europe': ['AX', 'AL', 'AD', 'AT', 'BY', 'BE', 'BA', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FO', 'FI', 'FR', 'DE', 'GI', 'GR', 'GG', 'HU', 'IS', 'IE', 'IM', 'IT', 'JE', 'XK', 'LV', 'LI', 'LT', 'LU', 'MK', 'MT', 'MD', 'MC', 'ME', 'NL', 'NO', 'PL', 'PT', 'RO', 'RU', 'SM', 'RS', 'SK', 'SI', 'ES', 'SJ', 'SE', 'CH', 'UA', 'GB', 'VA'],
            'North America': ['AI', 'AG', 'AW', 'BS', 'BB', 'BZ', 'BM', 'BQ', 'VG', 'CA', 'KY', 'CR', 'CU', 'CW', 'DM', 'DO', 'SV', 'GL', 'GD', 'GP', 'GT', 'HT', 'HN', 'JM', 'MQ', 'MX', 'MS', 'NI', 'PA', 'PM', 'PR', 'BL', 'KN', 'LC', 'MF', 'VC', 'SX', 'TT', 'TC', 'US', 'VI'],
            'South America': ['AR', 'BO', 'BR', 'CL', 'CO', 'EC', 'FK', 'GF', 'GY', 'PY', 'PE', 'SR', 'UY', 'VE'],
            'Oceania': ['AS', 'AU', 'CK', 'FJ', 'PF', 'GU', 'KI', 'MH', 'FM', 'NR', 'NC', 'NZ', 'NU', 'NF', 'MP', 'PW', 'PG', 'PN', 'WS', 'SB', 'TK', 'TO', 'TV', 'VU', 'WF'],
            'Antarctica': ['AQ', 'BV', 'TF', 'HM', 'GS']
        }
        
        # Settings
        self.settings = self.load_settings()
        
        # Audio playback using vlc (but simpler than python-vlc)
        # We'll use mpv or ffplay as subprocess
        self.is_playing = False
        self.is_muted = False
        self.volume = 0.7
        self.playback_process = None
        self.stream_thread = None
        self.stop_stream = False
        
        # Load favorites
        self.load_favorites()
        
        # Setup UI
        self.setup_ui()
        
        # Load initial data
        self.load_countries_and_languages()
        
        # Check for updates if enabled
        if self.settings.get('check_updates', True):
            wx.CallLater(1000, lambda: self.check_for_updates(manual=False))
        
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
        
        self.mute_btn = wx.Button(panel, label="🔊")
        self.mute_btn.Bind(wx.EVT_BUTTON, self.on_mute_toggle)
        volume_sizer.Add(self.mute_btn, 0, wx.ALL, 5)
        
        volume_sizer.Add(wx.StaticText(panel, label="Volume:"), 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
        
        self.volume_slider = wx.Slider(panel, value=70, minValue=0, maxValue=100, 
                                       style=wx.SL_HORIZONTAL|wx.SL_LABELS)
        self.volume_slider.Bind(wx.EVT_SLIDER, self.on_volume_change)
        volume_sizer.Add(self.volume_slider, 1, wx.ALL|wx.EXPAND, 5)
        
        main_sizer.Add(volume_sizer, 0, wx.ALL|wx.EXPAND, 5)
        control_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.load_btn = wx.Button(panel, label="Load Stations")
        self.load_btn.Bind(wx.EVT_BUTTON, self.on_load_stations)
        control_sizer.Add(self.load_btn, 0, wx.ALL, 5)
        
        self.play_stop_btn = wx.Button(panel, label="▶ Play")
        self.play_stop_btn.Bind(wx.EVT_BUTTON, self.on_play_stop_toggle)
        control_sizer.Add(self.play_stop_btn, 0, wx.ALL, 5)
        
        # Zapping controls
        control_sizer.Add(wx.StaticLine(panel, style=wx.LI_VERTICAL), 0, wx.EXPAND|wx.ALL, 5)
        
        self.prev_btn = wx.Button(panel, label="◀ Previous")
        self.prev_btn.Bind(wx.EVT_BUTTON, self.on_previous_favorite)
        control_sizer.Add(self.prev_btn, 0, wx.ALL, 5)
        
        self.next_btn = wx.Button(panel, label="Next ▶")
        self.next_btn.Bind(wx.EVT_BUTTON, self.on_next_favorite)
        control_sizer.Add(self.next_btn, 0, wx.ALL, 5)
        
        # Recording button
        control_sizer.Add(wx.StaticLine(panel, style=wx.LI_VERTICAL), 0, wx.EXPAND|wx.ALL, 5)
        
        self.record_btn = wx.Button(panel, label="⏺ Start Recording")
        self.record_btn.Bind(wx.EVT_BUTTON, self.on_record)
        control_sizer.Add(self.record_btn, 0, wx.ALL, 5)
        
        main_sizer.Add(control_sizer, 0, wx.ALL|wx.CENTER, 5)
        
        # Status bar with live region support
        self.status_bar = self.CreateStatusBar()
        self.status_bar.SetStatusText("Ready")
        
        # Live region for screen readers
        self.live_region = wx.Panel(panel)
        self.live_region.SetSize((0, 0))
        self.status_text = wx.StaticText(self.live_region, label="Ready", style=wx.ST_NO_AUTORESIZE)
        # Set ARIA live region
        if hasattr(self.status_text, 'SetName'):
            self.status_text.SetName("status")
        main_sizer.Add(self.live_region, 0, wx.ALL, 0)
        
        panel.SetSizer(main_sizer)
    
    def prompt_media_player_install(self):
        """Prompt user to install media player if none found"""
        dlg = InstallDialog(self)
        result = dlg.ShowModal()
        dlg.Destroy()
        
        if result == wx.ID_OK:
            # Check again after installation
            if MediaPlayerInstaller.check_player_available():
                self.set_status("Media player installed successfully")
            else:
                wx.MessageBox(
                    "Media player still not found. Please restart the application after manual installation.",
                    "Installation Issue", wx.OK | wx.ICON_WARNING
                )
        else:
            wx.MessageBox(
                "Without a media player, you won't be able to play radio streams.\n"
                "The application will continue, but playback will not work.",
                "Warning", wx.OK | wx.ICON_WARNING
            )
    
    def set_status(self, message):
        """Set status bar text and announce to screen readers via live region"""
        self.status_bar.SetStatusText(message)
        # Update live region for screen readers
        self.status_text.SetLabel(message)
        # Force update
        self.status_text.Update()
    
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
            'check_updates': True
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
    
    def check_for_updates(self, manual=False):
        """Check for updates"""
        def check():
            try:
                response = requests.get(UPDATE_URL, stream=True, timeout=5)
                if response.status_code == 200:
                    # Check version from a version.txt in the zip
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
                        tmp.write(response.content)
                        tmp_path = tmp.name
                    
                    try:
                        with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
                            if 'version.txt' in zip_ref.namelist():
                                version_content = zip_ref.read('version.txt').decode('utf-8').strip()
                                if version.parse(version_content) > version.parse(APP_VERSION):
                                    wx.CallAfter(self.show_update_dialog, version_content, tmp_path)
                                elif manual:
                                    wx.CallAfter(wx.MessageBox, "You have the latest version!", 
                                               "No Updates", wx.OK | wx.ICON_INFORMATION)
                            elif manual:
                                wx.CallAfter(wx.MessageBox, "Unable to check version.", 
                                           "Update Check", wx.OK | wx.ICON_WARNING)
                    finally:
                        if os.path.exists(tmp_path) and not manual:
                            os.unlink(tmp_path)
                            
            except Exception as e:
                print(f"Update check error: {e}")
                if manual:
                    wx.CallAfter(wx.MessageBox, f"Unable to check for updates: {e}", 
                               "Update Error", wx.OK | wx.ICON_ERROR)
        
        thread = threading.Thread(target=check)
        thread.daemon = True
        thread.start()
    
    def show_update_dialog(self, new_version, zip_path):
        """Show update available dialog"""
        msg = f"A new version ({new_version}) is available!\nCurrent version: {APP_VERSION}\n\nWould you like to download it?"
        dlg = wx.MessageDialog(self, msg, "Update Available", wx.YES_NO | wx.ICON_INFORMATION)
        if dlg.ShowModal() == wx.ID_YES:
            # Open download location
            import webbrowser
            webbrowser.open("https://gruiachiscop.dev/radio-browser-accessible/")
        dlg.Destroy()
        
        if os.path.exists(zip_path):
            os.unlink(zip_path)
    
    def load_countries_and_languages(self):
        """Load countries and languages into dropdowns"""
        self.set_status("Loading countries and languages...")
        
        def load_data():
            countries = self.api.get_countries()
            languages = self.api.get_languages()
            continents = self.api.get_continents()
            wx.CallAfter(self.populate_filters, countries, languages, continents)
        
        thread = threading.Thread(target=load_data)
        thread.daemon = True
        thread.start()
    
    def populate_filters(self, countries, languages, continents):
        """Populate filter dropdowns"""
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
        for continent in continents:
            self.continent_choice.Append(continent)
        self.continent_choice.SetSelection(0)
        
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
            self.set_status("Searching stations...")
            
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
        """Play a radio station using subprocess with ffplay or mpv"""
        try:
            # Stop current playback
            if self.is_playing:
                self.stop_playback()
            
            self.current_station = station
            self.now_playing_label.SetLabel(f"Playing: {station.name} ({station.location})")
            self.stream_url_label.SetLabel(f"Stream URL: {station.url}")
            
            # Try to use available media players
            player_cmd = None
            
            # Try ffplay (comes with ffmpeg)
            if shutil.which('ffplay'):
                volume_val = int(self.volume * 100)
                player_cmd = ['ffplay', '-nodisp', '-autoexit', '-volume', str(volume_val), station.url]
            # Try mpv
            elif shutil.which('mpv'):
                volume_val = int(self.volume * 100)
                player_cmd = ['mpv', '--no-video', '--volume=' + str(volume_val), station.url]
            # Try cvlc (VLC command line)
            elif shutil.which('cvlc'):
                volume_val = int(self.volume * 256)  # VLC uses 0-256
                player_cmd = ['cvlc', '--no-video', '--volume', str(volume_val), station.url]
            else:
                # Prompt to install
                dlg = wx.MessageDialog(
                    self,
                    "No media player found. Would you like to install FFmpeg now?",
                    "Media Player Required",
                    wx.YES_NO | wx.ICON_QUESTION
                )
                if dlg.ShowModal() == wx.ID_YES:
                    self.prompt_media_player_install()
                dlg.Destroy()
                return
            
            # Start playback process
            self.playback_process = subprocess.Popen(
                player_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            self.is_playing = True
            self.play_stop_btn.SetLabel("⏹ Stop")
            self.set_status(f"Playing {station.name}")
            
            # Monitor playback in thread
            def monitor():
                if self.playback_process:
                    self.playback_process.wait()
                    if self.is_playing:
                        wx.CallAfter(self.set_status, "Playback ended")
                        self.is_playing = False
                        wx.CallAfter(self.play_stop_btn.SetLabel, "▶ Play")
            
            threading.Thread(target=monitor, daemon=True).start()
            
        except Exception as e:
            wx.MessageBox(f"Error playing stream: {e}\n\nStream URL: {station.url}", 
                         "Playback Error", wx.OK | wx.ICON_ERROR)
            self.set_status(f"Error playing {station.name}")
    
    def stop_playback(self):
        """Stop playback"""
        if self.is_playing and self.playback_process:
            try:
                self.playback_process.terminate()
                self.playback_process.wait(timeout=2)
            except:
                try:
                    self.playback_process.kill()
                except:
                    pass
            self.playback_process = None
            self.is_playing = False
        
        self.play_stop_btn.SetLabel("▶ Play")
        self.now_playing_label.SetLabel("No station playing")
        self.stream_url_label.SetLabel("Stream URL: ")
        self.set_status("Stopped")
        
        if self.recording:
            self.stop_recording()
    
    def on_volume_change(self, event):
        """Handle volume slider change"""
        if not self.is_muted:
            self.volume = self.volume_slider.GetValue() / 100.0
            # If playing, restart with new volume
            if self.is_playing and self.current_station:
                current = self.current_station
                self.stop_playback()
                wx.CallLater(100, lambda: self.play_station(current))
            self.set_status(f"Volume: {int(self.volume * 100)}%")
    
    def on_mute_toggle(self, event):
        """Toggle mute"""
        self.is_muted = not self.is_muted
        if self.is_muted:
            # Stop playback to mute
            if self.is_playing and self.playback_process:
                self.playback_process.terminate()
            self.mute_btn.SetLabel("🔇")
            self.set_status("Muted")
        else:
            # Resume playback
            if self.current_station:
                self.play_station(self.current_station)
            self.mute_btn.SetLabel("🔊")
            self.set_status(f"Unmuted - Volume: {int(self.volume * 100)}%")
    
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