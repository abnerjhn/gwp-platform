import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date
from db import init_connection, get_table_df, upsert_data, get_project_meta, update_project_meta, update_activity_status_flow, seed_master_defaults, seed_activities_from_csv, upload_evidence, get_evidence_by_activity, get_evidence_url, get_all_evidence, delete_evidence
from logic import check_dependencies_blocking, check_is_blocked, check_can_complete, update_activity_status, get_dashboard_metrics, move_mechanism_stage, generate_graphviz_dot, PHASES_CONFIG
from components import render_kanban_card, render_mechanism_card, render_gantt_chart

st.set_page_config(page_title="GWP Platform", layout="wide", page_icon="🌐")

# --- INITIALIZATION ---
client = init_connection()
if not client:
    st.error("No hay conexión a BD.")
    st.stop()

# Load Meta
meta = get_project_meta()
PROJECT_NAME = meta.get('project_name', 'GWP Project')
LOGO = meta.get('logo_url', '')
# Parse Dates with fallback
try:
    proj_start_str = meta.get('start_date', '2023-10-01')
    PROJECT_START = datetime.strptime(proj_start_str, '%Y-%m-%d').date()
except:
    PROJECT_START = date.today()

try:
    PROJECT_DURATION = int(meta.get('duration_months', 12))
except:
    PROJECT_DURATION = 12

# --- SIDEBAR ---
with st.sidebar:
    if LOGO: 
        try:
            st.image(LOGO, width=200)
        except:
            st.warning("No se pudo cargar el logo.")
    st.title(PROJECT_NAME)
    
    # Login
    users_df = get_table_df("users")
    if not users_df.empty:
        # Create "Name (Role)" list
        valid_users = users_df.apply(lambda x: f"{x['full_name']} ({x['role']})", axis=1).tolist()
    else:
        valid_users = ["Admin (ADMIN)"]
    
    selected_user_str = st.selectbox("Usuario", ["Admin (ADMIN)"] + valid_users)
    
    # Parse Role
    if "ADMIN" in selected_user_str: 
        st.session_state['role'] = 'ADMIN'
        st.session_state['user_id'] = 'admin'
    else:
        # Extract from string "Name (ROLE)"
        st.session_state['role'] = selected_user_str.split('(')[-1].replace(')', '')
        # Find ID (simple lookup)
        user_row = users_df[users_df['full_name'] == selected_user_str.split(' (')[0]]
        st.session_state['user_id'] = user_row.iloc[0]['id'] if not user_row.empty else 'unknown'

    st.info(f"Rol: {st.session_state['role']}")

# --- TABS ---
# --- TABS ---
if st.session_state['role'] == 'ADMIN':
    tabs = st.tabs(["🗺️ Proceso Estático", "🚀 Actividades", "📂 Archivos", "📅 Planificación (CMS)", "⚙️ Configuración"])
else:
    tabs = st.tabs(["🗺️ Proceso Estático", "🚀 Actividades", "📂 Archivos", "📋 Mis Tareas"])

