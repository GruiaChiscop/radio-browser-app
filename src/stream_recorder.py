import threading
import requests


class StreamRecorder(threading.Thread):
    def __init__(self, url, filename):
        super().__init__()
        self.url = url
        self.filename = filename
        self._stop_event = threading.Event()
        self.daemon = True

    def run(self):
        try:
            with requests.get(
                self.url,
                stream=True,
                timeout=(10, 2),  # (connect, read) — read times out in 2 s max
                headers={"User-Agent": "RadioBrowserPlayer/1.0"},
            ) as response:
                response.raise_for_status()
                with open(self.filename, "wb") as f:
                    for chunk in response.iter_content(chunk_size=4096):
                        if self._stop_event.is_set():
                            break
                        if chunk:
                            f.write(chunk)
        except requests.exceptions.ReadTimeout:
            pass  # stop() was called; normal exit path
        except Exception as e:
            print(f"Recording error: {e}")

    def stop(self):
        self._stop_event.set()
