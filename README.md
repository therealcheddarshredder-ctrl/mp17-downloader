# MP17 Downloader Backend

FastAPI + yt-dlp + FFmpeg backend for MP17.

POST /request with {"url":"...","format":"mp3|mp4","quality":"128|192|320","fps":60,"bitrate":12}; poll /status?job_id=... and download /result?id=....

Only process media you are authorized to download or use. Do not use the service to bypass DRM or access controls.