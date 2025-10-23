import wx
from radio_api import RadioBrowserAPI, RadioStation
from StreamChecker import StreamChecker
class AddStationDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Add a custom station")
        self.is_stream_checked = False
        self.url = ""
        self.custom_name = ""
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
        ok_btn = wx.Button(panel, wx.ID_OK)
        ok_btn.Bind(wx.EVT_BUTTON, self.on_ok)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL)
        cancel_btn.Bind(wx.EVT_BUTTON, self.on_cancel)
        button_sizer.AddButton(ok_btn)
        button_sizer.AddButton(cancel_btn)
        button_sizer.Realize()
        sizer.Add(button_sizer, 0, wx.ALL | wx.EXPAND, 5)
    def on_check(self, event):
        checker = StreamChecker()
        self.url = self.url_text_box.GetValue()
        result= checker.is_valid_stream(self.url)
        if result['valid']:
            self.is_stream_checked = True
            message = f"{result.__str__()}"
            wx.MessageBox(f"Stream is valid! {message}", "Success", wx.OK | wx.ICON_INFORMATION)
        else:
            self.is_stream_checked = False
            wx.MessageBox("Stream is not valid. Please check the URL and try again.", "Error", wx.OK | wx.ICON_ERROR)
        event.Skip()
    def on_ok(self, event):
        if not self.is_stream_checked:
            wx.MessageBox("Please check the stream before adding the station.", "Warning", wx.OK | wx.ICON_WARNING)
            return
        self.custom_name = self.station_name_textCTRL.GetValue()
        if self.custom_name:
            self.station.name = f"Custom station: {self.custom_name}"
        else:
            self.station.name = "Custom Station"
            wx.MessageBox("The stream was added successfully. You'll find it in your favourites list", "Success", wx.OK | wx.ICON_INFORMATION)
        self.EndModal(wx.ID_OK)
    def on_cancel(self, event):
        self.EndModal(wx.ID_CANCEL)
    def get_station(self):
        if self.is_stream_checked:
            return self.station
        return None