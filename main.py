# main.py
import os
import logging
import requests
from flask import Flask, request, jsonify, render_template, Response
import yt_dlp

# Disable logging for yt-dlp to keep console clean
logging.getLogger('yt-dlp').setLevel(logging.ERROR)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-for-render')

# Professional browser headers to avoid blocking
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0',
    'Referer': 'https://www.tiktok.com/',
}

def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '')
    filename = ''.join(char for char in filename if ord(char) < 128)
    return filename[:100]

def get_video_info(url):
    """
    Extract video information using yt-dlp with TikTok-specific options
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'force_generic_extractor': False,
        'headers': BROWSER_HEADERS,
        'user_agent': BROWSER_HEADERS['User-Agent'],
        'referer': 'https://www.tiktok.com/',
        # TikTok specific options
        'extractor_args': {
            'tiktok': {
                'api_hostname': ['www.tiktok.com'],
                'embed_url': ['https://www.tiktok.com/embed'],
            }
        }
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info
            info = ydl.extract_info(url, download=False)
            
            # Get the best format URL
            download_url = None
            
            # Try to get the no-watermark version first
            if 'formats' in info and len(info['formats']) > 0:
                # Priority: video+audio with best quality, prefer no-watermark
                best_format = None
                best_quality = -1
                
                for f in info['formats']:
                    # Check if it's a video format
                    if f.get('vcodec') != 'none':
                        # Prefer formats with both video and audio
                        quality_score = 0
                        if f.get('acodec') != 'none':
                            quality_score = 1000
                        
                        # Add resolution bonus
                        height = f.get('height', 0)
                        if height:
                            quality_score += height
                        
                        # Check for no-watermark in format note
                        format_note = f.get('format_note', '').lower()
                        if 'watermark' not in format_note:
                            quality_score += 10000  # Strong preference for no-watermark
                        
                        if quality_score > best_quality:
                            best_quality = quality_score
                            best_format = f
                
                if best_format:
                    download_url = best_format['url']
                else:
                    # Fallback to first video format
                    for f in info['formats']:
                        if f.get('vcodec') != 'none':
                            download_url = f['url']
                            break
            
            # If no format found, try direct URL
            if not download_url:
                download_url = info.get('url')
            
            # For TikTok, sometimes the direct URL is in 'url' field
            if not download_url and 'entries' in info:
                # Handle playlist/redirect cases
                first_entry = info['entries'][0] if info['entries'] else None
                if first_entry and 'url' in first_entry:
                    download_url = first_entry['url']
            
            # Clean title
            title = info.get('title', 'tiktok_video')
            title = sanitize_filename(title)
            if not title or title == 'tiktok_video':
                import time
                title = f"tiktok_video_{int(time.time())}"
            
            result = {
                'title': title,
                'thumbnail': info.get('thumbnail', ''),
                'download_url': download_url,
                'duration': info.get('duration', 0),
                'platform': info.get('extractor_key', 'Unknown'),
                'ext': 'mp4'
            }
            
            # Validate we got a download URL
            if not result['download_url']:
                return None, "Could not extract video URL. The video might be protected."
            
            return result, None
            
    except Exception as e:
        error_msg = str(e)
        logging.error(f"yt-dlp error: {error_msg}")
        
        # Provide user-friendly error messages
        if 'Unsupported URL' in error_msg or 'not supported' in error_msg.lower():
            error_msg = "This link is not supported. Please use TikTok, Instagram, or YouTube links."
        elif 'private' in error_msg.lower() or 'login' in error_msg.lower():
            error_msg = "This video is private or requires login."
        elif 'unavailable' in error_msg.lower() or 'removed' in error_msg.lower():
            error_msg = "This video is unavailable or has been removed."
        elif '403' in error_msg or 'forbidden' in error_msg.lower():
            error_msg = "Access denied. Please try a different video or check if it's public."
        
        return None, error_msg

def stream_video_from_url(download_url):
    """
    Stream video from URL with TikTok-specific headers to avoid 403
    """
    try:
        # Enhanced headers for TikTok CDN
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'video/webm,video/mp4,video/*;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'https://www.tiktok.com/',
            'Origin': 'https://www.tiktok.com',
            'Sec-Fetch-Dest': 'video',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'cross-site',
            'Range': 'bytes=0-',
        }
        
        # First attempt with full headers
        response = requests.get(download_url, headers=headers, stream=True, timeout=30)
        
        # If 403, try with fewer headers
        if response.status_code == 403:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.tiktok.com/',
                'Range': 'bytes=0-',
            }
            response = requests.get(download_url, headers=headers, stream=True, timeout=30)
        
        response.raise_for_status()
        
        # Stream the content in chunks
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        
        # Get content type from response
        content_type = response.headers.get('content-type', 'video/mp4')
        
        # Ensure it's a video type
        if 'text' in content_type:
            content_type = 'video/mp4'
        
        return generate(), content_type
        
    except requests.exceptions.RequestException as e:
        logging.error(f"Streaming failed: {str(e)}")
        raise e

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download_video():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({'error': 'No URL provided'}), 400
    
    video_url = data['url'].strip()
    if not video_url:
        return jsonify({'error': 'URL cannot be empty'}), 400
    
    # Expand TikTok short URLs
    if 'tiktok.com' in video_url and ('vt.tiktok' in video_url or 'tiktok.com/t' in video_url):
        try:
            response = requests.head(video_url, headers=BROWSER_HEADERS, allow_redirects=True, timeout=10)
            video_url = response.url
        except:
            pass
    
    video_info, error = get_video_info(video_url)
    
    if error:
        return jsonify({'error': error}), 400
    
    if not video_info or not video_info.get('download_url'):
        return jsonify({'error': 'Could not extract video. Try a different link.'}), 400
    
    if not hasattr(app, 'video_cache'):
        app.video_cache = {}
    
    import uuid
    video_id = str(uuid.uuid4())
    app.video_cache[video_id] = {
        'download_url': video_info['download_url'],
        'title': video_info['title'],
        'ext': video_info.get('ext', 'mp4')
    }
    
    if len(app.video_cache) > 30:
        keys = list(app.video_cache.keys())
        for key in keys[:-30]:
            del app.video_cache[key]
    
    return jsonify({
        'success': True,
        'title': video_info['title'],
        'thumbnail': video_info['thumbnail'],
        'video_id': video_id,
        'duration': video_info['duration']
    })

@app.route('/proxy_download/<video_id>')
def proxy_download(video_id):
    if not hasattr(app, 'video_cache') or video_id not in app.video_cache:
        return jsonify({'error': 'Video not found or expired. Please try again.'}), 404
    
    video_data = app.video_cache[video_id]
    download_url = video_data['download_url']
    title = video_data['title']
    ext = video_data.get('ext', 'mp4')
    
    del app.video_cache[video_id]
    
    try:
        stream_generator, content_type = stream_video_from_url(download_url)
        
        filename = f"{title}.{ext}"
        
        return Response(
            stream_generator,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': content_type,
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
        )
        
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Download timeout. Please try again.'}), 504
    except requests.exceptions.RequestException as e:
        logging.error(f"Proxy download error: {str(e)}")
        return jsonify({'error': 'Failed to fetch video. Please try again.'}), 500
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred. Please try again.'}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
