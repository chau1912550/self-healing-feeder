-- TimescaleDB schema for simulated SCADA data
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS device_readings (
    time      TIMESTAMPTZ NOT NULL,
    event_id  TEXT        NOT NULL,
    feeder    TEXT        NOT NULL,
    device    TEXT        NOT NULL,
    status    TEXT        NOT NULL,
    ia        DOUBLE PRECISION,
    ib        DOUBLE PRECISION,
    ic        DOUBLE PRECISION,
    va_pu     DOUBLE PRECISION,
    vb_pu     DOUBLE PRECISION,
    vc_pu     DOUBLE PRECISION
);
SELECT create_hypertable('device_readings', 'time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS flisr_events (
    time      TIMESTAMPTZ NOT NULL,
    event_id  TEXT        NOT NULL,
    feeder    TEXT        NOT NULL,
    source    TEXT        NOT NULL,
    status    TEXT        NOT NULL,
    payload   JSONB
);
SELECT create_hypertable('flisr_events', 'time', if_not_exists => TRUE);
