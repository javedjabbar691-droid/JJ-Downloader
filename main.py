# main.py
import os
import logging
import tempfile
import requests
from flask import Flask, request, jsonify, render_template, send_file
import yt_dlp

# Disable logging for yt-dlp to keep console clean
logging.getLogger('yt-dlp').setLevel(logging.ERROR)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-for-replit')

def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '')
    return filename[:100]  # Limit length

def download_video_file(download_url, title):
    """
    Download the video from the direct URL and save to a temporary file
    Returns the temporary file path
    """
    try:
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
        temp_path = temp_file.name
        
        # Download the video with streaming
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(download_url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()
        
        # Write to temporary file
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                temp_file.write(chunk)
                downloaded += len(chunk)
        
        temp_file.close()
        return temp_path
        
    except Exception as e:
        logging.error(f"Download failed: {str(e)}")
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise e

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
                best_quality = 0
                
                for f in info['formats']:
                    # Preference order: video+audio, then video only, then audio only
                    has_video = f.get('vcodec') != 'none'
                    has_audio = f.get('acodec') != 'none'
                    
                    # Prioritize formats with both video and audio
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
            
            # Extract metadata
            result = {
                'title': title,
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
    
    # For the save endpoint, we need to store the URL temporarily
    # We'll store it in a simple dict (in production, use a proper cache/db)
    if not hasattr(app, 'temp_videos'):
        app.temp_videos = {}
    
    import uuid
    video_id = str(uuid.uuid4())
    app.temp_videos[video_id] = {
        'download_url': video_info['download_url'],
        'title': video_info['title']
    }
    
    return jsonify({
        'success': True,
        'title': video_info['title'],
        'thumbnail': video_info['thumbnail'],
        'video_id': video_id,
        'duration': video_info['duration']
    })

@app.route('/save/<video_id>')
def save_video(video_id):
    """
    Download the video file and serve it as an attachment
    """
    if not hasattr(app, 'temp_videos') or video_id not in app.temp_videos:
        return jsonify({'error': 'Video not found or expired'}), 404
    
    video_data = app.temp_videos[video_id]
    download_url = video_data['download_url']
    title = video_data['title']
    
    # Clean up after retrieval
    del app.temp_videos[video_id]
    
    try:
        # Download the video to a temporary file
        temp_file_path = download_video_file(download_url, title)
        
        # Serve the file as attachment
        return send_file(
            temp_file_path,
            as_attachment=True,
            download_name=f"{title}.mp4",
            mimetype='video/mp4'
        )
        
    except Exception as e:
        logging.error(f"Save error: {str(e)}")
        return jsonify({'error': f'Failed to download video: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
