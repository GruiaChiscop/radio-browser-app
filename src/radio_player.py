import threading
import time
from enum import Enum, auto
from sound_lib.output import Output
from sound_lib.stream import URLStream
from sound_lib.main import BassError

class PlayerState(Enum):
    IDLE = auto()
    CONNECTING = auto()
    PLAYING = auto()
    PAUSED = auto()
    STOPPED = auto()

class RadioPlayer:
    def __init__(self):
        self.state = PlayerState.IDLE
        self.output=Output()
        self.volume = 1.0
        self.current_url = None
        self.metadata_callback = None
        self.stream=None

        self._stop_metadata = threading.Event()
        self._metadata_thread = None

    def _play_internal(self, url):
        #this method should never be called directly
        try:
            self.state = PlayerState.CONNECTING
            self.stream=URLStream(url)
            self.stream.play()
            time.sleep(0.2)
            self.state = PlayerState.PLAYING
        except Exception as e:
            print(f"Error playing stream: {e}")
            self.state=PlayerState.IDLE
            self.stream=None

    def play(self, url: str):
        self.stop()
        self.current_url = url
        t = threading.Thread(target=self._play_internal, args=(url,), daemon=True)
        t.start()
        
    def stop(self):
        self.state=PlayerState.STOPPED
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.free()
            except BassError:
                pass
            finally:
                self.stream=None
        self._stop_metadata_thread()
    def pause(self):
        if self.stream is not None and  self.state==PlayerState.PLAYING:
            self.stream.pause()
            self.state=PlayerState.PAUSED
    
    def resume(self):
        if self.stream is None and self.state==PlayerState.PAUSED:
            self.stream.play()
            self.state=PlayerState.PLAYING
        
    def set_volume(self, vol: float):
        self.volume = max(0.0, min(1.0, float(vol)))
        if self.stream is not None and self.state==PlayerState.PLAYING:
            try:
                self.stream.set_volume(self.volume)
            except BassError:
                pass

    def set_metadata_callback(self, callback):
        """
        callback(text: str)
        """
        self.metadata_callback = callback

    def _start_metadata_thread(self):
        self._stop_metadata = threading.Event()
        self._metadata_thread = threading.Thread(target=self._metadata_worker, daemon=True)
        self._metadata_thread.start()

    def _stop_metadata_thread(self):
        if self._metadata_thread:
            self._stop_metadata.set()
            self._metadata_thread.join(timeout=1)
            self._metadata_thread = None

    def _metadata_worker(self):
        last_metadata = None
        while not self._stop_metadata.is_set():
            if self.state!=PlayerState.PLAYING or not self.stream:
                break
            tags = self.stream.get_tags()
            if tags:
                text = tags.decode(errors="ignore")

                # Avoid repeating the same metadata
                if text != last_metadata:
                    last_metadata = text
                    if self.metadata_callback:
                        self.metadata_callback(text)

            time.sleep(1.0)  # small delay

    # ---------------------------------------------------------
    # Cleanup
    # ---------------------------------------------------------
    def close(self):
        self.stop()
        self.output.free()