# --- VIEW: LIVE MAP ---
# --- VIEW: LIVE MAP ---
with tabs[0]:
    st.header("🗺️ Tablero de Control Visual")
    st.caption("Organización por Fases del Proyecto")
    
    # Generate DF
    map_df = get_table_df("activities")
    
    if not map_df.empty:
        # Create Tabs for each Phase + Full View + Critical Path
        phase_tabs_names = [p['name'] for p in PHASES_CONFIG.values()]
        phase_tabs_names.append("🔭 VISTA COMPLETA")
        phase_tabs_names.append("🔗 RUTA CRÍTICA")
        
        # Create Streamlit Tabs
        subtabs = st.tabs(phase_tabs_names)
        
        # Helper to render
        def render_tab_content(current_df, key_suffix, is_full=False, group_by_phases=True):
            if current_df.empty:
                st.warning("No hay actividades registradas para esta fase.")
                return

            try:
                dot = generate_graphviz_dot(current_df, group_by_phases=group_by_phases)
                if dot:
                    st.graphviz_chart(dot, use_container_width=True)
                    if not is_full:
                        st.caption("✅ Vista enfocada en fase específica.")
                else:
                    st.info("No se pudo generar el gráfico.")
            except Exception as e:
                st.error(f"Error generando gráfico: {e}")

        # 1. Render Individual Phases
        for i, (p_id, p_info) in enumerate(PHASES_CONFIG.items()):
            with subtabs[i]:
                # Filter Logic: Week based
                # Ensure week_start is numeric
                condition = map_df['week_start'].fillna(0).astype(int).between(p_info['start'], p_info['end'])
                subset = map_df[condition]
                
                render_tab_content(subset, f"p{p_id}")

        # 2. Render Full View (Last Tab)
        with subtabs[-2]: # Now second to last
            st.markdown("### Diagrama Completo")
            render_tab_content(map_df, "full", is_full=True)

        # 3. Critical Path / Connected View
        with subtabs[-1]:
            st.markdown("### 🔗 Ruta Crítica (Solo Conexiones)")
            
            # STRICT FILTERING Logic
            # 1. Clean dependencies to avoid false positives with '-', 'nan', etc.
            def normalize_dep(val):
                if pd.isna(val): return None
                s = str(val).strip()
                if s in ['-', '?', 'nan', 'None', '', '0']: return None
                return s
            
            # Work on a copy to filter
            analysis_df = map_df.copy()
            analysis_df['clean_dep'] = analysis_df['dependency_code'].apply(normalize_dep)
            
            # 2. Identify Parents (nodes that are pointed to)
            # CRITICAL FIX: Only consider dependencies that ACTUALLY EXIST in the dataset
            # Otherwise, a node pointing to a non-existent parent appears loose (edge not drawn) but passes the filter.
            
            valid_codes = set(analysis_df['activity_code'].astype(str).unique())
            
            # Filter dependencies: Keep only those that point to a valid code
            analysis_df['valid_dep'] = analysis_df['clean_dep'].apply(lambda x: x if x in valid_codes else None)
            
            # 3. Apply Conditions
            # cond1: I am a child of a VALID parent
            is_valid_child = analysis_df['valid_dep'].notna()
            
            # cond2: I am a parent of a VALID child (someone points to me using a valid ref)
            valid_parents = set(analysis_df['valid_dep'].dropna().unique())
            is_valid_parent = analysis_df['activity_code'].astype(str).isin(valid_parents)
            
            # Keep nodes that are part of a VALID COMPLETED relationship (either side)
            connected_pool = analysis_df[is_valid_child | is_valid_parent].copy()
            
            if not connected_pool.empty:
                # Pass group_by_phases=False to remove cluster boxes
                render_tab_content(current_df=connected_pool, key_suffix="critical", is_full=True, group_by_phases=False)
            else:
                st.info("No hay dependencias registradas para mostrar un flujo conectado.")
            
    else:
        st.warning("No hay datos para generar el mapa.")

# --- VIEW: FILE MANAGER ---
# Common for all
with tabs[2]:
    st.header("📂 Gestor Documental Centralizado")
    
    files = get_all_evidence()
    if not files:
        st.info("No hay archivos subidos aún.")
    else:
        # Search
        search_q = st.text_input("Buscar archivo...", "")
        
        # Display as grid/table
        # Custom display
        for f in files:
            # Filter
            if search_q and search_q.lower() not in f['filename'].lower() and search_q.lower() not in f['activity_code'].lower():
                continue
                
            with st.container():
                c_icon, c_info, c_btn = st.columns([1, 6, 2])
                c_icon.markdown("### 📄")
                
                with c_info:
                    st.markdown(f"**{f['filename']}**")
                    st.caption(f"Actividad: {f['activity_code']} | Subido por: {f.get('uploaded_by','?')} | {f['uploaded_at'][:10]}")
                    
                with c_btn:
                    c_down, c_del = st.columns([1, 1])
                    
                    # Download
                    url = get_evidence_url(f['storage_path'])
                    if url:
                        c_down.link_button("⬇️", url, help="Descargar")
                    else:
                        c_down.error("Link")

                    # Delete (Permission Check)
                    # Owner or Admin
                    can_data_delete = (st.session_state['role'] == 'ADMIN') or (st.session_state['role'] == f.get('uploaded_by'))
                    
                    if can_data_delete:
                        # Popover for confirmation
                        with c_del.popover("🗑️", help="Eliminar archivo"):
                            st.write("¿Estás seguro?")
                            if st.button("Sí, eliminar", key=f"del_conf_{f['id']}"):
                                success, msg = delete_evidence(f['storage_path'])
                                if success:
                                    st.success(msg)
                                    st.rerun()
                                else:
                                    st.error(msg)
                st.divider()

