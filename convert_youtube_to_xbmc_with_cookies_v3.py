#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
convert_youtube_to_xbmc_with_cookies.py
Usage:
  python3 convert_youtube_to_xbmc_with_cookies.py <youtube_url> [outdir] [cookies.txt]

- Télécharge la vidéo en MP4 (ou fallback MKV/best)
- Télécharge vignette (.jpg), sous-titres (.srt), et génère un .nfo XBMC
- Supporte les cookies YouTube (facilite l'accès aux vidéos restreintes et accélère extraction)
Dans un environnement python faire
python3 -m venv venv
source venv/bin/activate
pip install yt-dlp
pip install requests
deactivate - pour sortir
"""

import os
import sys
import re
import json
import shutil
import subprocess
from xml.sax.saxutils import escape

from urllib.parse import urlparse, urlunparse

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

def check_cookies_file(cookies_path):
    """
    Vérifie si le fichier de cookies existe et semble être au format Netscape.
    """
    if not cookies_path:
        return None
    
    if not os.path.exists(cookies_path):
        printWarning(f"Le fichier de cookies spécifié est introuvable : {cookies_path}")
        return None
    
    try:
        with open(cookies_path, 'r', encoding='utf-8', errors='ignore') as f:
            first_line = f.readline()
            if "# Netscape HTTP Cookie File" not in first_line:
                printWarning(f"Le fichier {cookies_path} ne semble pas être au format Netscape.")
                printWarning("Les cookies seront ignorés pour éviter des erreurs.")
                return None
    except Exception as e:
        printWarning(f"Erreur lors de la lecture du fichier de cookies : {e}")
        return None
        
    return cookies_path
    
def clean_title_and_tag(title):
    """
    Recherche des mots-clés spécifiques dans le titre, ajoute un tag, 
    et retire ces mots-clés du titre.
    
    Args:
        title (str): Le titre original de la vidéo.
        
    Returns:
        tuple: (titre_nettoye, liste_tags)
    """
    
    TAG_OPENING = [
        "générique",
        "opening",
        "générique début",
        "intro",
        # Ajoutez d'autres mots si nécessaire
    ]
    TAG_ENDING = [
        "générique fin",
        "générique de fin",
        "ending",
        # Ajoutez d'autres mots si nécessaire
    ]
    
    tags = []
    cleaned_title = title
    tag_added = False
    
    # 1. Détection et suppression des mots-clés
    for keyword in TAG_OPENING:
        # Construction d'un motif regex robuste (mots complets, ignorer ponctuation autour)
        pattern = r"[\s\(\)\[\]\-—:]*" + re.escape(keyword) + r"[\s\(\)\[\]\-—:]*"

        # Chercher dans le titre (flags=re.IGNORECASE)
        if re.search(pattern, cleaned_title, flags=re.IGNORECASE):
            # Valoriser le TAG une seule fois
            if not tag_added:
                tags.append("opening")
                tag_added = True
                
            # Retirer le mot-clé du titre en le remplaçant par un espace
            # L'opération est répétée sur cleaned_title pour gérer les occurrences multiples
            cleaned_title = re.sub(pattern, " ", cleaned_title, flags=re.IGNORECASE).strip()

    for keyword in TAG_ENDING:
        # Construction d'un motif regex robuste (mots complets, ignorer ponctuation autour)
        pattern = r"[\s\(\)\[\]\-—:]*" + re.escape(keyword) + r"[\s\(\)\[\]\-—:]*"

        # Chercher dans le titre (flags=re.IGNORECASE)
        if re.search(pattern, cleaned_title, flags=re.IGNORECASE):
            # Valoriser le TAG une seule fois
            if not tag_added:
                tags.append("ending")
                tag_added = True
                
            # Retirer le mot-clé du titre en le remplaçant par un espace
            # L'opération est répétée sur cleaned_title pour gérer les occurrences multiples
            cleaned_title = re.sub(pattern, " ", cleaned_title, flags=re.IGNORECASE).strip()


    # 2. Nettoyage final du titre
    
    # Remplacer les espaces multiples, tirets multiples, deux points par un seul espace
    #cleaned_title = re.sub(r'[\s\-—:]+', ' ', cleaned_title).strip(' -—:')
    
    # S'assurer qu'on ne renvoie pas une chaîne vide
    if not cleaned_title:
        return title, tags
        
    return cleaned_title, tags
    
def nettoyage_texte(psDescription):
    printInfo(f"-- nettoyage_texte DEB ")
    description=psDescription
    # --- CORRECTION : Nettoyage du PLOT/Description ---

    # 1. Définir le motif de recherche (non sensible à la casse)
    # Ce motif cherche 'Description de la chaîne' ou 'Chaîne YouTube' et capture
    # tout ce qui suit (.|\n)* jusqu'à la fin ($).
    patterns_to_remove = [
        r"Description de la chaîne.*",
        r"Chaîne YouTube.*",
        r"Chaîne YouTube", # Au cas où c'est le dernier mot
    ]
    
    # 2. Appliquer les suppressions
    for pattern in patterns_to_remove:
        # re.IGNORECASE pour ignorer la casse
        # re.DOTALL pour que le '.' corresponde aussi aux sauts de ligne
        description = re.sub(pattern, "", description, flags=re.IGNORECASE | re.DOTALL)
        
    # Nettoyer les espaces et sauts de ligne restants à la fin
    description = description.strip()
    printInfo(f"-- nettoyage_texte END ")
    return description

def download_thumb(url, path):
    printInfo(f"-- download_thumb({url}, {path}) DEB ")
    try:
        import requests
        
        # Le navigateur envoie un "User-Agent". On peut le simuler pour éviter le blocage.
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        
        r = requests.get(url, headers=headers, timeout=20)
        
        # Cette ligne va lever une erreur si le code est >= 400 (ex: 404 Not Found)
        r.raise_for_status() 
        
        with open(path, "wb") as f:
            f.write(r.content)
            
        printInfo("-- download_thumb END ")
        return True
        
    except requests.exceptions.HTTPError as e:
        # Erreur spécifique de statut HTTP (404, 500, etc.)
        printWarning(f"download_thumb ERROR: HTTP Statut {e.response.status_code} pour l'URL", url)
        return False
    except Exception as e:
        # Toutes les autres erreurs (connexion, SSL, timeout, etc.)
        printWarning(f"download_thumb ERROR: Exception non HTTP", e)
        return False

def get_info_module(url, cookies=None):
    printInfo(f"-- get_info_module({url}, {cookies}) DEB ")
    try:
        import yt_dlp
        opts = {
            "quiet": True,
            "no_warnings": True,
            "simulate": True,
            "format": "best[ext=mp4]/best",
        }
        if cookies:
            opts["cookiefile"] = cookies
        with yt_dlp.YoutubeDL(opts) as ydl:
            printInfo("-- get_info_module END ")
            return ydl.extract_info(url, download=False)
    except Exception:
        printInfo("-- get_info_module END ERROR")
        return None

def get_info_cli(url, cookies=None):
    printInfo(f"-- get_info_cli({url}, {cookies}) DEB ")
    # On cherche en priorité dans le venv local
    venv_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "yt-dlp")
    yt_bin = venv_bin if os.path.exists(venv_bin) else (shutil.which("yt-dlp") or shutil.which("youtube-dl"))
    if not yt_bin:
        raise FileNotFoundError("yt-dlp/youtube-dl introuvable")
    cmd = [yt_bin, "--ignore-config", "--no-warnings", "--dump-json"]
    if cookies:
        cmd += ["--cookies", cookies]
    cmd.append(url)
    
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
        stdout = completed.stdout.strip()
        printInfo("-- get_info_cli END ")
        return json.loads(stdout.splitlines()[0]) if stdout else None
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        printWarning(f"Erreur lors de l'extraction des infos via CLI (yt-dlp) : {error_msg}")
        return None
    except Exception as e:
        printWarning(f"Erreur inattendue dans get_info_cli : {e}")
        return None

def download_video(url, outdir, base, fmt, container, use_module, cookies=None):
    printInfo(f"-- download_video({url}, {outdir}, {base}, {fmt}, {container}, {use_module}, {cookies}) DEB ")
    outtmpl = os.path.join(outdir, base + ".%(ext)s")
    if use_module:
        printInfo(f"-- use_module=true ")
        import yt_dlp
        ydl_opts = {
            "format": fmt,
            "outtmpl": outtmpl,
            "merge_output_format": container,
            "quiet": False,
            "noprogress": True,
        }
        if cookies:
            ydl_opts["cookiefile"] = cookies
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    else:
        printInfo(f"-- use_module=false ")
        # On cherche en priorité dans le venv local
        venv_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "yt-dlp")
        yt_bin = venv_bin if os.path.exists(venv_bin) else (shutil.which("yt-dlp") or shutil.which("youtube-dl"))
        cmd = [
            yt_bin, "--ignore-config",
            "-f", fmt, "--merge-output-format", container,
            "-o", outtmpl,
        ]
        if cookies:
            cmd += ["--cookies", cookies]
        cmd.append(url)
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else str(e)
            raise Exception(f"yt-dlp a échoué avec l'erreur : {error_msg}")
            
    printInfo("-- download_video END ")
    
def download_subtitles(url, outdir, base, cookies=None):
    """Télécharge uniquement les sous-titres au format SRT, en mode module."""
    try:
        import yt_dlp
    except ImportError:
        printWarning("yt-dlp n'est pas installé comme module. Impossible de télécharger les sous-titres séparément.")
        return False

    # Le chemin de sortie doit être le dossier, yt-dlp gère le nom du fichier.
    outtmpl = os.path.join(outdir, base + ".%(ext)s")
    
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        # Options pour les sous-titres
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["fr", "en"], # On ne cherche que les sous-titres français ou anglais pour réduire le risque d'erreur 429
        "subtitlesformat": "srt",
        "skip_download": True, # CRUCIAL : Ne pas télécharger la vidéo
        "outtmpl": outtmpl,
    }
    
    if cookies:
        ydl_opts["cookiefile"] = cookies

    printInfo("Tentative de récupération des sous-titres...")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        printInfo("Récupération des sous-titres terminée.")
        return True
    except Exception as e:
        printWarning(f"Échec de la récupération des sous-titres : {e}")
        return False

def write_nfo(info, path, psTitle=None):
    printInfo("-- write_nfo({info}, {path}, {psTitle}) DEB ")
    title = info.get("title","")
    if psTitle:
        title=psTitle
    desc = nettoyage_texte(info.get("description",""))
    dur = info.get("duration",0)
    # Mise en forme du temps de lecture
    dur_str = f"{dur // 60:02}:{dur % 60:02}" if dur else ""
    up = info.get("uploader","")
    thumb = info.get("thumbnail","")
    #if pThumb_path:
    #   thumb = os.path.basename(pThumb_path)
    date = info.get("upload_date","")
    year = date[:4] if len(date)>=8 else ""
    prem = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date)>=8 else ""
    vid = info.get("id","")
    # ---------------- RÉCUPÉRATION DES TAGS MUSICAUX ----------------
    # Champs spécifiques aux fichiers musicaux/vidéos musicales
    artist = info.get("artist")
    album = info.get("album")
    genre = info.get("genre")
    # --- AJOUT DES BALISES MUSICALES (si elles existent) ---
    artist_str = ""
    if artist:
        # Note: Kodi peut utiliser <artist> pour l'artiste principal
        artist_str=f"  <artist>{escape(artist)}</artist>"
    album_str = ""
    if album:
        album_str=f"  <album>{escape(album)}</album>"
    # Insertion des genres (souvent une liste, mais yt-dlp renvoie parfois une chaîne unique)
    genre_str = ""
    if genre:
        # On peut ajouter le genre comme un <tag> OU comme <genre>. 
        # On utilise <genre> pour la classification musicale native.
        genre_str=f"  <genre>{escape(genre)}</genre>"
    #
    # --- APPEL DU CLEAN TITLE ---
    titleold, listTags = clean_title_and_tag(title)
    tags = ""
    for tag in listTags:
        tags = f"{tags}<tag>{escape(tag)}</tag>\n"
    #
    nfo = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie>
  <title>{escape(title)}</title>
  {artist_str}
  {album_str}
  {genre_str}
  <plot>{escape(desc)}</plot>
  {tags}
  <runtime>{dur_str}</runtime>
  <thumb>{escape(title)}-poster.jpg</thumb>
  <studio>{escape(up)}</studio>
  <year>{escape(year)}</year>
  <premiered>{escape(prem)}</premiered>
  <uniqueid type="youtube" default="true">{escape(vid)}</uniqueid>
</movie>"""
    with open(path,"w",encoding="utf-8") as f:
        f.write(nfo)

def main(url, outdir=".", psTitle=None, cookies=None):
    ensure_dir(outdir)

    # récupération des métadonnées
    printInfo("-------------------------------------")
    printInfo("---- recuperation métadonnées ----")

    # Validation initiale des cookies si fournis
    if cookies:
        cookies = check_cookies_file(cookies)

    info = get_info_module(url, cookies)
    use_module = info is not None
    if info is None:
        info = get_info_cli(url, cookies)

    if not info:
        printError("Impossible de récupérer les métadonnées.")
        sys.exit(1)

    if info.get("_type")=="playlist" and info.get("entries"):
        info = info["entries"][0]

    title = info.get("title", "video")
    if psTitle:
        title=psTitle
    base = sanitize_filename(title)
    #vdir = ensure_dir(os.path.join(outdir, base))
    vdir = ensure_dir(outdir)

    printInfo("-------------------------------------")
    printInfo("---- recuperation video ----")

    # Format prioritaire : MP4 avec une hauteur max de 480 pixels (qualité 480p),
    # sinon le meilleur format (best).
    fmt_candidates = ["best[height<=480][ext=mp4]/best", "best"]
    container_candidates = ["mp4", "mkv"]

    for fmt in fmt_candidates:
        for container in container_candidates:
            try:
                print(f"Téléchargement format={fmt}, container={container}")
                download_video(url, vdir, base, fmt, container, use_module, cookies)
                print("Téléchargement réussi")
                break
            except Exception as e:
                print("Échec :", e)
        else:
            continue
        break

    # recuperation des sous-titre
    printInfo("-------------------------------------")
    printInfo("---- recuperation sous-titre ----")
    download_subtitles(url, vdir, base, cookies) # Appel de la nouvelle fonction

     # vignette
    printInfo("-------------------------------------")
    printInfo("---- recuperation vignette ----")

    thumb_path = os.path.join(vdir, base + "-poster.jpg")
    vid_id = info.get("id")
    if vid_id:
        
        # 1. Tentative avec l'URL JPG de résolution maximale (idéale pour Kodi/XBMC)
        thumb_url_jpg_maxres = f"https://img.youtube.com/vi/{vid_id}/maxresdefault.jpg"
        printInfo(f"Tentative de téléchargement de l'URL JPG (maxres): {thumb_url_jpg_maxres}")
        
        if download_thumb(thumb_url_jpg_maxres, thumb_path):
            printInfo("Vignette JPG (maxres) téléchargée avec succès.")
        else:
            printWarning("Échec du téléchargement du JPG standard (maxres). Tentative avec l'URL de yt-dlp...")
            default_thumb_url = info.get("thumbnail")
            
            if default_thumb_url:
                # 2. Utiliser l'URL de yt-dlp (souvent hqdefault.jpg)
                
                # --- CORRECTION CRUCIALE : Nettoyer l'URL de ses paramètres de requête ---
                # On utilise urlparse et urlunparse pour reconstruire une URL sans les paramètres,
                # afin d'obtenir un nom de fichier valide, tout en conservant l'extension.
                from urllib.parse import urlparse, urlunparse
                parsed_url = urlparse(default_thumb_url)
                # Reconstruire l'URL sans le fragment et les paramètres de requête
                clean_url = urlunparse(parsed_url._replace(query='', fragment=''))
                
                # On force toujours l'enregistrement en .jpg car Kodi le préfère
                if download_thumb(clean_url, thumb_path):
                    printInfo(f"Vignette téléchargée avec succès (URL de yt-dlp nettoyée).")
                else:
                    printError("Impossible de télécharger la vignette sous quelque format que ce soit.")
            else:
                printError("Aucune URL de vignette n'a été trouvée dans les métadonnées.")
        
    # NFO
    print("-------------------------------------")
    print("---- ecriture fichier NFO ----")
    write_nfo(info, os.path.join(vdir, base + ".nfo"), title)

    print("\n✅ Terminé. Fichiers dans :", vdir)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 convert_youtube_to_xbmc_with_cookies.py <url> [outdir] [cookies_youtube.txt]")
        sys.exit(1)
    url = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else "."
    cookies = sys.argv[3] if len(sys.argv) > 3 else None
    sTitle = sys.argv[4] if len(sys.argv) > 4 else None
    main(url, outdir, sTitle, cookies)

