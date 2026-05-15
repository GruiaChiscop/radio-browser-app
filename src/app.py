import wx


class RadioBrowserApp(wx.App):
    def OnInit(self):
        from radio_browser import RadioPlayerFrame

        # Prevent multiple instances
        self._instance_checker = wx.SingleInstanceChecker("RadioBrowserPlayer")
        if self._instance_checker.IsAnotherRunning():
            wx.MessageBox(
                "Radio Browser Player is already running.",
                "Already Running",
                wx.OK | wx.ICON_INFORMATION,
            )
            return False

        self.frame = RadioPlayerFrame()
        return True


if __name__ == "__main__":
    app = RadioBrowserApp()
    app.MainLoop()
