import streamlit as st
from supabase import create_client, Client
import os
import pandas as pd
import csv


@st.cache_resource
def init_connection():
    """
    Initialize Supabase connection.
    Prioritizes Streamlit secrets (supporting [supabase] section), falls back to environment variables.
    """
    url = None
    key = None
    
    # 1. Try Streamlit Secrets
    try:
        if "supabase" in st.secrets:
            url = st.secrets["supabase"]["url"]
            key = st.secrets["supabase"]["key"]
        elif "SUPABASE_URL" in st.secrets:
            url = st.secrets["SUPABASE_URL"]
            key = st.secrets["SUPABASE_KEY"]
    except Exception:
        pass
        
    # 2. Fallback to Environment Variables
    if not url:
        url = os.environ.get("SUPABASE_URL")
    if not key:
        key = os.environ.get("SUPABASE_KEY")
        
    if not url or not key:
        return None
        
    return create_client(url, key)

# --- GENERIC CRUD ---

def get_table_df(table_name):
    """Generic fetcher for any table -> DataFrame"""
    client = init_connection()
    if not client: return pd.DataFrame()
    try:
        res = client.table(table_name).select("*").execute()
        return pd.DataFrame(res.data)
    except Exception as e:
        # print(f"Error fetching {table_name}: {e}")
        return pd.DataFrame()

def upsert_data(table_name, records):
    """Generic upsert for list of dicts"""
    client = init_connection()
    if not client: return False, "No Connection"
    try:
        # Assuming table has PK propertly set for Upsert behavior
        client.table(table_name).upsert(records).execute()
        return True, "Upsert Successful"
    except Exception as e:
        return False, str(e)

# --- HELPER FUNCTIONS ---

def get_activities_df():
    # Backwards compatibility
    return get_table_df("activities")

def get_project_meta():
    """Returns dict {key: value}"""
    df = get_table_df("project_meta")
    if df.empty: return {}
    return dict(zip(df['key'], df['value']))
    
def update_project_meta(key, value):
    return upsert_data("project_meta", [{"key": key, "value": value}])

def update_activity_status_flow(activity_id, new_status):
    """Helper for Kanban flow"""
    client = init_connection()
    try:
        client.table("activities").update({"status": new_status}).eq("id", activity_id).execute()
        return True, "Updated"
    except Exception as e:
        return False, str(e)

def seed_master_defaults():
    """Restores default Users and Products if missing"""
    client = init_connection()
    try:
        # Users
        users = [
            {"id": "u1", "email": "astrid@gwp.org", "full_name": "Astrid", "role": "COORD"},
            {"id": "u2", "email": "patricio@gwp.org", "full_name": "Patricio", "role": "FINANZAS"},
            {"id": "u3", "email": "constanza@gwp.org", "full_name": "Constanza", "role": "LEGAL"},
            {"id": "u4", "email": "visor@gob.cl", "full_name": "Visor Gobierno", "role": "GOBIERNO"}
        ]
        # Products
        products = [
             {'code': '1.1', 'name': 'Coordinación y Género'}, 
             {'code': '2.1', 'name': 'Mecanismos Financiación'}, 
             {'code': '2.2', 'name': 'Línea Base y Operación'}, 
             {'code': '3.1', 'name': 'Regulación Legal'}, 
             {'code': '3.2', 'name': 'Inclusión Normativa'}, 
             {'code': 'TRANS', 'name': 'Transversal/Gestión'}
        ]
        
        # Check if users empty or Just insert
        # We try to upsert. Note: ID is required for users if not auto-gen, provided dummy UUIDs or let it fail if ID exists
        # To be safe, let's just Upsert users by ID if we can, or email.
        # Since Schema v3 defined id as UUID DEFAULT gen_random_uuid(), we shouldn't provide small IDs like 'u1' usually unless testing.
        # But 'users' table might treat email as unique.
        
        # Let's clean the user payload to rely on email upsert logic if implemented or just insert
        for u in users:
             # Try insert, ignore if fails (email unique)
             try:
                 # Removing ID to let Supabase gen it
                 u_clean = {k: v for k, v in u.items() if k != 'id'}
                 client.table("users").insert(u_clean).execute()
             except:
                 pass
        
        # Products upsert
        client.table("contract_products").upsert(products).execute()
        
        return True, "Datos Restaurados Correctamente"
    except Exception as e:
        return False, f"Error: {str(e)}"

