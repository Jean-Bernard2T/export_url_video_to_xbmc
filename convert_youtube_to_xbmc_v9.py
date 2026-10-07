#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, re, json, shutil, subprocess
from xml.sax.saxutils import escape

# ---------------- utilitaires ----------------

def printDev(psTexte, psvaleur1=""):
    print(f"{psTexte}.{psvaleur1}")
    
# def printInfo(psTexte):
#     print(f"{psTexte}.")
    
def printInfo(psTexte, psvaleur1=""):
    print(f"{psTexte}.{psvaleur1}")
    
def printWarning(psTexte, psvaleur1=""):
    print(f"⚠️ {psTexte} {psvaleur1}.")

def printError(psTexte):
    print(f"⚠️ {psTexte}.")
    sys.exit(1)
    

def sanitize_filename(name, maxlen=200):
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    return name[:maxlen].strip()

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path

def download_thumb(url, path):
    if not url:
        return False
    try:
        import requests
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
        return True
    except Exception:
        return False

# ---------------- récupération métadonnées ----------------

def get_info_module(url):
    printInfo("--get_info_module({url}) ", url)
    try:
        import yt_dlp
        opts = {"quiet": True, "no_warnings": True, "simulate": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            printDev("Appel de ydl.extract_info({url}, download=False) ", url)
            return ydl.extract_info(url, download=False)
    except Exception:
        return None

def get_info_cli(url):
    yt_bin = shutil.which("yt-dlp") or shutil.which("youtube-dl")
    if not yt_bin:
        raise FileNotFoundError("yt-dlp non trouvé")
    cmd = [yt_bin, "--no-warnings", "--dump-json", url]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(completed.stdout.strip().splitlines()[0])

# ---------------- téléchargement ----------------

def download_video(url, outdir, base, fmt, container, use_module=True):
    outtmpl = os.path.join(outdir, base + ".%(ext)s")
    if use_module:
        import yt_dlp
        opts = {
            "format": fmt,
            "outtmpl": outtmpl,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["all"],
            "subtitlesformat": "srt",
            "merge_output_format": container,
            "quiet": False,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    else:
        yt_bin = shutil.which("yt-dlp") or shutil.which("youtube-dl")
        cmd = [
            yt_bin, "-f", fmt,
            "--merge-output-format", container,
            "--write-sub", "--write-auto-sub", "--sub-lang", "all", "--convert-subs", "srt",
            "-o", outtmpl, url
        ]
        subprocess.run(cmd, check=True)

# ---------------- génération NFO ----------------

def write_nfo(info, path):
    title = info.get("title","")
    desc = info.get("description","")
    dur = info.get("duration",0)
    up = info.get("uploader","")
    thumb = info.get("thumbnail","")
    date = info.get("upload_date","")
    year = date[:4] if len(date)>=8 else ""
    prem = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date)>=8 else ""
    vid = info.get("id","")
    nfo = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie>
  <title>{escape(title)}</title>
  <plot>{escape(desc)}</plot>
  <runtime>{dur}</runtime>
  <thumb>{escape(thumb)}</thumb>
  <studio>{escape(up)}</studio>
  <year>{escape(year)}</year>
  <premiered>{escape(prem)}</premiered>
  <uniqueid type="youtube" default="true">{escape(vid)}</uniqueid>
</movie>"""
    with open(path,"w",encoding="utf-8") as f:
        f.write(nfo)

# ---------------- main ----------------

def main(url, outdir="."):
    printInfo("--main ")
    ensure_dir(outdir)

    # récupération des métadonnées
    printInfo("-------------------------------------")
    printInfo("---- recuperation métadonnées ----")
    info, use_module = None, False
    try:
        info = get_info_module(url)
        use_module = True
    except Exception:
        try:
            info = get_info_cli(url)
        except Exception as e:
            printError("Impossible de récupérer les métadonnées :", e)

    if info is None:
        printError("Impossible de récupérer les métadonnées (info=None)")

    if info.get("_type")=="playlist" and info.get("entries"):
        info = info["entries"][0]

    base = sanitize_filename(info.get("title","video"))
    vdir = ensure_dir(os.path.join(outdir, base))

    printInfo("-------------------------------------")
    printInfo("---- recuperation video ----")

    # essais de format
    fmt_list = ["bestvideo[height<=720]+bestaudio/best", "best"]
    container_list = ["mp4", "mkv"]

    downloaded = False
    for fmt in fmt_list:
        for container in container_list:
            try:
                download_video(url, vdir, base, fmt, container, use_module)
                downloaded = True
                break
            except Exception:
                print(f"⚠️ Format {fmt} avec container {container} impossible, fallback...")
        if downloaded:
            break

    if not downloaded:
        try:
            printInfo("Tous les formats ont échoué, tentative finale avec 'best' mp4")
            download_video(url, vdir, base, "best", "mp4", use_module)
            downloaded = True
        except Exception:
            printWarning("Tous les formats ont échoué, Format best avec container mp4 impossible, fallback...")
            
    if not downloaded:
        printWarning("aucune vidéo télécharger...")

    # vignette
    printInfo("-------------------------------------")
    printInfo("---- recuperation vignette ----")
    thumb = info.get("thumbnail")
    if thumb:
        download_thumb(thumb, os.path.join(vdir, base+".jpg"))
        thumbOk = True

    # NFO
    print("-------------------------------------")
    print("---- ecriture fichier NFO ----")
    write_nfo(info, os.path.join(vdir, base+".nfo"))

    print("\n✅ Terminé. Fichiers dans :", vdir)
    for f in os.listdir(vdir):
        print(" -", f)

# ---------------- exécution ----------------

if __name__=="__main__":
    if len(sys.argv)<2:
        print("Usage: python3 convert_youtube_to_xbmc_v9.py <url> [outdir]")
        sys.exit(1)
    url = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv)>2 else "."
    main(url, outdir)

