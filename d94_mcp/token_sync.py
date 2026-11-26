"""SN_API_TOKEN 활성 토큰 해시 → AP-02 Redis allowlist 동기화 (Server UMD 엣지 1차 차단용).

    python -m d94_mcp.token_sync            # 1회
    python -m d94_mcp.token_sync --loop 3600

키 d94:api-token:active:{sha256} 만 쓴다 (원문 없음). DB 에 없는 키는 지운다.
최종 검증은 항상 d94-query — 여기 반영이 늦어도 폐기 토큰은 d94-query 에서 401.
"""

import json
import logging
import os
import sys
import time

PREFIX = "d94:api-token:active:"
MAX_TTL = 7200  # 배치 주기(1h) x2 — 배치가 한 번 실패해도 키가 살아 있게

# ponytail: EXPIRES_AT 은 tz 없는 TIMESTAMP(d94-query JVM 시간). DB 세션 tz 가 다르면 TTL 이 그만큼 어긋나지만
# MAX_TTL 상한과 d94-query 최종 검증이 있어 안전. 어긋남이 문제되면 DB·JVM tz 를 맞출 것
SQL = """
SELECT t.token_hash, t.service_cd, t.expires_at,
       EXTRACT(EPOCH FROM (t.expires_at - LOCALTIMESTAMP))::bigint
FROM sn_api_token t
JOIN gs_user u ON u.email = t.owner_id
WHERE t.revoked_at IS NULL AND t.expires_at > LOCALTIMESTAMP
  AND t.use_stat_cd = 'Usable' AND u.use_stat_cd = 'Usable'
"""

log = logging.getLogger("token_sync")


def sync(rows, r) -> tuple[int, int]:
    """rows=(hash, service, expires_at, ttl_seconds). 반환 (설정 수, 삭제 수)"""
    active = {PREFIX + h.strip(): (svc, exp, ttl) for h, svc, exp, ttl in rows}
    stale = [k for k in r.scan_iter(match=PREFIX + "*", count=500) if k not in active]
    pipe = r.pipeline(transaction=False)
    for key, (svc, exp, ttl) in active.items():
        pipe.set(key, json.dumps({"service": svc, "expiresAt": exp.isoformat()}), ex=max(1, min(int(ttl), MAX_TTL)))
    for key in stale:
        pipe.delete(key)
    pipe.execute()
    for key in stale:
        log.info("revoked/expired removed: %s…", key[len(PREFIX):][:8])
    return len(active), len(stale)


def run_once() -> None:
    import psycopg
    import redis

    env = os.environ
    with psycopg.connect(host=env.get("DB_HOST", "localhost"), port=env.get("DB_PORT", "5432"),
                         dbname=env["DB_NAME"], user=env["DB_USERNAME"], password=env["DB_PASSWORD"],
                         connect_timeout=10) as conn:
        rows = conn.execute(SQL).fetchall()
    r = redis.Redis(host=env["REDIS_HOST"], port=int(env.get("REDIS_PORT", "6379")),
                    password=env.get("REDIS_PASSWORD") or None,
                    ssl=env.get("REDIS_SSL_ENABLED", "false").lower() == "true",
                    decode_responses=True, socket_timeout=10)
    set_n, del_n = sync(rows, r)
    log.info("synced: %d active, %d removed", set_n, del_n)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    loop = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--loop" else 0
    while True:
        try:
            run_once()
            ok = True
        except Exception as e:  # 원인만 남기고 계속 (토큰 원문은 다루지 않으므로 메시지 노출 안전)
            log.error("sync failed: %s", e)
            ok = False
        if not loop:
            sys.exit(0 if ok else 1)
        time.sleep(loop if ok else 60)  # 실패 시 1분 뒤 재시도


if __name__ == "__main__":
    main()