# --- VIEW: CONFIGURATION (ADMIN) ---
if st.session_state['role'] == 'ADMIN':
    with tabs[4]:
        st.header("⚙️ Gestión de Datos Maestros")
        
        c1, c2 = st.columns(2)
        
        with c1:
            st.subheader("1. Productos Contractuales")
            prods_df = get_table_df("contract_products")
            edited_prods = st.data_editor(prods_df, key="ed_prods", num_rows="dynamic")
            if st.button("💾 Guardar Productos"):
                if not edited_prods.empty:
                    success, msg = upsert_data("contract_products", edited_prods.to_dict('records'))
                    if success: st.success("Productos actualizados")
                    else: st.error(msg)
                    
        with c2:
            st.subheader("2. Usuarios y Roles")
            users_df_edit = get_table_df("users")
            edited_users = st.data_editor(
                users_df_edit, 
                key="ed_users", 
                num_rows="dynamic",
                column_config={
                    "role": st.column_config.SelectboxColumn("Rol", options=["COORD", "FINANZAS", "LEGAL", "GOBIERNO"])
                }
            )
            if st.button("💾 Guardar Usuarios"):
                if not edited_users.empty:
                    success, msg = upsert_data("users", edited_users.to_dict('records'))
                    if success: st.success("Usuarios actualizados")
                    else: st.error(msg)
            
            st.divider()
            if st.button("⚠️ Restaurar Valores por Defecto (Seed)"):
                s, m = seed_master_defaults()
                if s: st.success(m); st.rerun()
                else: st.error(m)
                
            if st.button("📥 Importar Actividades desde CSV"):
                # Path hardcoded as per user context
                csv_path = r"c:\web_antigravity\GWP\Datos\matriz_actividades_integradas.csv"
                s, m = seed_activities_from_csv(csv_path)
                if s: st.success(m)
                else: st.error(m)

        st.divider()
        st.divider()
        st.subheader("3. Meta-Data Proyecto")
        
        # Calculate End Date for display
        proj_end_calc = PROJECT_START + timedelta(days=PROJECT_DURATION*30) # Approx
        
        with st.form("meta_form"):
            n_name = st.text_input("Nombre Proyecto", PROJECT_NAME)
            n_logo = st.text_input("Logo URL", LOGO)
            
            c_d1, c_d2 = st.columns(2)
            n_start = c_d1.date_input("Fecha Inicio Proyecto", PROJECT_START)
            n_dur = c_d2.number_input("Duración (Meses)", min_value=1, value=PROJECT_DURATION)
            
            st.caption(f"📅 Fecha Fin Estimada: {proj_end_calc.strftime('%d/%m/%Y')}")
            
            if st.form_submit_button("Actualizar Meta"):
                update_project_meta("project_name", n_name)
                update_project_meta("logo_url", n_logo)
                update_project_meta("start_date", n_start.strftime('%Y-%m-%d'))
                update_project_meta("duration_months", str(n_dur))
                st.rerun()

