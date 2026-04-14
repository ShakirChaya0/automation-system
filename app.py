"""
app.py - Panel de Control Local — Sistema de Asistencia Pro
Panel Streamlit para gestionar materias, configurar Telegram y
visualizar el historial de firmas.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from dotenv import load_dotenv, set_key

# ─── Configuración ────────────────────────────────────────────────────────────

load_dotenv()

TIMEZONE      = ZoneInfo("America/Argentina/Buenos_Aires")
MATERIAS_FILE = Path("materias.json")
LOG_FILE      = Path("log.json")
ENV_FILE      = Path(".env")

DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def cargar_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def guardar_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def guardar_env(key: str, value: str) -> None:
    """Guarda una variable en el archivo .env local."""
    ENV_FILE.touch(exist_ok=True)
    set_key(str(ENV_FILE), key, value)
    os.environ[key] = value


# ─── Estilos ──────────────────────────────────────────────────────────────────

def aplicar_estilos():
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Space+Grotesk:wght@400;600;700&display=swap');

        html, body, [class*="css"] {
            font-family: 'Space Grotesk', sans-serif;
        }
        .stApp {
            background: linear-gradient(135deg, #0d1117 0%, #161b22 50%, #0d1117 100%);
        }
        h1, h2, h3 {
            font-family: 'JetBrains Mono', monospace !important;
            letter-spacing: -1px;
        }
        .metric-card {
            background: rgba(22, 27, 34, 0.8);
            border: 1px solid rgba(48, 54, 61, 0.8);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            backdrop-filter: blur(10px);
        }
        .metric-number {
            font-size: 2.5rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
            color: #58a6ff;
        }
        .metric-label {
            font-size: 0.85rem;
            color: #8b949e;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .status-badge {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
        }
        .badge-success { background: rgba(35, 134, 54, 0.2); color: #3fb950; border: 1px solid #3fb950; }
        .badge-error   { background: rgba(248, 81, 73, 0.2);  color: #f85149; border: 1px solid #f85149; }
        .badge-pending { background: rgba(210, 153, 34, 0.2); color: #d29922; border: 1px solid #d29922; }
        .section-header {
            color: #58a6ff;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 2px;
            margin-bottom: 8px;
            padding-bottom: 8px;
            border-bottom: 1px solid rgba(88, 166, 255, 0.3);
        }
        div[data-testid="stExpander"] {
            border: 1px solid rgba(48, 54, 61, 0.8) !important;
            border-radius: 10px !important;
            background: rgba(22, 27, 34, 0.6) !important;
        }
        .stButton > button {
            background: linear-gradient(135deg, #1f6feb, #388bfd) !important;
            color: white !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 600 !important;
            transition: all 0.2s !important;
        }
        .stButton > button:hover {
            transform: translateY(-1px) !important;
            box-shadow: 0 4px 15px rgba(56, 139, 253, 0.3) !important;
        }
    </style>
    """, unsafe_allow_html=True)


# ─── Página: Dashboard ────────────────────────────────────────────────────────

def pagina_dashboard():
    st.markdown('<p class="section-header">// Resumen del Sistema</p>', unsafe_allow_html=True)

    log      = cargar_json(LOG_FILE, [])
    materias = cargar_json(MATERIAS_FILE, [])

    hoy      = datetime.now(tz=TIMEZONE).strftime("%Y-%m-%d")
    firmadas_hoy   = [e for e in log if e.get("fecha") == hoy]
    total_firmas   = len(log)
    total_materias = len(materias)

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-number">{total_materias}</div>
            <div class="metric-label">Materias Cargadas</div>
        </div>""", unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-number">{len(firmadas_hoy)}</div>
            <div class="metric-label">Firmadas Hoy</div>
        </div>""", unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-number">{total_firmas}</div>
            <div class="metric-label">Total Historial</div>
        </div>""", unsafe_allow_html=True)
    with col4:
        telegram_ok = bool(os.environ.get("TELEGRAM_TOKEN"))
        status_html = (
            '<span class="status-badge badge-success">● Activo</span>'
            if telegram_ok else
            '<span class="status-badge badge-error">● Inactivo</span>'
        )
        st.markdown(f"""
        <div class="metric-card">
            <div style="margin-top:8px">{status_html}</div>
            <div class="metric-label" style="margin-top:8px">Telegram Bot</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Estado de materias hoy
    st.markdown('<p class="section-header">// Estado de Materias — Hoy</p>', unsafe_allow_html=True)
    dia_actual = datetime.now(tz=TIMEZONE).strftime("%A").lower()
    dias_map   = {
        "monday": "lunes", "tuesday": "martes", "wednesday": "miercoles",
        "thursday": "jueves", "friday": "viernes", "saturday": "sabado", "sunday": "domingo"
    }
    dia_es = dias_map.get(dia_actual, dia_actual)

    materias_hoy = [m for m in materias if m.get("dia", "").lower().replace("é","e") == dia_es]

    if not materias_hoy:
        st.info(f"📅 No hay materias programadas para hoy ({dia_es.capitalize()}).")
    else:
        for m in materias_hoy:
            nombre = m["nombre_materia"]
            firmada = any(e.get("materia") == nombre and e.get("fecha") == hoy for e in log)
            badge = (
                '<span class="status-badge badge-success">✅ Firmada</span>'
                if firmada else
                '<span class="status-badge badge-pending">⏳ Pendiente</span>'
            )
            st.markdown(
                f"**{nombre}** &nbsp;|&nbsp; {m['hora_inicio']} - {m['hora_fin']} "
                f"&nbsp;|&nbsp; {m['comision']} &nbsp; {badge}",
                unsafe_allow_html=True
            )


