from fastapi import APIRouter, Depends
from db import get_db, parse_json_field
from auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/kategorien")
def get_kategorien():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM kategorien ORDER BY name")
            return [r["name"] for r in cur.fetchall()]


@router.get("/api/tags")
def get_tags():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT tags FROM rezepte WHERE tags IS NOT NULL AND tags != '[]'")
            rows = cur.fetchall()
    alle = set()
    for r in rows:
        try:
            alle.update(parse_json_field(r["tags"]))
        except Exception:
            pass
    return sorted(alle)


@router.get("/api/stats")
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
