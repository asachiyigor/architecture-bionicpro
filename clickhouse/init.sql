-- ClickHouse initialization script for BionicPRO
-- Creates database, tables, Kafka engines, and materialized views

-- Create database
CREATE DATABASE IF NOT EXISTS bionicpro;

-- =============================================================================
-- KAFKA ENGINE TABLES
-- These tables consume data from Kafka topics populated by Debezium CDC
-- =============================================================================

-- Kafka table for customers CDC events
CREATE TABLE IF NOT EXISTS bionicpro.customers_kafka (
    id Int64,
    username String,
    email String,
    first_name String,
    last_name String,
    prosthetic_model String,
    prosthetic_serial String,
    registration_date Date,
    updated_at DateTime64(3),
    __op String,
    __table String,
    __source_ts_ms Int64
) ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'kafka:9092',
    kafka_topic_list = 'bionicpro.public.customers',
    kafka_group_name = 'clickhouse_customers_consumer',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1,
    kafka_max_block_size = 1048576;

-- Kafka table for orders CDC events
CREATE TABLE IF NOT EXISTS bionicpro.orders_kafka (
    id Int64,
    customer_id Int64,
    order_number String,
    status String,
    total_amount Decimal(18, 2),
    created_at DateTime64(3),
    updated_at DateTime64(3),
    __op String,
    __table String,
    __source_ts_ms Int64
) ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'kafka:9092',
    kafka_topic_list = 'bionicpro.public.orders',
    kafka_group_name = 'clickhouse_orders_consumer',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1;

-- Kafka table for prosthetics CDC events
CREATE TABLE IF NOT EXISTS bionicpro.prosthetics_kafka (
    id Int64,
    customer_id Int64,
    serial_number String,
    model String,
    firmware_version String,
    activation_date Date,
    last_sync DateTime64(3),
    status String,
    __op String,
    __table String,
    __source_ts_ms Int64
) ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'kafka:9092',
    kafka_topic_list = 'bionicpro.public.prosthetics',
    kafka_group_name = 'clickhouse_prosthetics_consumer',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1;

-- =============================================================================
-- TARGET TABLES (ReplacingMergeTree)
-- Store the actual data with deduplication
-- =============================================================================

-- Customers table
CREATE TABLE IF NOT EXISTS bionicpro.customers (
    id Int64,
    user_id String MATERIALIZED toString(id),
    username String,
    email String,
    first_name String,
    last_name String,
    prosthetic_model String,
    prosthetic_serial String,
    registration_date Date,
    updated_at DateTime64(3),
    _version UInt64 MATERIALIZED toUnixTimestamp64Milli(updated_at)
) ENGINE = ReplacingMergeTree(_version)
ORDER BY id;

-- Orders table
CREATE TABLE IF NOT EXISTS bionicpro.orders (
    id Int64,
    customer_id Int64,
    order_number String,
    status String,
    total_amount Decimal(18, 2),
    created_at DateTime64(3),
    updated_at DateTime64(3),
    _version UInt64 MATERIALIZED toUnixTimestamp64Milli(updated_at)
) ENGINE = ReplacingMergeTree(_version)
ORDER BY id;

-- Prosthetics table
CREATE TABLE IF NOT EXISTS bionicpro.prosthetics (
    id Int64,
    customer_id Int64,
    serial_number String,
    model String,
    firmware_version String,
    activation_date Date,
    last_sync DateTime64(3),
    status String,
    _version UInt64 MATERIALIZED toUnixTimestamp64Milli(last_sync)
) ENGINE = ReplacingMergeTree(_version)
ORDER BY id;

-- Telemetry table (for ETL-loaded data)
CREATE TABLE IF NOT EXISTS bionicpro.telemetry (
    user_id String,
    device_serial String,
    event_date Date,
    event_time DateTime,
    battery_level Float32,
    usage_minutes Int32,
    movement_count Int32,
    error_code Nullable(String),
    sensor_data String,
    updated_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(event_date)
ORDER BY (user_id, event_date, event_time);

-- =============================================================================
-- MATERIALIZED VIEWS
-- Automatically move data from Kafka tables to target tables
-- =============================================================================

-- Materialized view for customers
CREATE MATERIALIZED VIEW IF NOT EXISTS bionicpro.customers_mv TO bionicpro.customers AS
SELECT
    id,
    username,
    email,
    first_name,
    last_name,
    prosthetic_model,
    prosthetic_serial,
    registration_date,
    updated_at
FROM bionicpro.customers_kafka
WHERE __op != 'd';  -- Ignore deletes or handle separately

-- Materialized view for orders
CREATE MATERIALIZED VIEW IF NOT EXISTS bionicpro.orders_mv TO bionicpro.orders AS
SELECT
    id,
    customer_id,
    order_number,
    status,
    total_amount,
    created_at,
    updated_at
FROM bionicpro.orders_kafka
WHERE __op != 'd';

-- Materialized view for prosthetics
CREATE MATERIALIZED VIEW IF NOT EXISTS bionicpro.prosthetics_mv TO bionicpro.prosthetics AS
SELECT
    id,
    customer_id,
    serial_number,
    model,
    firmware_version,
    activation_date,
    last_sync,
    status
FROM bionicpro.prosthetics_kafka
WHERE __op != 'd';

-- =============================================================================
-- REPORTS DATAMART
-- Aggregated view for reports API
-- =============================================================================

-- Reports datamart table
CREATE TABLE IF NOT EXISTS bionicpro.reports_datamart (
    user_id String,
    report_date Date,
    total_usage_hours Float32,
    avg_battery_level Float32,
    total_movements Int64,
    error_count Int32,
    last_sync_date DateTime,
    username String,
    email String,
    prosthetic_model String,
    updated_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(report_date)
ORDER BY (user_id, report_date);

-- Materialized view to build datamart from telemetry and customers
-- This automatically aggregates data as new telemetry arrives
CREATE MATERIALIZED VIEW IF NOT EXISTS bionicpro.reports_datamart_mv TO bionicpro.reports_datamart AS
SELECT
    t.user_id,
    t.event_date as report_date,
    SUM(t.usage_minutes) / 60.0 as total_usage_hours,
    AVG(t.battery_level) as avg_battery_level,
    SUM(t.movement_count) as total_movements,
    countIf(t.error_code IS NOT NULL AND t.error_code != '') as error_count,
    MAX(t.event_time) as last_sync_date,
    any(c.username) as username,
    any(c.email) as email,
    any(c.prosthetic_model) as prosthetic_model,
    now() as updated_at
FROM bionicpro.telemetry t
LEFT JOIN bionicpro.customers c ON t.user_id = c.user_id
GROUP BY t.user_id, t.event_date;

-- =============================================================================
-- USEFUL QUERIES FOR VERIFICATION
-- =============================================================================

-- Check data in customers (run manually)
-- SELECT * FROM bionicpro.customers FINAL LIMIT 10;

-- Check data in reports_datamart (run manually)
-- SELECT * FROM bionicpro.reports_datamart FINAL ORDER BY report_date DESC LIMIT 10;

-- Check Kafka consumption status
-- SELECT * FROM system.kafka_consumers;