# --- VIEW: PLANNING CMS (ADMIN) ---
if st.session_state['role'] == 'ADMIN':
    with tabs[3]:
        st.header("📅 Editor Maestro de Cronograma")
        st.info("CMS Integrado: Las opciones de Productos y Usuarios vienen de la DB.")
        
        # Fresh Fetch
        acts_df = get_table_df("activities")
        prods_df = get_table_df("contract_products")
        users_df = get_table_df("users")
        
        # --- PREPARE DROPDOWN OPTIONS (MAPPING) ---
        # 1. Products: "Code | Name"
        prod_map = {}
        prod_options = []
        if not prods_df.empty:
            for _, r in prods_df.iterrows():
                label = f"{r['code']} | {r['name']}"
                prod_map[r['code']] = label
                prod_options.append(label)
        
        # 2. Roles: "Role" (Or Name if preferred, but schema uses Role currently)
        # Requirement: "Assign Roles". Schema column is 'primary_role' which stores 'COORD', etc.
        # But user wants to pick names? If schema stores Role, sticking to Role or Role list.
        # Optimizing: Let's show "COORD", "FINANZAS" but ensure they come from Users table roles (distinct)
        user_roles = users_df['role'].unique().tolist() if not users_df.empty else ["COORD", "FINANZAS"]
        
        # --- APPLY MAPPING TO DATAFRAME FOR DISPLAY ---
        # We replace the raw codes with the friendly labels in the DF *before* showing the editor
        display_df = acts_df.copy()
        display_df['product_code'] = display_df['product_code'].map(prod_map).fillna(display_df['product_code'])
        
        dep_codes = acts_df['activity_code'].tolist() if not acts_df.empty else []

        # Editor
        edited_display_df = st.data_editor(
            display_df,
            key="cms_editor",
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "id": st.column_config.NumberColumn("ID Interno", disabled=True),
                "activity_code": st.column_config.TextColumn("Código", required=True),
                "product_code": st.column_config.SelectboxColumn("Producto", options=prod_options, required=True, width="medium"),
                "primary_role": st.column_config.SelectboxColumn("Rol Responsable", options=user_roles, required=True),
                "dependency_code": st.column_config.SelectboxColumn("Dependencia", options=dep_codes),
                "type_tag": st.column_config.SelectboxColumn("Tipo", options=["INT", "IND", "DEP", "INT+DEP", "IND+DEP", "IND-P"]),
                "status": st.column_config.SelectboxColumn("Estado", options=["PENDING", "IN_PROGRESS", "BLOCKED", "DONE"])
            },
            hide_index=True
        )
        
        if st.button("💾 Guardar Cronograma"):
            try:
                # --- REVERSE MAPPING (DISPLAY -> DB) ---
                # We need to turn "1.1 | Coord" back into "1.1"
                save_df = edited_display_df.copy()
                
                # Helper to strip " | Name"
                def unpack_product(val):
                    if isinstance(val, str) and " | " in val:
                        return val.split(" | ")[0]
                    return val
                
                save_df['product_code'] = save_df['product_code'].apply(unpack_product)
                
                # Prepare payload
                # We only want to save columns that exist in DB + ID
                # (Streamlit adds _index sometimes)
                valid_cols = ['id', 'activity_code', 'product_code', 'task_name', 'week_start', 'week_end', 'type_tag', 'dependency_code', 'primary_role', 'status']
                # Filter cols
                final_records = []
                for _, row in save_df.iterrows():
                    rec = {k: row[k] for k in valid_cols if k in row}
                    final_records.append(rec)

                success, msg = upsert_data("activities", final_records)
                if success:
                    st.success("✅ Cronograma Sincronizado")
                    st.balloons()
                    st.rerun()
                else:
                    st.error(f"Error: {msg}")
            except Exception as e:
                st.error(e)

# --- VIEW: FACTORY (KANBAN) ---
# Logic: Show tasks in columns based on Status. Buttons to move.
target_tab = tabs[1] if st.session_state['role'] == 'ADMIN' else tabs[1] 

