# main.py
import os
import logging
from flask import Flask, request, jsonify, render_template
import yt_dlp

# Disable logging for yt-dlp to keep console clean
logging.getLogger('yt-dlp').setLevel(logging.ERROR)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-for-replit')

# Define supported platforms and their options
def get_video_info(url):
    """
    Extract video information including direct download URL, thumbnail, and title.
    For TikTok: specifically tries to get no-watermark version.
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'force_generic_extractor': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info
            info = ydl.extract_info(url, download=False)
            
            # Determine best format (highest quality video+audio)
            # For TikTok, yt-dlp automatically prefers no-watermark if available
            if 'formats' in info and len(info['formats']) > 0:
                # Find best quality with both video and audio
                best_format = None
                for f in info['formats']:
                    if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                        if best_format is None or f.get('height', 0) > best_format.get('height', 0):
                            best_format = f
                if best_format:
                    download_url = best_format['url']
                else:
                    # Fallback to first format
                    download_url = info['formats'][0]['url']
            else:
                download_url = info.get('url')
            
            # Extract metadata
            result = {
                'title': info.get('title', 'Video'),
                'thumbnail': info.get('thumbnail', ''),
                'download_url': download_url,
                'duration': info.get('duration', 0),
                'platform': info.get('extractor_key', 'Unknown')
            }
            return result, None
            
    except Exception as e:
        error_msg = str(e)
        # Provide user-friendly error messages
        if 'Unsupported URL' in error_msg or 'not supported' in error_msg.lower():
            error_msg = "This link is not supported. Please use TikTok, Instagram, or YouTube links."
        elif 'private' in error_msg.lower() or 'login' in error_msg.lower():
            error_msg = "This video is private or requires login."
        elif 'unavailable' in error_msg.lower():
            error_msg = "This video is unavailable or has been removed."
        
        return None, error_msg

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
    
    return jsonify({
        'success': True,
        'title': video_info['title'],
        'thumbnail': video_info['thumbnail'],
        'download_url': video_info['download_url'],
        'duration': video_info['duration']
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
