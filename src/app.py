import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime, timedelta, date
from db import init_connection, get_table_df, upsert_data, get_project_meta, update_project_meta, update_activity_status_flow, seed_master_defaults, seed_activities_from_csv, upload_evidence, get_evidence_by_activity, get_evidence_url, get_all_evidence, delete_evidence, sync_activities_file_status
from logic import check_dependencies_blocking, check_is_blocked, check_can_complete, update_activity_status, get_dashboard_metrics, move_mechanism_stage, generate_graphviz_dot, PHASES_CONFIG
from components import render_kanban_card, render_mechanism_card, render_gantt_chart
import streamlit.components.v1 as components

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
    tabs = st.tabs(["📊 Dashboard", "🔀 Mapa de Procesos", "📋 Actividades", "📂 Archivos", "📅 Planificación (CMS)", "⚙️ Configuración"])
elif st.session_state['role'] == 'GOBIERNO':
    tabs = st.tabs(["📊 Dashboard", "🔀 Mapa de Procesos", "📋 Actividades", "📂 Archivos"])
else:
    tabs = st.tabs(["📊 Dashboard", "🔀 Mapa de Procesos", "📋 Actividades", "📋 Mis Tareas", "📂 Archivos"])


# --- VIEW: DASHBOARD ---
with tabs[0]:
    st.header("📊 Tablero de Control del Proyecto")
    
    # metrics
    d_df = get_table_df("activities")
    
    if d_df.empty:
        st.info("Sin datos para mostrar.")
    else:
        # Calcs
        total = len(d_df)
        done = len(d_df[d_df['status'] == 'DONE'])
        in_prog = len(d_df[d_df['status'] == 'IN_PROGRESS'])
        
        # Calculate real Blocked (DB Blocked + Visual Blocked)
        blocked_count = 0
        real_pending_count = 0
        
        for _, r in d_df.iterrows():
            s = r['status']
            if s == 'BLOCKED':
                blocked_count += 1
            elif s == 'PENDING':
                if check_is_blocked(r, d_df):
                    blocked_count += 1
                else:
                    real_pending_count += 1
            
        progress = int((done / total) * 100) if total > 0 else 0
        
        # Date Calc (Start & End)
        today = datetime.now().date()
        def get_dates_dash(row):
            try:
                ws = int(row.get('week_start') or 1)
                we = int(row.get('week_end') or 1)
                real_s = PROJECT_START + timedelta(weeks=ws-1)
                real_e = PROJECT_START + timedelta(weeks=we) - timedelta(days=1)
                return pd.Series([real_s, real_e])
            except:
                return pd.Series([PROJECT_START, PROJECT_START])

        d_df[['dash_start', 'dash_end']] = d_df.apply(get_dates_dash, axis=1)
        d_df['dash_start'] = pd.to_datetime(d_df['dash_start']).dt.date
        d_df['dash_end'] = pd.to_datetime(d_df['dash_end']).dt.date
        
        delayed = len(d_df[(d_df['dash_end'] < today) & (d_df['status'] != 'DONE')])

        # Row 1: Metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Actividades", total)
        m2.metric("Progreso Global", f"{progress}%", f"{in_prog} En curso")
        m3.metric("Bloqueadas", blocked_count, delta_color="inverse")
        m4.metric("Retrasadas", delayed, delta_color="inverse")
        
        st.divider()
        
        # Row 2: Charts (Visualizations)
        c_chart1, c_chart2 = st.columns(2)
        
        # Prepare Data Shared
        users_dash = get_table_df("users")
        role_map_dash = dict(zip(users_dash['role'], users_dash['full_name'])) if not users_dash.empty else {}
        
        with c_chart1:
            st.subheader("Distribución y Responsables")
            
            # Prepare Data for Stacked Chart
            chart_df = d_df.copy()
            chart_df['Responsable'] = chart_df['primary_role'].map(role_map_dash).fillna(chart_df['primary_role'])
            status_labels = {
                'PENDING': 'Pendiente', 'IN_PROGRESS': 'En Progreso', 
                'BLOCKED': 'Bloqueado', 'DONE': 'Listo'
            }
            chart_df['Estado'] = chart_df['status'].map(status_labels).fillna(chart_df['status'])
            
            c_stacked = alt.Chart(chart_df).mark_bar().encode(
                x=alt.X('Estado', sort=['Pendiente', 'En Progreso', 'Bloqueado', 'Listo'], title="Estado"),
                y=alt.Y('count()', title="Actividades"),
                color=alt.Color('Responsable', scale=alt.Scale(scheme='set2'), title="Responsable"),
                tooltip=['Estado', 'Responsable', 'count()']
            )
            st.altair_chart(c_stacked, use_container_width=True)
            
        with c_chart2:
            st.subheader("Avance por Producto (%)")
            
            # 1. Get Products
            prods_ref = get_table_df("contract_products")
            prod_map = {}
            if not prods_ref.empty:
                for _, r in prods_ref.iterrows():
                    prod_map[r['code']] = f"{r['code']} {r['name']}" # Use code+name for clarity
            
            # 2. Helper
            def get_prod_label(code):
                if not isinstance(code, str): return "General"
                c = code.split(' | ')[0]
                return prod_map.get(c, c)
            
            d_df['prod_label'] = d_df['product_code'].apply(get_prod_label)
            
            # 3. Calculate %
            d_df['is_done'] = d_df['status'] == 'DONE'
            prog_df = d_df.groupby('prod_label').agg(
                Total=('id', 'count'),
                Done=('is_done', 'sum')
            ).reset_index()
            
            prog_df['Porcentaje'] = (prog_df['Done'] / prog_df['Total'] * 100).round(1)
            
            c_prog = alt.Chart(prog_df).mark_bar().encode(
                x=alt.X('Porcentaje', scale=alt.Scale(domain=[0, 100])),
                y=alt.Y('prod_label', sort='-x', title="Producto"),
                color=alt.Color('Porcentaje', legend=None, scale=alt.Scale(scheme='greens')),
                tooltip=['prod_label', 'Porcentaje', 'Total', 'Done']
            )
            st.altair_chart(c_prog, use_container_width=True)
            
        st.divider()
        
        # Row 3: Actionable Cards
        st.subheader("🚀 Foco de Atención")
        
        # Ensure map is available
        d_users_ref = get_table_df("users")
        role_map_ref = dict(zip(d_users_ref['role'], d_users_ref['full_name'])) if not d_users_ref.empty else {}

        c_a1, c_a2 = st.columns(2)
        
        with c_a1:
            st.info("🔥 Top Cuellos de Botella (No Finalizados)")
            # Logic: Parents that block the most pending/in-progress items
            pending_df = d_df[~d_df['status'].isin(['DONE'])] 
            blockers = pending_df['dependency_code'].dropna()
            
            if blockers.empty:
                st.caption("No hay bloqueos activos.")
            else:
                top = blockers.value_counts().head(5)
                has_content = False
                for code, count in top.items():
                    # Check parent status
                    parent = d_df[d_df['activity_code'] == code]
                    if not parent.empty and parent.iloc[0]['status'] != 'DONE':
                        p_row = parent.iloc[0]
                        
                        # Prep Info
                        d_range = f"{p_row['dash_start'].strftime('%d/%m')} - {p_row['dash_end'].strftime('%d/%m')}"
                        primary = role_map_ref.get(p_row['primary_role'], p_row['primary_role'])
                        
                        co_raw = str(p_row.get('co_responsibles', ''))
                        # Clean split
                        co_list = [c.strip() for c in co_raw.split(',') if c.strip() and c.strip() not in ['nan', 'None']]
                        co_names = [role_map_ref.get(r, r) for r in co_list]
                        co_str = ", ".join(co_names) if co_names else "-"

                        with st.container(border=True):
                            st.markdown(f"**{code}** ({count} deps) | `{p_row['status']}`")
                            st.markdown(f"📅 {d_range}")
                            st.caption(f"👤 **{primary}** | 🤝 {co_str}")
                            st.caption(f"_{p_row['task_name']}_")
                        has_content = True
                
                if not has_content: st.caption("Los bloqueos actuales dependen de tareas ya finalizadas (Estable).")

        with c_a2:
            st.info("⏳ Próximos Vencimientos (7 Días)")
            next_week = today + timedelta(days=7)
            # Filter: Not Done AND Due in [Today, NextWeek]
            upcoming = d_df[
                (d_df['status'] != 'DONE') & 
                (d_df['dash_end'] >= today) & 
                (d_df['dash_end'] <= next_week)
            ].sort_values('dash_end').head(5)
            
            if upcoming.empty:
                st.caption("¡Todo al día! Nada vence esta semana.")
            else:
                for _, r in upcoming.iterrows():
                    delta = (r['dash_end'] - today).days
                    tag = "HOY" if delta == 0 else ("MAÑANA" if delta == 1 else f"en {delta} días")
                    
                    d_range = f"{r['dash_start'].strftime('%d/%m')} - {r['dash_end'].strftime('%d/%m')}"
                    primary = role_map_ref.get(r['primary_role'], r['primary_role'])
                    
                    co_raw = str(r.get('co_responsibles', ''))
                    co_list = [c.strip() for c in co_raw.split(',') if c.strip() and c.strip() not in ['nan', 'None']]
                    co_names = [role_map_ref.get(x, x) for x in co_list]
                    co_str = ", ".join(co_names) if co_names else "-"
                    
                    with st.container(border=True):
                        st.markdown(f"**{r['activity_code']}** ({tag}) | `{r['status']}`")
                        st.markdown(f"📅 {d_range}")
                        st.caption(f"👤 **{primary}** | 🤝 {co_str}")
                        st.caption(f"_{r['task_name']}_")

