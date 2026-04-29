"""Database connection, helpers and schema init."""
import json
from contextlib import contextmanager
import pymysql
import pymysql.cursors

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_CHARSET


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


def parse_json_field(val):
    if val is None:
        return []
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return []


def clean_row(row: dict) -> dict:
    row["zutaten"] = parse_json_field(row.get("zutaten"))
    row["tags"] = parse_json_field(row.get("tags"))
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


def get_bilder_batch(cur, rezept_ids: list) -> dict:
    if not rezept_ids:
        return {}
    placeholders = ','.join(['%s'] * len(rezept_ids))
    cur.execute(
        f"SELECT id, rezept_id, dateiname, ist_haupt FROM bilder "
        f"WHERE rezept_id IN ({placeholders}) ORDER BY ist_haupt DESC, id",
        rezept_ids
    )
    result: dict = {}
    for r in cur.fetchall():
        rid = r["rezept_id"]
        result.setdefault(rid, []).append({
            "id": r["id"], "dateiname": r["dateiname"],
            "url": f"/static/uploads/{r['dateiname']}",
            "ist_haupt": bool(r["ist_haupt"])
        })
    return result


def enrich(row: dict, cur) -> dict:
    row = clean_row(row)
    row["bilder"] = get_bilder(cur, row["id"])
    row["haupt_bild"] = next((b["url"] for b in row["bilder"] if b["ist_haupt"]), None)
    return row


def init_db():
    from slug_utils import make_slug
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

        # Migrations
        for col, alter in [
            ("slug",                "ADD COLUMN slug VARCHAR(300) UNIQUE AFTER titel"),
            ("kalorien_pro_portion","ADD COLUMN kalorien_pro_portion INT DEFAULT NULL AFTER bewertung"),
            ("bewertung",           "ADD COLUMN bewertung TINYINT DEFAULT NULL AFTER quelle_typ"),
        ]:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='rezepte' AND COLUMN_NAME=%s
                """, (col,))
                if cur.fetchone()["n"] == 0:
                    cur.execute(f"ALTER TABLE rezepte {alter}")
            conn.commit()

        # Backfill missing slugs
        with conn.cursor() as cur:
            cur.execute("SELECT id, titel FROM rezepte WHERE slug IS NULL OR slug=''")
            for row in cur.fetchall():
                cur.execute("UPDATE rezepte SET slug=%s WHERE id=%s",
                            (make_slug(row["titel"], row["id"]), row["id"]))
        conn.commit()
