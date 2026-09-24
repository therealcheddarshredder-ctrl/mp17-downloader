import os,re,subprocess,threading,time,uuid,json
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI,HTTPException,Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
OUTPUT_DIR=Path(os.getenv("OUTPUT_DIR","/data/downloads")); OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
JOB_TTL=int(os.getenv("JOB_TTL_SECONDS","900")); MAX_DURATION=int(os.getenv("MAX_DURATION_SECONDS","3600")); MAX_FILE_BYTES=int(os.getenv("MAX_FILE_BYTES",str(1024*1024*1024)))
app=FastAPI(title="MP17 Downloader",version="1.0.0")
app.add_middleware(CORSMiddleware,allow_origins=["https://mp17.higgsfield.app"],allow_methods=["GET","POST","OPTIONS"],allow_headers=["content-type"])
jobs={}; lock=threading.Lock(); active_by_ip={}
class ConvertRequest(BaseModel):
    url:str; format:str=Field(pattern="^(mp3|mp4)$"); quality:str="192"; fps:int=60; bitrate:int=12
def youtube_url(url):
    try:
        u=urlparse(url.strip()); return u.scheme in {"http","https"} and u.hostname and u.hostname.lower().removeprefix("www.") in {"youtube.com","youtu.be"}
    except: return False
def safe_title(title): return re.sub(r"[^A-Za-z0-9._ -]+","",title).strip()[:120] or "MP17"
def set_job(j,**v):
    with lock: jobs[j].update(v)
def cleanup_loop():
    while True:
        time.sleep(60); now=time.time()
        with lock:
            for j in [x for x,y in jobs.items() if y.get("finished_at") and now-y["finished_at"]>JOB_TTL]:
                p=jobs[j].get("path")
                if p:
                    try: Path(p).unlink(missing_ok=True)
                    except: pass
                jobs.pop(j,None)
threading.Thread(target=cleanup_loop,daemon=True).start()
def run_conversion(j,req):
    work=OUTPUT_DIR/j; work.mkdir(parents=True,exist_ok=True)
    try:
        set_job(j,status="processing")
        meta=subprocess.run(["yt-dlp","--js-runtimes","node","--no-playlist","--dump-single-json","--skip-download",req.url],capture_output=True,text=True,timeout=45,check=True)
        info=json.loads(meta.stdout); duration=int(info.get("duration") or 0)
        if duration>MAX_DURATION: raise RuntimeError("Video is longer than the 60-minute limit.")
        title=safe_title(info.get("title") or "MP17")
        if req.format=="mp3":
            q=req.quality if req.quality in {"128","192","320"} else "192"; template=str(work/f"{title}.%(ext)s")
            cmd=["yt-dlp","--js-runtimes","node","--no-playlist","-x","--audio-format","mp3","--audio-quality",f"{q}K","-o",template,req.url]
        else:
            template=str(work/"source.%(ext)s")
            cmd=["yt-dlp","--js-runtimes","node","--no-playlist","-f","bv*[height<=1080][fps<=60][vcodec^=avc1]+ba[acodec^=mp4a]/bv*[height<=1080][fps<=60]+ba/b","-o",template,req.url]
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=900)
        if r.returncode: raise RuntimeError((r.stderr or r.stdout or "Conversion failed")[-1500:])
        files=[p for p in work.iterdir() if p.is_file() and p.suffix.lower() in {".mp3",".mp4",".m4a",".webm",".mkv"}]
        if not files: raise RuntimeError("No output file was produced.")
        source=files[0]; final=work/(f"{title}.mp3" if req.format=="mp3" else f"{title}.mp4")
        if req.format=="mp3" and source.suffix.lower()!=".mp3":
            r=subprocess.run(["ffmpeg","-y","-i",str(source),"-vn","-codec:a","libmp3lame","-b:a",f"{req.quality}k",str(final)],capture_output=True,text=True,timeout=600)
            if r.returncode: raise RuntimeError((r.stderr or "FFmpeg failed")[-1500:])
            source.unlink(missing_ok=True)
        elif req.format=="mp4":
            r=subprocess.run(["ffmpeg","-y","-i",str(source),"-c:v","libx264","-preset","veryfast","-b:v",f"{req.bitrate}M","-maxrate",f"{req.bitrate}M","-bufsize",f"{req.bitrate*2}M","-r",str(req.fps),"-c:a","aac","-b:a","192k","-movflags","+faststart",str(final)],capture_output=True,text=True,timeout=1800)
            if r.returncode: raise RuntimeError((r.stderr or "FFmpeg failed")[-1500:])
            source.unlink(missing_ok=True)
        if final.stat().st_size>MAX_FILE_BYTES: final.unlink(missing_ok=True); raise RuntimeError("The resulting file is too large.")
        set_job(j,status="finished",filename=final.name,path=str(final),finished_at=time.time())
    except Exception as e: set_job(j,status="error",error=str(e),finished_at=time.time())
    finally:
        with lock:
            ip=jobs.get(j,{}).get("ip")
            if ip in active_by_ip: active_by_ip[ip]=(max(0,active_by_ip[ip][0]-1),time.time())
@app.get("/")
def health(): return {"status":"ok","service":"MP17 Downloader"}
@app.post("/request")
def request_conversion(body:ConvertRequest,request:Request):
    if not youtube_url(body.url): raise HTTPException(400,"Invalid YouTube URL.")
    ip=request.client.host if request.client else "unknown"
    with lock:
        count,_=active_by_ip.get(ip,(0,time.time()))
        if count>=2: raise HTTPException(429,"Too many active downloads. Please wait.")
        active_by_ip[ip]=(count+1,time.time())
    j=str(uuid.uuid4())
    with lock: jobs[j]={"status":"queued","ip":ip,"created_at":time.time()}
    threading.Thread(target=run_conversion,args=(j,body),daemon=True).start()
    return {"job_id":j,"status":"queued"}
@app.get("/status")
def status(job_id:str):
    with lock:
        job=jobs.get(job_id)
        if not job: raise HTTPException(404,"Job not found.")
        out={k:v for k,v in job.items() if k not in {"path","ip"}}
    if out.get("status")=="finished": out["downloadUrl"]=f"/result?id={job_id}"
    return out
@app.get("/result")
def result(job_id:str):
    with lock: job=jobs.get(job_id)
    if not job: raise HTTPException(404,"Job not found.")
    if job.get("status")!="finished": raise HTTPException(409,"Download is not ready yet.")
    p=Path(job["path"])
    if not p.exists(): raise HTTPException(404,"File expired.")
    return FileResponse(p,media_type="audio/mpeg" if p.suffix==".mp3" else "video/mp4",filename=job["filename"],headers={"Cache-Control":"private, max-age=60"})