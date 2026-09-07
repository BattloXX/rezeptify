import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from db import get_db, clean_row, enrich, get_bilder_batch
from models import RezeptIn
from slug_utils import make_slug
from auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/rezepte")
def get_rezepte(
    suche:         Optional[str] = Query(None),
    kategorie:     Optional[str] = Query(None),
    tag:           Optional[str] = Query(None),
    schwierigkeit: Optional[str] = Query(None),
    bewertung:     Optional[int] = Query(None),
    nur_favoriten: Optional[bool] = Query(None),
    nur_gekocht:   Optional[bool] = Query(None),
    sort:          Optional[str] = Query("neu"),
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
    if nur_favoriten:
        where.append("r.favorit = 1")
    if nur_gekocht:
        where.append("COALESCE(h.anzahl_gekocht, 0) > 0")

    w = ("WHERE " + " AND ".join(where)) if where else ""
    order = {"sterne": "r.bewertung DESC, r.erstellt_am DESC",
             "name":   "r.titel ASC",
             "neu":    "r.erstellt_am DESC",
             "favoriten": "r.favorit DESC, r.erstellt_am DESC",
             "zuletzt_gekocht": "h.zuletzt_gekocht DESC, r.erstellt_am DESC",
             "haeufig_gekocht": "COALESCE(h.anzahl_gekocht, 0) DESC, r.erstellt_am DESC",
             "lange_nicht_gekocht": "h.zuletzt_gekocht IS NOT NULL ASC, h.zuletzt_gekocht ASC, r.erstellt_am DESC"}.get(sort, "r.erstellt_am DESC")

    history_join = "LEFT JOIN (SELECT rezept_id, MAX(gekocht_am) AS zuletzt_gekocht, COUNT(*) AS anzahl_gekocht FROM kochhistorie GROUP BY rezept_id) h ON h.rezept_id = r.id"

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM rezepte r {history_join} {w}", params)
            total = cur.fetchone()["n"]
            cur.execute(f"SELECT r.*, h.zuletzt_gekocht, COALESCE(h.anzahl_gekocht, 0) AS anzahl_gekocht FROM rezepte r {history_join} {w} ORDER BY {order} LIMIT %s OFFSET %s",
                        params + [limit, offset])
            rows = cur.fetchall()
            bilder_map = get_bilder_batch(cur, [r["id"] for r in rows])
            items = []
            for row in rows:
                row = clean_row(row)
                row["bilder"] = bilder_map.get(row["id"], [])
                row["haupt_bild"] = next((b["url"] for b in row["bilder"] if b["ist_haupt"]), None)
                items.append(row)
    return {"total": total, "items": items, "limit": limit, "offset": offset}


@router.get("/api/rezepte/slug/{slug}")
def get_rezept_by_slug(slug: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT r.*, h.zuletzt_gekocht, COALESCE(h.anzahl_gekocht, 0) AS anzahl_gekocht
                FROM rezepte r LEFT JOIN (SELECT rezept_id, MAX(gekocht_am) AS zuletzt_gekocht, COUNT(*) AS anzahl_gekocht FROM kochhistorie GROUP BY rezept_id) h ON h.rezept_id=r.id
                WHERE r.slug=%s""", (slug,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Rezept nicht gefunden")
            return enrich(row, cur)


@router.get("/api/rezepte/{rid}")
def get_rezept(rid: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT r.*, h.zuletzt_gekocht, COALESCE(h.anzahl_gekocht, 0) AS anzahl_gekocht
                FROM rezepte r LEFT JOIN (SELECT rezept_id, MAX(gekocht_am) AS zuletzt_gekocht, COUNT(*) AS anzahl_gekocht FROM kochhistorie GROUP BY rezept_id) h ON h.rezept_id=r.id
                WHERE r.id=%s""", (rid,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Rezept nicht gefunden")
            return enrich(row, cur)


@router.patch("/api/rezepte/{rid}/bewertung")
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


@router.patch("/api/rezepte/{rid}/favorit")
def set_favorit(rid: int, body: dict):
    favorit = body.get("favorit")
    if not isinstance(favorit, bool):
        raise HTTPException(400, "favorit muss ein Boolean sein")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE rezepte SET favorit=%s WHERE id=%s", (favorit, rid))
            if cur.rowcount == 0:
                raise HTTPException(404, "Rezept nicht gefunden")
    return {"ok": True, "favorit": favorit}


@router.post("/api/rezepte", status_code=201)
def create_rezept(data: RezeptIn):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO rezepte (titel,beschreibung,zutaten,zubereitung,portionen,
                    zeit_vorb,zeit_koch,schwierigkeit,kategorie,tags,quelle_url,quelle_typ,
                    quelldatei,kalorien_pro_portion)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (data.titel, data.beschreibung,
                  json.dumps([z.dict() for z in data.zutaten], ensure_ascii=False),
                  data.zubereitung, data.portionen, data.zeit_vorb, data.zeit_koch,
                  data.schwierigkeit, data.kategorie,
                  json.dumps(data.tags, ensure_ascii=False),
                  data.quelle_url, data.quelle_typ, data.quelldatei, data.kalorien_pro_portion))
            new_id = cur.lastrowid
            slug = make_slug(data.titel, new_id)
            cur.execute("UPDATE rezepte SET slug=%s WHERE id=%s", (slug, new_id))
            cur.execute("SELECT * FROM rezepte WHERE id=%s", (new_id,))
            return enrich(cur.fetchone(), cur)


@router.put("/api/rezepte/{rid}")
def update_rezept(rid: int, data: RezeptIn):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE rezepte SET titel=%s,beschreibung=%s,zutaten=%s,zubereitung=%s,
                    portionen=%s,zeit_vorb=%s,zeit_koch=%s,schwierigkeit=%s,
                    kategorie=%s,tags=%s,quelle_url=%s,quelle_typ=%s,
                    quelldatei=%s,kalorien_pro_portion=%s
                WHERE id=%s
            """, (data.titel, data.beschreibung,
                  json.dumps([z.dict() for z in data.zutaten], ensure_ascii=False),
                  data.zubereitung, data.portionen, data.zeit_vorb, data.zeit_koch,
                  data.schwierigkeit, data.kategorie,
                  json.dumps(data.tags, ensure_ascii=False),
                  data.quelle_url, data.quelle_typ, data.quelldatei, data.kalorien_pro_portion, rid))
            slug = make_slug(data.titel, rid)
            cur.execute("UPDATE rezepte SET slug=%s WHERE id=%s", (slug, rid))
            cur.execute("SELECT * FROM rezepte WHERE id=%s", (rid,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Rezept nicht gefunden")
            return enrich(row, cur)


@router.delete("/api/rezepte/{rid}")
def delete_rezept(rid: int):
    from config import UPLOAD_DIR
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT dateiname FROM bilder WHERE rezept_id=%s", (rid,))
            for b in cur.fetchall():
                p = UPLOAD_DIR / b["dateiname"]
                if p.exists():
                    p.unlink()
            cur.execute("SELECT quelldatei FROM rezepte WHERE id=%s", (rid,))
            row = cur.fetchone()
            if row and row.get("quelldatei"):
                qf = UPLOAD_DIR / row["quelldatei"]
                if qf.exists():
                    qf.unlink()
            cur.execute("DELETE FROM rezepte WHERE id=%s", (rid,))
    return {"ok": True}
