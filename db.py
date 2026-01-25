import sqlite3
import pandas as pd
from datetime import datetime
import os

DB_NAME = "gwp_platform.db"

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    c = conn.cursor()

    # 1. Users
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT CHECK (role IN ('FINANZAS', 'LEGAL', 'COORD', 'GOBIERNO')) NOT NULL,
            avatar_url TEXT
        )
    ''')

    # 2. Contract Products
    c.execute('''
        CREATE TABLE IF NOT EXISTS contract_products (
            code TEXT PRIMARY KEY,
            name TEXT
        )
    ''')
    
    # 3. Activities
    # Added is_gate_blocker as per instructions, though not in original SQL provided
    c.execute('''
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_code TEXT UNIQUE NOT NULL,
            product_code TEXT,
            task_name TEXT NOT NULL,
            week_start INTEGER,
            week_end INTEGER,
            type_tag TEXT,
            dependency_code TEXT,
            evidence_requirement TEXT,
            primary_role TEXT NOT NULL,
            co_responsibles TEXT,
            status TEXT DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'IN_PROGRESS', 'BLOCKED', 'DONE')),
            has_file_uploaded BOOLEAN DEFAULT 0,
            is_gate_blocker BOOLEAN DEFAULT 0,
            FOREIGN KEY (product_code) REFERENCES contract_products(code)
        )
    ''')

    # 4. Evidence Files
    c.execute('''
        CREATE TABLE IF NOT EXISTS evidence_files (
            id TEXT PRIMARY KEY,
            activity_id INTEGER,
            uploader_id TEXT,
            file_url TEXT NOT NULL,
            file_name TEXT NOT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (activity_id) REFERENCES activities(id),
            FOREIGN KEY (uploader_id) REFERENCES users(id)
        )
    ''')

    # 5. Mechanisms
    c.execute('''
        CREATE TABLE IF NOT EXISTS mechanisms (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status_pipeline TEXT DEFAULT 'DRAFT',
            created_by TEXT,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')

    conn.commit()
    conn.close()
    print("Database initialized.")

def get_activities_df():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM activities", conn)
    conn.close()
    return df

def get_user_by_email(email):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = c.fetchone()
    conn.close()
    return user
