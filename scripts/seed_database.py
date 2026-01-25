import os
import pandas as pd
from supabase import create_client
from dotenv import load_dotenv

# Load .env for local script execution
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# Mapping rules
ROLE_MAPPING = {
    "Astrid": "COORD",
    "Patricio": "FINANZAS",
    "Constanza": "LEGAL",
    "Todos": "COORD",
    "GOV": "GOBIERNO"
}

def map_role(name):
    if not isinstance(name, str): return "COORD"
    clean_name = name.strip()
    return ROLE_MAPPING.get(clean_name, clean_name) # Fallback to original if not mapped

def seed_database():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ Error: SUPABASE_URL and SUPABASE_KEY are missing.")
        print("Please create a .env file or export them in your terminal.")
        return

    print("Connecting to Supabase...")
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Connection Failed: {e}")
        return

    # Check for CSV
    csv_path = "Datos/matriz_actividades_integradas.csv"
    # Fallback logic in case the user renamed it or using the other one
    if not os.path.exists(csv_path):
        csv_path = "Datos/Cronograma_Maestro_Import.csv"

    if not os.path.exists(csv_path):
        print(f"CSV not found at {csv_path}")
        return

    print(f"Reading {csv_path}...")
    try:
        df = pd.read_csv(csv_path, encoding='utf-8')
    except UnicodeDecodeError:
        print("UTF-8 failed, trying cp1252...")
        df = pd.read_csv(csv_path, encoding='cp1252')

    activities_list = []
    print("Processing rows and mapping roles...")

    for _, row in df.iterrows():
        # Robust column retrieval (Handling potential CSV header variations)
        code = row.get('ID') or row.get('activity_code')
        prod = row.get('Producto') or row.get('product_code')
        name = row.get('Actividad') or row.get('task_name')
        if not name and 'Actividad ' in row: name = row['Actividad '] # Common trailing space issue
        
        dep = row.get('Depende de') or row.get('dependency_code') or row.get('dependencies_text')
        # Clean dependency
        if pd.isna(dep) or str(dep).strip() in ['-', '?', 'nan']:
            dep = None
        else:
            dep = str(dep).strip()

        evidence = row.get('Evidencia') or row.get('evidence_requirement') or row.get('evidence_expected')
        if pd.isna(evidence) or str(evidence).strip() in ['-', '?', 'nan', '']:
            evidence = None
        else:
            evidence = str(evidence).strip()

        raw_role = row.get('Resp. primario') or row.get('primary_role') or row.get('responsible_role')
        role = map_role(raw_role)

        co_resp = row.get('Co-responsables') or row.get('co_responsibles')
        
        # Weeks
        w_start = row.get('Sem. inicio') or row.get('week_start')
        w_end = row.get('Sem. fin') or row.get('week_end')

        activities_list.append({
            "activity_code": str(code).strip(),
            "product_code": str(prod).strip() if pd.notna(prod) else None,
            "task_name": str(name).strip(),
            "week_start": int(w_start) if pd.notna(w_start) else None,
            "week_end": int(w_end) if pd.notna(w_end) else None,
            "type_tag": str(row.get('Tipo') or row.get('type_tag')).strip(),
            "dependency_code": dep,
            "evidence_requirement": evidence,
            "primary_role": role,
            "co_responsibles": str(co_resp) if pd.notna(co_resp) else None,
            "status": "PENDING",
            "has_file_uploaded": False
            # is_gate_blocker could be inferred or added if in CSV. Assuming default false or column handling if exists.
        })

    print(f"Upserting {len(activities_list)} records to 'activities' table...")
    
    # Supabase Upsert (Batching if necessary, but 100 is usually fine)
    try:
        data = supabase.table("activities").upsert(activities_list, on_conflict="activity_code").execute()
        print("Import Successful!")
    except Exception as e:
        print(f"Import Failed: {e}")

if __name__ == "__main__":
    seed_database()
