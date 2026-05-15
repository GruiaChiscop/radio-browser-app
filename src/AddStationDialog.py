import wx
<<<<<<< HEAD
from radio_api import RadioBrowserAPI, RadioStation
from streamChecker import StreamChecker
=======

from radio_api import RadioStation
from StreamChecker import StreamChecker


>>>>>>> claude/happy-volhard-12d9c0
class AddStationDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Add a custom station")
        self.is_stream_checked = False
        self.url = ""
        self.station = RadioStation(None, source="custom")

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(panel, label="Stream URL"), 0, wx.ALL, 5)
        self.url_text_box = wx.TextCtrl(panel, value=self.url)
        sizer.Add(self.url_text_box, 0, wx.ALL | wx.EXPAND, 5)

        sizer.Add(wx.StaticText(panel, label="Custom station name"), 0, wx.ALL, 5)
        self.station_name_ctrl = wx.TextCtrl(panel, value="")
        sizer.Add(self.station_name_ctrl, 0, wx.ALL | wx.EXPAND, 5)

        check_btn = wx.Button(panel, label="&Check stream")
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

        panel.SetSizer(sizer)
        sizer.Fit(self)
        self.Centre()

    def on_check(self, event):
        self.url = self.url_text_box.GetValue().strip()
        if not self.url:
            wx.MessageBox("Please enter a stream URL.", "Warning", wx.OK | wx.ICON_WARNING)
            return
        checker = StreamChecker()
        result = checker.is_valid_stream(self.url)
        if result["valid"]:
            self.is_stream_checked = True
            wx.MessageBox(
                f"Stream is valid!\nType: {result.get('stream_type', 'Unknown')}",
                "Success",
                wx.OK | wx.ICON_INFORMATION,
            )
        else:
            self.is_stream_checked = False
            wx.MessageBox(
                f"Stream check failed: {result.get('reason', 'Unknown error')}",
                "Invalid Stream",
                wx.OK | wx.ICON_ERROR,
            )

    def on_ok(self, event):
        if not self.is_stream_checked:
            wx.MessageBox(
                "Please check the stream before adding the station.",
                "Warning",
                wx.OK | wx.ICON_WARNING,
            )
            return
        custom_name = self.station_name_ctrl.GetValue().strip()
        self.station.url = self.url
        self.station.name = f"Custom: {custom_name}" if custom_name else "Custom Station"
        wx.MessageBox(
            "Station added successfully. You'll find it in your Favourites list.",
            "Success",
            wx.OK | wx.ICON_INFORMATION,
        )
        self.EndModal(wx.ID_OK)

    def on_cancel(self, event):
        self.EndModal(wx.ID_CANCEL)

    def get_station(self):
        if self.is_stream_checked:
            return self.station
        return None