# ─── Página: Gestión de Materias ──────────────────────────────────────────────

def pagina_materias():
    st.markdown('<p class="section-header">// Gestión de Materias</p>', unsafe_allow_html=True)

    materias = cargar_json(MATERIAS_FILE, [])

    # Listado con opciones de eliminación
    if materias:
        st.markdown("#### Materias Cargadas")
        for i, m in enumerate(materias):
            with st.expander(f"📚 {m['nombre_materia']} — {m['dia'].capitalize()} {m['hora_inicio']}-{m['hora_fin']}"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.json(m)
                with col2:
                    if st.button("🗑️ Eliminar", key=f"del_{i}"):
                        materias.pop(i)
                        guardar_json(MATERIAS_FILE, materias)
                        st.success("Materia eliminada.")
                        st.rerun()
    else:
        st.warning("No hay materias cargadas aún.")

    st.markdown("---")
    st.markdown("#### ➕ Agregar Nueva Materia")

    with st.form("form_nueva_materia"):
        col1, col2 = st.columns(2)
        with col1:
            nombre_materia = st.text_input("Nombre de la Materia *", placeholder="Ej: Bases de Datos")
            comision       = st.text_input("Comisión *", placeholder="Ej: Comisión 03")
            nombre_alumno  = st.text_input("Nombre del Alumno *", placeholder="Ej: Juan Pérez")
        with col2:
            dia         = st.selectbox("Día de Cursada *", DIAS_SEMANA)
            hora_inicio = st.time_input("Hora de Inicio *")
            hora_fin    = st.time_input("Hora de Fin *")
        link = st.text_input("Link del Formulario *", placeholder="https://docs.google.com/forms/...")

        submitted = st.form_submit_button("💾 Guardar Materia", use_container_width=True)
        if submitted:
            if not all([nombre_materia, comision, nombre_alumno, link]):
                st.error("⚠️ Todos los campos son obligatorios.")
            else:
                nueva = {
                    "nombre_materia": nombre_materia.strip(),
                    "comision":       comision.strip(),
                    "link":           link.strip(),
                    "dia":            dia,
                    "hora_inicio":    hora_inicio.strftime("%H:%M"),
                    "hora_fin":       hora_fin.strftime("%H:%M"),
                    "nombre_alumno":  nombre_alumno.strip(),
                }
                materias.append(nueva)
                guardar_json(MATERIAS_FILE, materias)
                st.success(f"✅ Materia '{nombre_materia}' guardada correctamente.")
                st.rerun()

    st.markdown("---")
    st.markdown("#### 📋 Editar JSON directamente")
    json_raw = st.text_area(
        "materias.json",
        value=json.dumps(materias, ensure_ascii=False, indent=2),
        height=300,
        label_visibility="collapsed"
    )
    if st.button("💾 Guardar JSON Raw"):
        try:
            nuevas = json.loads(json_raw)
            guardar_json(MATERIAS_FILE, nuevas)
            st.success("✅ JSON guardado.")
            st.rerun()
        except json.JSONDecodeError as e:
            st.error(f"JSON inválido: {e}")


# ─── Página: Configuración Telegram ──────────────────────────────────────────

def pagina_telegram():
    st.markdown('<p class="section-header">// Configuración de Telegram</p>', unsafe_allow_html=True)

    st.markdown("""
    **¿Cómo obtener tus credenciales?**
    1. Habla con [@BotFather](https://t.me/BotFather) en Telegram → `/newbot` → copia el **Token**.
    2. Habla con [@userinfobot](https://t.me/userinfobot) → copia tu **Chat ID**.
    3. En GitHub Actions → Repository Settings → Secrets → agrega `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID`.
    """)

    st.info("🔒 Los valores se guardan en `.env` para uso local. **Nunca subas `.env` a GitHub.**")

    current_token   = os.environ.get("TELEGRAM_TOKEN", "")
    current_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    with st.form("form_telegram"):
        token   = st.text_input(
            "TELEGRAM_TOKEN",
            value=current_token,
            type="password",
            placeholder="123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
        )
        chat_id = st.text_input(
            "TELEGRAM_CHAT_ID",
            value=current_chat_id,
            placeholder="123456789"
        )
        guardar = st.form_submit_button("💾 Guardar en .env", use_container_width=True)
        if guardar:
            if token:
                guardar_env("TELEGRAM_TOKEN", token)
            if chat_id:
                guardar_env("TELEGRAM_CHAT_ID", chat_id)
            st.success("✅ Credenciales guardadas en .env")

    st.markdown("---")
    st.markdown("#### 🧪 Test de Notificación")

    if st.button("📤 Enviar mensaje de prueba"):
        token_actual   = os.environ.get("TELEGRAM_TOKEN")
        chat_id_actual = os.environ.get("TELEGRAM_CHAT_ID")
        if not token_actual or not chat_id_actual:
            st.error("⚠️ Configurá primero el token y el chat ID.")
        else:
            try:
                import httpx
                resp = httpx.post(
                    f"https://api.telegram.org/bot{token_actual}/sendMessage",
                    json={
                        "chat_id": chat_id_actual,
                        "text":    "🤖 Test exitoso desde el Panel de Control de Asistencia Pro!",
                        "parse_mode": "HTML"
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                st.success("✅ Mensaje de prueba enviado correctamente!")
            except Exception as e:
                st.error(f"❌ Error: {e}")


# ─── Página: Historial ────────────────────────────────────────────────────────

def pagina_historial():
    st.markdown('<p class="section-header">// Historial de Asistencias</p>', unsafe_allow_html=True)

    log = cargar_json(LOG_FILE, [])

    if not log:
        st.info("📭 No hay registros de asistencias todavía.")
        return

    # Convertir a DataFrame
    df = pd.DataFrame(log)
    df["fecha"] = pd.to_datetime(df["fecha"])

    # Filtros
    col1, col2, col3 = st.columns(3)
    with col1:
        materias_opts = ["Todas"] + sorted(df["materia"].unique().tolist())
        filtro_materia = st.selectbox("Filtrar por Materia", materias_opts)
    with col2:
        if not df.empty:
            fecha_min = df["fecha"].min().date()
            fecha_max = df["fecha"].max().date()
            rango = st.date_input("Rango de Fechas", value=(fecha_min, fecha_max))
        else:
            rango = None
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🗑️ Limpiar Log Completo"):
            if st.session_state.get("confirmar_limpiar"):
                guardar_json(LOG_FILE, [])
                st.success("Log limpiado.")
                st.session_state["confirmar_limpiar"] = False
                st.rerun()
            else:
                st.session_state["confirmar_limpiar"] = True
                st.warning("⚠️ Hacé clic de nuevo para confirmar.")

    # Aplicar filtros
    df_filtrado = df.copy()
    if filtro_materia != "Todas":
        df_filtrado = df_filtrado[df_filtrado["materia"] == filtro_materia]
    if rango and len(rango) == 2:
        df_filtrado = df_filtrado[
            (df_filtrado["fecha"].dt.date >= rango[0]) &
            (df_filtrado["fecha"].dt.date <= rango[1])
        ]

    # Estadísticas rápidas
    st.markdown(f"**{len(df_filtrado)}** registros encontrados")
    st.markdown("---")

    # Tabla
    if not df_filtrado.empty:
        cols_display = ["fecha", "materia", "comision", "alumno", "hora"]
        cols_exist   = [c for c in cols_display if c in df_filtrado.columns]
        st.dataframe(
            df_filtrado[cols_exist].sort_values("fecha", ascending=False).reset_index(drop=True),
            use_container_width=True,
            hide_index=True,
        )

        # Descarga
        csv = df_filtrado.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Descargar CSV",
            data=csv,
            file_name=f"asistencias_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )

    # Gráfico de actividad
    if len(df) >= 3:
        st.markdown("---")
        st.markdown("#### 📊 Actividad por Materia")
        conteo = df["materia"].value_counts().reset_index()
        conteo.columns = ["Materia", "Asistencias"]
        st.bar_chart(conteo.set_index("Materia"))


# ─── App Principal ────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Asistencia Pro · Panel",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    aplicar_estilos()

    # Sidebar
    with st.sidebar:
        st.markdown("# 🎓 Asistencia Pro")
        st.markdown(
            '<p style="color:#8b949e;font-size:0.8rem;font-family:\'JetBrains Mono\',monospace">'
            'Sistema Set & Forget v1.0</p>',
            unsafe_allow_html=True
        )
        st.markdown("---")

        hora_ar = datetime.now(tz=TIMEZONE).strftime("%H:%M:%S")
        st.markdown(
            f'<p style="color:#58a6ff;font-family:\'JetBrains Mono\',monospace;font-size:0.9rem">'
            f'🕐 {hora_ar} ARG</p>',
            unsafe_allow_html=True
        )

        st.markdown("---")
        pagina = st.radio(
            "Navegación",
            ["📊 Dashboard", "📚 Materias", "💬 Telegram", "📋 Historial"],
            label_visibility="collapsed"
        )
        st.markdown("---")
        st.markdown(
            '<p style="color:#484f58;font-size:0.7rem">Ejecutar bot localmente:<br>'
            '<code style="color:#79c0ff">python bot.py</code></p>',
            unsafe_allow_html=True
        )

    # Routing
    if "Dashboard" in pagina:
        pagina_dashboard()
    elif "Materias" in pagina:
        pagina_materias()
    elif "Telegram" in pagina:
        pagina_telegram()
    elif "Historial" in pagina:
        pagina_historial()


if __name__ == "__main__":
    main()
