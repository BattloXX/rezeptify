"""Local recipe suggestions for the "Was kochen wir?" view."""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth import require_auth
from db import clean_row, get_bilder_batch, get_db


router = APIRouter(dependencies=[Depends(require_auth)])


def _has_ingredients(recipe: dict, requested: list[str]) -> bool:
    """Return whether every requested term occurs in an ingredient name."""
    names = " ".join(
        str(ingredient.get("name", "")).lower()
        for ingredient in recipe.get("zutaten", [])
        if isinstance(ingredient, dict)
    )
    return all(term in names for term in requested)


@router.get("/api/rezepte/vorschlag")
def get_vorschlaege(
    zutaten: Optional[str] = Query(None),
    max_zeit: Optional[int] = Query(None, ge=0),
    kategorie: Optional[str] = Query(None),
    vegetarisch: Optional[bool] = Query(None),
    vegan: Optional[bool] = Query(None),
    favorit: Optional[bool] = Query(None),  # Reserved for Feature 5.
    bewertung_min: Optional[int] = Query(None, ge=1, le=5),
    schwierigkeit: Optional[str] = Query(None),
    text: Optional[str] = Query(None),
):
    where, params = [], []
    if max_zeit is not None:
        where.append("(COALESCE(r.zeit_vorb, 0) + COALESCE(r.zeit_koch, 0)) <= %s")
        params.append(max_zeit)
    if kategorie:
        where.append("r.kategorie = %s")
        params.append(kategorie)
    if vegetarisch:
        where.append("JSON_SEARCH(r.tags, 'one', %s) IS NOT NULL")
        params.append("vegetarisch")
    if vegan:
        where.append("JSON_SEARCH(r.tags, 'one', %s) IS NOT NULL")
        params.append("vegan")
    if bewertung_min is not None:
        where.append("r.bewertung >= %s")
        params.append(bewertung_min)
    if schwierigkeit:
        where.append("r.schwierigkeit = %s")
        params.append(schwierigkeit)
    if text:
        # Tags are deliberately included as a fallback because they are not in
        # the FULLTEXT index (and often carry useful terms such as "Pasta").
        where.append("(MATCH(r.titel, r.beschreibung) AGAINST (%s IN BOOLEAN MODE) "
                     "OR JSON_SEARCH(r.tags, 'one', %s) IS NOT NULL)")
        params.extend([text + "*", "%" + text + "%"])

    # ``favorit`` is accepted now for forward-compatible clients.  There is no
    # corresponding database field until Feature 5, so it intentionally has no
    # effect here.
    _ = favorit
    requested_ingredients = [part.strip().lower() for part in (zutaten or "").split(",") if part.strip()]
    sql_where = "WHERE " + " AND ".join(where) if where else ""

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT r.* FROM rezepte r {sql_where} ORDER BY r.erstellt_am DESC LIMIT 200",
                params,
            )
            rows = [clean_row(row) for row in cur.fetchall()]
            if requested_ingredients:
                rows = [row for row in rows if _has_ingredients(row, requested_ingredients)]
            bilder_map = get_bilder_batch(cur, [row["id"] for row in rows])

    for row in rows:
        row["bilder"] = bilder_map.get(row["id"], [])
        row["haupt_bild"] = next((bild["url"] for bild in row["bilder"] if bild["ist_haupt"]), None)
    return {"rezepte": rows}
