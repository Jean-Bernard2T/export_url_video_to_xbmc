#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_youtube_to_xbmc_simple_v3.py
Usage:
  python3 convert_youtube_to_xbmc_simple_v3.py <youtube_url> [outdir]

Comportement:
 - Essaye format "best[ext=mp4]/best" (MP4 si possible)
 - Si échec -> retente en MKV
 - Si toujours échec -> fallback "best" (MP4 puis MKV)
 - Télécharge sous-titres (.srt), vignette (.jpg), et génère un .nfo XBMC
"""

import os
import sys
import re
import json
import shutil
import subprocess
from xml.sax.saxutils import escape

# ---------- utilitaires ----------

def sanitize_filename(name, maxlen=200):
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = re.sub(r'\s+$', '', name)
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

# ---------- récupération métadonnées ----------

def get_info_module(url):
    """Récupère les métadonnées via le module yt_dlp (override du format pour éviter configs problématiques)."""
    try:
        import yt_dlp
        opts = {
            "quiet": True,
            "no_warnings": True,
            "simulate": True,
            # override toute config persistant qui pourrait casser extract_info
            "format": "best[ext=mp4]/best",
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        # ne pas spammer la trace complète, on retourne None pour fallback CLI
        # print("get_info_module error:", e)
        return None

def get_info_cli(url):
    """Récupère les métadonnées via le binaire yt-dlp (ignore la config utilisateur)."""
    yt_bin = shutil.which("yt-dlp") or shutil.which("youtube-dl")
    if not yt_bin:
        raise FileNotFoundError("Aucun binaire 'yt-dlp' ou 'youtube-dl' trouvé dans le PATH.")
    # --ignore-config évite d'utiliser ~/.config/yt-dlp/config qui pourrait contenir un format invalide
    cmd = [yt_bin, "--ignore-config", "--no-warnings", "--dump-json", url]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
    stdout = completed.stdout.strip()
    if not stdout:
        return None
    # si dump-json renvoie plusieurs lignes (playlist), on prend la première JSON
    first_line = stdout.splitlines()[0]
    return json.loads(first_line)

# ---------- téléchargement ----------

def download_with_module(url, outdir, base, fmt, container):
    import yt_dlp
    outtmpl = os.path.join(outdir, base + ".%(ext)s")
    ydl_opts = {
        "format": fmt,
        "outtmpl": outtmpl,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["all"],
        "subtitlesformat": "srt",
        "merge_output_format": container,
        "quiet": False,
        "noprogress": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

def download_with_cli(url, outdir, base, fmt, container):
    yt_bin = shutil.which("yt-dlp") or shutil.which("youtube-dl")
    if not yt_bin:
        raise FileNotFoundError("Aucun binaire 'yt-dlp' ou 'youtube-dl' trouvé dans le PATH.")
    outtmpl = os.path.join(outdir, base + ".%(ext)s")
    cmd = [
        yt_bin,
        "--ignore-config",
        "-f", fmt,
        "--merge-output-format", container,
        "--write-sub", "--write-auto-sub", "--sub-lang", "all", "--convert-subs", "srt",
        "-o", outtmpl,
        url
    ]
    subprocess.run(cmd, check=True)

# wrapper pour choisir module ou CLI
def download_video(url, outdir, base, fmt, container, use_module):
    if use_module:
        download_with_module(url, outdir, base, fmt, container)
    else:
        download_with_cli(url, outdir, base, fmt, container)

# ---------- génération NFO ----------

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

# ---------- main ----------

def main(url, outdir="."):
    ensure_dir(outdir)

    # 1) récupérer métadonnées (module -> CLI)
    info = None
    use_module = False
    try:
        info = get_info_module(url)
        if info is not None:
            use_module = True
    except Exception:
        info = None

    if info is None:
        try:
            info = get_info_cli(url)
        except subprocess.CalledProcessError as e:
            print("Échec get_info via CLI:", e.stderr or e)
            info = None
        except Exception as e:
            print("Impossible d'obtenir les métadonnées :", e)
            info = None

    if info is None:
        print("Impossible de récupérer les métadonnées. Astuce: vérifie que 'yt-dlp --list-formats <URL>' fonctionne.")
        sys.exit(1)

    # si playlist -> prendre la première entrée
    if isinstance(info, dict) and info.get("_type") == "playlist" and info.get("entries"):
        info = info["entries"][0]

    title = info.get("title", "video")
    base = sanitize_filename(title)
    vdir = ensure_dir(os.path.join(outdir, base))

    # 2) stratégie de téléchargement (ordre d'essai)
    fmt_candidates = ["best[ext=mp4]/best", "best"]
    container_candidates = ["mp4", "mkv"]

    downloaded = False
    last_error = None

    for fmt in fmt_candidates:
        for container in container_candidates:
            try:
                print(f"Essai : format={fmt}, container={container}, méthode={'module' if use_module else 'cli'}")
                download_video(url, vdir, base, fmt, container, use_module)
                downloaded = True
                print("Téléchargement réussi :", fmt, container)
                break
            except subprocess.CalledProcessError as e:
                # erreur venant du binaire
                last_error = e
                stderr = (e.stderr or str(e)) if hasattr(e, "stderr") else str(e)
                print("Erreur subprocess:", stderr)
            except Exception as e:
                last_error = e
                print("Erreur:", e)
        if downloaded:
            break

    if not downloaded:
        print("Tous les essais ont échoué. Dernière erreur :", last_error)
        print("Suggestion : lancer manuellement : yt-dlp --ignore-config --list-formats <URL> pour voir les formats disponibles.")
        sys.exit(2)

    # 3) vignette + nfo
    thumb = info.get("thumbnail")
    if thumb:
        ok = download_thumb(thumb, os.path.join(vdir, base + ".jpg"))
        if ok:
            print("Vignette téléchargée.")
    write_nfo(info, os.path.join(vdir, base + ".nfo"))

    print("\n✅ Terminé. Fichiers dans :", vdir)
    for f in os.listdir(vdir):
        print(" -", f)

# ---------- exécution ----------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 convert_youtube_to_xbmc_simple_v3.py <url> [outdir]")
        sys.exit(1)
    url = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else "."
    main(url, outdir)

