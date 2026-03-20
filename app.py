"""
Rezeptify – Persönliche Rezeptdatenbank
FastAPI + MariaDB (PyMySQL) + Anthropic Claude
CloudPanel / uWSGI kompatibel
"""
import json, re, uuid, base64, shutil, unicodedata, io
from pathlib import Path
from typing import Optional, List
from urllib.parse import urljoin, urlparse

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import pymysql
import pymysql.cursors
import httpx
from bs4 import BeautifulSoup
from anthropic import Anthropic
from contextlib import contextmanager

from config import (
    BASE_DIR, UPLOAD_DIR,
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_CHARSET,
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    MAX_UPLOAD_MB, ALLOWED_IMAGES,
    APP_TITLE, DEBUG
)

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ── DB ────────────────────────────────────────────────────────────────────────
@contextmanager
def get_db():
    conn = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, database=DB_NAME, charset=DB_CHARSET,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False, connect_timeout=10,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rezepte (
                    id            INT AUTO_INCREMENT PRIMARY KEY,
                    titel         VARCHAR(255) NOT NULL,
                    slug          VARCHAR(300) UNIQUE,
                    beschreibung  TEXT DEFAULT '',
                    zutaten       JSON,
                    zubereitung   TEXT DEFAULT '',
                    portionen     INT DEFAULT 4,
                    zeit_vorb     INT DEFAULT 0,
                    zeit_koch     INT DEFAULT 0,
                    schwierigkeit ENUM('leicht','mittel','schwer') DEFAULT 'mittel',
                    kategorie     VARCHAR(100) DEFAULT '',
                    tags          JSON,
                    quelle_url    VARCHAR(500) DEFAULT '',
                    quelle_typ    VARCHAR(50) DEFAULT 'manuell',
                    bewertung              TINYINT DEFAULT NULL,
                    kalorien_pro_portion   INT DEFAULT NULL,
                    erstellt_am            DATETIME DEFAULT CURRENT_TIMESTAMP,
                    geaendert_am  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FULLTEXT KEY ft_rezepte (titel, beschreibung)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bilder (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    rezept_id   INT NOT NULL,
                    dateiname   VARCHAR(255) NOT NULL,
                    ist_haupt   TINYINT(1) DEFAULT 0,
                    erstellt_am DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (rezept_id) REFERENCES rezepte(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kategorien (
                    id   INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) UNIQUE NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            for k in ["Frühstück","Vorspeise","Hauptgericht","Dessert","Snack",
                      "Getränk","Backen","Salat","Suppe","Sonstiges"]:
                cur.execute("INSERT IGNORE INTO kategorien (name) VALUES (%s)", (k,))
            # Migration: add slug column if not exists (for existing installs)
            cur.execute("""
                SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='rezepte' AND COLUMN_NAME='slug'
            """)
            if cur.fetchone()["n"] == 0:
                cur.execute("ALTER TABLE rezepte ADD COLUMN slug VARCHAR(300) UNIQUE AFTER titel")
        conn.commit()
        # Migration: add kalorien_pro_portion column if not exists
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='rezepte' AND COLUMN_NAME='kalorien_pro_portion'
            """)
            if cur.fetchone()["n"] == 0:
                cur.execute("ALTER TABLE rezepte ADD COLUMN kalorien_pro_portion INT DEFAULT NULL AFTER bewertung")
        conn.commit()
        # Migration: add bewertung column if not exists
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='rezepte' AND COLUMN_NAME='bewertung'
            """)
            if cur.fetchone()["n"] == 0:
                cur.execute("ALTER TABLE rezepte ADD COLUMN bewertung TINYINT DEFAULT NULL AFTER quelle_typ")
        conn.commit()
        # Backfill slugs for existing recipes without one
        with conn.cursor() as cur:
            cur.execute("SELECT id, titel FROM rezepte WHERE slug IS NULL OR slug=''")
            for row in cur.fetchall():
                slug = make_slug(row["titel"], row["id"])
                cur.execute("UPDATE rezepte SET slug=%s WHERE id=%s", (slug, row["id"]))
        conn.commit()

# ── Slug Helper ──────────────────────────────────────────────────────────────
def make_slug(titel: str, rid: int = None) -> str:
    """Generate a URL-friendly slug from a recipe title."""
    # Normalize unicode (ä→ae etc.)
    s = titel.lower().strip()
    replacements = [('ä','ae'),('ö','oe'),('ü','ue'),('ß','ss'),
                    ('à','a'),('á','a'),('â','a'),('è','e'),('é','e'),
                    ('ê','e'),('ì','i'),('í','i'),('î','i'),('ò','o'),
                    ('ó','o'),('ô','o'),('ù','u'),('ú','u'),('û','u')]
    for src, dst in replacements:
        s = s.replace(src, dst)
    # Remove remaining non-ASCII
    s = unicodedata.normalize('NFD', s)
    s = s.encode('ascii', 'ignore').decode('ascii')
    # Replace non-alphanumeric with hyphens
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = s.strip('-')
    # Limit length
    if len(s) > 80:
        s = s[:80].rstrip('-')
    # Append ID to guarantee uniqueness
    if rid:
        s = f"{s}-{rid}"
    return s or f"rezept-{rid}"

def ensure_slug(conn, rid: int, titel: str):
    """Set slug for a recipe if it doesn't have one yet."""
    with conn.cursor() as cur:
        cur.execute("SELECT slug FROM rezepte WHERE id=%s", (rid,))
        row = cur.fetchone()
        if row and not row.get("slug"):
            slug = make_slug(titel, rid)
            cur.execute("UPDATE rezepte SET slug=%s WHERE id=%s", (slug, rid))

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title=APP_TITLE, docs_url="/api/docs" if DEBUG else None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup():
    init_db()

# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_json_field(val):
    if val is None: return []
    if isinstance(val, (list, dict)): return val
    try: return json.loads(val)
    except: return []

def clean_row(row: dict) -> dict:
    row["zutaten"] = parse_json_field(row.get("zutaten"))
    row["tags"]    = parse_json_field(row.get("tags"))
    for f in ("erstellt_am", "geaendert_am"):
        if row.get(f) and not isinstance(row[f], str):
            row[f] = row[f].isoformat()
    return row

def get_bilder(cur, rezept_id: int) -> list:
    cur.execute(
        "SELECT id, dateiname, ist_haupt FROM bilder WHERE rezept_id=%s ORDER BY ist_haupt DESC, id",
        (rezept_id,)
    )
    return [{"id": r["id"], "dateiname": r["dateiname"],
             "url": f"/static/uploads/{r['dateiname']}",
             "ist_haupt": bool(r["ist_haupt"])} for r in cur.fetchall()]

def enrich(row: dict, cur) -> dict:
    row = clean_row(row)
    row["bilder"]     = get_bilder(cur, row["id"])
    row["haupt_bild"] = next((b["url"] for b in row["bilder"] if b["ist_haupt"]), None)
    return row

# ── Image resize settings ────────────────────────────────────────────────────
IMG_MAX_PX   = 1600   # Max width or height in pixels
IMG_QUALITY  = 82     # JPEG quality (82 = guter Kompromiss Qualität/Größe)
IMG_MAX_BYTE = MAX_UPLOAD_MB * 1024 * 1024

def resize_and_save(data: bytes, ext: str) -> str:
    """Resize image to max IMG_MAX_PX, convert to JPEG, save. Returns filename."""
    try:
        from PIL import Image, ExifTags
        img = Image.open(io.BytesIO(data))

        # Auto-rotate based on EXIF orientation (fixes phone photos)
        try:
            exif = img._getexif()
            if exif:
                for tag, val in exif.items():
                    if ExifTags.TAGS.get(tag) == 'Orientation':
                        rotations = {3:180, 6:270, 8:90}
                        if val in rotations:
                            img = img.rotate(rotations[val], expand=True)
                        break
        except Exception:
            pass

        # Convert palette/RGBA to RGB
        if img.mode in ('RGBA', 'P', 'LA'):
            bg = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            bg.paste(img, mask=img.split()[-1] if img.mode in ('RGBA','LA') else None)
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Resize if too large (keep aspect ratio)
        w, h = img.size
        if w > IMG_MAX_PX or h > IMG_MAX_PX:
            img.thumbnail((IMG_MAX_PX, IMG_MAX_PX), Image.LANCZOS)

        # Save as JPEG
        fname = f"{uuid.uuid4().hex}.jpg"
        dest  = UPLOAD_DIR / fname
        img.save(dest, 'JPEG', quality=IMG_QUALITY, optimize=True)
        return fname

    except ImportError:
        # Pillow not installed — save as-is
        fname = f"{uuid.uuid4().hex}{ext}"
        dest  = UPLOAD_DIR / fname
        dest.write_bytes(data)
        return fname
    except Exception:
        # If resize fails — save original
        fname = f"{uuid.uuid4().hex}{ext}"
        dest  = UPLOAD_DIR / fname
        dest.write_bytes(data)
        return fname


def save_upload(file: UploadFile) -> str:
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_IMAGES:
        raise HTTPException(400, f"Dateityp nicht erlaubt: {ext}")
    data = file.file.read()
    if len(data) > IMG_MAX_BYTE:
        raise HTTPException(413, f"Datei zu groß (max {MAX_UPLOAD_MB} MB)")
    return resize_and_save(data, ext)

def download_image(img_url: str, base_url: str) -> Optional[str]:
    """Download an image from a URL and save it to uploads. Returns filename or None."""
    try:
        # Make absolute URL
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
                # Try from URL
                url_ext = Path(urlparse(img_url).path).suffix.lower()
                ext = url_ext if url_ext in {".jpg",".jpeg",".png",".webp",".gif"} else ".jpg"
            if len(resp.content) > MAX_UPLOAD_MB * 1024 * 1024:
                return None
            return resize_and_save(resp.content, ext)
    except Exception:
        return None

def extract_best_image(html: str, page_url: str) -> Optional[str]:
    """Extract the best recipe image URL from HTML."""
    # Priority 1: og:image meta tag
    og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if not og:
        og = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.I)
    if og:
        return og.group(1)

    # Priority 2: JSON-LD image
    jld = re.search(r'"image"\s*:\s*["\[]([^"\]]+)', html)
    if jld:
        return jld.group(1).strip('"')

    # Priority 3: large img tag with recipe-like class/id
    imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', html, re.I)
    for img in imgs:
        if any(k in img.lower() for k in ["recipe","rezept","food","dish","hero","main","featured"]):
            return img

    return None

# ── Models ────────────────────────────────────────────────────────────────────
class Zutat(BaseModel):
    menge:   Optional[str] = ""
    einheit: Optional[str] = ""
    name:    str

class RezeptIn(BaseModel):
    titel:         str
    beschreibung:  Optional[str] = ""
    zutaten:       Optional[List[Zutat]] = []
    zubereitung:   Optional[str] = ""
    portionen:     Optional[int] = 4
    zeit_vorb:     Optional[int] = 0
    zeit_koch:     Optional[int] = 0
    schwierigkeit: Optional[str] = "mittel"
    kategorie:     Optional[str] = ""
    tags:          Optional[List[str]] = []
    quelle_url:              Optional[str] = ""
    quelle_typ:              Optional[str] = "manuell"
    kalorien_pro_portion:    Optional[int] = None

# ── REZEPTE ───────────────────────────────────────────────────────────────────
@app.get("/api/rezepte")
def get_rezepte(
    suche:         Optional[str] = Query(None),
    kategorie:     Optional[str] = Query(None),
    tag:           Optional[str] = Query(None),
    schwierigkeit: Optional[str] = Query(None),
    bewertung:     Optional[int] = Query(None),
    sort:          Optional[str] = Query("neu"),   # neu | sterne | name
    limit:  int = Query(60, le=200),
    offset: int = Query(0),
):
    where, params = [], []
    if suche:
        where.append("MATCH(r.titel, r.beschreibung) AGAINST (%s IN BOOLEAN MODE)")
        params.append(suche + "*")
    if kategorie:
        where.append("r.kategorie = %s"); params.append(kategorie)
    if schwierigkeit:
        where.append("r.schwierigkeit = %s"); params.append(schwierigkeit)
    if tag:
        where.append("JSON_SEARCH(r.tags, 'one', %s) IS NOT NULL"); params.append(tag)
    if bewertung:
        where.append("r.bewertung = %s"); params.append(bewertung)

    w = ("WHERE " + " AND ".join(where)) if where else ""
    order = {"sterne": "r.bewertung DESC, r.erstellt_am DESC",
             "name":   "r.titel ASC",
             "neu":    "r.erstellt_am DESC"}.get(sort, "r.erstellt_am DESC")

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM rezepte r {w}", params)
            total = cur.fetchone()["n"]
            cur.execute(f"SELECT r.* FROM rezepte r {w} ORDER BY {order} LIMIT %s OFFSET %s",
                        params + [limit, offset])
            items = [enrich(r, cur) for r in cur.fetchall()]
    return {"total": total, "items": items, "limit": limit, "offset": offset}


@app.get("/api/rezepte/{rid}")
def get_rezept(rid: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM rezepte WHERE id=%s", (rid,))
            row = cur.fetchone()
            if not row: raise HTTPException(404, "Rezept nicht gefunden")
            return enrich(row, cur)


@app.get("/api/rezepte/slug/{slug}")
def get_rezept_by_slug(slug: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM rezepte WHERE slug=%s", (slug,))
            row = cur.fetchone()
            if not row: raise HTTPException(404, "Rezept nicht gefunden")
            return enrich(row, cur)


@app.patch("/api/rezepte/{rid}/bewertung")
def set_bewertung(rid: int, body: dict):
    sterne = body.get("sterne")
    if sterne is not None and sterne not in range(1, 6):
        raise HTTPException(400, "Bewertung muss zwischen 1 und 5 liegen")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE rezepte SET bewertung=%s WHERE id=%s", (sterne, rid))
            if cur.rowcount == 0:
                raise HTTPException(404, "Rezept nicht gefunden")
    return {"ok": True, "bewertung": sterne}


@app.post("/api/rezepte", status_code=201)
def create_rezept(data: RezeptIn):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO rezepte (titel,beschreibung,zutaten,zubereitung,portionen,
                    zeit_vorb,zeit_koch,schwierigkeit,kategorie,tags,quelle_url,quelle_typ,
                    kalorien_pro_portion)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (data.titel, data.beschreibung,
                  json.dumps([z.dict() for z in data.zutaten], ensure_ascii=False),
                  data.zubereitung, data.portionen, data.zeit_vorb, data.zeit_koch,
                  data.schwierigkeit, data.kategorie,
                  json.dumps(data.tags, ensure_ascii=False),
                  data.quelle_url, data.quelle_typ,
                  data.kalorien_pro_portion))
            new_id = cur.lastrowid
            # Generate and save slug
            slug = make_slug(data.titel, new_id)
            cur.execute("UPDATE rezepte SET slug=%s WHERE id=%s", (slug, new_id))
            cur.execute("SELECT * FROM rezepte WHERE id=%s", (new_id,))
            return enrich(cur.fetchone(), cur)


@app.put("/api/rezepte/{rid}")
def update_rezept(rid: int, data: RezeptIn):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE rezepte SET titel=%s,beschreibung=%s,zutaten=%s,zubereitung=%s,
                    portionen=%s,zeit_vorb=%s,zeit_koch=%s,schwierigkeit=%s,
                    kategorie=%s,tags=%s,quelle_url=%s,quelle_typ=%s,
                    kalorien_pro_portion=%s
                WHERE id=%s
            """, (data.titel, data.beschreibung,
                  json.dumps([z.dict() for z in data.zutaten], ensure_ascii=False),
                  data.zubereitung, data.portionen, data.zeit_vorb, data.zeit_koch,
                  data.schwierigkeit, data.kategorie,
                  json.dumps(data.tags, ensure_ascii=False),
                  data.quelle_url, data.quelle_typ,
                  data.kalorien_pro_portion, rid))
            # Regenerate slug if titel changed
            slug = make_slug(data.titel, rid)
            cur.execute("UPDATE rezepte SET slug=%s WHERE id=%s", (slug, rid))
            cur.execute("SELECT * FROM rezepte WHERE id=%s", (rid,))
            row = cur.fetchone()
            if not row: raise HTTPException(404, "Rezept nicht gefunden")
            return enrich(row, cur)


@app.delete("/api/rezepte/{rid}")
def delete_rezept(rid: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT dateiname FROM bilder WHERE rezept_id=%s", (rid,))
            for b in cur.fetchall():
                p = UPLOAD_DIR / b["dateiname"]
                if p.exists(): p.unlink()
            cur.execute("DELETE FROM rezepte WHERE id=%s", (rid,))
    return {"ok": True}

# ── BILDER ────────────────────────────────────────────────────────────────────
@app.post("/api/rezepte/{rid}/bilder")
def upload_bild(rid: int, file: UploadFile = File(...), ist_haupt: bool = Form(False)):
    with get_db() as conn:
        with conn.cursor() as cur:
            if not cur.execute("SELECT 1 FROM rezepte WHERE id=%s", (rid,)):
                raise HTTPException(404, "Rezept nicht gefunden")
    fname = save_upload(file)
    with get_db() as conn:
        with conn.cursor() as cur:
            if ist_haupt:
                cur.execute("UPDATE bilder SET ist_haupt=0 WHERE rezept_id=%s", (rid,))
            cur.execute("INSERT INTO bilder (rezept_id,dateiname,ist_haupt) VALUES (%s,%s,%s)",
                        (rid, fname, 1 if ist_haupt else 0))
    return {"dateiname": fname, "url": f"/static/uploads/{fname}", "ist_haupt": ist_haupt}


@app.post("/api/rezepte/{rid}/bilder/attach")
def attach_downloaded_bild(rid: int, body: dict):
    """Attach an already-downloaded image file to a recipe."""
    dateiname = body.get("dateiname", "").strip()
    if not dateiname: raise HTTPException(400, "dateiname fehlt")
    if not (UPLOAD_DIR / dateiname).exists(): raise HTTPException(404, "Bilddatei nicht gefunden")
    ist_haupt = body.get("ist_haupt", True)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM rezepte WHERE id=%s", (rid,))
            if not cur.fetchone(): raise HTTPException(404, "Rezept nicht gefunden")
            if ist_haupt: cur.execute("UPDATE bilder SET ist_haupt=0 WHERE rezept_id=%s", (rid,))
            cur.execute("INSERT INTO bilder (rezept_id,dateiname,ist_haupt) VALUES (%s,%s,%s)", (rid, dateiname, 1 if ist_haupt else 0))
    return {"dateiname": dateiname, "url": f"/static/uploads/{dateiname}", "ist_haupt": ist_haupt}


@app.delete("/api/bilder/{bid}")
def delete_bild(bid: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT dateiname FROM bilder WHERE id=%s", (bid,))
            row = cur.fetchone()
            if not row: raise HTTPException(404, "Bild nicht gefunden")
            p = UPLOAD_DIR / row["dateiname"]
            if p.exists(): p.unlink()
            cur.execute("DELETE FROM bilder WHERE id=%s", (bid,))
    return {"ok": True}


@app.put("/api/bilder/{bid}/haupt")
def set_haupt(bid: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT rezept_id FROM bilder WHERE id=%s", (bid,))
            row = cur.fetchone()
            if not row: raise HTTPException(404, "Bild nicht gefunden")
            cur.execute("UPDATE bilder SET ist_haupt=0 WHERE rezept_id=%s", (row["rezept_id"],))
            cur.execute("UPDATE bilder SET ist_haupt=1 WHERE id=%s", (bid,))
    return {"ok": True}

# ── KATEGORIEN & TAGS & STATS ─────────────────────────────────────────────────
@app.get("/api/kategorien")
def get_kategorien():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM kategorien ORDER BY name")
            return [r["name"] for r in cur.fetchall()]

@app.get("/api/tags")
def get_tags():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT tags FROM rezepte WHERE tags IS NOT NULL AND tags != '[]'")
            rows = cur.fetchall()
    alle = set()
    for r in rows:
        try: alle.update(parse_json_field(r["tags"]))
        except: pass
    return sorted(alle)

@app.get("/api/stats")
def get_stats():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM rezepte")
            total = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM bilder")
            bilder = cur.fetchone()["n"]
            cur.execute("""SELECT kategorie, COUNT(*) AS n FROM rezepte
                WHERE kategorie!='' GROUP BY kategorie ORDER BY n DESC LIMIT 5""")
            kats = cur.fetchall()
    return {"total_rezepte": total, "total_bilder": bilder,
            "top_kategorien": [{"name": r["kategorie"], "count": r["n"]} for r in kats]}

# ── Claude Prompts ────────────────────────────────────────────────────────────
_JSON_SCHEMA = """{
  "titel": "Rezeptname",
  "beschreibung": "Kurzbeschreibung (1-2 Sätze)",
  "zutaten": [
    {"menge": "200", "einheit": "g", "name": "Mehl"},
    {"menge": "3", "einheit": "EL", "name": "Olivenöl"},
    {"menge": "", "einheit": "", "name": "Salz nach Geschmack"}
  ],
  "zubereitung": "Schritt-für-Schritt Zubereitung",
  "portionen": 4,
  "zeit_vorb": 15,
  "zeit_koch": 30,
  "schwierigkeit": "leicht",
  "kategorie": "Hauptgericht",
  "tags": ["vegetarisch", "schnell"],
  "kalorien_pro_portion": 450
}"""

_RULES = """Regeln:
- Antworte NUR mit dem JSON-Objekt – KEIN Markdown, KEINE Backticks, KEIN Text davor oder danach
- Alle Strings müssen gültige JSON-Strings sein (keine unescapten Anführungszeichen darin)
- Zeilenumbrüche in Strings als \\n schreiben, nicht als echte Zeilenumbrüche
- schwierigkeit: nur "leicht", "mittel" oder "schwer"
- kategorie: Frühstück | Vorspeise | Hauptgericht | Dessert | Snack | Getränk | Backen | Salat | Suppe | Sonstiges
- zeit_vorb / zeit_koch: Minuten als Ganzzahl (0 wenn unbekannt)
- kalorien_pro_portion: Geschätzte Kalorien (kcal) pro Portion als Ganzzahl. Berechne anhand der Zutaten und Mengen. Falls nicht schätzbar: null
- Falls kein Rezept erkennbar: {"fehler": "Kein Rezept gefunden"}
- Antworte auf Deutsch"""

PROMPT_URL   = f"Du bist ein Rezept-Extraktor. Analysiere den Webseiteninhalt und extrahiere das Rezept.\n\nGib dieses JSON zurück:\n{_JSON_SCHEMA}\n\n{_RULES}\n\nInhalt:"
PROMPT_IMAGE = f"Du bist ein Rezept-Extraktor. Analysiere das Bild/PDF (Screenshot, Foto oder PDF eines Rezepts).\n\nGib dieses JSON zurück:\n{_JSON_SCHEMA}\n\n{_RULES}"

def parse_claude(raw: str) -> dict:
    """Robust JSON parser — handles markdown fences, truncation, bad chars."""
    raw = raw.strip()

    # Strip markdown fences
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    raw = raw.strip()

    # Strategy 1: direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract first {...} block (handles extra text before/after)
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    # Strategy 3: truncated JSON — try closing open structures
    truncated = raw.rstrip().rstrip(',')
    for suffix in ['"}', '"]}', '"}]}', '"\n}', ']\n}']:
        try:
            return json.loads(truncated + '\n' + suffix)
        except json.JSONDecodeError:
            pass

    # Strategy 4: use json5-style tolerant parse — fix common issues
    fixed = raw
    # Replace single quotes with double quotes (only unescaped ones)
    fixed = re.sub(r"(?<![\\])'", '"', fixed)
    # Remove trailing commas before } or ]
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
    # Remove control characters
    fixed = re.sub(r'[\x00-\x1f\x7f]', ' ', fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Nothing worked — raise with the raw response for debugging
    raise ValueError(f"JSON konnte nicht geparst werden. Antwort war: {raw[:300]}")

def check_api_key():
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-DEIN"):
        raise HTTPException(500, "ANTHROPIC_API_KEY nicht konfiguriert")

# ── HTML Cleaner ─────────────────────────────────────────────────────────────
def clean_html(html: str) -> str:
    """Strip navigation, scripts, ads etc. — keep only readable text. Reduces tokens ~75%."""
    try:
        soup = BeautifulSoup(html, 'html.parser')
        # Remove noise tags (only simple tag names — no CSS selectors!)
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside',
                         'iframe', 'noscript', 'form', 'button', 'svg', 'meta', 'link']):
            tag.decompose()

        # Try to find the main recipe content area (priority order)
        main = (
            soup.find('main') or
            soup.find(id='recipe') or
            soup.find(id='wprm-recipe-container') or   # WordPress recipe plugin
            soup.find(class_='wprm-recipe-container') or
            soup.find(class_='tasty-recipes') or        # Tasty Recipes plugin
            soup.find(class_='recipe-card') or
            soup.find(class_='recipe') or
            soup.find(attrs={'itemtype': 'http://schema.org/Recipe'}) or
            soup.find('article') or
            soup                                         # fallback: whole page
        )
        text = main.get_text(separator=' ', strip=True)
        # Collapse whitespace
        text = ' '.join(text.split())
        # 15000 chars ≈ 3750 tokens — good balance between cost and completeness
        return text[:15000]
    except Exception:
        # If BeautifulSoup fails for any reason, send raw text stripped of tags
        import re
        text = re.sub(r'<[^>]+>', ' ', html)
        text = ' '.join(text.split())
        return text[:15000]

# ── URL ANALYSE (with image download) ────────────────────────────────────────
@app.post("/api/analysiere-url")
def analysiere_url(body: dict):
    url = body.get("url", "").strip()
    if not url: raise HTTPException(400, "URL fehlt")
    check_api_key()

    try:
        with httpx.Client(follow_redirects=True, timeout=20.0,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; Rezeptify/1.0)"}) as client:
            resp = client.get(url)
            raw_html = resp.text
    except Exception as e:
        raise HTTPException(400, f"URL nicht abrufbar: {e}")

    # Extract best image BEFORE cleaning (needs full HTML)
    downloaded_image = None
    img_url = extract_best_image(raw_html[:30000], url)
    if img_url:
        downloaded_image = download_image(img_url, url)

    # Clean HTML → plain text (massiv weniger Tokens)
    clean_text = clean_html(raw_html)

    quelle_typ = "web"
    if "youtube.com" in url or "youtu.be" in url: quelle_typ = "youtube"
    elif "tiktok.com"    in url: quelle_typ = "tiktok"
    elif "instagram.com" in url: quelle_typ = "instagram"
    elif any(x in url for x in ["chefkoch","allrecipes","lecker.de"]): quelle_typ = "rezeptseite"

    claude = Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = claude.messages.create(
        model=CLAUDE_MODEL, max_tokens=2048,
        messages=[{"role": "user", "content": f"{PROMPT_URL}\n\n(URL: {url})\n---\n{clean_text}\n---"}]
    )
    try:
        result = parse_claude(msg.content[0].text)
    except Exception as e:
        raise HTTPException(500, f"Claude-Antwort konnte nicht geparst werden: {e}")
    if result.get("fehler"):
        if downloaded_image:
            p = UPLOAD_DIR / downloaded_image
            if p.exists(): p.unlink()
        raise HTTPException(422, result["fehler"])

    result.update({"quelle_url": url, "quelle_typ": quelle_typ,
                   "downloaded_image": downloaded_image})
    return result

# ── BILD / PDF ANALYSE ────────────────────────────────────────────────────────
@app.post("/api/analysiere-bild")
async def analysiere_bild(file: UploadFile = File(...)):
    check_api_key()

    ext = Path(file.filename).suffix.lower()
    data = await file.read()

    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Datei zu groß (max {MAX_UPLOAD_MB} MB)")

    # PDF handling
    if ext == ".pdf":
        b64 = base64.standard_b64encode(data).decode()
        claude = Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = claude.messages.create(
            model=CLAUDE_MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64",
                 "media_type": "application/pdf", "data": b64}},
                {"type": "text", "text": PROMPT_IMAGE}
            ]}]
        )
    else:
        # Image handling
        media_map = {".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png",
                     ".webp":"image/webp",".gif":"image/gif",".heic":"image/jpeg"}
        if ext not in media_map:
            raise HTTPException(400, f"Format nicht unterstützt: {ext} (JPG, PNG, WebP, PDF)")
        b64 = base64.standard_b64encode(data).decode()
        claude = Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = claude.messages.create(
            model=CLAUDE_MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": media_map[ext], "data": b64}},
                {"type": "text", "text": PROMPT_IMAGE}
            ]}]
        )

    try:
        result = parse_claude(msg.content[0].text)
    except Exception as e:
        raise HTTPException(500, f"Claude-Antwort konnte nicht geparst werden: {e}")
    if result.get("fehler"):
        raise HTTPException(422, result["fehler"])

    result["quelle_typ"] = "pdf-import" if ext == ".pdf" else "bild-import"
    return result

# ── REZEPT SUCHBOT ───────────────────────────────────────────────────────────
SEARCH_SYSTEM = """Du bist ein Rezept-Assistent für die Familie Battlogg in Vorarlberg, Österreich.

Deine Aufgabe: Suche 2-3 der besten Rezepte im Internet basierend auf dem Wunsch des Benutzers.

Wichtige Kriterien:
- Nur Rezepte mit guten Bewertungen (mindestens 4 Sterne oder sehr positiven Kommentaren)
- Bevorzuge deutschsprachige Quellen: chefkoch.de, lecker.de, küchengötter.de, gutekueche.at, ichkoche.at, rezeptwelt.at
- Ernährungseinschränkungen und Wünsche des Benutzers beachten
- Zutaten im deutschsprachigen Raum erhältlich (keine exotischen US-Spezialitäten)

Ablauf:
1. Suche im Web nach passenden Rezepten
2. Wähle die 2-3 besten basierend auf Bewertungen und Relevanz
3. Extrahiere jedes Rezept vollständig
4. Antworte NUR mit einem validen JSON-Array (kein Markdown, keine Erklärungen):

[
  {
    "titel": "Rezeptname",
    "beschreibung": "Kurzbeschreibung (1-2 Sätze)",
    "zutaten": [
      {"menge": "200", "einheit": "g", "name": "Mehl"},
      {"menge": "3", "einheit": "EL", "name": "Olivenöl"}
    ],
    "zubereitung": "Schritt-für-Schritt Zubereitung",
    "portionen": 4,
    "zeit_vorb": 15,
    "zeit_koch": 30,
    "schwierigkeit": "leicht",
    "kategorie": "Hauptgericht",
    "tags": ["vegetarisch", "schnell"],
    "kalorien_pro_portion": 450,
    "quelle_url": "https://...",
    "quelle_typ": "web",
    "suchinfo": "Bewertung und Quelle, z.B. '4.8 Sterne auf Chefkoch, über 500 Bewertungen'"
  }
]

Regeln:
- Gib IMMER ein Array zurück, auch wenn nur 1 Ergebnis vorhanden
- schwierigkeit: nur "leicht", "mittel" oder "schwer"
- kategorie: Frühstück | Vorspeise | Hauptgericht | Dessert | Snack | Getränk | Backen | Salat | Suppe | Sonstiges
- Antworte auf Deutsch
- Falls kein passendes Rezept: [{"fehler": "Kein passendes Rezept gefunden: [Grund]"}]"""

@app.post("/api/rezept-suche")
def rezept_suche(body: dict):
    anfrage = body.get("anfrage", "").strip()
    if not anfrage:
        raise HTTPException(400, "Anfrage fehlt")
    check_api_key()

    claude = Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=5000,
        system=SEARCH_SYSTEM,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": f"Suche 2-3 Rezepte für: {anfrage}"}]
    )

    # Collect all content blocks and handle tool use loop
    messages = [{"role": "user", "content": f"Suche 2-3 Rezepte für: {anfrage}"}]
    final_text = ""

    current_msg = msg
    for _ in range(4):  # max 4 tool rounds
        # Extract text from current response
        for block in current_msg.content:
            if getattr(block, "type", None) == "text":
                final_text = block.text

        if current_msg.stop_reason != "tool_use":
            break

        # Build tool results and continue
        messages.append({"role": "assistant", "content": current_msg.content})
        tool_results = [
            {"type": "tool_result", "tool_use_id": b.id, "content": "Suche durchgeführt"}
            for b in current_msg.content if getattr(b, "type", None) == "tool_use"
        ]
        messages.append({"role": "user", "content": tool_results})

        current_msg = claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=5000,
            system=SEARCH_SYSTEM,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=messages
        )

    if not final_text:
        raise HTTPException(500, "Keine Antwort von Claude erhalten")

    # Parse — expect array
    try:
        raw = final_text.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        results = json.loads(raw)
        if isinstance(results, dict):
            results = [results]  # wrap single object
    except Exception as e:
        raise HTTPException(500, f"Antwort konnte nicht geparst werden: {e}")

    # Check for error
    if len(results) == 1 and results[0].get("fehler"):
        raise HTTPException(422, results[0]["fehler"])

    # Filter out any error objects
    results = [r for r in results if not r.get("fehler")]
    if not results:
        raise HTTPException(422, "Keine passenden Rezepte gefunden")

    return results


# ── STATIC + SPA ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

@app.get("/{full_path:path}")
def spa(full_path: str):
    return FileResponse(str(BASE_DIR / "static" / "index.html"))
