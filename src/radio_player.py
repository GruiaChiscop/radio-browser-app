import threading
import time
from pybass import *

class RadioPlayer:
    def __init__(self):
        self.stream = None
        self.volume = 1.0
        self.current_url = None
        self.metadata_callback = None

        self._stop_metadata = threading.Event()
        self._metadata_thread = None

        # Initialise BASS
        if not BASS_Init(-1, 44100, 0, 0, 0):
            raise RuntimeError(f"BASS_Init failed: {BASS_ErrorGetCode()}")

    # ---------------------------------------------------------
    # Play a radio URL
    # ---------------------------------------------------------
    def play(self, url: str):
        # Stop previous stream
        self.stop()

        self.current_url = url

        # Create new stream
        self.stream = BASS_StreamCreateURL(
            url.encode(),
            0,
            0,
            None,
            0
        )

        if not self.stream:
            raise RuntimeError(f"Could not create stream: {BASS_ErrorGetCode()}")

        # Apply previous volume
        self.set_volume(self.volume)

        # Start playback
        if not BASS_ChannelPlay(self.stream, False):
            raise RuntimeError(f"Channel play failed: {BASS_ErrorGetCode()}")

        # Start metadata thread
        self._start_metadata_thread()

    # ---------------------------------------------------------
    # Stop playback and free the stream
    # ---------------------------------------------------------
    def stop(self):
        if self.stream:
            BASS_ChannelStop(self.stream)
            BASS_StreamFree(self.stream)
            self.stream = None

        self._stop_metadata_thread()

    # ---------------------------------------------------------
    # Pause / resume
    # ---------------------------------------------------------
    def pause(self):
        if self.stream:
            BASS_ChannelPause(self.stream)

    def resume(self):
        if self.stream:
            BASS_ChannelPlay(self.stream, False)

    # ---------------------------------------------------------
    # Volume 0.0 – 1.0
    # ---------------------------------------------------------
    def set_volume(self, vol: float):
        self.volume = max(0.0, min(1.0, float(vol)))
        if self.stream:
            # BASS attribute for volume
            BASS_ChannelSetAttribute(self.stream, BASS_ATTRIB_VOL, self.volume)

    # ---------------------------------------------------------
    # Metadata handling
    # ---------------------------------------------------------
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
            if not self.stream:
                break

            # Get ICY metadata
            tags = BASS_ChannelGetTags(self.stream, BASS_TAG_ICY)
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
        BASS_Free()
