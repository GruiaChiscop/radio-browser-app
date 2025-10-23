import psutil
import platform
from typing import List, Dict, Optional, Set
from dataclasses import dataclass
from enum import Enum


class ScreenReader(Enum):
    """Known screen readers with their process names."""
    NVDA = ["nvda.exe", "nvda_service.exe", "nvda_slave.exe"]
    JAWS = ["jfw.exe", "jfwservice.exe"]
    NARRATOR = ["narrator.exe"]
    ZDSR = ["zdsr.exe"]
    SUPERNOVA = ["supernova.exe", "supernovaaccessbridge.exe"]
    WINDOW_EYES = ["gweyes.exe"]
    SYSTEMACCESS = ["saapi32.exe", "saapi64.exe"]
    COBRA = ["cobra.exe"]
    ORCA = ["orca"]  # Linux
    VOICEOVER = ["VoiceOver"]  # macOS (part of system)
    TALKBACK = ["talkback"]  # Android
    CHROMEVOX = ["chromevox"]  # Chrome OS


@dataclass
class ProcessInfo:
    """Information about a running process."""
    pid: int
    name: str
    exe_path: Optional[str]
    status: str
    cpu_percent: float
    memory_mb: float
    username: Optional[str]
    
    def __repr__(self):
        return f"ProcessInfo(pid={self.pid}, name='{self.name}', status='{self.status}')"


@dataclass
class ProcessCheckResult:
    """Result of a process check."""
    is_running: bool
    process_count: int
    processes: List[ProcessInfo]
    
    def __repr__(self):
        return f"ProcessCheckResult(is_running={self.is_running}, count={self.process_count})"


class ProcessChecker:
    """
    Check if processes are running by name.
    Handles multiple instances and provides detailed process information.
    """
    
    def __init__(self, case_sensitive: bool = False):
        """
        Initialize the process checker.
        
        Args:
            case_sensitive: Whether process name matching should be case-sensitive
        """
        self.case_sensitive = case_sensitive
        self.system = platform.system()
        
    def is_process_running(self, process_name: str) -> ProcessCheckResult:
        """
        Check if a process with the given name is running.
        
        Args:
            process_name: Name of the process to check (e.g., "nvda.exe", "chrome")
            
        Returns:
            ProcessCheckResult with running status and process details
        """
        processes = self.find_processes(process_name)
        
        return ProcessCheckResult(
            is_running=len(processes) > 0,
            process_count=len(processes),
            processes=processes
        )
    
    def find_processes(self, process_name: str) -> List[ProcessInfo]:
        """
        Find all processes matching the given name.
        
        Args:
            process_name: Name of the process to find
            
        Returns:
            List of ProcessInfo objects for matching processes
        """
        matching_processes = []
        
        # Normalize process name for comparison
        search_name = process_name if self.case_sensitive else process_name.lower()
        
        try:
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'status', 
                                            'cpu_percent', 'memory_info', 'username']):
                try:
                    proc_name = proc.info['name']
                    
                    if not proc_name:
                        continue
                    
                    # Normalize for comparison
                    compare_name = proc_name if self.case_sensitive else proc_name.lower()
                    
                    # Check if names match
                    if self._name_matches(compare_name, search_name):
                        # Verify process is actually running
                        if self._is_process_actually_running(proc):
                            process_info = self._create_process_info(proc)
                            matching_processes.append(process_info)
                            
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Process terminated or we don't have permission
                    continue
                    
        except Exception as e:
            # Handle unexpected errors gracefully
            pass
        
        return matching_processes
    
    def check_multiple_processes(self, process_names: List[str]) -> Dict[str, ProcessCheckResult]:
        """
        Check multiple processes at once.
        
        Args:
            process_names: List of process names to check
            
        Returns:
            Dictionary mapping process names to their check results
        """
        results = {}
        
        for process_name in process_names:
            results[process_name] = self.is_process_running(process_name)
        
        return results
    
    def get_all_running_processes(self) -> List[ProcessInfo]:
        """
        Get information about all running processes.
        
        Returns:
            List of ProcessInfo objects for all running processes
        """
        all_processes = []
        
        try:
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'status',
                                            'cpu_percent', 'memory_info', 'username']):
                try:
                    if self._is_process_actually_running(proc):
                        process_info = self._create_process_info(proc)
                        all_processes.append(process_info)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception:
            pass
        
        return all_processes
    
    def _name_matches(self, proc_name: str, search_name: str) -> bool:
        """Check if process name matches search criteria."""
        # Exact match
        if proc_name == search_name:
            return True
        
        # Match without extension (e.g., "nvda" matches "nvda.exe")
        proc_base = proc_name.rsplit('.', 1)[0]
        search_base = search_name.rsplit('.', 1)[0]
        
        return proc_base == search_base
    
    def _is_process_actually_running(self, proc: psutil.Process) -> bool:
        """
        Verify that a process is actually running (not zombie, etc.).
        
        Args:
            proc: psutil.Process object
            
        Returns:
            True if process is running, False otherwise
        """
        try:
            status = proc.status()
            
            # Check if process is in a running state
            if status in [psutil.STATUS_RUNNING, psutil.STATUS_SLEEPING, 
                         psutil.STATUS_DISK_SLEEP, psutil.STATUS_IDLE]:
                return True
            
            # On Windows, also accept STATUS_STOPPED for services
            if self.system == 'Windows' and status == 'stopped':
                # Try to get more info - if we can, it's somewhat alive
                try:
                    proc.name()
                    return True
                except:
                    return False
            
            return False
            
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
    
    def _create_process_info(self, proc: psutil.Process) -> ProcessInfo:
        """Create ProcessInfo object from psutil.Process."""
        try:
            # Get memory usage in MB
            memory_bytes = proc.info.get('memory_info')
            memory_mb = memory_bytes.rss / (1024 * 1024) if memory_bytes else 0.0
            
            return ProcessInfo(
                pid=proc.info['pid'],
                name=proc.info['name'] or 'Unknown',
                exe_path=proc.info.get('exe'),
                status=proc.info.get('status', 'unknown'),
                cpu_percent=proc.info.get('cpu_percent', 0.0) or 0.0,
                memory_mb=memory_mb,
                username=proc.info.get('username')
            )
        except Exception:
            # Fallback with minimal info
            return ProcessInfo(
                pid=proc.info['pid'],
                name=proc.info['name'] or 'Unknown',
                exe_path=None,
                status='unknown',
                cpu_percent=0.0,
                memory_mb=0.0,
                username=None
            )


