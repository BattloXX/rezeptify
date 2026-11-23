"""Versioned data export; deliberately bypasses lazy reads and schema helpers."""
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pymysql.cursors import DictCursor

from auth import require_auth
from db import get_db

router = APIRouter(dependencies=[Depends(require_auth)])


class _ReadOnlyCursor(DictCursor):
    """Keep export queries SELECT-only, including future additions."""

    def execute(self, query, args=None):
        if not query.lstrip().upper().startswith("SELECT "):
            raise ValueError("Export only permits SELECT queries")
        return super().execute(query, args)


def _serialize(value):
    if isinstance(value, datetime):
        # MariaDB's naive timestamps represent UTC in Rezeptify.
        return value.replace(tzinfo=timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _parse_fields(row, *fields):
    for field in fields:
        if row[field] is not None:
            row[field] = json.loads(row[field])
    return row


def _recipes(cur, limit, offset):
    cur.execute("SELECT COUNT(*) AS n FROM rezepte")
    total = cur.fetchone()["n"]
    cur.execute("SELECT * FROM rezepte ORDER BY id LIMIT %s OFFSET %s", (limit, offset))
    recipes = cur.fetchall()
    for recipe in recipes:
        _parse_fields(recipe, "zutaten", "tags")
        filename = recipe["quelldatei"]
        recipe["quelldatei_url"] = f"/static/uploads/{filename}" if filename else None
        cur.execute("SELECT id, dateiname, ist_haupt, erstellt_am FROM bilder "
                    "WHERE rezept_id=%s ORDER BY ist_haupt DESC, id", (recipe["id"],))
        recipe["bilder"] = [dict(row, url=f"/static/uploads/{row['dateiname']}")
                            for row in cur.fetchall()]
        cur.execute("SELECT position, text, zutaten_indices, timer_sekunden FROM rezept_schritte "
                    "WHERE rezept_id=%s ORDER BY position", (recipe["id"],))
        recipe["schritte"] = [_parse_fields(row, "zutaten_indices") for row in cur.fetchall()]
        cur.execute("SELECT id, gekocht_am, portionen_verwendet, notiz, "
                    "nachtraegliche_bewertung, erstellt_am FROM kochhistorie "
                    "WHERE rezept_id=%s ORDER BY id", (recipe["id"],))
        recipe["kochhistorie"] = cur.fetchall()
    return {"total": total, "limit": limit, "offset": offset, "rezepte": recipes}


def _meta(cur):
    cur.execute("SELECT name FROM kategorien ORDER BY name")
    categories = [row["name"] for row in cur.fetchall()]
    cur.execute("SELECT id, rezept_id, datum, mahlzeit, portionen, notiz, erstellt_am "
                "FROM wochenplan ORDER BY id")
    week_plan = cur.fetchall()
    shopping = {}
    for key, query in (
        ("kategorien", "SELECT * FROM einkauf_kategorien ORDER BY id"),
        ("artikel", "SELECT * FROM einkauf_artikel ORDER BY name_norm"),
        ("laeden", "SELECT * FROM laeden ORDER BY id"),
        ("laden_kategorie_rang", "SELECT * FROM laden_kategorie_rang ORDER BY laden_id, kategorie_id"),
        ("listen", "SELECT * FROM einkaufslisten ORDER BY uuid"),
    ):
        cur.execute(query)
        shopping[key] = cur.fetchall()
    cur.execute("SELECT uuid, liste_uuid, name, menge, einheit, menge_text, notiz, "
                "kategorie_id, rang, erledigt, manuell, herkunft, erstellt_am "
                "FROM einkaufsliste_eintraege WHERE geloescht_am IS NULL ORDER BY id")
    shopping["eintraege"] = [_parse_fields(row, "herkunft") for row in cur.fetchall()]
    return {"kategorien": categories, "wochenplan": week_plan, "einkauf": shopping}


@router.get("/api/export/v1")
def export_v1(
    teil: Literal["rezepte", "meta"] = Query(...),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    from app import APP_VERSION

    with get_db() as conn:
        with conn.cursor(_ReadOnlyCursor) as cur:
            data = _recipes(cur, limit, offset) if teil == "rezepte" else _meta(cur)
    return _serialize({"format": "rezeptify-export/v1", "version": APP_VERSION, **data})
