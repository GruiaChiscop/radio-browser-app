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
from typing import Optional, Dict, Callable
from threading import Thread
import time


class UpdateInfo:
    """Container for update information."""
    def __init__(self, version: str, download_url: str, changelog: str, 
                 size: int = 0, checksum: str = "", required: bool = False):
        self.version = version
        self.download_url = download_url
        self.changelog = changelog
        self.size = size
        self.checksum = checksum
        self.required = required


class ChangelogDialog(wx.Dialog):
    """Dialog to display changelog and prompt for update."""
    
    def __init__(self, parent, update_info: UpdateInfo, current_version: str):
        super().__init__(parent, title="Update Available", 
                        size=(600, 500),
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        
        self.update_info = update_info
        self.current_version = current_version
        
        self._create_ui()
        self.Centre()
    
    def _create_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Title
        title = wx.StaticText(panel, label="A new version is available!")
        title_font = title.GetFont()
        title_font.PointSize += 3
        title_font = title_font.Bold()
        title.SetFont(title_font)
        main_sizer.Add(title, 0, wx.ALL, 10)
        
        # Version info
        version_text = f"Current Version: {self.current_version}\n"
        version_text += f"New Version: {self.update_info.version}"
        version_label = wx.StaticText(panel, label=version_text)
        main_sizer.Add(version_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        # Size info if available
        if self.update_info.size > 0:
            size_mb = self.update_info.size / (1024 * 1024)
            size_text = f"Download Size: {size_mb:.2f} MB"
            size_label = wx.StaticText(panel, label=size_text)
            main_sizer.Add(size_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        # Changelog
        changelog_label = wx.StaticText(panel, label="What's New:")
        changelog_label_font = changelog_label.GetFont()
        changelog_label_font = changelog_label_font.Bold()
        changelog_label.SetFont(changelog_label_font)
        main_sizer.Add(changelog_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        
        changelog_text = wx.TextCtrl(panel, 
                                     value=self.update_info.changelog,
                                     style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        main_sizer.Add(changelog_text, 1, wx.ALL | wx.EXPAND, 10)
        
        # Required update warning
        if self.update_info.required:
            warning = wx.StaticText(panel, 
                                   label="⚠ This is a required update. The application may not work correctly without it.")
            warning.SetForegroundColour(wx.Colour(200, 0, 0))
            main_sizer.Add(warning, 0, wx.ALL, 10)
        
        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        if not self.update_info.required:
            skip_btn = wx.Button(panel, wx.ID_CANCEL, "Skip This Version")
            button_sizer.Add(skip_btn, 0, wx.RIGHT, 5)
            
            later_btn = wx.Button(panel, wx.ID_NO, "Remind Me Later")
            button_sizer.Add(later_btn, 0, wx.RIGHT, 5)
        
        update_btn = wx.Button(panel, wx.ID_OK, "Update Now")
        update_btn.SetDefault()
        button_sizer.Add(update_btn, 0)
        
        main_sizer.Add(button_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        
        panel.SetSizer(main_sizer)


class DownloadProgressDialog(wx.Dialog):
    """Dialog showing download progress with cancellation support."""
    
    def __init__(self, parent, title="Downloading Update"):
        super().__init__(parent, title=title, 
                        size=(500, 200),
                        style=wx.DEFAULT_DIALOG_STYLE)
        
        self.cancelled = False
        self._create_ui()
        self.Centre()
    
    def _create_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Status text
        self.status_label = wx.StaticText(panel, label="Preparing download...")
        main_sizer.Add(self.status_label, 0, wx.ALL | wx.EXPAND, 10)
        
        # Progress bar
        self.progress_bar = wx.Gauge(panel, range=100)
        main_sizer.Add(self.progress_bar, 0, wx.ALL | wx.EXPAND, 10)
        
        # Speed and size info
        self.info_label = wx.StaticText(panel, label="")
        main_sizer.Add(self.info_label, 0, wx.ALL | wx.EXPAND, 10)
        
        # Cancel button
        self.cancel_btn = wx.Button(panel, wx.ID_CANCEL, "Cancel")
        self.cancel_btn.Bind(wx.EVT_BUTTON, self.on_cancel)
        main_sizer.Add(self.cancel_btn, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        panel.SetSizer(main_sizer)
    
    def update_progress(self, percent: float, downloaded: int, total: int, speed: float):
        """Update progress information."""
        wx.CallAfter(self._update_progress_ui, percent, downloaded, total, speed)
    
    def _update_progress_ui(self, percent: float, downloaded: int, total: int, speed: float):
        self.progress_bar.SetValue(int(percent))
        
        downloaded_mb = downloaded / (1024 * 1024)
        total_mb = total / (1024 * 1024)
        speed_mb = speed / (1024 * 1024)
        
        self.status_label.SetLabel(f"Downloading update... {percent:.1f}%")
        self.info_label.SetLabel(
            f"{downloaded_mb:.2f} MB / {total_mb:.2f} MB  |  Speed: {speed_mb:.2f} MB/s"
        )
    
    def update_status(self, message: str):
        """Update status message."""
        wx.CallAfter(self.status_label.SetLabel, message)
    
    def on_cancel(self, event):
        self.cancelled = True
        self.cancel_btn.Enable(False)
        self.status_label.SetLabel("Cancelling download...")


class AppUpdater:
    """
    Complete application updater with UI support.
    
    Handles checking for updates, downloading, and replacing the application.
    """
    
    def __init__(self, 
                 current_version: str,
                 update_url: str,
                 app_name: str = "Application",
                 parent_window: Optional[wx.Window] = None):
        """
        Initialise the updater.
        
        Args:
            current_version: Current application version (e.g., "1.0.0")
            update_url: URL to check for updates (should return JSON)
            app_name: Name of the application
            parent_window: Parent window for dialogs
        """
        self.current_version = current_version
        self.update_url = update_url
        self.app_name = app_name
        self.parent_window = parent_window
        self.temp_dir = tempfile.mkdtemp(prefix="app_update_")
        
    def check_for_updates(self, show_no_update_dialog: bool = False) -> Optional[UpdateInfo]:
        """
        Check if updates are available.
        
        Args:
            show_no_update_dialog: Show dialog if no updates are available
            
        Returns:
            UpdateInfo object if update available, None otherwise
        """
        try:
            response = requests.get(self.update_url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Expected JSON format:
            # {
            #     "version": "1.2.0",
            #     "download_url": "https://...",
            #     "changelog": "- New feature\n- Bug fixes",
            #     "size": 12345678,
            #     "checksum": "sha256hash",
            #     "required": false
            # }
            
            latest_version = data.get('version', '')
            
            if self._compare_versions(latest_version, self.current_version) > 0:
                return UpdateInfo(
                    version=latest_version,
                    download_url=data.get('download_url', ''),
                    changelog=data.get('changelog', 'No changelog available.'),
                    size=data.get('size', 0),
                    checksum=data.get('checksum', ''),
                    required=data.get('required', False)
                )
            else:
                if show_no_update_dialog and self.parent_window:
                    wx.MessageBox(
                        f"You are running the latest version ({self.current_version})",
                        "No Updates Available",
                        wx.OK | wx.ICON_INFORMATION,
                        self.parent_window
                    )
                return None
                
        except requests.RequestException as e:
            if self.parent_window and show_no_update_dialog:
                wx.MessageBox(
                    f"Failed to check for updates:\n{str(e)}",
                    "Update Check Failed",
                    wx.OK | wx.ICON_ERROR,
                    self.parent_window
                )
            return None
        except Exception as e:
            if self.parent_window and show_no_update_dialog:
                wx.MessageBox(
                    f"Error checking for updates:\n{str(e)}",
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                    self.parent_window
                )
            return None
    
    def prompt_update(self, update_info: UpdateInfo) -> int:
        """
        Show update dialog to user.
        
        Returns:
            wx.ID_OK: User wants to update now
            wx.ID_NO: Remind later
            wx.ID_CANCEL: Skip this version
        """
        dlg = ChangelogDialog(self.parent_window, update_info, self.current_version)
        result = dlg.ShowModal()
        dlg.Destroy()
        return result
    
    def download_and_install(self, update_info: UpdateInfo, 
                            on_complete: Optional[Callable] = None) -> bool:
        """
        Download and install update with progress dialog.
        
        Args:
            update_info: Update information
            on_complete: Callback function called after successful installation
            
        Returns:
            True if successful, False otherwise
        """
        progress_dlg = DownloadProgressDialog(self.parent_window)
        progress_dlg.Show()
        
        success = [False]  # Use list to modify in thread
        
        def download_thread():
            try:
                # Download file
                local_file = self._download_file(
                    update_info.download_url,
                    progress_dlg
                )
                
                if progress_dlg.cancelled or not local_file:
                    wx.CallAfter(progress_dlg.Close)
                    return
                
                # Verify checksum if provided
                if update_info.checksum:
                    progress_dlg.update_status("Verifying download...")
                    if not self._verify_checksum(local_file, update_info.checksum):
                        wx.CallAfter(self._show_error, "Download verification failed!")
                        wx.CallAfter(progress_dlg.Close)
                        return
                
                # Install update
                progress_dlg.update_status("Installing update...")
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
                wx.CallAfter(self._show_error, f"Update failed:\n{str(e)}")
                wx.CallAfter(progress_dlg.Close)
        
        thread = Thread(target=download_thread, daemon=True)
        thread.start()
        
        progress_dlg.ShowModal()
        progress_dlg.Destroy()
        
        return success[0]
    
    def _download_file(self, url: str, progress_dlg: DownloadProgressDialog) -> Optional[str]:
        """Download file with progress tracking."""
        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            
            # Determine file extension
            ext = self._get_file_extension(url, response)
            local_file = os.path.join(self.temp_dir, f"update{ext}")
            
            downloaded = 0
            start_time = time.time()
            
            with open(local_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if progress_dlg.cancelled:
                        return None
                    
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # Calculate progress
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            elapsed = time.time() - start_time
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            
                            progress_dlg.update_progress(
                                percent, downloaded, total_size, speed
                            )
            
            return local_file
            
        except Exception as e:
            wx.CallAfter(self._show_error, f"Download failed:\n{str(e)}")
            return None
    
    def _get_file_extension(self, url: str, response: requests.Response) -> str:
        """Determine file extension from URL or headers."""
        # Try from URL
        path = url.split('?')[0]
        ext = os.path.splitext(path)[1]
        if ext:
            return ext
        
        # Try from Content-Type
        content_type = response.headers.get('Content-Type', '').lower()
        if 'zip' in content_type:
            return '.zip'
        elif 'exe' in content_type:
            return '.exe'
        elif 'dmg' in content_type:
            return '.dmg'
        elif 'deb' in content_type:
            return '.deb'
        elif 'rpm' in content_type:
            return '.rpm'
        
        # Default based on platform
        system = platform.system()
        if system == 'Windows':
            return '.exe'
        elif system == 'Darwin':
            return '.dmg'
        else:
            return '.bin'
    
    def _verify_checksum(self, file_path: str, expected_checksum: str) -> bool:
        """Verify file checksum."""
        try:
            sha256_hash = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)
            
            return sha256_hash.hexdigest().lower() == expected_checksum.lower()
        except Exception:
            return False
    
    def _install_update(self, update_file: str, progress_dlg: DownloadProgressDialog) -> bool:
        """Install the update based on platform."""
        system = platform.system()
        
        try:
            if system == 'Windows':
                return self._install_windows(update_file, progress_dlg)
            elif system == 'Darwin':
                return self._install_macos(update_file, progress_dlg)
            elif system == 'Linux':
                return self._install_linux(update_file, progress_dlg)
            else:
                wx.CallAfter(self._show_error, f"Unsupported platform: {system}")
                return False
        except Exception as e:
            wx.CallAfter(self._show_error, f"Installation error:\n{str(e)}")
            return False
    
    def _install_windows(self, update_file: str, progress_dlg: DownloadProgressDialog) -> bool:
        """Install update on Windows."""
        current_exe = sys.executable
        
        # Create batch script to replace executable
        batch_script = os.path.join(self.temp_dir, "update.bat")
        
        with open(batch_script, 'w') as f:
            f.write('@echo off\n')
            f.write('timeout /t 2 /nobreak > nul\n')  # Wait for app to close
            f.write(f'del /f /q "{current_exe}"\n')
            f.write(f'move /y "{update_file}" "{current_exe}"\n')
            f.write(f'start "" "{current_exe}"\n')
            f.write(f'del "%~f0"\n')  # Delete batch script itself
        
        # Launch batch script and exit
        subprocess.Popen([batch_script], creationflags=subprocess.CREATE_NO_WINDOW,
                        shell=True)
        return True
    
    def _install_macos(self, update_file: str, progress_dlg: DownloadProgressDialog) -> bool:
        """Install update on macOS."""
        # For .dmg files, mount and copy
        if update_file.endswith('.dmg'):
            # Mount DMG
            mount_point = os.path.join(self.temp_dir, "mount")
            os.makedirs(mount_point, exist_ok=True)
            subprocess.run(['hdiutil', 'attach', update_file, '-mountpoint', mount_point],
                          check=True)
            
            # Find .app bundle
            app_bundle = None
            for item in os.listdir(mount_point):
                if item.endswith('.app'):
                    app_bundle = os.path.join(mount_point, item)
                    break
            
            if not app_bundle:
                return False
            
            # Get current app path
            current_app = self._get_macos_app_path()
            
            # Create update script
            script_path = os.path.join(self.temp_dir, "update.sh")
            with open(script_path, 'w') as f:
                f.write('#!/bin/bash\n')
                f.write('sleep 2\n')
                f.write(f'rm -rf "{current_app}"\n')
                f.write(f'cp -R "{app_bundle}" "{os.path.dirname(current_app)}"\n')
                f.write(f'hdiutil detach "{mount_point}"\n')
                f.write(f'open "{current_app}"\n')
            
            os.chmod(script_path, 0o755)
            subprocess.Popen([script_path])
            return True
        
        return False
    
    def _install_linux(self, update_file: str, progress_dlg: DownloadProgressDialog) -> bool:
        """Install update on Linux."""
        current_exe = sys.executable
        
        # Create shell script to replace executable
        script_path = os.path.join(self.temp_dir, "update.sh")
        
        with open(script_path, 'w') as f:
            f.write('#!/bin/bash\n')
            f.write('sleep 2\n')
            f.write(f'rm -f "{current_exe}"\n')
            f.write(f'mv "{update_file}" "{current_exe}"\n')
            f.write(f'chmod +x "{current_exe}"\n')
            f.write(f'"{current_exe}" &\n')
        
        os.chmod(script_path, 0o755)
        subprocess.Popen([script_path])
        return True
    
    def _get_macos_app_path(self) -> str:
        """Get the path to the .app bundle on macOS."""
        exe_path = sys.executable
        while exe_path != '/' and not exe_path.endswith('.app'):
            exe_path = os.path.dirname(exe_path)
        return exe_path if exe_path.endswith('.app') else ''
    
    def _show_restart_dialog(self):
        """Show dialog prompting to restart application."""
        dlg = wx.MessageDialog(
            self.parent_window,
            "Update installed successfully!\n\nThe application will now restart.",
            "Update Complete",
            wx.OK | wx.ICON_INFORMATION
        )
        dlg.ShowModal()
        dlg.Destroy()
        
        # Restart application
        self._restart_application()
    
    def _restart_application(self):
        """Restart the application."""
        wx.CallAfter(self._do_restart)
    
    def _do_restart(self):
        """Actually perform the restart."""
        if self.parent_window:
            app = wx.GetApp()
            if app:
                app.ExitMainLoop()
        
        # Small delay before exiting
        wx.CallLater(500, self._exit_app)
    
    def _exit_app(self):
        """Exit the application."""
        os._exit(0)
    
    def _show_error(self, message: str):
        """Show error dialog."""
        wx.MessageBox(message, "Error", wx.OK | wx.ICON_ERROR, self.parent_window)
    
    def _compare_versions(self, v1: str, v2: str) -> int:
        """
        Compare two version strings.
        
        Returns:
            1 if v1 > v2
            0 if v1 == v2
            -1 if v1 < v2
        """
        def normalize(v):
            parts = [int(x) for x in v.split('.') if x.isdigit()]
            return parts
        
        v1_parts = normalize(v1)
        v2_parts = normalize(v2)
        
        # Pad with zeros
        max_len = max(len(v1_parts), len(v2_parts))
        v1_parts += [0] * (max_len - len(v1_parts))
        v2_parts += [0] * (max_len - len(v2_parts))
        
        for a, b in zip(v1_parts, v2_parts):
            if a > b:
                return 1
            elif a < b:
                return -1
        
        return 0
    
    def             update(self, manual: bool = False):
        """Check for updates and perform update if available."""
        update_info = self.check_for_updates(show_no_update_dialog=manual)
        if update_info:
            user_choice = self.prompt_update(update_info)
            if user_choice == wx.ID_OK:
                self.download_and_install(update_info)
            elif user_choice == wx.ID_NO:
                # Remind later
                pass
            elif user_choice == wx.ID_CANCEL:
                # Skip this version
                pass
    def cleanup(self):
        """Clean up temporary files."""
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass
