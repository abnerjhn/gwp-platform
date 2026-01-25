import streamlit as st
import pandas as pd
import altair as alt
from db import get_connection, get_activities_df, get_user_by_email
from logic import check_dependencies_blocking, update_activity_status, get_dashboard_metrics, move_mechanism_stage

st.set_page_config(page_title="GWP Platform", layout="wide", page_icon="🌐")

# --- Authentication Mock ---
if 'user_role' not in st.session_state:
    st.session_state['user_role'] = 'COORD' # Default
    st.session_state['user_email'] = 'astrid@gwp.org'

with st.sidebar:
    st.image("https://placehold.co/200x50/png?text=GWP+Integration", use_container_width=True)
    st.title("GWP Management")
    
    selected_user = st.selectbox("Simular Usuario:", 
        ["Astrid (COORD)", "Patricio (FINANZAS)", "Constanza (LEGAL)", "Gobierno (VISOR)"]
    )
    
    if "Astrid" in selected_user:
        st.session_state['user_role'] = 'COORD'
        st.session_state['user_email'] = 'astrid@gwp.org'
    elif "Patricio" in selected_user:
        st.session_state['user_role'] = 'FINANZAS'
        st.session_state['user_email'] = 'patricio@gwp.org'
    elif "Constanza" in selected_user:
        st.session_state['user_role'] = 'LEGAL'
        st.session_state['user_email'] = 'constanza@gwp.org'
    else:
        st.session_state['user_role'] = 'GOBIERNO'
        st.session_state['user_email'] = 'gov@gob.cl'
        
    st.info(f"Logueado como: **{st.session_state['user_role']}**")

# --- Main Views ---
page = st.radio("Navegación", ["🏠 Dashboard", "🏭 Fábrica Mecanismos", "📋 Mis Tareas", "📚 Biblioteca"], horizontal=True)

if page == "🏠 Dashboard":
    st.header("Torre de Control Integrada")
    
    # Metrics
    metrics = get_dashboard_metrics()
    col1, col2, col3 = st.columns(3)
    col1.metric("Progreso Global", f"{metrics['progress_percent']}%")
    col2.metric("Actividades Completadas", f"{metrics['completed']}/{metrics['total_activities']}")
    col3.metric("Próximo Hito Pago", "Producto 1.1 (En 5 días)")
    
    # Gantt Chart
    st.subheader("Cronograma Maestro")
    df = get_activities_df()
    
    if not df.empty:
        # Altair Gantt
        chart = alt.Chart(df).mark_bar().encode(
            x=alt.X('week_start', title='Semana Inicio'),
            x2='week_end',
            y=alt.Y('task_name', sort='x', title='Actividad'),
            color=alt.Color('status', scale=alt.Scale(domain=['PENDING', 'IN_PROGRESS', 'BLOCKED', 'DONE'], range=['lightgray', 'blue', 'red', 'green'])),
            tooltip=['activity_code', 'task_name', 'status', 'primary_role']
        ).interactive()
        
        st.altair_chart(chart, use_container_width=True)
    
    # Blocking Alerts
    st.subheader("🚨 Alertas de Bloqueo")
    # Identify blocked tasks logic
    blocked_tasks = []
    for index, row in df.iterrows():
        if check_dependencies_blocking(row['id']):
            blocked_tasks.append(row)
            
    if blocked_tasks:
        for task in blocked_tasks:
            st.error(f"**{task['activity_code']}** - {task['task_name']} está BLOQUEADA por dependencia {task['dependency_code']}")
    else:
        st.success("No hay bloqueos críticos actuales.")

