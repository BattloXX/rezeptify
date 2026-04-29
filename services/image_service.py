"""Image download, resize, EXIF rotation and save."""
import io, uuid, re
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

from config import UPLOAD_DIR, MAX_UPLOAD_MB, ALLOWED_IMAGES


IMG_MAX_PX  = 1600
IMG_QUALITY = 82
IMG_MAX_BYTE = MAX_UPLOAD_MB * 1024 * 1024


def resize_and_save(data: bytes, ext: str) -> str:
    try:
        from PIL import Image, ExifTags
        img = Image.open(io.BytesIO(data))
        try:
            exif = img._getexif()
            if exif:
                for tag, val in exif.items():
                    if ExifTags.TAGS.get(tag) == 'Orientation':
                        for deg in {3: 180, 6: 270, 8: 90}.get(val, []):
                            img = img.rotate(deg, expand=True)
                        break
        except Exception:
            pass
        if img.mode in ('RGBA', 'P', 'LA'):
            bg = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            bg.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        w, h = img.size
        if w > IMG_MAX_PX or h > IMG_MAX_PX:
            img.thumbnail((IMG_MAX_PX, IMG_MAX_PX), Image.LANCZOS)
        fname = f"{uuid.uuid4().hex}.jpg"
        img.save(UPLOAD_DIR / fname, 'JPEG', quality=IMG_QUALITY, optimize=True)
        return fname
    except ImportError:
        fname = f"{uuid.uuid4().hex}{ext}"
        (UPLOAD_DIR / fname).write_bytes(data)
        return fname
    except Exception:
        fname = f"{uuid.uuid4().hex}{ext}"
        (UPLOAD_DIR / fname).write_bytes(data)
        return fname


def validate_and_save(data: bytes, ext: str) -> str:
    if ext not in ALLOWED_IMAGES:
        from fastapi import HTTPException
        raise HTTPException(400, f"Dateityp nicht erlaubt: {ext}")
    if len(data) > IMG_MAX_BYTE:
        from fastapi import HTTPException
        raise HTTPException(413, f"Datei zu groß (max {MAX_UPLOAD_MB} MB)")
    return resize_and_save(data, ext)


def download_image(img_url: str, base_url: str) -> Optional[str]:
    try:
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        elif img_url.startswith("/"):
            parsed = urlparse(base_url)
            img_url = f"{parsed.scheme}://{parsed.netloc}{img_url}"
        elif not img_url.startswith("http"):
            img_url = urljoin(base_url, img_url)
        with httpx.Client(follow_redirects=True, timeout=15.0,
                          headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = client.get(img_url)
            if resp.status_code != 200:
                return None
            ct = resp.headers.get("content-type", "")
            ext_map = {"image/jpeg": ".jpg", "image/png": ".png",
                       "image/webp": ".webp", "image/gif": ".gif"}
            ext = ext_map.get(ct.split(";")[0].strip())
            if not ext:
                url_ext = Path(urlparse(img_url).path).suffix.lower()
                ext = url_ext if url_ext in {".jpg",".jpeg",".png",".webp",".gif"} else ".jpg"
            if len(resp.content) > IMG_MAX_BYTE:
                return None
            return resize_and_save(resp.content, ext)
    except Exception:
        return None


def extract_best_image(html: str, page_url: str) -> Optional[str]:
    og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if not og:
        og = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.I)
    if og:
        return og.group(1)
    jld = re.search(r'"image"\s*:\s*["\[]([^"\]]+)', html)
    if jld:
        return jld.group(1).strip('"')
    imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', html, re.I)
    for img in imgs:
        if any(k in img.lower() for k in ["recipe","rezept","food","dish","hero","main","featured"]):
            return img
    return None


def search_recipe_image(titel: str) -> Optional[str]:
    if not titel or not titel.strip():
        return None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "de-DE,de;q=0.9",
        }
        with httpx.Client(follow_redirects=True, timeout=15.0, headers=headers) as client:
            resp = client.get("https://www.chefkoch.de/suche.php", params={"suche": titel.strip()})
            matches = re.findall(r'href="(https://www\.chefkoch\.de/rezepte/\d+/[^"?#]+)"', resp.text)
            if not matches:
                return None
            resp2 = client.get(matches[0])
            img_url = extract_best_image(resp2.text[:30000], matches[0])
            if img_url:
                return download_image(img_url, matches[0])
    except Exception:
        pass
    return None
