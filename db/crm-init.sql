-- CRM Database Initialization Script
-- Creates tables for customers, orders, and prosthetics

-- Customers table
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    prosthetic_model VARCHAR(100),
    prosthetic_serial VARCHAR(100),
    registration_date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    order_number VARCHAR(50) NOT NULL UNIQUE,
    status VARCHAR(50) DEFAULT 'pending',
    total_amount DECIMAL(18, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Prosthetics table
CREATE TABLE IF NOT EXISTS prosthetics (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    serial_number VARCHAR(100) NOT NULL UNIQUE,
    model VARCHAR(100),
    firmware_version VARCHAR(50),
    activation_date DATE,
    last_sync TIMESTAMP,
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better query performance
CREATE INDEX idx_customers_username ON customers(username);
CREATE INDEX idx_customers_email ON customers(email);
CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_prosthetics_customer_id ON prosthetics(customer_id);
CREATE INDEX idx_prosthetics_serial ON prosthetics(serial_number);

-- Create publication for Debezium CDC
CREATE PUBLICATION bionicpro_publication FOR TABLE customers, orders, prosthetics;

-- Insert sample data
INSERT INTO customers (username, email, first_name, last_name, prosthetic_model, prosthetic_serial, registration_date)
VALUES
    ('prothetic1', 'prothetic1@example.com', 'Prothetic', 'One', 'BionicArm Pro', 'BA-001-2024', '2024-01-15'),
    ('prothetic2', 'prothetic2@example.com', 'Prothetic', 'Two', 'BionicArm Lite', 'BA-002-2024', '2024-02-20'),
    ('prothetic3', 'prothetic3@example.com', 'Prothetic', 'Three', 'BionicHand Plus', 'BH-001-2024', '2024-03-10'),
    ('user1', 'user1@example.com', 'User', 'One', 'BionicArm Pro', 'BA-003-2024', '2024-04-05'),
    ('user2', 'user2@example.com', 'User', 'Two', 'BionicLeg Standard', 'BL-001-2024', '2024-05-12')
ON CONFLICT (username) DO NOTHING;

INSERT INTO prosthetics (customer_id, serial_number, model, firmware_version, activation_date, last_sync, status)
SELECT
    c.id,
    c.prosthetic_serial,
    c.prosthetic_model,
    '2.1.0',
    c.registration_date + INTERVAL '7 days',
    NOW() - INTERVAL '1 hour',
    'active'
FROM customers c
ON CONFLICT (serial_number) DO NOTHING;

INSERT INTO orders (customer_id, order_number, status, total_amount)
SELECT
    c.id,
    'ORD-' || TO_CHAR(NOW(), 'YYYYMMDD') || '-' || c.id,
    'completed',
    25000.00 + (c.id * 1000)
FROM customers c
ON CONFLICT (order_number) DO NOTHING;

-- Create function and trigger for updating updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_customers_updated_at
    BEFORE UPDATE ON customers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_orders_updated_at
    BEFORE UPDATE ON orders
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_prosthetics_updated_at
    BEFORE UPDATE ON prosthetics
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
