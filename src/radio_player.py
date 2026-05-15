import re
import threading
import time
from enum import Enum, auto
from typing import Optional

import requests
from sound_lib.output import Output
from sound_lib.stream import URLStream
from sound_lib.main import BassError


def _resolve_playlist(url: str) -> Optional[str]:
    """Fetch a PLS or M3U playlist URL and return the first stream URL inside it."""
    try:
        r = requests.get(
            url, timeout=8,
            headers={"User-Agent": "RadioBrowserPlayer/1.0"},
            allow_redirects=True,
        )
        r.raise_for_status()
        text = r.text.strip()

        # PLS: [playlist] section with File1=url, File2=url, …
        if "[playlist]" in text.lower():
            for line in text.splitlines():
                m = re.match(r"^File\d+=(.+)$", line.strip(), re.IGNORECASE)
                if m:
                    return m.group(1).strip()

        # M3U / M3U8: first non-comment, non-empty line that looks like a URL
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line.startswith("http"):
                return line
    except Exception:
        pass
    return None


class PlayerState(Enum):
    IDLE = auto()
    CONNECTING = auto()
    PLAYING = auto()
    PAUSED = auto()
    STOPPED = auto()


class RadioPlayer:
    def __init__(self):
        self.state = PlayerState.IDLE
        self.output = Output()
        self.volume = 1.0
        self.current_url = None
        self.metadata_callback = None
        self.on_error = lambda msg: None
        self.stream = None

        self._stop_metadata = threading.Event()
        self._metadata_thread = None

    def _play_internal(self, url: str):
        try:
            self.state = PlayerState.CONNECTING
            try:
                self.stream = URLStream(url)
            except BassError as e:
                # Error 41 = BASS_ERROR_FILEFORM: server returned a playlist
                # (M3U/PLS) instead of a raw stream. Try to resolve it.
                if getattr(e, "code", None) == 41 or str(e).startswith("41,"):
                    resolved = _resolve_playlist(url)
                    if resolved and resolved != url:
                        self.current_url = resolved
                        self.stream = URLStream(resolved)
                    else:
                        raise
                else:
                    raise
            self.stream.set_volume(self.volume)
            self.stream.play()
            time.sleep(0.2)
            self.state = PlayerState.PLAYING
            self._start_metadata_thread()
        except Exception as e:
            self.on_error(f"Could not play stream: {e}")
            self.state = PlayerState.IDLE
            self.stream = None

    def play(self, url: str):
        self.stop()
        self.current_url = url
        t = threading.Thread(target=self._play_internal, args=(url,), daemon=True)
        t.start()

    def stop(self):
        self._stop_metadata_thread()
        self.state = PlayerState.STOPPED
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.free()
            except BassError:
                pass
            finally:
                self.stream = None

    def pause(self):
        if self.stream is not None and self.state == PlayerState.PLAYING:
            self.stream.pause()
            self.state = PlayerState.PAUSED

    def resume(self):
        if self.stream is not None and self.state == PlayerState.PAUSED:
            self.stream.play()
            self.state = PlayerState.PLAYING

    def set_volume(self, vol: float):
        self.volume = max(0.0, min(1.0, float(vol)))
        if self.stream is not None:
            try:
                self.stream.set_volume(self.volume)
            except BassError:
                pass

    def set_metadata_callback(self, callback):
        self.metadata_callback = callback

    # ------------------------------------------------------------------
    # ICY metadata thread
    # ------------------------------------------------------------------

    def _start_metadata_thread(self):
        self._stop_metadata = threading.Event()
        self._metadata_thread = threading.Thread(target=self._metadata_worker, daemon=True)
        self._metadata_thread.start()

    def _stop_metadata_thread(self):
        if self._metadata_thread:
            self._stop_metadata.set()
            self._metadata_thread.join(timeout=2)
            self._metadata_thread = None

    def _parse_icy_title(self, raw: str) -> str:
        """Extract StreamTitle from ICY metadata string."""
        m = re.search(r"StreamTitle='([^']*)'", raw)
        if m:
            return m.group(1).strip()
        return raw.strip()

    def _metadata_worker(self):
        last_title = None
        while not self._stop_metadata.is_set():
            if self.state != PlayerState.PLAYING or not self.stream:
                break
            try:
                tags = self.stream.get_tags()
                if tags:
                    raw = tags.decode(errors="replace")
                    title = self._parse_icy_title(raw)
                    if title and title != last_title:
                        last_title = title
                        if self.metadata_callback:
                            self.metadata_callback(title)
            except Exception:
                pass
            self._stop_metadata.wait(timeout=2.0)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self):
        self.stop()
        self.output.free()