def seed_activities_from_csv(file_path):
    """Reads CSV and seeds activities table"""
    client = init_connection()
    try:
        # Role Reverse Map
        name_to_role = {
            "Astrid": "COORD",
            "Patricio": "FINANZAS", 
            "Constanza": "LEGAL",
            "GOV": "GOBIERNO",
            "Todos": "COORD" # Fallback
        }

        activities = []
        # Try cp1252 (common in Excel/Windows)
        with open(file_path, 'r', encoding='cp1252') as f: 
            reader = csv.DictReader(f)
            # CSV Cols: ID,Producto,Actividad ,Sem. inicio,Sem. fin,Tipo,Depende de,Evidencia ,Resp. primario,Co-responsables
            # Clean keys (strip spaces)
            reader.fieldnames = [name.strip() for name in reader.fieldnames]
            
            for row in reader:
                # Map
                code = row.get("ID", "").strip()
                if not code: continue
                
                # Clean integers
                try: ws = int(row.get("Sem. inicio", 1))
                except: ws = 1
                try: we = int(row.get("Sem. fin", 1))
                except: we = 1
                
                # Clean Role
                raw_resp = row.get("Resp. primario", "Astrid").strip()
                role = name_to_role.get(raw_resp, "COORD") # Default to COORD if unknown
                
                # Clean Dependency
                dep = row.get("Depende de", "").strip()
                if dep == "?" or dep == "": dep = None
                
                # Product
                prod = row.get("Producto", "").strip()
                
                act = {
                    "activity_code": code,
                    "product_code": prod,
                    "task_name": row.get("Actividad", "").strip(),
                    "week_start": ws,
                    "week_end": we,
                    "type_tag": row.get("Tipo", "INT").strip(),
                    "dependency_code": dep,
                    "primary_role": role,
                    "status": "PENDING", # Default
                    "co_responsibles": row.get("Co-responsables", "")
                }
                activities.append(act)
        
        # Upsert
        # We need a conflict key. activity_code should be unique usually.
        # But 'activities' PK is 'id' (serial/uuid).
        # We need to check if we can upsert by 'activity_code'.
        # If schema doesn't have unique constraint on activity_code, upsert might insert duplicates.
        # Strategy: First check if activity_code exists, update it. Else insert.
        # Bulk upsert is better if unique constraint exists. 
        # Assuming activity_code is NOT unique constraint in v4 schema (it was just text).
        # Let's try to Delete All and Rewrite? No, unsafe.
        # Let's Lookup by code.
        
        for a in activities:
            # Check exist
            res = client.table("activities").select("id").eq("activity_code", a["activity_code"]).execute()
            if res.data:
                # Update
                uid = res.data[0]['id']
                client.table("activities").update(a).eq("id", uid).execute()
            else:
                # Insert
                client.table("activities").insert(a).execute()
                
        return True, f"Se importaron {len(activities)} actividades."
        
    except Exception as e:
        return False, str(e)

# --- STORAGE FUNCTIONS ---

def upload_evidence(file_obj, activity_code, user_role):
    """
    Uploads file to Supabase Storage ('evidence' bucket) and records metadata in DB.
    """
    client = init_connection()
    try:
        # 1. Upload to Storage
        # Path: {activity_code}/{filename}
        # Sanitize filename
        filename = file_obj.name
        storage_path = f"{activity_code}/{filename}"
        
        file_bytes = file_obj.getvalue()
        content_type = file_obj.type
        
        # Upload using 'upsert' option if supported by lib validation, else try normal
        # Check supabase-py storage lib docs or just try default upload
        res = client.storage.from_("evidence").upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        
        # 2. Insert/Update DB Record
        # We delete old metadata to simple "upsert" logic without unique constraint issues
        client.table("evidence_files").delete().eq("storage_path", storage_path).execute()
        
        metadata = {
            "activity_code": activity_code,
            "filename": filename,
            "storage_path": storage_path,
            "file_size": len(file_bytes),
            "content_type": content_type,
            "uploaded_by": user_role
        }
        
        client.table("evidence_files").insert(metadata).execute()
        
        return True, "Archivo subido correctamente."
        
    except Exception as e:
        print(f"🔴 DEBUG UPLOAD ERROR: {str(e)}") # Log to console
        return False, f"Error Upload: {str(e)}"

def get_evidence_url(storage_path):
    """Generates a signed URL (valid 1 hour) for download"""
    client = init_connection()
    try:
        # Create Signed URL
        res = client.storage.from_("evidence").create_signed_url(storage_path, 3600)
        return res['signedURL']
    except Exception as e:
        return None

def get_evidence_by_activity(activity_code):
    """Returns list of files for an activity"""
    client = init_connection()
    try:
        res = client.table("evidence_files").select("*").eq("activity_code", activity_code).execute()
        return res.data
    except:
        return []

def get_all_evidence():
    """Returns list of all files for File Manager"""
    client = init_connection()
    try:
        res = client.table("evidence_files").select("*").order("uploaded_at", desc=True).execute()
        return res.data
    except:
        return []

def delete_evidence(storage_path):
    """Deletes file from storage and DB"""
    client = init_connection()
    try:
        # 1. Delete from Storage
        # Remove expects a list of paths
        res = client.storage.from_("evidence").remove([storage_path])
        
        # 2. Delete from DB
        client.table("evidence_files").delete().eq("storage_path", storage_path).execute()
        
        return True, "Archivo eliminado."
    except Exception as e:
        return False, str(e)
