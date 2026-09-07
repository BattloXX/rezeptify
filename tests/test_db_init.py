def test_init_db_creates_kochmodus_schema(client):
    from db import get_db, init_db

    init_db()  # Must remain idempotent against the MariaDB test database.
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COLUMN_NAME FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='rezepte'
                  AND COLUMN_NAME='schritte_quelle'
            """)
            assert cur.fetchone()
            cur.execute("""
                SELECT TABLE_NAME FROM information_schema.TABLES
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='rezept_schritte'
            """)
            assert cur.fetchone()
