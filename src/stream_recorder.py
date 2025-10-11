import threading
import urllib.request
class StreamRecorder(threading.Thread):
    def __init__(self, url, filename):
        super().__init__()
        self.url = url
        self.filename = filename
        self.recording = True
        self.daemon = True
        
    def run(self):
        try:
            req = urllib.request.Request(self.url, headers={'User-Agent': 'RadioBrowserPlayer/1.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                with open(self.filename, 'wb') as f:
                    while self.recording:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
        except Exception as e:
            print(f"Recording error: {e}")
    
    def stop(self):
        self.recording = False
