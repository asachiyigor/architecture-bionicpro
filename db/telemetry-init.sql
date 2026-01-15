-- Telemetry Database Initialization Script
-- Creates tables for prosthetic telemetry data

-- Telemetry events table
CREATE TABLE IF NOT EXISTS telemetry_events (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    device_serial VARCHAR(100) NOT NULL,
    event_date DATE NOT NULL,
    event_time TIMESTAMP NOT NULL,
    battery_level DECIMAL(5, 2),
    usage_minutes INTEGER DEFAULT 0,
    movement_count INTEGER DEFAULT 0,
    error_code VARCHAR(50),
    sensor_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better query performance
CREATE INDEX idx_telemetry_user_id ON telemetry_events(user_id);
CREATE INDEX idx_telemetry_device ON telemetry_events(device_serial);
CREATE INDEX idx_telemetry_date ON telemetry_events(event_date);
CREATE INDEX idx_telemetry_user_date ON telemetry_events(user_id, event_date);

-- Partitioning by month for better performance on large datasets
-- Note: In production, use native PostgreSQL partitioning

-- Insert sample telemetry data for the past 30 days
DO $$
DECLARE
    day_offset INTEGER;
    user_rec RECORD;
BEGIN
    -- Generate data for each day in the past 30 days
    FOR day_offset IN 0..29 LOOP
        -- For each user (1-5)
        FOR user_rec IN SELECT generate_series(1, 5) as user_id LOOP
            -- Insert multiple events per day
            INSERT INTO telemetry_events (
                user_id,
                device_serial,
                event_date,
                event_time,
                battery_level,
                usage_minutes,
                movement_count,
                error_code,
                sensor_data
            )
            SELECT
                user_rec.user_id,
                CASE user_rec.user_id
                    WHEN 1 THEN 'BA-001-2024'
                    WHEN 2 THEN 'BA-002-2024'
                    WHEN 3 THEN 'BH-001-2024'
                    WHEN 4 THEN 'BA-003-2024'
                    ELSE 'BL-001-2024'
                END,
                CURRENT_DATE - day_offset,
                (CURRENT_DATE - day_offset) + (hour_num || ' hours')::INTERVAL,
                50 + RANDOM() * 50,  -- Battery 50-100%
                15 + FLOOR(RANDOM() * 30)::INTEGER,  -- 15-45 minutes usage
                100 + FLOOR(RANDOM() * 500)::INTEGER,  -- 100-600 movements
                CASE WHEN RANDOM() < 0.05 THEN 'E' || FLOOR(RANDOM() * 10)::INTEGER ELSE NULL END,
                jsonb_build_object(
                    'temperature', 35 + RANDOM() * 5,
                    'pressure', 900 + RANDOM() * 100,
                    'humidity', 40 + RANDOM() * 30
                )
            FROM generate_series(8, 20, 2) as hour_num;  -- Events from 8am to 8pm every 2 hours
        END LOOP;
    END LOOP;
END $$;

-- Create view for daily aggregations
CREATE OR REPLACE VIEW daily_telemetry_summary AS
SELECT
    user_id,
    device_serial,
    event_date,
    SUM(usage_minutes) as total_usage_minutes,
    AVG(battery_level) as avg_battery_level,
    SUM(movement_count) as total_movements,
    COUNT(error_code) FILTER (WHERE error_code IS NOT NULL) as error_count,
    MAX(event_time) as last_event_time
FROM telemetry_events
GROUP BY user_id, device_serial, event_date;
