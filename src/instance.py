import os
import sys
import platform
import tempfile
import fcntl
import socket
import struct
import hashlib
import psutil
from pathlib import Path
from typing import Optional, Callable
import atexit


class SingleInstanceException(Exception):
    """Exception raised when another instance is already running."""
    pass


class SingleInstance:
    """
    Ensures only one instance of an application is running.
    
    Supports multiple methods across different platforms:
    - File locking (cross-platform)
    - Socket binding (cross-platform)
    - Process checking (cross-platform)
    
    Usage:
        # Method 1: Context manager
        with SingleInstance("my_app"):
            # Your application code here
            run_app()
        
        # Method 2: Manual control
        instance = SingleInstance("my_app")
        if not instance.is_already_running():
            # Your application code
            run_app()
            instance.cleanup()
        else:
            print("Already running!")
    """
    
    def __init__(self, 
                 app_id: str,
                 method: str = "auto",
                 on_already_running: Optional[Callable] = None,
                 raise_on_duplicate: bool = False):
        """
        Initialize single instance checker.
        
        Args:
            app_id: Unique identifier for your application
            method: Method to use: "auto", "file", "socket", "process"
            on_already_running: Callback function when instance exists
            raise_on_duplicate: Raise exception if already running
        """
        self.app_id = app_id
        self.method = method
        self.on_already_running = on_already_running
        self.raise_on_duplicate = raise_on_duplicate
        self.system = platform.system()
        
        # State tracking
        self.lock_file = None
        self.lock_fd = None
        self.socket = None
        self.is_locked = False
        
        # Generate unique identifiers
        self.unique_id = self._generate_unique_id()
        
        # Determine method to use
        if self.method == "auto":
            self.method = self._determine_best_method()
        
        # Register cleanup
        atexit.register(self.cleanup)
        
        # Perform the lock
        self._acquire_lock()
    
    def _generate_unique_id(self) -> str:
        """Generate a unique ID based on app_id and user."""
        # Include username to allow different users to run the app
        username = os.getenv('USER') or os.getenv('USERNAME') or 'default'
        
        # Create hash of app_id + username
        unique_string = f"{self.app_id}_{username}"
        hash_obj = hashlib.md5(unique_string.encode())
        return hash_obj.hexdigest()
    
    def _determine_best_method(self) -> str:
        """Determine the best locking method for the current platform."""
        if self.system == "Windows":
            # Windows: prefer socket method (file locking can be problematic)
            return "socket"
        else:
            # Linux/macOS: prefer file locking (most reliable)
            return "file"
    
    def _acquire_lock(self):
        """Acquire lock using the selected method."""
        if self.method == "file":
            self._acquire_file_lock()
        elif self.method == "socket":
            self._acquire_socket_lock()
        elif self.method == "process":
            self._check_process_lock()
        else:
            raise ValueError(f"Unknown method: {self.method}")
    
    def _acquire_file_lock(self):
        """Acquire lock using file locking mechanism."""
        # Get lock file path
        if self.system == "Windows":
            lock_dir = Path(tempfile.gettempdir())
        else:
            # Use /tmp on Unix systems
            lock_dir = Path("/tmp")
        
        self.lock_file = lock_dir / f"{self.unique_id}.lock"
        
        try:
            # Open lock file
            self.lock_fd = open(self.lock_file, 'w')
            
            # Try to acquire exclusive lock
            if self.system == "Windows":
                # Windows file locking
                import msvcrt
                try:
                    msvcrt.locking(self.lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
                    self.is_locked = True
                except IOError:
                    self._handle_already_running("File lock")
            else:
                # Unix file locking (fcntl)
                try:
                    fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.is_locked = True
                    
                    # Write PID to lock file
                    self.lock_fd.write(str(os.getpid()))
                    self.lock_fd.flush()
                except IOError:
                    self._handle_already_running("File lock")
                    
        except Exception as e:
            raise SingleInstanceException(f"Failed to acquire file lock: {e}")
    
    def _acquire_socket_lock(self):
        """Acquire lock using socket binding mechanism."""
        # Calculate port from unique_id (range: 49152-65535)
        port_base = 49152
        port_range = 16384
        hash_value = int(self.unique_id[:8], 16)
        port = port_base + (hash_value % port_range)
        
        try:
            # Create socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            
            # Set socket options
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Try to bind to localhost
            self.socket.bind(('127.0.0.1', port))
            self.socket.listen(1)
            self.is_locked = True
            
        except socket.error:
            self._handle_already_running("Socket")
        except Exception as e:
            raise SingleInstanceException(f"Failed to acquire socket lock: {e}")
    
    def _check_process_lock(self):
        """Check for running processes with the same executable."""
        current_pid = os.getpid()
        current_exe = sys.executable
        current_script = os.path.abspath(sys.argv[0])
        
        # Get current process command line
        try:
            current_proc = psutil.Process(current_pid)
            current_cmdline = current_proc.cmdline()
        except:
            current_cmdline = []
        
        # Check all running processes
        for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
            try:
                # Skip ourselves
                if proc.info['pid'] == current_pid:
                    continue
                
                # Check if same executable
                if proc.info['exe'] == current_exe:
                    # Check if same script
                    cmdline = proc.info.get('cmdline', [])
                    
                    # For Python scripts, check if running same script
                    if cmdline and len(cmdline) > 1:
                        script_path = os.path.abspath(cmdline[1]) if len(cmdline) > 1 else ""
                        
                        if script_path == current_script:
                            # Found another instance
                            self._handle_already_running("Process check")
                            return
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # No other instance found
        self.is_locked = True
    
    def _handle_already_running(self, method: str):
        """Handle the case when application is already running."""
        if self.on_already_running:
            self.on_already_running()
        
        if self.raise_on_duplicate:
            raise SingleInstanceException(
                f"Another instance of '{self.app_id}' is already running (detected via {method})"
            )
        
        self.is_locked = False
    
    def is_already_running(self) -> bool:
        """
        Check if another instance is already running.
        
        Returns:
            True if another instance exists, False otherwise
        """
        return not self.is_locked
    
    def cleanup(self):
        """Clean up locks and resources."""
        # Close socket
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        
        # Release file lock
        if self.lock_fd:
            try:
                if self.system != "Windows":
                    fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_UN)
                self.lock_fd.close()
            except:
                pass
            self.lock_fd = None
        
        # Remove lock file
        if self.lock_file and self.lock_file.exists():
            try:
                self.lock_file.unlink()
            except:
                pass
        
        self.is_locked = False
    
    def __enter__(self):
        """Context manager entry."""
        if self.is_already_running():
            raise SingleInstanceException(
                f"Another instance of '{self.app_id}' is already running"
            )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.cleanup()
        return False
    
    def __del__(self):
        """Destructor."""
        self.cleanup()


