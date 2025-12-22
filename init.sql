CREATE TABLE IF NOT EXISTS migrated_data (
    id INTEGER PRIMARY KEY,
    full_name TEXT,
    birth_date DATE,
    processed_at TIMESTAMP DEFAULT NOW()
);