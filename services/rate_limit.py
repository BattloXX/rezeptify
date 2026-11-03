"""Database-backed Claude quotas shared by all application workers."""
from fastapi import HTTPException, Request

import config
import request_utils
from db import get_db


def enforce_ki_limit(request: Request, endpunkt: str):
    if request.scope.get("rezeptify_internal"):
        return
    ip = request_utils.client_ip(request)
    per_ip = getattr(config, "KI_LIMIT_PRO_IP_STUNDE", 30)
    total = getattr(config, "KI_LIMIT_GESAMT_TAG", 300)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT GET_LOCK('rezeptify_ki_limit', 5) AS locked")
            if not cur.fetchone()["locked"]:
                raise HTTPException(429, "KI-Limit erreicht, bitte später erneut versuchen",
                                    headers={"Retry-After": "3600"})
            try:
                cur.execute("""DELETE FROM ki_nutzung
                    WHERE erstellt_am < UTC_TIMESTAMP() - INTERVAL 2 DAY""")
                cur.execute("""SELECT COUNT(*) AS anzahl FROM ki_nutzung
                    WHERE ip=%s AND erstellt_am >= UTC_TIMESTAMP() - INTERVAL 1 HOUR""", (ip,))
                ip_count = cur.fetchone()["anzahl"]
                cur.execute("""SELECT COUNT(*) AS anzahl FROM ki_nutzung
                    WHERE erstellt_am >= UTC_TIMESTAMP() - INTERVAL 24 HOUR""")
                total_count = cur.fetchone()["anzahl"]
                if (per_ip and ip_count >= per_ip) or (total and total_count >= total):
                    raise HTTPException(429, "KI-Limit erreicht, bitte später erneut versuchen",
                                        headers={"Retry-After": "3600"})
                cur.execute("""INSERT INTO ki_nutzung (ip, endpunkt, erstellt_am)
                    VALUES (%s, %s, UTC_TIMESTAMP())""", (ip, endpunkt))
                # Publish the reservation before another worker acquires the lock.
                conn.commit()
            finally:
                cur.execute("SELECT RELEASE_LOCK('rezeptify_ki_limit')")