elif page == "📋 Mis Tareas":
    st.header(f"Mis Tareas ({st.session_state['user_role']})")
    
    df = get_activities_df()
    
    # Filter by Role (or Co-responsible)
    # Simple logic: Primary role or listed in co-responsibles
    # Note: co_responsibles is text, so we do a simple contains check or strict role check
    # For MVP, listing if Primary matches
    
    my_tasks = df[df['primary_role'] == st.session_state['user_role']]
    
    for idx, row in my_tasks.iterrows():
        with st.expander(f"{row['activity_code']} - {row['task_name']} [{row['status']}]"):
            
            # Check Blocking
            is_blocked = check_dependencies_blocking(row['id'])
            
            if is_blocked:
                st.markdown("🔒 **TAREA BLOQUEADA** - Dependencia pendiente.")
            else:
                st.markdown("✅ **Habilitada**")
            
            st.write(f"**Evidencia Requerida:** {row['evidence_requirement']}")
            
            # Upload Evidence
            uploaded_file = st.file_uploader("Subir Evidencia", key=f"file_{row['id']}")
            has_file = row['has_file_uploaded']
            
            if uploaded_file:
                # Mock upload
                st.success("Archivo subido exitosamente (Simulado)")
                has_file = True # In a real app, update DB here
                # Auto-update database flag for simulation
                conn = get_connection()
                c = conn.cursor()
                c.execute("UPDATE activities SET has_file_uploaded = 1 WHERE id = ?", (row['id'],))
                conn.commit()
                conn.close()

            # Actions
            col_act1, col_act2 = st.columns(2)
            
            # Mark Done Button
            if row['status'] != 'DONE':
                if col_act1.button("Marcar como DONE", key=f"done_{row['id']}", disabled=is_blocked):
                    success, msg = update_activity_status(row['id'], 'DONE', st.session_state['user_role'], has_file)
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            else:
                st.info("Tarea Completada.")

elif page == "🏭 Fábrica Mecanismos":
    st.header("Kanban de Mecanismos")
    st.info("Visualización del Pipeline de Aprobación")
    
    # Mock Mechanism Data (Since we didn't seed mechanisms, let's create a dummy one in memory or DB if empty)
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM mechanisms")
    mechs = c.fetchall()
    
    if not mechs:
        # Create a dummy one
        c.execute("INSERT INTO mechanisms (id, name, status_pipeline, created_by) VALUES (?, ?, ?, ?)", 
                 ("m1", "Mecanismo Bonos Carbono v1", "DRAFT", "u2"))
        conn.commit()
        mechs = [("m1", "Mecanismo Bonos Carbono v1", "DRAFT", "u2")]
    conn.close()
    
    # Columns
    cols = st.columns(4)
    stages = ["DRAFT", "LEGAL_REVIEW", "GENDER_REVIEW", "APPROVED"]
    titles = ["📝 Borrador (Finanzas)", "⚖️ Revisión Legal", "💜 Revisión Género", "✅ Aprobado"]
    
    for i, stage in enumerate(stages):
        with cols[i]:
            st.subheader(titles[i])
            # Filter mechs in this stage
            stage_mechs = [m for m in mechs if m[2] == stage]
            
            for m in stage_mechs:
                st.markdown(f"""
                <div style="border:1px solid #ccc; padding: 10px; border-radius: 5px; margin-bottom: 10px;">
                    <strong>{m[1]}</strong>
                </div>
                """, unsafe_allow_html=True)
                
                # Advance Button
                if st.button("Avanzar ➡️", key=f"adv_{m[0]}"):
                    success, msg = move_mechanism_stage(m[0], stage, st.session_state['user_role'])
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

elif page == "📚 Biblioteca":
    st.header("Biblioteca Documental")
    st.info("Repositorio centralizado de evidencias.")
    
    # List all activities that have files uploaded (simulated)
    conn = get_connection()
    df_files = pd.read_sql_query("SELECT * FROM activities WHERE has_file_uploaded = 1", conn)
    conn.close()
    
    if not df_files.empty:
        st.dataframe(df_files[['activity_code', 'task_name', 'evidence_requirement', 'primary_role']])
    else:
        st.write("No hay documentos subidos aún.")

