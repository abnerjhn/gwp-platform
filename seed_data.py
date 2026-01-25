import pandas as pd
import sqlite3
import uuid
from db import init_db, get_connection

# Role Mapping Mapping as per instructions
ROLE_MAPPING = {
    "Astrid": "COORD",
    "Patricio": "FINANZAS",
    "Constanza": "LEGAL",
    "Todos": "COORD", # Default fallback if needed, or handle as shared
    "GOV": "GOBIERNO"
}

def seed_data():
    init_db()
    conn = get_connection()
    c = conn.cursor()

    # 1. Seed Users
    users = [
        ("u1", "astrid@gwp.org", "Astrid", "COORD", None),
        ("u2", "patricio@gwp.org", "Patricio", "FINANZAS", None),
        ("u3", "constanza@gwp.org", "Constanza", "LEGAL", None),
        ("u4", "gov@gob.cl", "Visor Gobierno", "GOBIERNO", None)
    ]
    
    for u in users:
        try:
            c.execute("INSERT INTO users (id, email, full_name, role, avatar_url) VALUES (?, ?, ?, ?, ?)", u)
        except sqlite3.IntegrityError:
            pass # Already exists

    # 2. Seed Contract Products
    products = [
        ('1.1', 'Coordinación y Género'), 
        ('2.1', 'Mecanismos Financiación'), 
        ('2.2', 'Línea Base y Operación'), 
        ('3.1', 'Regulación Legal'), 
        ('3.2', 'Inclusión Normativa'), 
        ('TRANS', 'Transversal/Gestión')
    ]
    
    for p in products:
        try:
            c.execute("INSERT INTO contract_products (code, name) VALUES (?, ?)", p)
        except sqlite3.IntegrityError:
            pass

    # 3. Seed Activities from CSV
    # We use Cronograma_Maestro_Import.csv as the primary source as requested in Step 3
    csv_path = "Datos/Cronograma_Maestro_Import.csv"
    try:
        df = pd.read_csv(csv_path)
        
        # Clear existing activities to avoid duplicates during dev
        c.execute("DELETE FROM activities")
        
        for _, row in df.iterrows():
            # Map Role
            raw_role = row.get('responsible_role', '')
            primary_role = ROLE_MAPPING.get(raw_role, raw_role) # Fallback to raw if not in map
            if primary_role not in ['COORD', 'FINANZAS', 'LEGAL', 'GOBIERNO']:
                primary_role = 'COORD' # Default safe fallback
            
            # Map Boolean
            is_gate = str(row.get('is_gate_blocker', 'FALSE')).upper() == 'TRUE'
            
            activity_data = (
                row.get('activity_code'),
                row.get('product_code'),
                row.get('task_name'),
                row.get('week_start'),
                row.get('week_end'),
                row.get('type_tag'),
                row.get('dependencies_text'), # Assuming this maps to dependency_code in our schema logic
                row.get('evidence_expected'),
                primary_role,
                "Todos" if raw_role == "Todos" else None, # Simplified co-responsible
                'PENDING', # Status
                0, # has_file_uploaded
                1 if is_gate else 0 # is_gate_blocker
            )
            
            c.execute('''
                INSERT INTO activities (
                    activity_code, product_code, task_name, week_start, week_end, 
                    type_tag, dependency_code, evidence_requirement, primary_role, 
                    co_responsibles, status, has_file_uploaded, is_gate_blocker
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', activity_data)
            
        print(f"Imported {len(df)} activities.")
        
    except Exception as e:
        print(f"Error importing CSV: {e}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    seed_data()