class ScreenReaderChecker(ProcessChecker):
    """
    Specialized checker for detecting screen readers.
    Extends ProcessChecker with screen reader specific functionality.
    """
    
    def __init__(self):
        """Initialize screen reader checker."""
        super().__init__(case_sensitive=False)
        self.detected_readers: Set[str] = set()
    
    def is_screen_reader_running(self) -> bool:
        """
        Check if any known screen reader is running.
        
        Returns:
            True if at least one screen reader is detected
        """
        self.detected_readers.clear()
        
        for reader in ScreenReader:
            if self._check_screen_reader(reader):
                self.detected_readers.add(reader.name)
        
        return len(self.detected_readers) > 0
    
    def get_running_screen_readers(self) -> List[str]:
        """
        Get list of all running screen readers.
        
        Returns:
            List of screen reader names that are currently running
        """
        self.is_screen_reader_running()  # Populate detected_readers
        return list(self.detected_readers)
    
    def get_detailed_screen_reader_info(self) -> Dict[str, List[ProcessInfo]]:
        """
        Get detailed information about running screen readers.
        
        Returns:
            Dictionary mapping screen reader names to their process information
        """
        detailed_info = {}
        
        for reader in ScreenReader:
            processes = []
            
            for process_name in reader.value:
                result = self.is_process_running(process_name)
                if result.is_running:
                    processes.extend(result.processes)
            
            if processes:
                detailed_info[reader.name] = processes
        
        return detailed_info
    
    def check_specific_screen_reader(self, reader_name: str) -> ProcessCheckResult:
        """
        Check if a specific screen reader is running.
        
        Args:
            reader_name: Name of the screen reader (e.g., "NVDA", "JAWS")
            
        Returns:
            ProcessCheckResult with information about the screen reader
        """
        reader_name_upper = reader_name.upper()
        
        try:
            reader = ScreenReader[reader_name_upper]
        except KeyError:
            # Unknown screen reader
            return ProcessCheckResult(
                is_running=False,
                process_count=0,
                processes=[]
            )
        
        all_processes = []
        
        for process_name in reader.value:
            result = self.is_process_running(process_name)
            if result.is_running:
                all_processes.extend(result.processes)
        
        return ProcessCheckResult(
            is_running=len(all_processes) > 0,
            process_count=len(all_processes),
            processes=all_processes
        )
    
    def _check_screen_reader(self, reader: ScreenReader) -> bool:
        """Check if a specific screen reader enum is running."""
        for process_name in reader.value:
            result = self.is_process_running(process_name)
            if result.is_running:
                return True
        return False
    
    def is_nvda_running(self) -> bool:
        """Quick check for NVDA."""
        return self.check_specific_screen_reader("NVDA").is_running
    
    def is_jaws_running(self) -> bool:
        """Quick check for JAWS."""
        return self.check_specific_screen_reader("JAWS").is_running
    
    def is_narrator_running(self) -> bool:
        """Quick check for Windows Narrator."""
        return self.check_specific_screen_reader("NARRATOR").is_running
    
    def get_accessibility_summary(self) -> Dict[str, any]:
        """
        Get a comprehensive summary of accessibility tools running.
        
        Returns:
            Dictionary with accessibility information
        """
        running_readers = self.get_running_screen_readers()
        detailed_info = self.get_detailed_screen_reader_info()
        
        total_processes = sum(len(procs) for procs in detailed_info.values())
        
        return {
            'screen_reader_active': len(running_readers) > 0,
            'running_screen_readers': running_readers,
            'total_screen_reader_processes': total_processes,
            'detailed_info': detailed_info,
            'platform': self.system
        }

