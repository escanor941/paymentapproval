CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS factories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    location TEXT NOT NULL,
    is_deleted BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    mobile TEXT,
    address TEXT,
    gst_no TEXT,
    is_deleted BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS item_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_deleted BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_deleted BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payment_modes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_deleted BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS purchase_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_date DATE NOT NULL,
    factory_id INTEGER NOT NULL,
    vendor_id INTEGER NOT NULL,
    vendor_mobile TEXT,
    item_category TEXT NOT NULL,
    item_name TEXT NOT NULL,
    qty REAL NOT NULL,
    unit TEXT NOT NULL,
    rate REAL NOT NULL,
    amount REAL NOT NULL,
    gst_percent REAL DEFAULT 0,
    final_amount REAL NOT NULL,
    reason TEXT NOT NULL,
    urgent_flag BOOLEAN DEFAULT 0,
    requested_by TEXT NOT NULL,
    requested_by_user_id INTEGER NOT NULL,
    geo_latitude REAL,
    geo_longitude REAL,
    geo_accuracy_m REAL,
    geo_captured_at DATETIME,
    is_in_factory BOOLEAN,
    distance_from_factory_m REAL,
    bill_image_path TEXT,
    notes TEXT,
    approval_status TEXT DEFAULT 'Pending',
    approved_amount REAL,
    approval_remark TEXT,
    priority TEXT,
    expected_payment_date DATE,
    approved_by INTEGER,
    approved_at DATETIME,
    payment_status TEXT DEFAULT 'Unpaid',
    is_unread_admin BOOLEAN DEFAULT 1,
    is_deleted BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(factory_id) REFERENCES factories(id),
    FOREIGN KEY(vendor_id) REFERENCES vendors(id),
    FOREIGN KEY(requested_by_user_id) REFERENCES users(id),
    FOREIGN KEY(approved_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS user_presence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    factory_id INTEGER,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    accuracy_m REAL,
    is_in_factory BOOLEAN,
    distance_from_factory_m REAL,
    last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(factory_id) REFERENCES factories(id)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    payment_date DATE NOT NULL,
    payment_mode TEXT NOT NULL,
    transaction_ref TEXT,
    paid_amount REAL NOT NULL,
    balance_amount REAL DEFAULT 0,
    remark TEXT,
    created_by INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(request_id) REFERENCES purchase_requests(id),
    FOREIGN KEY(created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_by INTEGER,
    changed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(changed_by) REFERENCES users(id)
);
