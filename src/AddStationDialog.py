import wx
from radio_api import RadioBrowserAPI, RadioStation
import requests
class AddStationDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Add a custom station")
        self.is_stream_checked = False
        self.url = ""
        self.custom_name = ""
        self.station = RadioStation()
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(panel, label="Stream URL"), 0, wx.ALL, 5)
        self.url_text_box = wx.TextCtrl(panel, value = self.url)
        sizer.Add(self.url_text_box, 0, wx.ALL, 5)
        sizer.Add(wx.StaticText(panel, label = "Custom station name"), 0, wx.ALL, 5)
        self.station_name_textCTRL = wx.TextCtrl(panel, value = self.custom_name)
        sizer.Add(self.station_name_textCTRL, 0, wx.ALL, 5)
        check_btn = wx.Button(panel, label = "&Check stream")
        check_btn.Bind(wx.EVT_BUTTON, self.on_check)
        sizer.Add(check_btn, 0, wx.ALL, 5)
        button_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(wx.ID_OK)
        cancel_btn = wx.Button(wx.ID_CANCEL)
        button_sizer.AddButton(ok_btn)
        button_sizer.AddButton(cancel_btn)
        button_sizer.Realize()
        sizer.Add(button_sizer, 0, wx.ALL | wx.EXPAND, 5)
    def on_check(self, event):
        #Check if the stream URL is valid
        self.url = self.url_text_box.GetValue()
        self.custom_name = self.station_name_textCTRL.GetValue()
        def check():
            pass