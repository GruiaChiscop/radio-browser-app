import wx
import wx.adv

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
        #self.GetParent().updater.check_for_updates(True)
        old_parent_window = self.GetParent().updater.parent_window
        self.GetParent().updater.parent_window = self
        self.GetParent().updater.update(True)
        self.GetParent().updater.parent_window = old_parent_window
    
    def on_ok(self, event):
        self.settings['recording_dir'] = self.rec_dir_text.GetValue()
        self.settings['source'] = 'radiobrowser' if self.rb_radiobrowser.GetValue() else 'onlineradiobox'
        self.settings['autoplay'] = self.autoplay_cb.GetValue()
        self.settings['buffer_size'] = self.buffer_spin.GetValue()
        self.settings['check_updates'] = self.check_updates_cb.GetValue()
        self.EndModal(wx.ID_OK)
