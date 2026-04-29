from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from db import get_db
from services.image_service import validate_and_save, search_recipe_image
from config import UPLOAD_DIR
from auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/api/rezepte/{rid}/bilder")
def upload_bild(rid: int, file: UploadFile = File(...), ist_haupt: bool = Form(False)):
    with get_db() as conn:
        with conn.cursor() as cur:
            if not cur.execute("SELECT 1 FROM rezepte WHERE id=%s", (rid,)):
                raise HTTPException(404, "Rezept nicht gefunden")
    ext = Path(file.filename).suffix.lower()
    fname = validate_and_save(file.file.read(), ext)
    with get_db() as conn:
        with conn.cursor() as cur:
            if ist_haupt:
                cur.execute("UPDATE bilder SET ist_haupt=0 WHERE rezept_id=%s", (rid,))
            cur.execute("INSERT INTO bilder (rezept_id,dateiname,ist_haupt) VALUES (%s,%s,%s)",
                        (rid, fname, 1 if ist_haupt else 0))
    return {"dateiname": fname, "url": f"/static/uploads/{fname}", "ist_haupt": ist_haupt}


@router.post("/api/rezepte/{rid}/bilder/attach")
def attach_downloaded_bild(rid: int, body: dict):
    dateiname = body.get("dateiname", "").strip()
    if not dateiname:
        raise HTTPException(400, "dateiname fehlt")
    if not (UPLOAD_DIR / dateiname).exists():
        raise HTTPException(404, "Bilddatei nicht gefunden")
    ist_haupt = body.get("ist_haupt", True)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM rezepte WHERE id=%s", (rid,))
            if not cur.fetchone():
                raise HTTPException(404, "Rezept nicht gefunden")
            if ist_haupt:
                cur.execute("UPDATE bilder SET ist_haupt=0 WHERE rezept_id=%s", (rid,))
            cur.execute("INSERT INTO bilder (rezept_id,dateiname,ist_haupt) VALUES (%s,%s,%s)",
                        (rid, dateiname, 1 if ist_haupt else 0))
    return {"dateiname": dateiname, "url": f"/static/uploads/{dateiname}", "ist_haupt": ist_haupt}


@router.delete("/api/bilder/{bid}")
def delete_bild(bid: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT dateiname FROM bilder WHERE id=%s", (bid,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Bild nicht gefunden")
            p = UPLOAD_DIR / row["dateiname"]
            if p.exists():
                p.unlink()
            cur.execute("DELETE FROM bilder WHERE id=%s", (bid,))
    return {"ok": True}


@router.put("/api/bilder/{bid}/haupt")
def set_haupt(bid: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT rezept_id FROM bilder WHERE id=%s", (bid,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Bild nicht gefunden")
            cur.execute("UPDATE bilder SET ist_haupt=0 WHERE rezept_id=%s", (row["rezept_id"],))
            cur.execute("UPDATE bilder SET ist_haupt=1 WHERE id=%s", (bid,))
    return {"ok": True}


@router.post("/api/rezepte/{rid}/fetch-bild")
def fetch_bild_auto(rid: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM bilder WHERE rezept_id=%s", (rid,))
            if cur.fetchone()["n"] > 0:
                return {"ok": True, "skipped": True}
            cur.execute("SELECT titel FROM rezepte WHERE id=%s", (rid,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Rezept nicht gefunden")
            titel = row["titel"]
    fname = search_recipe_image(titel)
    if fname:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO bilder (rezept_id, dateiname, ist_haupt) VALUES (%s, %s, 1)",
                            (rid, fname))
        return {"ok": True, "dateiname": fname, "url": f"/static/uploads/{fname}"}
    return {"ok": True, "skipped": True, "reason": "no image found"}