class SingleInstanceGuard:
    """
    Simplified single instance guard with automatic error handling.
    
    Usage:
        guard = SingleInstanceGuard("my_app")
        if not guard.allow_execution():
            sys.exit(1)
        
        # Your application code here
        run_app()
    """
    
    def __init__(self, 
                 app_id: str,
                 show_message: bool = True,
                 message: Optional[str] = None):
        """
        Initialize single instance guard.
        
        Args:
            app_id: Unique application identifier
            show_message: Whether to show message box on duplicate
            message: Custom message to show (None = default)
        """
        self.app_id = app_id
        self.show_message = show_message
        self.message = message or f"Another instance of {app_id} is already running."
        self.instance = None
    
    def allow_execution(self) -> bool:
        """
        Check if execution should be allowed.
        
        Returns:
            True if this is the only instance, False otherwise
        """
        try:
            self.instance = SingleInstance(
                self.app_id,
                raise_on_duplicate=False
            )
            
            if self.instance.is_already_running():
                if self.show_message:
                    self._show_already_running_message()
                return False
            
            return True
            
        except Exception as e:
            print(f"Error checking single instance: {e}")
            return True  # Allow execution on error
    
    def _show_already_running_message(self):
        """Show message that application is already running."""
        try:
            # Try to use GUI dialog if available
            if self._try_wx_dialog():
                return
            elif self._try_tkinter_dialog():
                return
        except:
            pass
        
        # Fallback to console message
        print(self.message)
    
    def _try_wx_dialog(self) -> bool:
        """Try to show wxPython dialog."""
        try:
            import wx
            app = wx.App()
            wx.MessageBox(
                self.message,
                "Application Already Running",
                wx.OK | wx.ICON_WARNING
            )
            return True
        except:
            return False
    
    def _try_tkinter_dialog(self) -> bool:
        """Try to show Tkinter dialog."""
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning(
                "Application Already Running",
                self.message
            )
            root.destroy()
            return True
        except:
            return False
    
    def cleanup(self):
        """Cleanup resources."""
        if self.instance:
            self.instance.cleanup()
