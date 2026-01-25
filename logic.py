from db import get_connection

def check_dependencies_blocking(activity_id):
    """
    Returns True if the activity is BLOCKED by a dependency.
    """
    conn = get_connection()
    c = conn.cursor()
    
    # Get dependency code for the current activity
    c.execute("SELECT dependency_code FROM activities WHERE id = ?", (activity_id,))
    res = c.fetchone()
    if not res:
        conn.close()
        return False
        
    dep_code = res[0]
    
    # If no dependency or dependency is '-' or empty
    if not dep_code or dep_code == '-' or dep_code == '?':
        conn.close()
        return False
    
    # Find the status of the parent activity
    # Note: dep_code in activities table is stored in activity_code column
    c.execute("SELECT status FROM activities WHERE activity_code = ?", (dep_code,))
    parent = c.fetchone()
    conn.close()
    
    if not parent:
        # Parent not found (maybe external or typo), assume not blocked or handle strictly
        return False
        
    parent_status = parent[0]
    
    # Blocked if parent is NOT DONE
    return parent_status != 'DONE'

def update_activity_status(activity_id, new_status, user_role, has_file):
    """
    Updates the status of an activity enforcing rules.
    Returns (success, message).
    """
    conn = get_connection()
    c = conn.cursor()
    
    c.execute("SELECT evidence_requirement, is_gate_blocker, dependency_code FROM activities WHERE id = ?", (activity_id,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return False, "Activity not found"
        
    evidence_req, is_gate, dep_code = row
    
    # 1. Check Dependency Block
    if check_dependencies_blocking(activity_id):
        conn.close()
        return False, f"Bloqueado: La dependencia {dep_code} no está terminada."

    # 2. Check Evidence Rule
    # If trying to mark as DONE, check evidence
    if new_status == 'DONE':
        if evidence_req and evidence_req != '-' and not has_file:
            conn.close()
            return False, f"Requisito: Debes subir evidencia '{evidence_req}' antes de completar."
            
    # 3. Save
    c.execute("UPDATE activities SET status = ? WHERE id = ?", (new_status, activity_id))
    conn.commit()
    conn.close()
    
    return True, "Estado actualizado."

def get_dashboard_metrics():
    conn = get_connection()
    c = conn.cursor()
    
    c.execute("SELECT count(*) FROM activities")
    total = c.fetchone()[0]
    
    c.execute("SELECT count(*) FROM activities WHERE status='DONE'")
    done = c.fetchone()[0]
    
    progress = (done / total * 100) if total > 0 else 0
    
    conn.close()
    return {
        "total_activities": total,
        "completed": done,
        "progress_percent": round(progress, 1)
    }

def move_mechanism_stage(mech_id, current_stage, user_role):
    """
    Pipeline Logic: DRAFT -> LEGAL -> GENDER -> APPROVED
    """
    # Simply hardcoding the pipeline progression for now based on roles
    # Patricio (FINANZAS) creates DRAFT -> moves to LEGAL
    # Constanza (LEGAL) moves LEGAL -> GENDER
    # Astrid (COORD) moves GENDER -> APPROVED
    
    next_stages = {
        'DRAFT': 'LEGAL_REVIEW',
        'LEGAL_REVIEW': 'GENDER_REVIEW',
        'GENDER_REVIEW': 'APPROVED'
    }
    
    allowed_roles = {
        'DRAFT': ['FINANZAS'],
        'LEGAL_REVIEW': ['LEGAL'],
        'GENDER_REVIEW': ['COORD']
    }
    
    target_stage = next_stages.get(current_stage)
    
    if not target_stage:
        return False, "Ya está en etapa final o estado desconocido."
        
    required_role = allowed_roles.get(current_stage)
    
    # Allow superuser or specific role
    if user_role not in required_role:
         return False, f"No tienes permisos. Solo {required_role} puede avanzar esta etapa."

    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE mechanisms SET status_pipeline = ? WHERE id = ?", (target_stage, mech_id))
    conn.commit()
    conn.close()
    
    return True, f"Avanzado a {target_stage}"