# --- VIEW: LIVE MAP ---
# --- VIEW: LIVE MAP ---
with tabs[1]:
    # Generate DF
    map_df = get_table_df("activities")
    
    if not map_df.empty:
        # Helper to render
        def render_tab_content(current_df, key_suffix, is_full=False, group_by_phases=True, rankdir='TB'):
            if current_df.empty:
                st.warning("No hay actividades registradas para esta fase.")
                return

            try:
                dot = generate_graphviz_dot(current_df, group_by_phases=group_by_phases, rankdir=rankdir)
                if dot:
                    # RENDER STRATEGY: Embed SVG in scrollable HTML container
                    # This allows scrolling large diagrams instead of shrinking them
                    try:
                        svg = dot.pipe(format='svg').decode('utf-8')
                        
                        # Custom Scrollable Container with Embedded Download
                        container_id = f"graph_container_{key_suffix}"
                        
                        html_code = f"""
                        <!DOCTYPE html>
                        <html>
                        <head>
                            <script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"></script>
                            <style>
                                body, html {{ margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; }}
                                #{container_id} {{
                                    width: 100%;
                                    height: 100vh;
                                    border: 1px solid #e0e0e0;
                                    background-color: white;
                                    position: relative;
                                }}
                                .controls {{
                                    position: absolute;
                                    top: 20px;
                                    right: 20px;
                                    z-index: 100;
                                    display: flex;
                                    flex-direction: column;
                                    gap: 8px;
                                    background: rgba(255, 255, 255, 0.9);
                                    padding: 8px;
                                    border-radius: 8px;
                                    box-shadow: 0 2px 6px rgba(0,0,0,0.15);
                                }}
                                .btn {{
                                    width: 30px;
                                    height: 30px;
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                    cursor: pointer;
                                    background: #fff;
                                    border: 1px solid #ccc;
                                    border-radius: 4px;
                                    font-family: sans-serif;
                                    font-size: 18px;
                                    font-weight: bold;
                                    color: #333;
                                    user-select: none;
                                }}
                                .btn:hover {{ background: #f0f0f0; border-color: #999; }}
                                .reset-btn {{ font-size: 12px; height: auto; padding: 4px; }}
                                .download {{ font-size: 16px; }}
                            </style>
                        </head>
                        <body>
                            <div id="{container_id}">
                                <div class="controls">
                                    <div class="btn zoom-in" title="Zoom In">+</div>
                                    <div class="btn zoom-out" title="Zoom Out">-</div>
                                    <div class="btn reset-btn reset" title="Reset">⟲</div>
                                    <div class="btn download" title="Descargar SVG">💾</div>
                                </div>
                                {svg}
                            </div>
                            <!-- Hidden Data Block for Download -->
                            <script id="raw_svg_data" type="text/plain">{svg}</script>
                            <script>
                                (function() {{
                                    var container = document.getElementById('{container_id}');
                                    var svgElement = container.querySelector('svg');
                                    var panZoom = null;
                                    
                                    function triggerDownload() {{
                                        // Get ORIGINAL, PRISTINE SVG content (High Res)
                                        // We read it from the hidden script block to avoid the pan-zoom group transforms
                                        var rawContent = document.getElementById('raw_svg_data').textContent;
                                        
                                        // Create file
                                        var blob = new Blob([rawContent], {{type: "image/svg+xml;charset=utf-8"}});
                                        var url = URL.createObjectURL(blob);
                                        
                                        // Download link
                                        var downloadLink = document.createElement("a");
                                        downloadLink.href = url;
                                        downloadLink.download = "mapa_proceso_full.svg";
                                        document.body.appendChild(downloadLink);
                                        downloadLink.click();
                                        document.body.removeChild(downloadLink);
                                    }}

                                    function init() {{
                                        if (panZoom) return;
                                        if (container.clientWidth === 0 || container.clientHeight === 0) return;
                                        
                                        svgElement.setAttribute('width', '100%');
                                        svgElement.setAttribute('height', '100%');
                                        
                                        try {{
                                            panZoom = svgPanZoom(svgElement, {{
                                                zoomEnabled: true, controlIconsEnabled: false,
                                                fit: true, center: true,
                                                minZoom: 0.1, maxZoom: 10, dblClickZoomEnabled: false
                                            }});
                                            
                                            // Bind Controls
                                            container.querySelector('.zoom-in').addEventListener('click', function() {{ panZoom.zoomIn(); }});
                                            container.querySelector('.zoom-out').addEventListener('click', function() {{ panZoom.zoomOut(); }});
                                            container.querySelector('.reset').addEventListener('click', function() {{ panZoom.resetZoom(); panZoom.center(); }});
                                            container.querySelector('.download').addEventListener('click', triggerDownload);
                                            
                                            window.addEventListener('resize', function() {{
                                                if(panZoom) {{ panZoom.resize(); panZoom.fit(); panZoom.center(); }}
                                            }});
                                        }} catch(e) {{ console.error("Init Error", e); }}
                                    }}
                                    
                                    if (window.ResizeObserver) {{
                                        var ro = new ResizeObserver(function(entries) {{
                                            for (var i = 0; i < entries.length; i++) {{
                                                if (entries[i].contentRect.width > 0) init();
                                            }}
                                        }});
                                        ro.observe(container);
                                    }} else {{ setTimeout(init, 500); }}
                                    init();
                                }})()
                            </script>
                        </body>
                        </html>
                        """
                        
                        # Render component with generous height
                        components.html(html_code, height=700, scrolling=True)
                        
                        if not is_full:
                             st.caption("💡 Usa las barras de desplazamiento para navegar el diagrama.")
                             
                    except Exception as pipe_err:
                         # Fallback if dot binary missing or pipe fails
                         st.warning(f"Modo interactivo limitado (Error SVG: {pipe_err}). Usando vista estática.")
                         st.graphviz_chart(dot, use_container_width=True)
                         
                else:
                    st.info("No se pudo generar el gráfico.")
            except Exception as e:
                st.error(f"Error generando gráfico: {e}")

        # Just one main view now
        
        # --- VIEW: PROCESS MAP (Previously Full View) ---
        st.markdown("### 🔀 Mapa de Procesos Integrado")
        
        # Controls Bar
        with st.container():
            # Row 1: Phase Filter
            all_phase_names = [p['name'] for p in PHASES_CONFIG.values()]
            selected_phases = st.multiselect("Filtrar por Fases", all_phase_names, default=all_phase_names)

            # Row 2: Display Options
            c1, c2, c3, c4 = st.columns([3, 3, 2, 2])
            with c1:
                orientation = st.radio("Orientación", ["Vertical (TB)", "Horizontal (LR)"], index=0, horizontal=True)
                # Apply previous swap fix: Vertical->LR, Horizontal->TB
                rank_dir = "LR" if "Vertical" in orientation else "TB"
            with c2:
                selected_statuses = st.multiselect("Filtrar Estado", ["PENDING", "IN_PROGRESS", "DONE"], default=["PENDING", "IN_PROGRESS", "DONE"])
            with c3:
                st.write("") # Spacer
                st.write("")
                group_phases = st.checkbox("Agrupar Fases", value=True)
            with c4:
                st.write("")
                st.write("")
                only_connected = st.checkbox("Solo Conexiones", value=True)
        
        st.divider()
        
        # --- DATA PROCESSING ---
        full_view_df = map_df.copy()

        # 1. Filter by Phases
        if not selected_phases:
            st.warning("⚠️ Selecciona al menos una fase para visualizar.")
            full_view_df = pd.DataFrame()
        else:
            # Build list of allowed weeks based on selected phases
            allowed_weeks = []
            for p_name in selected_phases:
                for p_cfg in PHASES_CONFIG.values():
                    if p_cfg['name'] == p_name:
                        allowed_weeks.extend(range(p_cfg['start'], p_cfg['end'] + 2)) # Safety margin
            
            # Filter Week
            full_view_df['week_start'] = full_view_df['week_start'].fillna(0).astype(int)
            full_view_df = full_view_df[full_view_df['week_start'].isin(allowed_weeks)]
            
            # Filter Status
            if selected_statuses:
                full_view_df = full_view_df[full_view_df['status'].isin(selected_statuses)]
            else:
                full_view_df = pd.DataFrame() # No status selected = empty

        # 2. Filter Critical Path (Only Connected)
        if only_connected and not full_view_df.empty:
            # Strict Referential Integrity Filter
            def normalize_dep(val):
                s = str(val).strip()
                if pd.isna(val) or s in ['-', '?', 'nan', 'None', '', '0']: return None
                return s
            
            analysis_df = full_view_df.copy()
            analysis_df['clean_dep'] = analysis_df['dependency_code'].apply(normalize_dep)
            
            # Valid codes are only those CURRENTLY in the view (after phase filter)
            valid_codes = set(analysis_df['activity_code'].astype(str).unique())
            analysis_df['valid_dep'] = analysis_df['clean_dep'].apply(lambda x: x if x in valid_codes else None)
            
            is_valid_child = analysis_df['valid_dep'].notna()
            valid_parents = set(analysis_df['valid_dep'].dropna().unique())
            is_valid_parent = analysis_df['activity_code'].astype(str).isin(valid_parents)
            
            full_view_df = analysis_df[is_valid_child | is_valid_parent].copy()

        # 3. Apply Sorting (ALWAYS BY WEEK/DATE + INTERNAL ID)
        if not full_view_df.empty:
            full_view_df = full_view_df.sort_values(['week_start', 'id'])
        
        render_tab_content(full_view_df, "main_map", is_full=True, group_by_phases=group_phases, rankdir=rank_dir)
        
    else:
        st.info("No hay datos de actividades cargados en el sistema.")
            


