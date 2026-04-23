# main.py
import os
import logging
import io
import requests
from flask import Flask, request, jsonify, render_template, send_file, Response
import yt_dlp

# Disable logging for yt-dlp to keep console clean
logging.getLogger('yt-dlp').setLevel(logging.ERROR)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-for-render')

# Professional browser headers to avoid blocking
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0',
}

def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '')
    # Remove emojis and other non-ASCII if needed
    filename = ''.join(char for char in filename if ord(char) < 128)
    return filename[:100]  # Limit length

def get_video_info(url):
    """
    Extract video information including direct download URL, thumbnail, and title.
    Uses yt-dlp with proper headers to avoid blocking.
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'force_generic_extractor': False,
        'headers': BROWSER_HEADERS,
        'user_agent': BROWSER_HEADERS['User-Agent'],
        'referer': 'https://www.tiktok.com/',
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info
            info = ydl.extract_info(url, download=False)
            
            # Determine best format (highest quality video+audio)
            if 'formats' in info and len(info['formats']) > 0:
                best_format = None
                best_quality = 0
                
                for f in info['formats']:
                    # Preference order: video+audio, then video only
                    has_video = f.get('vcodec') != 'none'
                    has_audio = f.get('acodec') != 'none'
                    
                    # Quality scoring
                    quality_score = 0
                    if has_video and has_audio:
                        quality_score = 3
                    elif has_video:
                        quality_score = 2
                    elif has_audio:
                        quality_score = 1
                    
                    # Check resolution for video
                    height = f.get('height', 0)
                    if height:
                        quality_score += height / 1000
                    
                    if quality_score > best_quality:
                        best_quality = quality_score
                        best_format = f
                
                if best_format:
                    download_url = best_format['url']
                else:
                    # Fallback to first format
                    download_url = info['formats'][0]['url']
            else:
                download_url = info.get('url')
            
            # Clean title for filename
            title = info.get('title', 'video')
            title = sanitize_filename(title)
            if not title or title == 'video':
                title = f"video_{abs(hash(download_url)) % 10000}"
            
            # Extract metadata
            result = {
                'title': title,
                'thumbnail': info.get('thumbnail', ''),
                'download_url': download_url,
                'duration': info.get('duration', 0),
                'platform': info.get('extractor_key', 'Unknown'),
                'ext': best_format.get('ext', 'mp4') if best_format else 'mp4'
            }
            return result, None
            
    except Exception as e:
        error_msg = str(e)
        # Provide user-friendly error messages
        if 'Unsupported URL' in error_msg or 'not supported' in error_msg.lower():
            error_msg = "This link is not supported. Please use TikTok, Instagram, or YouTube links."
        elif 'private' in error_msg.lower() or 'login' in error_msg.lower():
            error_msg = "This video is private or requires login."
        elif 'unavailable' in error_msg.lower() or 'removed' in error_msg.lower():
            error_msg = "This video is unavailable or has been removed."
        elif 'blocked' in error_msg.lower() or '429' in error_msg:
            error_msg = "Rate limited. Please try again in a few minutes."
        
        return None, error_msg

def stream_video_from_url(download_url):
    """
    Stream video from URL to memory using requests with proper headers.
    Returns a generator for streaming or BytesIO object.
    """
    try:
        # Make request with browser headers
        headers = BROWSER_HEADERS.copy()
        headers['Range'] = 'bytes=0-'  # Request full video
        
        response = requests.get(download_url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()
        
        # Stream the content in chunks
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        
        return generate(), response.headers.get('content-type', 'video/mp4')
        
    except Exception as e:
        logging.error(f"Streaming failed: {str(e)}")
        raise e

@app.route('/')
def index():
    """Serve the frontend page"""
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download_video():
    """
    API endpoint to process video URL and return download info.
    Expects JSON: {"url": "https://..."}
    """
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({'error': 'No URL provided'}), 400
    
    video_url = data['url'].strip()
    if not video_url:
        return jsonify({'error': 'URL cannot be empty'}), 400
    
    # Process the video
    video_info, error = get_video_info(video_url)
    
    if error:
        return jsonify({'error': error}), 400
    
    if not video_info or not video_info.get('download_url'):
        return jsonify({'error': 'Could not extract video. Try a different link.'}), 400
    
    # Store in memory cache (will be cleaned on next request or expire)
    if not hasattr(app, 'video_cache'):
        app.video_cache = {}
    
    import uuid
    video_id = str(uuid.uuid4())
    app.video_cache[video_id] = {
        'download_url': video_info['download_url'],
        'title': video_info['title'],
        'ext': video_info.get('ext', 'mp4')
    }
    
    # Clean up old entries (keep last 50)
    if len(app.video_cache) > 50:
        keys = list(app.video_cache.keys())
        for key in keys[:-50]:
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
    """
    Stream video directly from source to user without saving to disk.
    Uses memory streaming to comply with Render's free tier.
    """
    if not hasattr(app, 'video_cache') or video_id not in app.video_cache:
        return jsonify({'error': 'Video not found or expired. Please try again.'}), 404
    
    video_data = app.video_cache[video_id]
    download_url = video_data['download_url']
    title = video_data['title']
    ext = video_data.get('ext', 'mp4')
    
    # Remove from cache after retrieval to free memory
    del app.video_cache[video_id]
    
    try:
        # Get streaming generator
        stream_generator, content_type = stream_video_from_url(download_url)
        
        # Create filename
        filename = f"{title}.{ext}"
        
        # Send file as attachment with streaming
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
        return jsonify({'error': 'Download timeout. The video might be too large or server is slow.'}), 504
    except requests.exceptions.RequestException as e:
        logging.error(f"Proxy download error: {str(e)}")
        return jsonify({'error': f'Failed to fetch video: {str(e)}'}), 500
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred. Please try again.'}), 500

# Health check endpoint for Render
@app.route('/health')
def health():
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
