import requests
import urllib.parse
from typing import Dict, Tuple, Optional
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

class StreamChecker:
    """
    A comprehensive stream validator that checks if URLs are valid streaming sources.
    Supports audio and video streams in various formats.
    """
    
    # Common streaming MIME types
    STREAM_CONTENT_TYPES = {
        'audio/mpeg', 'audio/mp3', 'audio/aac', 'audio/aacp',
        'audio/ogg', 'audio/opus', 'audio/flac', 'audio/wav',
        'audio/x-wav', 'audio/wave', 'audio/vnd.wave',
        'audio/mp4', 'audio/x-m4a', 'audio/webm',
        'video/mp4', 'video/webm', 'video/ogg', 'video/x-flv',
        'video/mp2t', 'video/3gpp', 'video/quicktime',
        'application/vnd.apple.mpegurl', 'application/x-mpegurl',
        'application/dash+xml', 'application/octet-stream'
    }
    
    # Streaming file extensions
    STREAM_EXTENSIONS = {
        '.m3u', '.m3u8', '.pls', '.asx', '.xspf',
        '.mp3', '.aac', '.ogg', '.flac', '.wav',
        '.mp4', '.webm', '.flv', '.ts', '.m4a'
    }
    
    def __init__(self, timeout: int = 10, max_redirect: int = 5):
        """
        Initialize the StreamChecker.
        
        Args:
            timeout: Maximum time to wait for response (seconds)
            max_redirect: Maximum number of redirects to follow
        """
        self.timeout = timeout
        self.max_redirect = max_redirect
        self.session = requests.Session()
        self.session.max_redirects = max_redirect
        
    def is_valid_stream(self, url: str, check_playability: bool = True) -> Dict:
        """
        Check if a URL is a valid stream.
        
        Args:
            url: The URL to check
            check_playability: If True, attempts to read stream data
            
        Returns:
            Dict with keys:
                - valid: Boolean indicating if stream is valid
                - reason: String explaining the result
                - content_type: The detected content type (if available)
                - status_code: HTTP status code (if available)
                - stream_type: Type of stream detected
        """
        result = {
            'valid': False,
            'reason': '',
            'content_type': None,
            'status_code': None,
            'stream_type': None
        }
        
        # Validate URL format
        if not self._is_valid_url(url):
            result['reason'] = 'Invalid URL format'
            return result
        
        # Check URL extension
        stream_type = self._check_url_extension(url)
        if stream_type:
            result['stream_type'] = stream_type
        
        try:
            # Send HEAD request first (efficient)
            head_valid, head_result = self._check_with_head(url)
            
            if head_valid:
                result.update(head_result)
                result['valid'] = True
                return result
            
            # If HEAD fails or is inconclusive, try GET with streaming
            get_valid, get_result = self._check_with_get(url, check_playability)
            
            if get_valid:
                result.update(get_result)
                result['valid'] = True
                return result
            
            # Merge failure reasons
            result.update(get_result)
            
        except requests.exceptions.Timeout:
            result['reason'] = 'Request timeout'
        except requests.exceptions.TooManyRedirects:
            result['reason'] = 'Too many redirects'
        except requests.exceptions.ConnectionError:
            result['reason'] = 'Connection error'
        except requests.exceptions.RequestException as e:
            result['reason'] = f'Request error: {str(e)}'
        except Exception as e:
            result['reason'] = f'Unexpected error: {str(e)}'
        
        return result
    
    def _is_valid_url(self, url: str) -> bool:
        """Validate URL format."""
        try:
            parsed = urllib.parse.urlparse(url)
            return bool(parsed.scheme in ['http', 'https'] and parsed.netloc)
        except Exception:
            return False
    
    def _check_url_extension(self, url: str) -> Optional[str]:
        """Check if URL has a streaming file extension."""
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.lower()
        
        for ext in self.STREAM_EXTENSIONS:
            if path.endswith(ext):
                if ext in ['.m3u', '.m3u8']:
                    return 'HLS playlist'
                elif ext == '.pls':
                    return 'PLS playlist'
                elif ext in ['.mp3', '.aac', '.ogg', '.flac', '.wav', '.m4a']:
                    return 'Audio stream'
                elif ext in ['.mp4', '.webm', '.flv', '.ts']:
                    return 'Video stream'
        return None
    
    def _check_with_head(self, url: str) -> Tuple[bool, Dict]:
        """Perform HEAD request to check headers."""
        result = {
            'reason': '',
            'content_type': None,
            'status_code': None,
            'stream_type': None
        }
        
        try:
            response = self.session.head(
                url,
                timeout=self.timeout,
                allow_redirects=True,
                headers={'User-Agent': 'Mozilla/5.0 (compatible; StreamChecker/1.0)'}
            )
            
            result['status_code'] = response.status_code
            
            if response.status_code != 200:
                result['reason'] = f'HTTP {response.status_code}'
                return False, result
            
            content_type = response.headers.get('Content-Type', '').lower()
            result['content_type'] = content_type
            
            # Check if content type indicates streaming
            for stream_type in self.STREAM_CONTENT_TYPES:
                if stream_type in content_type:
                    result['reason'] = 'Valid stream (HEAD check)'
                    result['stream_type'] = self._categorize_stream(content_type)
                    return True, result
            
            # Check for ICY protocol (Shoutcast/Icecast)
            if 'icy-name' in response.headers or 'icy-metaint' in response.headers:
                result['reason'] = 'Valid ICY stream'
                result['stream_type'] = 'ICY/Shoutcast stream'
                return True, result
            
            result['reason'] = 'Content type not recognized as stream'
            return False, result
            
        except Exception as e:
            result['reason'] = f'HEAD request failed: {str(e)}'
            return False, result
    
    def _check_with_get(self, url: str, check_playability: bool) -> Tuple[bool, Dict]:
        """Perform GET request with streaming to verify actual stream data."""
        result = {
            'reason': '',
            'content_type': None,
            'status_code': None,
            'stream_type': None
        }
        
        try:
            response = self.session.get(
                url,
                timeout=self.timeout,
                stream=True,
                allow_redirects=True,
                headers={'User-Agent': 'Mozilla/5.0 (compatible; StreamChecker/1.0)'}
            )
            
            result['status_code'] = response.status_code
            
            if response.status_code != 200:
                result['reason'] = f'HTTP {response.status_code}'
                return False, result
            
            content_type = response.headers.get('Content-Type', '').lower()
            result['content_type'] = content_type
            
            # Check ICY headers
            if 'icy-name' in response.headers or 'icy-metaint' in response.headers:
                result['reason'] = 'Valid ICY stream'
                result['stream_type'] = 'ICY/Shoutcast stream'
                return True, result
            
            # Check content type
            for stream_type in self.STREAM_CONTENT_TYPES:
                if stream_type in content_type:
                    result['stream_type'] = self._categorize_stream(content_type)
                    
                    if check_playability:
                        # Try to read some data to verify stream is active
                        if self._verify_stream_data(response):
                            result['reason'] = 'Valid and active stream'
                            return True, result
                        else:
                            result['reason'] = 'Stream not providing data'
                            return False, result
                    else:
                        result['reason'] = 'Valid stream (content type)'
                        return True, result
            
            # If no recognized content type, try reading data anyway
            if check_playability and self._verify_stream_data(response):
                result['reason'] = 'Active stream (unrecognized type)'
                result['stream_type'] = 'Unknown stream type'
                return True, result
            
            result['reason'] = 'Not recognized as a valid stream'
            return False, result
            
        except Exception as e:
            result['reason'] = f'GET request failed: {str(e)}'
            return False, result
    def _verify_stream_data(self, response: requests.Response, min_bytes: int = 1024) -> bool:
        """Verify that stream is providing actual binary data (not HTML)."""
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(lambda: b"".join(next(response.iter_content(chunk_size=min_bytes)) for _ in range(1)))
                try:
                    chunk = future.result(timeout=5)
                    if not chunk:
                        return False
                    # Reject text-based responses (HTML, JSON, XML)
                    if chunk.strip().startswith(b"<") or b"<!DOCTYPE html" in chunk[:200].lower():
                        return False
                    if b"html" in chunk[:200].lower():
                        return False
                    return True
                except FuturesTimeoutError:
                    return False
        except Exception:
            return False
        finally:
            response.close()
    def _categorize_stream(self, content_type: str) -> str:
        """Categorize stream type based on content type."""
        if 'audio' in content_type:
            return 'Audio stream'
        elif 'video' in content_type:
            return 'Video stream'
        elif 'mpegurl' in content_type or 'm3u' in content_type:
            return 'HLS playlist'
        elif 'dash' in content_type:
            return 'DASH stream'
        else:
            return 'Unknown stream type'
    
    def check_multiple_streams(self, urls: list, check_playability: bool = True) -> Dict[str, Dict]:
        """
        Check multiple streams concurrently.
        
        Args:
            urls: List of URLs to check
            check_playability: If True, attempts to read stream data
            
        Returns:
            Dictionary mapping URLs to their check results
        """
        results = {}
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_url = {
                executor.submit(self.is_valid_stream, url, check_playability): url 
                for url in urls
            }
            
            for future in future_to_url:
                url = future_to_url[future]
                try:
                    results[url] = future.result(timeout=self.timeout + 5)
                except Exception as e:
                    results[url] = {
                        'valid': False,
                        'reason': f'Check failed: {str(e)}',
                        'content_type': None,
                        'status_code': None,
                        'stream_type': None
                    }
        
        return results
    
    def __del__(self):
        """Cleanup session on deletion."""
        if hasattr(self, 'session'):
            self.session.close()
