from db import get_connection, update_activity_status
from logic import check_dependencies_blocking, move_mechanism_stage
import sqlite3

def run_tests():
    print("Running Logic Tests...")
    conn = get_connection()
    c = conn.cursor()
    
    # 1. Test Dependency Blocking
    # Find a task that has a dependency
    c.execute("SELECT id, activity_code, dependency_code FROM activities WHERE dependency_code IS NOT NULL AND dependency_code != '-' AND dependency_code != '?' LIMIT 1")
    row = c.fetchone()
    
    if row:
        task_id, code, dep_code = row
        print(f"Testing blocking for {code} (Depends on {dep_code})")
        
        # Ensure parent is NOT DONE
        c.execute("UPDATE activities SET status = 'PENDING' WHERE activity_code = ?", (dep_code,))
        conn.commit()
        
        is_blocked = check_dependencies_blocking(task_id)
        print(f"  - Parent PENDING -> Blocked? {is_blocked} (Expected: True)")
        
        # Set parent to DONE
        c.execute("UPDATE activities SET status = 'DONE' WHERE activity_code = ?", (dep_code,))
        conn.commit()
        
        is_blocked = check_dependencies_blocking(task_id)
        print(f"  - Parent DONE -> Blocked? {is_blocked} (Expected: False)")
    else:
        print("Skipping blocking test (no dependent task found in seed data)")

    # 2. Test Evidence Requirement
    # Pick a task with evidence requirement
    c.execute("SELECT id, activity_code FROM activities WHERE evidence_requirement IS NOT NULL AND evidence_requirement != '-' LIMIT 1")
    row = c.fetchone()
    if row:
        task_id, code = row
        print(f"Testing Evidence for {code}")
        
        # Try to complete without file
        success, msg = update_activity_status(task_id, 'DONE', 'COORD', has_file=False)
        print(f"  - Complete without file -> {success} ({msg}) (Expected: False)")
        
        # Try to complete WITH file
        success, msg = update_activity_status(task_id, 'DONE', 'COORD', has_file=True)
        print(f"  - Complete with file -> {success} ({msg}) (Expected: True)")
        
    # 3. Test Pipeline
    print("Testing Pipeline...")
    c.execute("DELETE FROM mechanisms")
    c.execute("INSERT INTO mechanisms (id, name, status_pipeline) VALUES (?, ?, ?)", ("test1", "Mech Test", "DRAFT"))
    conn.commit()
    
    # Try to move as WRONG role
    success, msg = move_mechanism_stage("test1", "DRAFT", "COORD") # COORD cannot move DRAFT->LEGAL (Finanzas does)
    print(f"  - Move DRAFT->LEGAL as COORD -> {success} ({msg}) (Expected: False)")
    
    # Try to move as CORRECT role
    success, msg = move_mechanism_stage("test1", "DRAFT", "FINANZAS")
    print(f"  - Move DRAFT->LEGAL as FINANZAS -> {success} ({msg}) (Expected: True)")
    
    conn.close()

if __name__ == "__main__":
    run_tests()
