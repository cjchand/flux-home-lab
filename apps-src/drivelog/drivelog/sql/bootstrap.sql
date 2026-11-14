CREATE SCHEMA IF NOT EXISTS drivelog;

CREATE TABLE IF NOT EXISTS drivelog.drivers (
    id         serial PRIMARY KEY,
    name       text UNIQUE NOT NULL,
    is_student boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS drivelog.drive_tags (
    teslamate_drive_id bigint PRIMARY KEY,
    driver_id          integer REFERENCES drivelog.drivers (id),
    tagged_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS drivelog.settings (
    key   text PRIMARY KEY,
    value text
);