with target_tab:
    st.subheader("Tablero de Actividades")
    
    df_acts = get_table_df("activities")
    users_df = get_table_df("users")
    
    # Map Role -> Name
    role_map = {}
    if not users_df.empty:
        for _, u in users_df.iterrows():
            role_map[u['role']] = u['full_name']
            
    # Enrich DF with Name for Gantt
    df_acts['responsible_name'] = df_acts['primary_role'].map(role_map).fillna(df_acts['primary_role'])

    # --- PREPARE DATE LOGIC ---
    def add_real_dates(df):
        if df.empty: return df
        # Lambda to safe convert
        def get_dates(row):
            try:
                ws = int(row.get('week_start') or 1)
                we = int(row.get('week_end') or 1)
                p_start = PROJECT_START
                
                # Logic: Week 1 Start = Project Start
                # Real Start = p_start + (ws-1) weeks
                # Real End = p_start + (we) weeks - 1 day (standard project week end)
                
                real_s = p_start + timedelta(weeks=ws-1)
                real_e = p_start + timedelta(weeks=we) - timedelta(days=1) # Friday? or Sunday? Let's say full week.
                
                # Return strings for display and objs, but let's stick to objs for Altair
                return pd.Series([real_s, real_e])
            except:
                return pd.Series([PROJECT_START, PROJECT_START])

        df[['real_start_date', 'real_end_date']] = df.apply(get_dates, axis=1)
        return df

    df_acts = add_real_dates(df_acts)

    df_acts = add_real_dates(df_acts)

    # --- DIALOG: Evidence Manager ---
    @st.dialog("📂 Gestión de Evidencias")
    def evidence_dialog(row, is_mine, role):
        st.markdown(f"**Actividad:** {row['activity_code']}")
        st.caption(row['task_name'])
        st.divider()
        
        # 1. List Files
        evidences = get_evidence_by_activity(row['activity_code'])
        if evidences:
            st.markdown("###### 📄 Archivos Adjuntos:")
            for ev in evidences:
                c1, c2, c3 = st.columns([6, 1, 1])
                with c1:
                    st.write(f"• {ev['filename']}")
                with c2:
                    d_url = get_evidence_url(ev['storage_path'])
                    if d_url:
                        st.markdown(f"[⬇️]({d_url})")
                with c3:
                    # Delete Check
                    can_del = (role == 'ADMIN') or (role == ev.get('uploaded_by'))
                    if can_del:
                        with st.popover("🗑️", help="Eliminar"):
                            st.write("¿Borrar?")
                            if st.button("Sí", key=f"dlg_del_{ev['id']}"):
                                success, msg = delete_evidence(ev['storage_path'])
                                if success:
                                    st.success("Eliminado")
                                    st.rerun()
                                else:
                                    st.error(msg)
            st.divider()
        else:
            st.info("No hay archivos adjuntos.")

        # 2. Upload New
        if is_mine or role == 'ADMIN':
            st.markdown("###### 📤 Subir Nuevo:")
            up_file = st.file_uploader("Seleccionar archivo", key=f"dlg_up_{row['id']}", label_visibility="collapsed")
            
            if up_file:
                if st.button("Confirmar Subida", type="primary"):
                    # Visual Progress
                    prog = st.progress(0, text="Iniciando subida...")
                    import time
                    prog.progress(30, text="Enviando a la nube...")
                    
                    success, msg_up = upload_evidence(up_file, row['activity_code'], role)
                    
                    if success:
                        prog.progress(100, text="¡Completado!")
                        time.sleep(0.5)
                        st.success("Archivo subido con éxito.")
                        st.rerun()
                    else:
                        st.error(msg_up)

    # --- HELPER: Render Board ---
    def render_board(dataframe):
        if dataframe.empty:
            st.info("No hay actividades en esta sección.")
            return

        cols = st.columns(4)
        statuses = ["PENDING", "IN_PROGRESS", "BLOCKED", "DONE"]
        labels = ["😴 Pendiente", "🔨 En Progreso", "🔒 Bloqueado", "✅ Listo"]
        
        for i, status in enumerate(statuses):
            with cols[i]:
                st.markdown(f"### {labels[i]}")
                subset = dataframe[dataframe['status'] == status]
                
                for _, row in subset.iterrows():
                    is_blocked = check_is_blocked(row, df_acts) # Uses the GLOBAL df_acts 
                    
                    is_mine = row['primary_role'] == st.session_state['role']
                    
                    # Colors/Style indicators
                    border_color = "red" if is_blocked else "#ddd"
                    
                    # Resolve Name
                    role_code = row['primary_role']
                    user_name = role_map.get(role_code, role_code)
                    
                    # Dates
                    try:
                        d_s = row['real_start_date'].strftime('%d %b')
                        d_e = row['real_end_date'].strftime('%d %b')
                        date_info = f"{d_s} - {d_e}"
                    except:
                        date_info = f"Sem {row.get('week_start')} - {row.get('week_end')}"

                    type_info = f"{row.get('type_tag')}"
                    
                    dep = row.get('dependency_code')
                    
                    co = row.get('co_responsibles')
                    co_info = f"👥 {co}" if co and str(co) != 'nan' else ""
                    
                    # Evidence Check
                    evidences = get_evidence_by_activity(row['activity_code'])
                    has_evidence = len(evidences) > 0
                    
                    # --- NATIVE CONTAINER CARD ---
                    with st.container(border=True):
                        # Row 1: Header + Evidence
                        c_head, c_act = st.columns([6, 1])
                        with c_head:
                            st.markdown(f"**{row['activity_code']}** {row['task_name']}")
                        with c_act:
                            btn_icon = "📎" if has_evidence else "➕"
                            if st.button(btn_icon, key=f"btn_ev_{row['id']}", help="Gestionar Evidencias", type="tertiary"):
                                evidence_dialog(row, is_mine, st.session_state['role'])

                        # Row 2: Meta + Navigation
                        c_meta, c_nav = st.columns([5, 2])
                        
                        with c_meta:
                            meta_line = f"🏷️ {type_info} | 🗓️ {date_info} | 👤 {user_name}"
                            st.caption(meta_line)
                            if is_blocked:
                                st.markdown(f":red[🔒 Bloqueado por {dep}]", help=f"Depende de {dep}")
                            if co_info: st.caption(co_info)
                            
                        with c_nav:
                            # Navigation Buttons aligned to right
                            c_b_prev, c_b_next = st.columns(2)
                            
                            # Prev
                            if status not in ['PENDING', 'BLOCKED']:
                                prev_stat = 'PENDING'
                                if status == 'DONE': prev_stat = 'IN_PROGRESS'
                                if c_b_prev.button("◀", key=f"prev_{row['id']}", help="Regresar"):
                                    update_activity_status_flow(row['id'], prev_stat)
                                    st.rerun()

                            # Next
                            if status != 'DONE':
                                next_stat = 'IN_PROGRESS'
                                if status == 'IN_PROGRESS': next_stat = 'DONE'
                                
                                can_move = True
                                help_txt = "Avanzar"
                                
                                if is_blocked:
                                    can_move = False
                                    help_txt = "Bloqueado por dependencia"
                                
                                if next_stat == 'DONE':
                                    can_comp, msg = check_can_complete(row)
                                    if not can_comp:
                                        can_move = False
                                        help_txt = msg
                                
                                if c_b_next.button("▶", key=f"next_{row['id']}", disabled=not can_move, help=help_txt):
                                    update_activity_status_flow(row['id'], next_stat)
                                    st.rerun()

    # --- SPLIT LOGIC ---
    # --- VIEW SELECTOR ---
    c_view, c_opt = st.columns([2, 4])
    view_mode = c_view.radio("Modo de Vista", ["Kanban", "Cronograma"], horizontal=True, label_visibility="collapsed")
    
    show_today_line = False
    if view_mode == "Cronograma":
        show_today_line = c_opt.checkbox("📍 Mostrar línea de hoy", value=True)

    # --- SPLIT LOGIC ---
    current_role = st.session_state['role']
    
    # Helper to render chosen view
    def render_content(df):
        if view_mode == "Kanban":
            render_board(df)
        else:
            if df.empty:
                st.info("No hay datos para mostrar en el cronograma.")
            else:
                render_gantt_chart(df, show_today=show_today_line)

    if current_role == 'ADMIN':
        render_content(df_acts)
    else:
        # Find user name
        curr_user_rows = users_df[users_df['role'] == current_role]
        curr_name = curr_user_rows.iloc[0]['full_name'] if not curr_user_rows.empty else "Unknown"
        
        # 1. Primary
        df_primary = df_acts[df_acts['primary_role'] == current_role]
        
        # 2. Co-Responsible
        def is_co_responsible(row):
            co = str(row.get('co_responsibles', ''))
            if co and co != 'nan' and co != 'None':
                if current_role in co: return True
                if curr_name in co: return True
            return False
            
        df_co = df_acts[df_acts.apply(is_co_responsible, axis=1)]
        
        subtab1, subtab2 = st.tabs(["👑 Mis Responsabilidades", "🤝 Co-Responsables"])
        
        with subtab1:
            render_content(df_primary)
            
        with subtab2:
            render_content(df_co)
