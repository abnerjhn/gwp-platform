import pandas as pd
import graphviz

def check_is_blocked(activity_row, all_activities_df):
    """
    Hard Lock Rule: Returns True if the parent dependency is NOT DONE.
    """
    dep_code = activity_row.get('dependency_code')
    
    # 1. No dependency -> Not blocked
    if pd.isna(dep_code) or not dep_code or dep_code == '-':
        return False
        
    # 2. Find parent
    # usage of 'activity_code' as the key
    parent_rows = all_activities_df[all_activities_df['activity_code'] == dep_code]
    
    if parent_rows.empty:
        # Parent not found in DB? 
        # Safe strategy: If external dependency is missing, warn but maybe don't block forever.
        # Strict strategy: Block.
        # Returning False here assuming it might be an external reference not in system.
        return False
        
    parent_status = parent_rows.iloc[0]['status']
    
    # 3. Check status
    if parent_status != 'DONE':
        return True
        
    return False

def check_can_complete(activity_row, has_file_uploaded_override=None):
    """
    Evidence Rule: Cannot be DONE if evidence is required but missing.
    """
    evidence_req = activity_row.get('evidence_requirement')
    
    # Clean check
    if not evidence_req or pd.isna(evidence_req) or evidence_req == '-':
        return True, "OK"
        
    # Check upload status
    # Allow override for UI simulation before db refresh
    has_file = has_file_uploaded_override if has_file_uploaded_override is not None else activity_row.get('has_file_uploaded', False)
    
    if not has_file:
        return False, f"Falta evidencia: {evidence_req}"
        
    return True, "OK"

def get_grouped_columns(df):
    """
    Helper to group activities for Kanban.
    Simplification: Group by 'product_code' or Status for the Factory.
    """
    # ... any specific logic needed for Kanban
    return df

def generate_graphviz_dot(df):
    """
    Generates Graphviz Graph object for the Live Process Map.
    """
    if df.empty: return None
    
    # 1. Init Graph
    dot = graphviz.Digraph(comment='Plan Integrado')
    dot.attr(compound='true')
    dot.attr(rankdir='TB') 
    dot.attr(splines='polyline') # Polyline is more stable for complex hierarchies
    dot.attr(nodesep='0.5')
    dot.attr(ranksep='0.8')
    dot.attr(newrank='true') # Critical for aligning nodes across clusters
    
    # 2. Phases Logic
    phases = {
        0: {"name": "FASE 0: ARRANQUE",     "start": 0,  "end": 1},
        1: {"name": "FASE 1: BASELINE",     "start": 2,  "end": 5},
        2: {"name": "FASE 2: FÁBRICA",      "start": 6,  "end": 11},
        3: {"name": "FASE 3: CARPINTERÍA",  "start": 12, "end": 20},
        4: {"name": "FASE 4: CIERRE",       "start": 21, "end": 999}
    }
    
    # Collect nodes per phase to group them
    nodes_by_phase = {pid: [] for pid in phases}
    
    for _, row in df.iterrows():
        wk = int(row.get('week_start') or 1)
        for p_id, p_info in phases.items():
            if wk >= p_info["start"] and wk <= p_info["end"]:
                nodes_by_phase[p_id].append(row)
                break

    # 3. Draw Phases (Clusters) & Nodes
    # We iterate phases in order
    sorted_phases = sorted(phases.keys())
    
    for p_id in sorted_phases:
        rows = nodes_by_phase[p_id]
        # We draw the cluster even if empty (to maintain the spine) or skip? 
        # If we skip, the spine breaks. Better to check if we have data or handle spine properly.
        # But user data might be sparse. Let's only list phases that have data to avoid empty boxes
        # UNLESS we want empty boxes for structure. Let's stick to phases with nodes for now
        # and rely on the spine connecting only existing phases.
        if not rows: continue
        
        p_info = phases[p_id]
        
        with dot.subgraph(name=f'cluster_{p_id}') as c:
            c.attr(label=p_info['name'])
            c.attr(style='filled', color='#f8f9fa')
            c.attr(fontsize='14', fontname='Helvetica-Bold')
            
            # --- INVISIBLE SPINE ANCHOR ---
            # This node forces alignment
            anchor_name = f'anchor_{p_id}'
            c.node(anchor_name, label='', style='invis', shape='point', width='0', group='spine')
            
            for row in rows:
                # -- STYLE LOGIC --
                status = row['status']
                is_blocked = check_is_blocked(row, df)
                
                # Colors
                fill = '#ffffff' # Default PENDING
                color = '#6c757d'
                style = 'filled'
                
                if status == 'DONE':
                    fill = '#d4edda' # Green
                    color = '#28a745'
                elif status == 'IN_PROGRESS':
                    fill = '#fff3cd' # Yellow
                    color = '#ffc107'
                    
                if is_blocked and status != 'DONE':
                    fill = '#f8d7da' # Red
                    color = '#dc3545'
                    style = 'filled,dashed'
                
                # Shapes
                role = str(row['primary_role']).upper()
                shape = 'box' # Default
                if 'FINANZAS' in role: shape = 'box'
                elif 'LEGAL' in role: shape = 'note'
                elif 'COORD' in role: shape = 'ellipse'
                elif 'GOBIERNO' in role: shape = 'component'
                
                # Label & Tooltip
                full_name = row['task_name']
                tooltip = f"{full_name}\nResponsable: {role}\nEstado: {status}"
                
                short_name = full_name[:20] + "..." if len(full_name) > 20 else full_name
                label = f"{row['activity_code']}\n{short_name}"
                
                c.node(row['activity_code'], label=label, shape=shape, fillcolor=fill, color=color, style=style, fontname='Helvetica', fontsize='10', tooltip=tooltip)

    # 4. Connect the Invisible Spine (Force Verticality)
    active_phases = sorted([p for p in phases.keys() if nodes_by_phase[p]])
    for i in range(len(active_phases) - 1):
        u = f'anchor_{active_phases[i]}'
        v = f'anchor_{active_phases[i+1]}'
        # High weight to enforce straight line
        dot.edge(u, v, style='invis', weight='2000')

    # 5. Draw Edges (Dependencies)
    # Outside clusters
    for _, row in df.iterrows():
        dep = row.get('dependency_code')
        if dep and str(dep) != 'nan' and dep != '-' and dep in df['activity_code'].values:
            # Use constraint=true (default) but weight=1 so it yields to the spine
            dot.edge(dep, row['activity_code'], color='#666666', weight='1')
            
    return dot