# --- VIEW: FILE MANAGER ---
# Common for all
file_tab_idx = 2 if st.session_state['role'] in ['ADMIN', 'GOBIERNO'] else 3
with tabs[file_tab_idx]:
    st.header("📂 Gestor Documental Centralizado")
    
    files = get_all_evidence()
    if not files:
        st.info("No hay archivos subidos aún.")
    else:
        # Search
        search_q = st.text_input("Buscar archivo...", "")
        
        # Display as grid/table
        # Custom display
        # Custom display: Group by PRODUCT
        
        # 1. Fetch Context Data
        acts_ref = get_table_df("activities")
        prods_ref = get_table_df("contract_products")
        
        # 2. Build Mappings
        # Prod Code -> Prod Name
        prod_name_map = {}
        if not prods_ref.empty:
            for _, r in prods_ref.iterrows():
                prod_name_map[r['code']] = f"{r['code']} {r['name']}"
                
        # Activity Code -> Product Name
        act_to_prod = {}
        if not acts_ref.empty:
            for _, r in acts_ref.iterrows():
                # Clean product code if pipe exists
                p_c = r['product_code']
                if isinstance(p_c, str) and " | " in p_c: p_c = p_c.split(" | ")[0]
                
                p_name = prod_name_map.get(p_c, "Sin Producto / General")
                act_to_prod[r['activity_code']] = p_name
        
        # 3. Group Files
        grouped_files = {}
        
        for f in files:
            # Filter
            if search_q and search_q.lower() not in f['filename'].lower() and search_q.lower() not in f['activity_code'].lower():
                continue
                
            # Get Group
            a_code = f['activity_code']
            group_name = act_to_prod.get(a_code, "Otros / Sin Asignar")
            
            if group_name not in grouped_files:
                grouped_files[group_name] = []
            grouped_files[group_name].append(f)
            
        # 4. Render Groups (Sorted)
        for g_name in sorted(grouped_files.keys()):
            p_files = grouped_files[g_name]
            
            with st.expander(f"📦 {g_name} ({len(p_files)})", expanded=True):
                for f in p_files:
                     c1, c2, c3, c4 = st.columns([0.5, 4, 3, 2])
                     c1.write("📄")
                     with c2:
                         st.markdown(f"**{f['filename']}**")
                         st.caption(f"🆔 {f['activity_code']}")
                     with c3:
                         st.caption(f"👤 {f.get('uploaded_by','?')} | 📅 {f['uploaded_at'][:10]}")
                     
                     with c4:
                         c_d, c_del = st.columns([1, 1])
                         url = get_evidence_url(f['storage_path'])
                         if url: 
                             c_d.markdown(f"[⬇️]({url})")
                         
                         can_del = (st.session_state['role'] == 'ADMIN') or (st.session_state['role'] == f.get('uploaded_by'))
                         if can_del:
                             with c_del.popover("🗑️"):
                                 if st.button("Conf.", key=f"del_f_{f['id']}"):
                                     delete_evidence(f['storage_path'])
                                     st.rerun()
                     st.divider()

