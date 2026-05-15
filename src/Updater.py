import wx
import requests
import json
import os
import sys
import shutil
import tempfile
import subprocess
import platform
import hashlib
from pathlib import Path
from typing import Optional, Callable
from threading import Thread
import time


class UpdateInfo:
    def __init__(self, version: str, download_url: str, changelog: str,
                 size: int = 0, checksum: str = "", required: bool = False):
        self.version = version
        self.download_url = download_url
        self.changelog = changelog
        self.size = size
        self.checksum = checksum
        self.required = required


class ChangelogDialog(wx.Dialog):
    def __init__(self, parent, update_info: UpdateInfo, current_version: str):
        super().__init__(parent, title="Update Available",
                         size=(620, 520),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.update_info = update_info
        self.current_version = current_version
        self._create_ui()
        self.Centre()

    def _create_ui(self):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(panel, label="A new version is available!")
        font = title.GetFont()
        font = font.Bold()
        font.SetPointSize(font.GetPointSize() + 3)
        title.SetFont(font)
        sizer.Add(title, 0, wx.ALL, 10)

        version_text = (
            f"Current Version: {self.current_version}\n"
            f"New Version: {self.update_info.version}"
        )
        sizer.Add(wx.StaticText(panel, label=version_text), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        if self.update_info.size > 0:
            size_mb = self.update_info.size / (1024 * 1024)
            sizer.Add(
                wx.StaticText(panel, label=f"Download Size: {size_mb:.2f} MB"),
                0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10,
            )

        lbl = wx.StaticText(panel, label="What's New:")
        lbl.SetFont(lbl.GetFont().Bold())
        sizer.Add(lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        changelog_ctrl = wx.TextCtrl(
            panel, value=self.update_info.changelog,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
        )
        sizer.Add(changelog_ctrl, 1, wx.ALL | wx.EXPAND, 10)

        if self.update_info.required:
            warn = wx.StaticText(
                panel,
                label="This is a required update. The application may not work without it.",
            )
            warn.SetForegroundColour(wx.Colour(200, 0, 0))
            sizer.Add(warn, 0, wx.ALL, 10)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        if not self.update_info.required:
            skip_btn = wx.Button(panel, wx.ID_CANCEL, "Skip This Version")
            btn_sizer.Add(skip_btn, 0, wx.RIGHT, 5)
            later_btn = wx.Button(panel, wx.ID_NO, "Remind Me Later")
            btn_sizer.Add(later_btn, 0, wx.RIGHT, 5)

        update_btn = wx.Button(panel, wx.ID_OK, "Update Now")
        update_btn.SetDefault()
        btn_sizer.Add(update_btn, 0)
        sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        panel.SetSizer(sizer)


class DownloadProgressDialog(wx.Dialog):
    def __init__(self, parent, title="Downloading Update"):
        super().__init__(parent, title=title,
                         size=(520, 220),
                         style=wx.DEFAULT_DIALOG_STYLE)
        self.cancelled = False
        self._create_ui()
        self.Centre()

    def _create_ui(self):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.status_label = wx.StaticText(panel, label="Preparing download…")
        sizer.Add(self.status_label, 0, wx.ALL | wx.EXPAND, 10)

        self.progress_bar = wx.Gauge(panel, range=100)
        sizer.Add(self.progress_bar, 0, wx.ALL | wx.EXPAND, 10)

        self.info_label = wx.StaticText(panel, label="")
        sizer.Add(self.info_label, 0, wx.ALL | wx.EXPAND, 10)

        self.cancel_btn = wx.Button(panel, wx.ID_CANCEL, "Cancel")
        self.cancel_btn.Bind(wx.EVT_BUTTON, self.on_cancel)
        sizer.Add(self.cancel_btn, 0, wx.ALL | wx.ALIGN_CENTER, 10)

        panel.SetSizer(sizer)

    def update_progress(self, percent: float, downloaded: int, total: int, speed: float):
        wx.CallAfter(self._update_ui, percent, downloaded, total, speed)

    def _update_ui(self, percent, downloaded, total, speed):
        self.progress_bar.SetValue(int(percent))
        dl_mb = downloaded / (1024 * 1024)
        tot_mb = total / (1024 * 1024)
        spd_mb = speed / (1024 * 1024)
        self.status_label.SetLabel(f"Downloading update… {percent:.1f}%")
        self.info_label.SetLabel(f"{dl_mb:.2f} MB / {tot_mb:.2f} MB  |  {spd_mb:.2f} MB/s")

    def update_status(self, message: str):
        wx.CallAfter(self.status_label.SetLabel, message)

    def on_cancel(self, event):
        self.cancelled = True
        self.cancel_btn.Enable(False)
        self.status_label.SetLabel("Cancelling…")


class AppUpdater:
    """
    Checks for updates via the GitHub Releases API and installs them.

    Expected URL format:
        https://api.github.com/repos/<owner>/<repo>/releases/latest

    Falls back to the legacy custom JSON format if "tag_name" is absent.
    """

    def __init__(self, current_version: str, update_url: str,
                 app_name: str = "Application",
                 parent_window: Optional[wx.Window] = None):
        self.current_version = current_version
        self.update_url = update_url
        self.app_name = app_name
        self.parent_window = parent_window
        self.temp_dir = tempfile.mkdtemp(prefix="app_update_")

    # ------------------------------------------------------------------
    # Update check
    # ------------------------------------------------------------------

    def check_for_updates(self, show_no_update_dialog: bool = False) -> Optional[UpdateInfo]:
        try:
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": f"{self.app_name}/{self.current_version}",
            }
            response = requests.get(self.update_url, headers=headers, timeout=12)
            response.raise_for_status()
            data = response.json()

            # GitHub Releases API response
            if "tag_name" in data:
                return self._parse_github_release(data, show_no_update_dialog)

            # Legacy custom JSON format
            return self._parse_legacy_format(data, show_no_update_dialog)

        except requests.RequestException as e:
            if show_no_update_dialog and self.parent_window:
                wx.MessageBox(
                    f"Failed to check for updates:\n{e}",
                    "Update Check Failed",
                    wx.OK | wx.ICON_ERROR,
                    self.parent_window,
                )
        except Exception as e:
            if show_no_update_dialog and self.parent_window:
                wx.MessageBox(
                    f"Error checking for updates:\n{e}",
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                    self.parent_window,
                )
        return None

    def _parse_github_release(self, data: dict, show_no_update: bool) -> Optional[UpdateInfo]:
        raw_tag = data.get("tag_name", "")
        latest_version = raw_tag.lstrip("vV")

        if self._compare_versions(latest_version, self.current_version) <= 0:
            if show_no_update and self.parent_window:
                wx.MessageBox(
                    f"You are running the latest version ({self.current_version}).",
                    "No Updates Available",
                    wx.OK | wx.ICON_INFORMATION,
                    self.parent_window,
                )
            return None

        # Pick the best asset for the current platform
        system = platform.system()
        assets = data.get("assets", [])
        download_url = ""
        size = 0
        ext_map = {"Windows": ".exe", "Darwin": ".dmg", "Linux": ".AppImage"}
        wanted_ext = ext_map.get(system, ".bin")

        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith(wanted_ext.lower()):
                download_url = asset.get("browser_download_url", "")
                size = asset.get("size", 0)
                break

        # Fall back to the first asset if nothing matched
        if not download_url and assets:
            download_url = assets[0].get("browser_download_url", "")
            size = assets[0].get("size", 0)

        changelog = data.get("body", "See the GitHub release page for details.")
        # GitHub release bodies often contain Markdown — keep them as-is
        return UpdateInfo(
            version=latest_version,
            download_url=download_url,
            changelog=changelog,
            size=size,
            checksum="",
            required=False,
        )

    def _parse_legacy_format(self, data: dict, show_no_update: bool) -> Optional[UpdateInfo]:
        latest_version = data.get("version", "")
        if self._compare_versions(latest_version, self.current_version) <= 0:
            if show_no_update and self.parent_window:
                wx.MessageBox(
                    f"You are running the latest version ({self.current_version}).",
                    "No Updates Available",
                    wx.OK | wx.ICON_INFORMATION,
                    self.parent_window,
                )
            return None
        return UpdateInfo(
            version=latest_version,
            download_url=data.get("download_url", ""),
            changelog=data.get("changelog", "No changelog available."),
            size=data.get("size", 0),
            checksum=data.get("checksum", ""),
            required=data.get("required", False),
        )

    # ------------------------------------------------------------------
    # UI prompts
    # ------------------------------------------------------------------

    def prompt_update(self, update_info: UpdateInfo) -> int:
        dlg = ChangelogDialog(self.parent_window, update_info, self.current_version)
        result = dlg.ShowModal()
        dlg.Destroy()
        return result

    # ------------------------------------------------------------------
    # Download & install
    # ------------------------------------------------------------------

    def download_and_install(self, update_info: UpdateInfo,
                             on_complete: Optional[Callable] = None) -> bool:
        progress_dlg = DownloadProgressDialog(self.parent_window)
        progress_dlg.Show()
        success = [False]

        def worker():
            try:
                local_file = self._download_file(update_info.download_url, progress_dlg)
                if progress_dlg.cancelled or not local_file:
                    wx.CallAfter(progress_dlg.Close)
                    return

                if update_info.checksum:
                    progress_dlg.update_status("Verifying download…")
                    if not self._verify_checksum(local_file, update_info.checksum):
                        wx.CallAfter(self._show_error, "Download verification failed!")
                        wx.CallAfter(progress_dlg.Close)
                        return

                progress_dlg.update_status("Installing update…")
                if self._install_update(local_file, progress_dlg):
                    success[0] = True
                    wx.CallAfter(progress_dlg.Close)
                    if on_complete:
                        wx.CallAfter(on_complete)
                    else:
                        wx.CallAfter(self._show_restart_dialog)
                else:
                    wx.CallAfter(self._show_error, "Installation failed!")
                    wx.CallAfter(progress_dlg.Close)
            except Exception as e:
                wx.CallAfter(self._show_error, f"Update failed:\n{e}")
                wx.CallAfter(progress_dlg.Close)

        Thread(target=worker, daemon=True).start()
        progress_dlg.ShowModal()
        progress_dlg.Destroy()
        return success[0]

    def _download_file(self, url: str, progress_dlg: DownloadProgressDialog) -> Optional[str]:
        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))
            ext = self._get_file_extension(url, response)
            local_file = os.path.join(self.temp_dir, f"update{ext}")
            downloaded = 0
            start_time = time.time()

            with open(local_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if progress_dlg.cancelled:
                        return None
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            elapsed = time.time() - start_time
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            progress_dlg.update_progress(
                                (downloaded / total_size) * 100,
                                downloaded, total_size, speed,
                            )
            return local_file
        except Exception as e:
            wx.CallAfter(self._show_error, f"Download failed:\n{e}")
            return None

    @staticmethod
    def _get_file_extension(url: str, response: requests.Response) -> str:
        ext = os.path.splitext(url.split("?")[0])[1]
        if ext:
            return ext
        ct = response.headers.get("Content-Type", "").lower()
        if "zip" in ct:
            return ".zip"
        if "exe" in ct:
            return ".exe"
        if "dmg" in ct:
            return ".dmg"
        system = platform.system()
        return {"Windows": ".exe", "Darwin": ".dmg"}.get(system, ".bin")

    @staticmethod
    def _verify_checksum(file_path: str, expected: str) -> bool:
        try:
            h = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    h.update(chunk)
            return h.hexdigest().lower() == expected.lower()
        except Exception:
            return False

    def _install_update(self, update_file: str, progress_dlg: DownloadProgressDialog) -> bool:
        system = platform.system()
        try:
            if system == "Windows":
                return self._install_windows(update_file)
            if system == "Darwin":
                return self._install_macos(update_file)
            if system == "Linux":
                return self._install_linux(update_file)
            wx.CallAfter(self._show_error, f"Unsupported platform: {system}")
            return False
        except Exception as e:
            wx.CallAfter(self._show_error, f"Installation error:\n{e}")
            return False

    def _install_windows(self, update_file: str) -> bool:
        current_exe = sys.executable
        batch = os.path.join(self.temp_dir, "update.bat")
        with open(batch, "w") as f:
            f.write("@echo off\n")
            f.write("timeout /t 2 /nobreak > nul\n")
            f.write(f'del /f /q "{current_exe}"\n')
            f.write(f'move /y "{update_file}" "{current_exe}"\n')
            f.write(f'start "" "{current_exe}"\n')
            f.write('del "%~f0"\n')
        subprocess.Popen([batch], creationflags=subprocess.CREATE_NO_WINDOW, shell=True)
        return True

    def _install_macos(self, update_file: str) -> bool:
        if not update_file.endswith(".dmg"):
            return False
        mount_pt = os.path.join(self.temp_dir, "mount")
        os.makedirs(mount_pt, exist_ok=True)
        subprocess.run(["hdiutil", "attach", update_file, "-mountpoint", mount_pt], check=True)
        app_bundle = next(
            (os.path.join(mount_pt, x) for x in os.listdir(mount_pt) if x.endswith(".app")),
            None,
        )
        if not app_bundle:
            return False
        current_app = self._get_macos_app_path()
        script = os.path.join(self.temp_dir, "update.sh")
        with open(script, "w") as f:
            f.write("#!/bin/bash\nsleep 2\n")
            f.write(f'rm -rf "{current_app}"\n')
            f.write(f'cp -R "{app_bundle}" "{os.path.dirname(current_app)}"\n')
            f.write(f'hdiutil detach "{mount_pt}"\n')
            f.write(f'open "{current_app}"\n')
        os.chmod(script, 0o755)
        subprocess.Popen([script])
        return True

    def _install_linux(self, update_file: str) -> bool:
        current_exe = sys.executable
        script = os.path.join(self.temp_dir, "update.sh")
        with open(script, "w") as f:
            f.write("#!/bin/bash\nsleep 2\n")
            f.write(f'rm -f "{current_exe}"\n')
            f.write(f'mv "{update_file}" "{current_exe}"\n')
            f.write(f'chmod +x "{current_exe}"\n')
            f.write(f'"{current_exe}" &\n')
        os.chmod(script, 0o755)
        subprocess.Popen([script])
        return True

    @staticmethod
    def _get_macos_app_path() -> str:
        exe = sys.executable
        while exe != "/" and not exe.endswith(".app"):
            exe = os.path.dirname(exe)
        return exe if exe.endswith(".app") else ""

    def _show_restart_dialog(self):
        wx.MessageBox(
            "Update installed successfully!\n\nThe application will now restart.",
            "Update Complete",
            wx.OK | wx.ICON_INFORMATION,
            self.parent_window,
        )
        wx.CallLater(500, self._exit_app)

    def _show_error(self, message: str):
        wx.MessageBox(message, "Error", wx.OK | wx.ICON_ERROR, self.parent_window)

    def _exit_app(self):
        os._exit(0)

    # ------------------------------------------------------------------
    # Version comparison
    # ------------------------------------------------------------------

    @staticmethod
    def _compare_versions(v1: str, v2: str) -> int:
        """Return 1 if v1 > v2, -1 if v1 < v2, 0 if equal."""
        import re

        def normalize(v):
            cleaned = v.strip().lstrip("vV").split("-")[0].split("+")[0]
            parts = []
            for token in cleaned.split("."):
                m = re.match(r"(\d+)", token)
                parts.append(int(m.group(1)) if m else 0)
            return parts

        p1, p2 = normalize(v1), normalize(v2)
        length = max(len(p1), len(p2), 3)
        p1 += [0] * (length - len(p1))
        p2 += [0] * (length - len(p2))
        for a, b in zip(p1, p2):
            if a > b:
                return 1
            if a < b:
                return -1
        return 0

    # ------------------------------------------------------------------
    # High-level entry point
    # ------------------------------------------------------------------

    def update(self, manual: bool = False):
        info = self.check_for_updates(show_no_update_dialog=manual)
        if not info:
            return
        choice = self.prompt_update(info)
        if choice == wx.ID_OK:
            self.download_and_install(info)
        elif choice == wx.ID_CANCEL and info.required:
            wx.MessageBox(
                "This update is required. The application will now exit.",
                "Update Required",
                wx.OK | wx.ICON_WARNING,
                self.parent_window,
            )
            self._exit_app()

    def cleanup(self):
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass
