"""Database connection, helpers and schema init."""
import json
from contextlib import contextmanager
import pymysql
import pymysql.cursors

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_CHARSET

# Informative Version für den Health-Endpoint; init_db() bleibt bewusst idempotent.
SCHEMA_VERSION = 3


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


def build_suchtext(titel, beschreibung, kategorie, tags, zutaten) -> str:
    parts = [titel, beschreibung, kategorie]
    parts.extend(parse_json_field(tags))
    for zutat in parse_json_field(zutaten):
        if isinstance(zutat, dict):
            parts.extend([zutat.get("name"), zutat.get("gruppe")])
    return " ".join(str(part) for part in parts if part)


def clean_row(row: dict) -> dict:
    row["zutaten"] = parse_json_field(row.get("zutaten"))
    row["tags"] = parse_json_field(row.get("tags"))
    for f in ("erstellt_am", "geaendert_am", "zuletzt_gekocht"):
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rezept_schritte (
                    id              INT AUTO_INCREMENT PRIMARY KEY,
                    rezept_id       INT NOT NULL,
                    position        SMALLINT NOT NULL,
                    text            TEXT NOT NULL,
                    zutaten_indices JSON NULL,
                    timer_sekunden  INT NULL,
                    erstellt_am     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_rezept_schritte_position (rezept_id, position),
                    FOREIGN KEY (rezept_id) REFERENCES rezepte(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS einkaufsliste_eintraege (
                    id           INT AUTO_INCREMENT PRIMARY KEY,
                    name         VARCHAR(255) NOT NULL,
                    menge        DECIMAL(10,3) NULL,
                    einheit      VARCHAR(32) NULL,
                    menge_text   VARCHAR(64) NULL,
                    erledigt     TINYINT(1) NOT NULL DEFAULT 0,
                    manuell      TINYINT(1) NOT NULL DEFAULT 0,
                    herkunft     JSON NULL,
                    sortierung   SMALLINT NULL,
                    erstellt_am  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    geaendert_am TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wochenplan (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    rezept_id   INT NOT NULL,
                    datum       DATE NOT NULL,
                    mahlzeit    ENUM('fruehstueck','mittag','abend','snack') DEFAULT 'abend',
                    portionen   SMALLINT NULL,
                    notiz       VARCHAR(255) NULL,
                    erstellt_am TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_wochenplan_datum (datum),
                    FOREIGN KEY (rezept_id) REFERENCES rezepte(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kochhistorie (
                    id                       INT AUTO_INCREMENT PRIMARY KEY,
                    rezept_id                INT NOT NULL,
                    gekocht_am               DATETIME DEFAULT CURRENT_TIMESTAMP,
                    portionen_verwendet      SMALLINT NULL,
                    notiz                    TEXT NULL,
                    nachtraegliche_bewertung TINYINT NULL,
                    erstellt_am              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_kochhistorie_rezept_gekocht (rezept_id, gekocht_am),
                    FOREIGN KEY (rezept_id) REFERENCES rezepte(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ki_nutzung (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    ip VARCHAR(64) NOT NULL,
                    endpunkt VARCHAR(50) NOT NULL,
                    erstellt_am DATETIME NOT NULL,
                    INDEX (erstellt_am),
                    INDEX (ip, erstellt_am)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS system_updates (
                    id            INT AUTO_INCREMENT PRIMARY KEY,
                    gestartet_am  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status        ENUM('laufend','neustart_ausgeloest','abgeschlossen','fehlgeschlagen') NOT NULL DEFAULT 'laufend',
                    von_version   VARCHAR(20) NULL,
                    ziel_version  VARCHAR(20) NULL,
                    backup_pfad   VARCHAR(255) NULL,
                    log           TEXT NULL,
                    fehler        TEXT NULL,
                    beendet_am    TIMESTAMP NULL,
                    INDEX idx_system_updates_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS error_log (
                    id              INT AUTO_INCREMENT PRIMARY KEY,
                    erstellt_am     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    methode         VARCHAR(10) NOT NULL,
                    pfad            VARCHAR(500) NOT NULL,
                    exception_typ   VARCHAR(255) NOT NULL,
                    nachricht       TEXT NULL,
                    INDEX idx_error_log_erstellt_am (erstellt_am)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mcp_oauth_clients (
                    client_id VARCHAR(255) PRIMARY KEY,
                    client_name VARCHAR(255) NULL,
                    redirect_uris JSON NOT NULL,
                    grant_types JSON NOT NULL,
                    response_types JSON NOT NULL,
                    token_endpoint_auth_method VARCHAR(50) NOT NULL DEFAULT 'none',
                    scope VARCHAR(255) NULL,
                    metadata JSON NULL,
                    erstellt_am TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mcp_oauth_auth_codes (
                    code_hash CHAR(64) PRIMARY KEY,
                    client_id VARCHAR(255) NOT NULL,
                    redirect_uri VARCHAR(500) NOT NULL,
                    redirect_uri_explicit TINYINT(1) NOT NULL DEFAULT 1,
                    code_challenge VARCHAR(255) NOT NULL,
                    scope VARCHAR(255) NULL,
                    resource VARCHAR(500) NULL,
                    subject VARCHAR(255) NULL,
                    expires_at DATETIME NOT NULL,
                    erstellt_am TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (client_id) REFERENCES mcp_oauth_clients(client_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mcp_oauth_tokens (
                    token_hash CHAR(64) PRIMARY KEY,
                    token_type ENUM('access','refresh') NOT NULL,
                    client_id VARCHAR(255) NOT NULL,
                    scope VARCHAR(255) NULL,
                    resource VARCHAR(500) NULL,
                    subject VARCHAR(255) NULL,
                    expires_at DATETIME NULL,
                    revoked TINYINT(1) NOT NULL DEFAULT 0,
                    rotated_at DATETIME NULL,
                    linked_token_hash CHAR(64) NULL,
                    erstellt_am TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_mcp_oauth_tokens_client (client_id),
                    FOREIGN KEY (client_id) REFERENCES mcp_oauth_clients(client_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mcp_oauth_pending (
                    pending_id CHAR(64) PRIMARY KEY,
                    client_id VARCHAR(255) NOT NULL,
                    redirect_uri VARCHAR(500) NOT NULL,
                    redirect_uri_explicit TINYINT(1) NOT NULL DEFAULT 1,
                    code_challenge VARCHAR(255) NOT NULL,
                    scope VARCHAR(255) NULL,
                    resource VARCHAR(500) NULL,
                    state_value VARCHAR(2048) NULL,
                    expires_at DATETIME NOT NULL,
                    erstellt_am TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (client_id) REFERENCES mcp_oauth_clients(client_id) ON DELETE CASCADE
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
            ("quelldatei",          "ADD COLUMN quelldatei VARCHAR(255) DEFAULT NULL AFTER quelle_typ"),
            ("schritte_quelle",     "ADD COLUMN schritte_quelle ENUM('keine','auto','manuell') DEFAULT 'keine' AFTER zubereitung"),
            ("favorit",              "ADD COLUMN favorit TINYINT(1) NOT NULL DEFAULT 0 AFTER bewertung"),
            ("suchtext",            "ADD COLUMN suchtext LONGTEXT NULL"),
        ]:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='rezepte' AND COLUMN_NAME=%s
                """, (col,))
                if cur.fetchone()["n"] == 0:
                    cur.execute(f"ALTER TABLE rezepte {alter}")
            conn.commit()

        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='mcp_oauth_tokens' AND COLUMN_NAME='rotated_at'
            """)
            if cur.fetchone()["n"] == 0:
                cur.execute("ALTER TABLE mcp_oauth_tokens ADD COLUMN rotated_at DATETIME NULL AFTER revoked")
        conn.commit()

        # Backfill missing slugs
        with conn.cursor() as cur:
            cur.execute("SELECT id, titel FROM rezepte WHERE slug IS NULL OR slug=''")
            for row in cur.fetchall():
                cur.execute("UPDATE rezepte SET slug=%s WHERE id=%s",
                            (make_slug(row["titel"], row["id"]), row["id"]))
        conn.commit()

        # Backfill search text for existing recipes
        with conn.cursor() as cur:
            cur.execute("SELECT id, titel, beschreibung, kategorie, tags, zutaten FROM rezepte WHERE suchtext IS NULL")
            for row in cur.fetchall():
                cur.execute("UPDATE rezepte SET suchtext=%s WHERE id=%s",
                            (build_suchtext(row["titel"], row["beschreibung"], row["kategorie"],
                                           row["tags"], row["zutaten"]), row["id"]))
        conn.commit()

        # Shopping sync schema; old integer IDs remain available to legacy routes.
        from uuid import uuid4
        from services.einkauf_sync import rang_initial, server_hlc, standard_liste
        from services.shopping_service import normalize_name
        with conn.cursor() as cur:
            for table, definition in [
                ("einkaufslisten", """uuid CHAR(36) PRIMARY KEY, name VARCHAR(120) NOT NULL,
                    seq BIGINT NOT NULL DEFAULT 0, ist_standard TINYINT(1) NOT NULL DEFAULT 0,
                    archiviert TINYINT(1) NOT NULL DEFAULT 0,
                    erstellt_am TIMESTAMP DEFAULT CURRENT_TIMESTAMP"""),
                ("einkauf_ops", """op_id CHAR(36) PRIMARY KEY, liste_uuid CHAR(36) NOT NULL,
                    eintrag_uuid CHAR(36) NULL, typ VARCHAR(32) NOT NULL, hlc VARCHAR(64) NOT NULL,
                    daten JSON NULL, ergebnis VARCHAR(16) NOT NULL, seq BIGINT NOT NULL DEFAULT 0,
                    empfangen_am DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_ops_eintrag (eintrag_uuid, typ, hlc)"""),
                ("einkauf_aliase", """alt_uuid CHAR(36) PRIMARY KEY, ziel_uuid CHAR(36) NOT NULL,
                    liste_uuid CHAR(36) NOT NULL, seq BIGINT NOT NULL DEFAULT 0,
                    INDEX idx_alias_liste_seq (liste_uuid, seq)"""),
            ]:
                cur.execute(f"CREATE TABLE IF NOT EXISTS {table} ({definition}) "
                            "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci")
            columns = {
                "uuid": "CHAR(36) NULL", "liste_uuid": "CHAR(36) NULL",
                "name_norm": "VARCHAR(255) NULL", "notiz": "VARCHAR(255) NULL",
                "kategorie_id": "INT NULL", "rang": "VARCHAR(64) NULL",
                "erledigt_am": "DATETIME NULL", "geloescht_am": "DATETIME NULL",
                "seq": "BIGINT NOT NULL DEFAULT 0",
            }
            for field in ("inhalt", "menge", "status", "position", "geloescht"):
                columns["hlc_" + field] = "VARCHAR(64) NOT NULL DEFAULT ''"
            for column, definition in columns.items():
                cur.execute("""SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='einkaufsliste_eintraege'
                    AND COLUMN_NAME=%s""", (column,))
                if not cur.fetchone()["n"]:
                    cur.execute(f"ALTER TABLE einkaufsliste_eintraege ADD COLUMN {column} {definition}")
            for index, definition in [
                ("uq_einkauf_uuid", "UNIQUE INDEX uq_einkauf_uuid (uuid)"),
                ("idx_einkauf_liste_seq", "INDEX idx_einkauf_liste_seq (liste_uuid, seq)"),
            ]:
                cur.execute("""SELECT COUNT(*) AS n FROM information_schema.STATISTICS
                    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='einkaufsliste_eintraege'
                    AND INDEX_NAME=%s""", (index,))
                if not cur.fetchone()["n"]:
                    cur.execute(f"ALTER TABLE einkaufsliste_eintraege ADD {definition}")
            liste_uuid = standard_liste(cur)
            cur.execute("SELECT seq FROM einkaufslisten WHERE uuid=%s FOR UPDATE", (liste_uuid,))
            seq = cur.fetchone()["seq"]
            cur.execute("SELECT MAX(seq) AS seq FROM einkaufsliste_eintraege WHERE liste_uuid=%s", (liste_uuid,))
            seq = max(seq, cur.fetchone()["seq"] or 0)
            cur.execute("SELECT id, name FROM einkaufsliste_eintraege WHERE uuid IS NULL ORDER BY erledigt, sortierung IS NULL, sortierung, id")
            rows = cur.fetchall()
            hlc = server_hlc() if rows else None
            for i, row in enumerate(rows):
                seq += 1
                cur.execute("""UPDATE einkaufsliste_eintraege SET uuid=%s, liste_uuid=%s,
                    name_norm=%s, rang=%s, hlc_inhalt=%s, hlc_menge=%s, hlc_status=%s,
                    hlc_position=%s, hlc_geloescht=%s, seq=%s WHERE id=%s""",
                            (str(uuid4()), liste_uuid, normalize_name(row["name"]), rang_initial(i),
                             hlc, hlc, hlc, hlc, hlc, seq, row["id"]))
            cur.execute("UPDATE einkaufslisten SET seq=%s WHERE uuid=%s", (seq, liste_uuid))
        conn.commit()

        # Shopping categories and store-specific aisle ordering.
        with conn.cursor() as cur:
            for table, definition in [
                ("einkauf_kategorien", """id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(80) UNIQUE,
                    icon VARCHAR(40), standard_rang VARCHAR(64), aktiv TINYINT(1) DEFAULT 1"""),
                ("einkauf_artikel", """name_norm VARCHAR(255) PRIMARY KEY, anzeigename VARCHAR(255),
                    kategorie_id INT NULL, letzte_menge DECIMAL(10,3) NULL, letzte_einheit VARCHAR(32) NULL,
                    anzahl_gekauft INT DEFAULT 0, zuletzt_gekauft DATETIME NULL, intervall_tage DECIMAL(6,2) NULL,
                    vorrat TINYINT(1) DEFAULT 0, ausgeblendet TINYINT(1) DEFAULT 0,
                    quelle ENUM('start','gelernt') DEFAULT 'gelernt', geaendert_seq BIGINT DEFAULT 0"""),
                ("laeden", """id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(80) UNIQUE,
                    aktiv TINYINT(1) DEFAULT 1, standard TINYINT(1) DEFAULT 0"""),
                ("laden_kategorie_rang", """laden_id INT, kategorie_id INT, rang VARCHAR(64),
                    PRIMARY KEY (laden_id,kategorie_id)"""),
            ]:
                cur.execute(f"CREATE TABLE IF NOT EXISTS {table} ({definition}) "
                            "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci")
            cur.execute("""SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='einkaufslisten' AND COLUMN_NAME='laden_id'""")
            if not cur.fetchone()["n"]:
                cur.execute("ALTER TABLE einkaufslisten ADD COLUMN laden_id INT NULL")
            from services.einkauf_woerterbuch import seed
            seed(cur)
        conn.commit()
