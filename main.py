from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import re

app = FastAPI(title="VidSnap API", version="1.0.0")

# CORS — allow vidsnap.site to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.vidsnap.site",
        "https://vidsnap.site",
        "https://vidsnap-rosy.vercel.app",
        "http://localhost",
        "http://127.0.0.1"
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

class URLRequest(BaseModel):
    url: str

def clean_quality(fmt):
    """Return a clean quality label from yt-dlp format info."""
    h = fmt.get("height")
    if h:
        if h >= 2160: return "4K"
        if h >= 1080: return "1080p"
        if h >= 720:  return "720p"
        if h >= 480:  return "480p"
        if h >= 360:  return "360p"
        return f"{h}p"
    note = fmt.get("format_note", "")
    if note: return note
    return "HD"

@app.get("/")
def root():
    return {"status": "VidSnap API is running ✅"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/download")
def download(url: str):
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "cookiesfrombrowser": None,
        "extractor_args": {},
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=422, detail=f"Could not extract: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    title     = info.get("title", "Video")
    thumbnail = info.get("thumbnail", "")
    duration  = info.get("duration", 0)
    uploader  = info.get("uploader", "")
    webpage   = info.get("webpage_url", url)

    formats_raw = info.get("formats") or []
    medias = []

    # --- Video formats (with audio merged or has audio) ---
    video_fmts = []
    for f in formats_raw:
        vcodec = f.get("vcodec", "none")
        acodec = f.get("acodec", "none")
        furl   = f.get("url", "")
        ext    = f.get("ext", "mp4")
        height = f.get("height")

        if not furl or furl.startswith("manifest"):
            continue
        if vcodec == "none" or not vcodec:
            continue
        # prefer formats that have both video+audio
        has_audio = acodec and acodec != "none"
        if height and height >= 144:
            video_fmts.append({
                "url": furl,
                "ext": ext if ext in ["mp4","webm","mkv"] else "mp4",
                "quality": clean_quality(f),
                "height": height or 0,
                "has_audio": has_audio,
                "tbr": f.get("tbr", 0) or 0
            })

    # Sort by height desc, prefer has_audio
    video_fmts.sort(key=lambda x: (x["height"], x["has_audio"], x["tbr"]), reverse=True)

    # Deduplicate by quality label — keep best per quality
    seen_q = {}
    for vf in video_fmts:
        q = vf["quality"]
        if q not in seen_q:
            seen_q[q] = vf

    for vf in seen_q.values():
        medias.append({
            "url":       vf["url"],
            "extension": vf["ext"],
            "quality":   vf["quality"],
            "type":      "video"
        })

    # --- Audio only ---
    audio_fmts = []
    for f in formats_raw:
        vcodec = f.get("vcodec", "none")
        acodec = f.get("acodec", "none")
        furl   = f.get("url", "")
        if not furl: continue
        if (vcodec == "none" or not vcodec) and acodec and acodec != "none":
            audio_fmts.append({
                "url":  furl,
                "ext":  f.get("ext", "mp3"),
                "abr":  f.get("abr", 0) or 0,
                "tbr":  f.get("tbr", 0) or 0
            })

    if audio_fmts:
        audio_fmts.sort(key=lambda x: x["abr"] or x["tbr"], reverse=True)
        best_audio = audio_fmts[0]
        medias.append({
            "url":       best_audio["url"],
            "extension": "mp3",
            "quality":   "Audio MP3",
            "type":      "audio"
        })

    # Fallback — if no formats parsed, use direct url
    if not medias and info.get("url"):
        medias.append({
            "url":       info["url"],
            "extension": info.get("ext", "mp4"),
            "quality":   "Best Quality",
            "type":      "video"
        })

    return {
        "success":   True,
        "title":     title,
        "thumbnail": thumbnail,
        "duration":  duration,
        "uploader":  uploader,
        "webpage":   webpage,
        "medias":    medias
    }
