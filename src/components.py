import streamlit as st
import altair as alt
import pandas as pd
from logic import check_is_blocked

def render_gantt_chart(df, show_today=False):
    """
    Renders the Gantt chart using Altair.
    """
    if df.empty:
        st.info("No hay datos para mostrar en el cronograma.")
        return

    # Color mapping for status
    domain = ['PENDING', 'IN_PROGRESS', 'BLOCKED', 'DONE']
    range_ = ['#e0e0e0', '#3b82f6', '#ef4444', '#22c55e'] # Gray, Blue, Red, Green

    # Create composite label for Y axis
    df['label'] = df['activity_code'] + " - " + df['task_name']
    
    # Calculate Dynamic Height
    # 30px per row + buffer. Min height 400.
    row_height = 30
    dynamic_height = max(400, len(df) * row_height + 50)

    # Base Chart
    bars = alt.Chart(df).mark_bar(cornerRadius=5, height=20).encode(
        x=alt.X('real_start_date:T', title='Calendario'),  
        x2='real_end_date:T',
        y=alt.Y('label', sort='x', title=None), 
        color=alt.Color('status', scale=alt.Scale(domain=domain, range=range_), legend=alt.Legend(title="Estado")),
        tooltip=[
            alt.Tooltip('activity_code', title='Código'),
            alt.Tooltip('task_name', title='Actividad'),
            alt.Tooltip('status', title='Estado'),
            alt.Tooltip('responsible_name', title='Responsable'),
            alt.Tooltip('co_responsibles', title='Co-Responsables'),
            alt.Tooltip('product_code', title='Producto'),
            alt.Tooltip('type_tag', title='Tipo'),
            alt.Tooltip('dependency_code', title='Dependencia'),
            alt.Tooltip('real_start_date', title='Inicio', format='%d %b %Y'),
            alt.Tooltip('real_end_date', title='Fin', format='%d %b %Y')
        ]
    ).properties(
        title="Cronograma Maestro de Actividades",
        height=dynamic_height
    )

    final_chart = bars

    if show_today:
        from datetime import datetime
        today_df = pd.DataFrame({'date': [datetime.now()]})
        
        rule = alt.Chart(today_df).mark_rule(color='red', strokeDash=[5, 5]).encode(
            x='date:T',
            tooltip=[alt.Tooltip('date', title='HOY', format='%d %b %Y')]
        )
        final_chart = alt.layer(bars, rule)

    st.altair_chart(final_chart, use_container_width=True)

def render_kanban_card(row, is_blocked):
    """
    Renders a single card for the Kanban/Task view.
    """
    # Visual Styles
    border_color = "#ef4444" if is_blocked else "#e5e7eb"
    bg_color = "#fef2f2" if is_blocked else "#ffffff"
    opacity = "0.6" if is_blocked else "1.0"
    
    with st.container():
        st.markdown(f"""
        <div style="
            border: 2px solid {border_color};
            background-color: {bg_color};
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
            opacity: {opacity};
        ">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-weight:bold; font-size:0.9rem; color:#6b7280;">{row['activity_code']}</span>
                <span style="font-size:0.8rem; background:#eff6ff; padding:2px 6px; border-radius:4px; color:#1e40af;">{row['primary_role']}</span>
            </div>
            <h4 style="margin: 0.5rem 0; font-size:1rem;">{row['task_name']}</h4>
        </div>
        """, unsafe_allow_html=True)
        
        # Blocking Alert
        if is_blocked:
            st.error(f"🔒 BLOQUEADO por {row['dependency_code']}")
        
        # Evidence Alert
    
def render_mechanism_card(mech, user_role, on_click_action):
    """
    Renders a Mechanism card with Action Buttons based on Role & Stage.
    """
    status = mech['status_pipeline']
    can_act = False
    next_stage = None
    action_label = ""
    
    # Logic: Who can move what?
    # DRAFT (Finanzas) -> LEGAL_REVIEW
    if status == 'DRAFT' and user_role == 'FINANZAS':
        can_act = True
        next_stage = 'LEGAL_REVIEW'
        action_label = "Solicitar Revisión Legal ➡️"
        
    # LEGAL_REVIEW (Legal) -> GENDER_REVIEW
    elif status == 'LEGAL_REVIEW' and user_role == 'LEGAL':
        can_act = True
        next_stage = 'GENDER_REVIEW'
        action_label = "Aprobar Legal ⚖️"
        
    # GENDER_REVIEW (Coord) -> APPROVED
    elif status == 'GENDER_REVIEW' and user_role == 'COORD':
        can_act = True
        next_stage = 'APPROVED'
        action_label = "Aprobar Inclusión 💜"

    # Styling
    st.markdown(f"""
    <div style="
        border: 1px solid #ddd;
        background-color: white;
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 10px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    ">
        <strong>{mech['name']}</strong><br>
        <small style="color:gray">{mech.get('description', '')}</small>
    </div>
    """, unsafe_allow_html=True)
    
    if can_act:
        if st.button(action_label, key=f"mech_{mech['id']}"):
            on_click_action(mech['id'], next_stage)
