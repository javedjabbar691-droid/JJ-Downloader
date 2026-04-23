# main.py
import os
import logging
import requests
import re
import json
from flask import Flask, request, jsonify, render_template, Response
import yt_dlp

logging.getLogger('yt-dlp').setLevel(logging.ERROR)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-for-render')

# Browser headers that mimic a real user
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
}

# Simple cookie file path (will be created automatically)
COOKIE_FILE = 'cookies.txt'

def create_default_cookies():
    """Create a minimal cookies file to avoid bot detection"""
    if not os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, 'w') as f:
            # Write Netscape format cookie file header
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# This is a generated file - do not edit\n\n")

def get_video_info(url):
    """Extract video info with cookies to avoid bot detection"""
    
    # Create cookie file if it doesn't exist
    create_default_cookies()
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'headers': BROWSER_HEADERS,
        'user_agent': BROWSER_HEADERS['User-Agent'],
        'cookiefile': COOKIE_FILE,  # Use cookies file
        'ignoreerrors': True,
        'no_check_certificate': True,
        'sleep_interval': 2,  # Slow down to avoid detection
        'max_sleep_interval': 5,
        'sleep_interval_requests': 1,
    }
    
    # Special handling for different platforms
    if 'youtube.com' in url or 'youtu.be' in url:
        ydl_opts['extractor_args'] = {
            'youtube': {
                'skip': ['hls', 'dash'],
                'player_client': ['android', 'web'],  # Use android client to avoid bot detection
            }
        }
    elif 'tiktok.com' in url:
        ydl_opts['extractor_args'] = {
            'tiktok': {
                'api_hostname': ['www.tiktok.com'],
            }
        }
        # Handle TikTok short URLs
        if 'vt.tiktok.com' in url or '/t/' in url:
            try:
                response = requests.head(url, headers=BROWSER_HEADERS, allow_redirects=True, timeout=10)
                url = response.url
            except:
                pass
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info
            info = ydl.extract_info(url, download=False)
            
            if info is None:
                return None, "Could not extract video info. The video might be private or unavailable."
            
            # Handle playlist/entries
            if 'entries' in info and info['entries']:
                info = info['entries'][0]
                if info is None:
                    return None, "No valid video found in the playlist."
            
            # Get download URL
            download_url = None
            best_height = 0
            
            # Try to get best format
            if 'formats' in info and info['formats']:
                # Find best video+audio format
                for f in info['formats']:
                    if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                        height = f.get('height', 0)
                        if height > best_height:
                            download_url = f['url']
                            best_height = height
                
                # If no video+audio, get any video format
                if not download_url:
                    for f in info['formats']:
                        if f.get('vcodec') != 'none':
                            download_url = f['url']
                            break
            
            # Fallback to direct URL
            if not download_url:
                download_url = info.get('url')
            
            if not download_url:
                return None, "No downloadable video URL found. The video might be age-restricted or unavailable."
            
            # Get title safely
            title = info.get('title', 'video')
            title = re.sub(r'[<>:"/\\|?*]', '', title)
            title = title[:100] if title else 'video'
            
            if not title or title == 'video' or title == '':
                import time
                title = f"video_{int(time.time())}"
            
            # Get thumbnail
            thumbnail = info.get('thumbnail', '')
            if not thumbnail and 'thumbnails' in info and info['thumbnails']:
                thumbnail = info['thumbnails'][-1]['url'] if info['thumbnails'] else ''
            
            result = {
                'title': title,
                'thumbnail': thumbnail,
                'download_url': download_url,
                'duration': info.get('duration', 0),
            }
            
            return result, None
            
    except Exception as e:
        error_msg = str(e)
        logging.error(f"yt-dlp error: {error_msg}")
        
        # User-friendly errors
        if 'Sign in to confirm' in error_msg or 'bot' in error_msg.lower():
            error_msg = "YouTube is blocking this request. Please try a different video or use a YouTube link that doesn't require age verification."
        elif 'private' in error_msg.lower():
            error_msg = "This video is private or requires login."
        elif 'unavailable' in error_msg.lower() or 'removed' in error_msg.lower():
            error_msg = "This video has been removed or is unavailable."
        elif 'age' in error_msg.lower() or 'restricted' in error_msg.lower():
            error_msg = "This video is age-restricted and cannot be downloaded."
        elif 'not supported' in error_msg.lower():
            error_msg = "This link format is not supported."
        else:
            error_msg = f"Failed to process video: {error_msg[:100]}"
        
        return None, error_msg

def stream_video_from_url(download_url):
    """Stream video with proper headers"""
    try:
        headers = {
            'User-Agent': BROWSER_HEADERS['User-Agent'],
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Range': 'bytes=0-',
        }
        
        # Add referer based on URL
        if 'youtube.com' in download_url or 'googlevideo.com' in download_url:
            headers['Referer'] = 'https://www.youtube.com/'
        elif 'tiktok.com' in download_url or 'tiktokcdn.com' in download_url:
            headers['Referer'] = 'https://www.tiktok.com/'
        elif 'instagram.com' in download_url or 'cdninstagram.com' in download_url:
            headers['Referer'] = 'https://www.instagram.com/'
        
        response = requests.get(download_url, headers=headers, stream=True, timeout=60)
        
        # Handle 403 errors
        if response.status_code == 403:
            # Try without Range header
            headers.pop('Range', None)
            response = requests.get(download_url, headers=headers, stream=True, timeout=60)
        
        response.raise_for_status()
        
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        
        content_type = response.headers.get('content-type', 'video/mp4')
        return generate(), content_type
        
    except Exception as e:
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
    
    # Validate URL format
    if not video_url.startswith(('http://', 'https://')):
        video_url = 'https://' + video_url
    
    # Get video info
    video_info, error = get_video_info(video_url)
    
    if error:
        return jsonify({'error': error}), 400
    
    if not video_info:
        return jsonify({'error': 'Could not process video. Try a different link.'}), 400
    
    # Store in cache
    if not hasattr(app, 'video_cache'):
        app.video_cache = {}
    
    import uuid
    video_id = str(uuid.uuid4())
    app.video_cache[video_id] = {
        'download_url': video_info['download_url'],
        'title': video_info['title']
    }
    
    # Clean old cache (keep last 20)
    if len(app.video_cache) > 20:
        keys = list(app.video_cache.keys())
        for key in keys[:-20]:
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
        return jsonify({'error': 'Video expired. Please try again.'}), 404
    
    video_data = app.video_cache[video_id]
    download_url = video_data['download_url']
    title = video_data['title']
    
    del app.video_cache[video_id]
    
    try:
        stream_generator, content_type = stream_video_from_url(download_url)
        filename = f"{title}.mp4"
        
        return Response(
            stream_generator,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': content_type,
                'Cache-Control': 'no-cache, no-store, must-revalidate',
            }
        )
    except Exception as e:
        return jsonify({'error': f'Download failed: {str(e)}'}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
