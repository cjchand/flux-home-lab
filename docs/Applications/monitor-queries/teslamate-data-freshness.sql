-- Uptime Kuma monitor: "Teslamate - Data Freshness" (PostgreSQL type)
--
-- Paste this into the monitor's Query field. Uptime Kuma's postgres monitor
-- IGNORES the result set entirely -- it only fails if the query throws. So the
-- health condition has to RAISE, and the exception text becomes the heartbeat
-- message and the Slack alert body.
--
-- Why it keys on state rather than a plain "max(date) is recent" check:
-- TeslaMate writes nothing at all while a car is asleep or offline, so a naive
-- freshness check would fire every night. This only alerts when a car's open
-- state row says 'online' -- i.e. data is actually expected -- but its newest
-- position is older than 15 minutes. Measured cadence while online is a
-- position every 1-6s (p99 = 3s), so 15 minutes is a very wide margin.
--
-- Timestamps are `timestamp without time zone` holding UTC, hence the explicit
-- `now() AT TIME ZONE 'UTC'` rather than relying on session TimeZone.
--
-- Limitation: if TeslaMate dies while every car is asleep, the open state row
-- stays 'asleep'/'offline' and this stays green until a car next wakes. The
-- separate "Teslamate" HTTP monitor covers process liveness.

DO $$
DECLARE stale TEXT;
BEGIN
  SELECT string_agg(
           format('%s (%s min old)', c.name,
                  ROUND(EXTRACT(EPOCH FROM ((now() AT TIME ZONE 'UTC') - p.last_pos)) / 60)),
           ', ' ORDER BY c.name)
    INTO stale
    FROM states s
    JOIN cars c ON c.id = s.car_id
    LEFT JOIN LATERAL (
      SELECT MAX(date) AS last_pos FROM positions WHERE car_id = s.car_id
    ) p ON TRUE
   WHERE s.end_date IS NULL
     AND s.state = 'online'
     AND (p.last_pos IS NULL
          OR p.last_pos < (now() AT TIME ZONE 'UTC') - interval '15 minutes');

  IF stale IS NOT NULL THEN
    RAISE EXCEPTION 'TeslaMate data stale while car online: %', stale;
  END IF;
END $$;