# --- VIEW: CONFIGURATION (ADMIN) ---
if st.session_state['role'] == 'ADMIN':
    with tabs[5]:
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
    with tabs[4]:
        st.header("📅 Editor Maestro de Cronograma")
        st.info("CMS Integrado: Las opciones de Productos y Usuarios vienen de la DB.")
        
        # Fresh Fetch - Sync Files First
        sync_activities_file_status()
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
                "status": st.column_config.SelectboxColumn("Estado", options=["PENDING", "IN_PROGRESS", "BLOCKED", "DONE"]),
                "evidence_requirement": st.column_config.SelectboxColumn("Evidencia Req.", options=["SI", "NO"]),
                "has_file_uploaded": st.column_config.CheckboxColumn("📂?", disabled=True)
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
                valid_cols = ['id', 'activity_code', 'product_code', 'task_name', 'week_start', 'week_end', 'type_tag', 'dependency_code', 'primary_role', 'status', 'evidence_requirement']
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
    st.subheader("📋 Tablero de Actividades")
    
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
    def render_board(dataframe, key_suffix="main"):
        if dataframe.empty:
            st.info("No hay actividades en esta sección.")
            return

        cols = st.columns(4)
        statuses = ["BLOCKED", "PENDING", "IN_PROGRESS", "DONE"]
        labels = ["🔒 Bloqueado", "😴 Pendiente", "🔨 En Progreso", "✅ Listo"]
        
        # Visual Bucketing (Move Blocked Pending -> Blocked Column)
        buckets = {s: [] for s in statuses}
        for _, row in dataframe.iterrows():
            s = row['status']
            if s == 'PENDING' and check_is_blocked(row, df_acts):
                s = 'BLOCKED'
            if s in buckets: buckets[s].append(row)

        for i, status in enumerate(statuses):
            with cols[i]:
                st.markdown(f"### {labels[i]}")
                subset = pd.DataFrame(buckets[status]) if buckets[status] else pd.DataFrame()
                
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
                            if st.button(btn_icon, key=f"btn_ev_{key_suffix}_{row['id']}", help="Gestionar Evidencias", type="tertiary"):
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
                                if c_b_prev.button("◀", key=f"prev_{key_suffix}_{row['id']}", help="Regresar"):
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
                                
                                if c_b_next.button("▶", key=f"next_{key_suffix}_{row['id']}", disabled=not can_move, help=help_txt):
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
    # Helper to render chosen view
    def render_content(df, key_suffix="main"):
        if view_mode == "Kanban":
            render_board(df, key_suffix)
        else:
            if df.empty:
                st.info("No hay datos para mostrar en el cronograma.")
            else:
                render_gantt_chart(df, show_today=show_today_line)

    if current_role == 'ADMIN':
        render_content(df_acts)
    elif current_role == 'GOBIERNO':
        # GOBIERNO View: All activities (except ADMIN) without subtabs
        st.info("Vista de Supervisión Gubernamental (Todas las Actividades)")
        df_gov = df_acts[df_acts['primary_role'] != 'ADMIN']
        render_content(df_gov, "gov_all")
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
        
        subtab1, subtab2, subtab3 = st.tabs(["👑 Mis Responsabilidades", "🤝 Co-Responsables", "📚 Todas"])
        
        with subtab1:
            render_content(df_primary, "user_primary")
            
        with subtab2:
            render_content(df_co, "user_co")
            
        with subtab3:
            # Combine both
            df_all = pd.concat([df_primary, df_co]).drop_duplicates(subset=['id'])
            render_content(df_all, "user_all")

# --- VIEW: MY TASKS (USER ONLY) ---
if st.session_state['role'] not in ['ADMIN', 'GOBIERNO']:
    with tabs[3]:
        st.header("📋 Tablero de Prioridades Personales")
        
        df_all_tasks = get_table_df("activities")
        users_df = get_table_df("users")
        
        if df_all_tasks.empty:
            st.info("No se encontraron actividades.")
        else:
            # --- DATE LOGIC (Local Helper) ---
            def calculate_dates(row):
                try:
                    ws = int(row.get('week_start') or 1)
                    we = int(row.get('week_end') or 1)
                    p_start = PROJECT_START
                    real_s = p_start + timedelta(weeks=ws-1)
                    real_e = p_start + timedelta(weeks=we) - timedelta(days=1)
                    return pd.Series([real_s, real_e])
                except:
                    return pd.Series([PROJECT_START, PROJECT_START])
            
            df_all_tasks[['real_start_date', 'real_end_date']] = df_all_tasks.apply(calculate_dates, axis=1)
            # Ensure DateTime type for .dt accessor
            df_all_tasks['real_start_date'] = pd.to_datetime(df_all_tasks['real_start_date'])
            df_all_tasks['real_end_date'] = pd.to_datetime(df_all_tasks['real_end_date'])
            
            # --- FILTER: MY TASKS ---
            curr_role = st.session_state['role']
            role_map = {r['role']: r['full_name'] for _, r in users_df.iterrows()} if not users_df.empty else {}
            curr_name = role_map.get(curr_role, "")
            
            def is_mine(row):
                # SPECIAL RULE: GOBIERNO sees everything EXCEPT Admin tasks
                if curr_role == 'GOBIERNO':
                    return row['primary_role'] != 'ADMIN'

                # Standard Rule
                if row['primary_role'] == curr_role: return True
                co = str(row.get('co_responsibles', ''))
                if curr_role in co: return True
                if curr_name and curr_name in co: return True
                return False
            
            df_mine = df_all_tasks[df_all_tasks.apply(is_mine, axis=1)].copy()
            
            if df_mine.empty:
                st.success("🎉 ¡Estás libre! No tienes actividades asignadas.")
            else:
                # --- CONTROLS ---
                today = datetime.now().date()
                
                # Default Week Range
                def_start = today - timedelta(days=today.weekday())
                def_end = def_start + timedelta(days=6)

                c_f1, c_f2 = st.columns([3, 4])
                with c_f1:
                    date_range = st.date_input("📅 Filtrar por Fechas (Desde - Hasta)", value=(def_start, def_end))
                    
                    if isinstance(date_range, tuple) or isinstance(date_range, list):
                        if len(date_range) == 2:
                            start_week, end_week = date_range
                        elif len(date_range) == 1:
                            start_week = date_range[0]
                            end_week = start_week
                        else:
                            start_week, end_week = def_start, def_end
                    else:
                        start_week, end_week = def_start, def_end
                
                st.caption(f"Mostrando: {start_week.strftime('%d/%m')} - {end_week.strftime('%d/%m')}")
                st.divider()
                
                # --- SEGMENT 1: RETRASADAS (Delayed) ---
                df_mine['date_only_end'] = df_mine['real_end_date'].dt.date
                delayed_mask = (df_mine['date_only_end'] < today) & (df_mine['status'] != 'DONE')
                df_delayed = df_mine[delayed_mask]
                
                if not df_delayed.empty:
                    st.error(f"🚨 TIENES {len(df_delayed)} ACTIVIDADES RETRASADAS")
                    for _, row in df_delayed.iterrows():
                        with st.container(border=True):
                            c1, c2 = st.columns([5, 1])
                            c1.markdown(f"**{row['activity_code']}** {row['task_name']}")
                            c1.caption(f"Debió terminar: {row['real_end_date'].strftime('%d %b')}")
                
                # --- SEGMENT 2: URGENTE / BLOQUEANTE (Blocking Others) ---
                pending_all = df_all_tasks[df_all_tasks['status'] != 'DONE']
                blocking_codes = pending_all['dependency_code'].dropna().unique()
                
                blocking_mask = (df_mine['activity_code'].isin(blocking_codes)) & (df_mine['status'] != 'DONE')
                df_urgent = df_mine[blocking_mask]
                
                if not df_urgent.empty:
                    st.warning(f"🔥 {len(df_urgent)} ACTIVIDADES ESTÁN BLOQUEANDO AL EQUIPO")
                    for _, row in df_urgent.iterrows():
                         with st.container(border=True):
                            st.markdown(f"**{row['activity_code']}** {row['task_name']}")
                            blocked_kids = pending_all[pending_all['dependency_code'] == row['activity_code']]
                            kids_str = ", ".join(blocked_kids['activity_code'].tolist())
                            st.caption(f"Estás bloqueando a: {kids_str}")

                # --- SEGMENT 3: THIS WEEK ---
                df_mine['date_only_start'] = df_mine['real_start_date'].dt.date
                week_mask = (df_mine['date_only_start'] <= end_week) & (df_mine['date_only_end'] >= start_week)
                df_week = df_mine[week_mask]
                
                st.subheader("📆 Tu Planificación Semanal")
                
                if df_week.empty:
                    st.info("Nada planificado para esta semana específica.")
                else:
                    for _, row in df_week.iterrows():
                        status_icon = "✅" if row['status'] == 'DONE' else "🔄"
                        with st.container(border=True):
                            st.markdown(f"**{status_icon} {row['activity_code']}** - {row['task_name']}")
                            st.caption(f"{row['real_start_date'].strftime('%d %b')} -> {row['real_end_date'].strftime('%d %b')} | Estado: {row['status']}")
