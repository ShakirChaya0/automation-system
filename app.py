"""
app.py - Panel de Control Local — Sistema de Asistencia Pro
Panel Streamlit para gestionar materias, configurar Telegram y
visualizar el historial de firmas.
"""

import json
import os
from datetime import datetime, time as dt_time
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

DIAS_SEMANA  = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DIAS_MAP_ES  = {
    "monday": "lunes", "tuesday": "martes", "wednesday": "miercoles",
    "thursday": "jueves", "friday": "viernes", "saturday": "sabado", "sunday": "domingo",
}
DIAS_MAP_NORM = {  # con tilde → sin tilde
    "miércoles": "miercoles", "sábado": "sabado", "lúnes": "lunes",
}


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
    ENV_FILE.touch(exist_ok=True)
    set_key(str(ENV_FILE), key, value)
    os.environ[key] = value


def normalizar_dia(dia: str) -> str:
    tabla = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")
    return dia.lower().translate(tabla)


def ahora_art() -> datetime:
    return datetime.now(tz=TIMEZONE)


def dia_actual_es() -> str:
    return DIAS_MAP_ES.get(ahora_art().strftime("%A").lower(), "")


def proxima_materia(materias: list, log_data: list) -> dict | None:
    """
    Devuelve la próxima materia que aún NO fue firmada hoy,
    ordenada por hora de inicio del día actual.
    """
    hoy    = ahora_art().strftime("%Y-%m-%d")
    dia_es = dia_actual_es()

    pendientes = []
    for m in materias:
        if normalizar_dia(m.get("dia", "")) != dia_es:
            continue
        nombre   = m["nombre_materia"]
        firmada  = any(e.get("materia") == nombre and e.get("fecha") == hoy for e in log_data)
        if not firmada:
            pendientes.append(m)

    if not pendientes:
        return None

    pendientes.sort(key=lambda m: m.get("hora_inicio", "99:99"))
    return pendientes[0]


# ─── Estilos ──────────────────────────────────────────────────────────────────

def aplicar_estilos():
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Sora:wght@300;400;600;700&display=swap');

        html, body, [class*="css"]  { font-family: 'Sora', sans-serif; }
        h1, h2, h3, code            { font-family: 'JetBrains Mono', monospace !important; }

        .stApp {
            background: linear-gradient(160deg, #090e17 0%, #0d1520 60%, #0a1219 100%);
        }

        /* Tarjetas métricas */
        .metric-card {
            background: rgba(13, 17, 28, 0.85);
            border: 1px solid rgba(56, 139, 253, 0.18);
            border-radius: 14px;
            padding: 22px 18px;
            text-align: center;
            transition: border-color .25s;
        }
        .metric-card:hover { border-color: rgba(56,139,253,.5); }
        .metric-number {
            font-size: 2.6rem; font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
            color: #58a6ff; line-height: 1;
        }
        .metric-label {
            font-size: .75rem; color: #6e7681;
            text-transform: uppercase; letter-spacing: 1.5px; margin-top: 8px;
        }

        /* Badges */
        .badge {
            display: inline-block; padding: 3px 11px;
            border-radius: 20px; font-size: .72rem;
            font-weight: 600; font-family: 'JetBrains Mono', monospace;
        }
        .badge-ok      { background:rgba(35,134,54,.2);  color:#3fb950; border:1px solid #3fb950; }
        .badge-warn    { background:rgba(210,153,34,.2); color:#d29922; border:1px solid #d29922; }
        .badge-error   { background:rgba(248,81,73,.2);  color:#f85149; border:1px solid #f85149; }
        .badge-info    { background:rgba(56,139,253,.15);color:#58a6ff; border:1px solid #388bfd; }

        /* Encabezados de sección */
        .sec-header {
            color: #388bfd; font-family: 'JetBrains Mono', monospace;
            font-size: .72rem; text-transform: uppercase; letter-spacing: 2.5px;
            margin: 0 0 14px 0; padding-bottom: 8px;
            border-bottom: 1px solid rgba(56,139,253,.25);
        }

        /* Fila de materia */
        .materia-row {
            display: flex; align-items: center; justify-content: space-between;
            padding: 10px 16px; margin-bottom: 6px;
            background: rgba(22,27,42,.7);
            border: 1px solid rgba(48,54,72,.6);
            border-radius: 10px;
        }
        .materia-nombre { font-weight: 600; font-size: .95rem; color: #e6edf3; }
        .materia-meta   { font-size: .78rem; color: #8b949e; font-family: 'JetBrains Mono', monospace; }

        /* Próxima materia highlight */
        .proxima-card {
            background: rgba(56,139,253,.08);
            border: 1px solid rgba(56,139,253,.35);
            border-radius: 12px; padding: 16px 20px; margin-bottom: 16px;
        }
        .proxima-title { font-size: .7rem; color: #388bfd; text-transform: uppercase;
                         letter-spacing: 2px; font-family: 'JetBrains Mono', monospace; }
        .proxima-nombre { font-size: 1.25rem; font-weight: 700; color: #e6edf3; margin: 4px 0; }

        /* Botones */
        .stButton > button {
            background: linear-gradient(135deg, #1f6feb, #388bfd) !important;
            color: white !important; border: none !important;
            border-radius: 9px !important; font-weight: 600 !important;
            transition: all .2s !important;
        }
        .stButton > button:hover {
            transform: translateY(-1px) !important;
            box-shadow: 0 4px 18px rgba(56,139,253,.35) !important;
        }

        div[data-testid="stExpander"] {
            border: 1px solid rgba(48,54,72,.7) !important;
            border-radius: 10px !important;
            background: rgba(13,17,28,.7) !important;
        }
    </style>
    """, unsafe_allow_html=True)


# ─── Página: Dashboard ────────────────────────────────────────────────────────

def pagina_dashboard():
    st.markdown('<p class="sec-header">// Resumen del Sistema</p>', unsafe_allow_html=True)

    log_data  = cargar_json(LOG_FILE, [])
    materias  = cargar_json(MATERIAS_FILE, [])
    ahora_dt  = ahora_art()
    hoy       = ahora_dt.strftime("%Y-%m-%d")
    dia_es    = dia_actual_es()

    firmadas_hoy   = [e for e in log_data if e.get("fecha") == hoy]
    materias_hoy   = [m for m in materias if normalizar_dia(m.get("dia","")) == dia_es]
    total_firmas   = len(log_data)
    total_materias = len(materias)
    telegram_ok    = bool(os.environ.get("TELEGRAM_TOKEN"))

    # ── KPIs ──────────────────────────────────────────────────────────────
    cols = st.columns(4)
    kpis = [
        (total_materias, "Materias Config."),
        (len(materias_hoy), "Clases Hoy"),
        (len(firmadas_hoy), "Firmadas Hoy"),
        (total_firmas,  "Total Historial"),
    ]
    for col, (num, label) in zip(cols, kpis):
        with col:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="metric-number">{num}</div>'
                f'<div class="metric-label">{label}</div>'
                f'</div>',
                unsafe_allow_html=True
            )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Próxima materia pendiente ──────────────────────────────────────────
    proxima = proxima_materia(materias, log_data)
    if proxima:
        hora_actual = ahora_dt.time()
        h_ini       = datetime.strptime(proxima["hora_inicio"], "%H:%M").time()
        estado_txt  = "🟢 En curso" if hora_actual >= h_ini else f"⏰ Inicia a las {proxima['hora_inicio']}"
        st.markdown(
            f'<div class="proxima-card">'
            f'<div class="proxima-title">Próxima firma pendiente</div>'
            f'<div class="proxima-nombre">{proxima["nombre_materia"]}</div>'
            f'<span class="materia-meta">{estado_txt} &nbsp;·&nbsp; '
            f'{proxima["hora_inicio"]}–{proxima["hora_fin"]} &nbsp;·&nbsp; '
            f'Com. {proxima["comision"]}</span>'
            f'</div>',
            unsafe_allow_html=True
        )

    # ── Estado materias del día ────────────────────────────────────────────
    st.markdown(
        f'<p class="sec-header">// Clases de Hoy — {dia_es.capitalize()}</p>',
        unsafe_allow_html=True
    )

    if not materias_hoy:
        st.info(f"📅 No hay materias programadas para el {dia_es.capitalize()}.")
    else:
        hora_actual = ahora_dt.time()
        for m in materias_hoy:
            nombre  = m["nombre_materia"]
            firmada = any(e.get("materia") == nombre and e.get("fecha") == hoy for e in log_data)
            h_ini   = datetime.strptime(m["hora_inicio"], "%H:%M").time()
            h_fin   = datetime.strptime(m["hora_fin"],    "%H:%M").time()

            if firmada:
                badge = '<span class="badge badge-ok">✅ Firmada</span>'
            elif h_ini <= hora_actual <= h_fin:
                badge = '<span class="badge badge-info">🔵 En ventana</span>'
            elif hora_actual > h_fin:
                badge = '<span class="badge badge-error">⛔ Vencida</span>'
            else:
                badge = '<span class="badge badge-warn">⏳ Pendiente</span>'

            st.markdown(
                f'<div class="materia-row">'
                f'<div>'
                f'  <div class="materia-nombre">{nombre}</div>'
                f'  <div class="materia-meta">{m["hora_inicio"]}–{m["hora_fin"]} · Com. {m["comision"]}</div>'
                f'</div>'
                f'{badge}'
                f'</div>',
                unsafe_allow_html=True
            )

    # ── Estado del sistema ─────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<p class="sec-header">// Estado del Sistema</p>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        tg_badge = (
            '<span class="badge badge-ok">● Configurado</span>' if telegram_ok
            else '<span class="badge badge-error">● Sin configurar</span>'
        )
        st.markdown(f"**Telegram Bot** &nbsp; {tg_badge}", unsafe_allow_html=True)
    with col2:
        hora_str = ahora_dt.strftime("%H:%M:%S")
        st.markdown(
            f'**Hora actual ART** &nbsp; '
            f'<code style="color:#58a6ff">{hora_str}</code>',
            unsafe_allow_html=True
        )


# ─── Página: Gestión de Materias ──────────────────────────────────────────────

def pagina_materias():
    st.markdown('<p class="sec-header">// Gestión de Materias</p>', unsafe_allow_html=True)

    materias = cargar_json(MATERIAS_FILE, [])

    if materias:
        st.markdown("#### Materias cargadas")
        for i, m in enumerate(materias):
            with st.expander(
                f"📚 {m.get('nombre_materia','?')} — "
                f"{m.get('dia','').capitalize()} "
                f"{m.get('hora_inicio','')}–{m.get('hora_fin','')}"
            ):
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
    st.markdown("#### ➕ Agregar nueva materia")

    with st.form("form_nueva_materia", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            nombre_materia = st.text_input("Nombre de la Materia *",
                placeholder="Ej: Investigación Operativa")
            comision       = st.text_input("Comisión *",
                placeholder="Ej: 401  (texto exacto del formulario)")
            nombre_alumno  = st.text_input("Nombre del Alumno *",
                placeholder="Ej: Chaya, Shakir Lucas  (texto exacto)")
        with col2:
            dia         = st.selectbox("Día *", DIAS_SEMANA)
            hora_inicio = st.time_input("Hora de inicio *",
                value=dt_time(8, 0), step=900)
            hora_fin    = st.time_input("Hora de fin *",
                value=dt_time(10, 0), step=900)
        link = st.text_input("Link del formulario *",
            placeholder="https://forms.cloud.microsoft/...")

        st.caption(
            "⚠️ **Importante:** `Comisión` y `Nombre del Alumno` deben coincidir "
            "**exactamente** con el texto que aparece en el formulario (mayúsculas, comas, etc.)."
        )

        if st.form_submit_button("💾 Guardar materia", use_container_width=True):
            if not all([nombre_materia, comision, nombre_alumno, link]):
                st.error("⚠️ Todos los campos son obligatorios.")
            else:
                nueva = {
                    "nombre_materia": nombre_materia.strip(),
                    "comision":       comision.strip(),
                    "link":           link.strip(),
                    "dia":            normalizar_dia(dia),
                    "hora_inicio":    hora_inicio.strftime("%H:%M"),
                    "hora_fin":       hora_fin.strftime("%H:%M"),
                    "nombre_alumno":  nombre_alumno.strip(),
                }
                materias.append(nueva)
                guardar_json(MATERIAS_FILE, materias)
                st.success(f"✅ '{nombre_materia}' guardada.")
                st.rerun()

    st.markdown("---")
    st.markdown("#### 📋 Editar JSON directamente")
    json_raw = st.text_area(
        "materias.json (edición directa)",
        value=json.dumps(materias, ensure_ascii=False, indent=2),
        height=320,
    )
    if st.button("💾 Guardar JSON"):
        try:
            nuevas = json.loads(json_raw)
            if not isinstance(nuevas, list):
                st.error("El JSON debe ser una lista `[...]`.")
            else:
                guardar_json(MATERIAS_FILE, nuevas)
                st.success("✅ JSON guardado correctamente.")
                st.rerun()
        except json.JSONDecodeError as e:
            st.error(f"JSON inválido: {e}")


# ─── Página: Configuración Telegram ──────────────────────────────────────────

def pagina_telegram():
    st.markdown('<p class="sec-header">// Configuración de Telegram</p>', unsafe_allow_html=True)

    with st.expander("📖 ¿Cómo obtener las credenciales?", expanded=False):
        st.markdown("""
        **Token del Bot:**
        1. Abrir Telegram → buscar **@BotFather** → `/newbot`
        2. Seguir los pasos y copiar el token (formato `123456:ABC...`)

        **Chat ID:**
        1. Buscar **@userinfobot** en Telegram → `/start`
        2. Copiar el número de "Id"

        **En GitHub Actions:**
        → Repositorio → **Settings** → **Secrets and variables** → **Actions**
        → Crear `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID`
        """)

    st.info("🔒 Los valores se guardan en `.env` para uso **local únicamente**. Nunca subas `.env` a GitHub.")

    with st.form("form_telegram"):
        token   = st.text_input(
            "TELEGRAM_TOKEN",
            value=os.environ.get("TELEGRAM_TOKEN", ""),
            type="password",
            placeholder="123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
        )
        chat_id = st.text_input(
            "TELEGRAM_CHAT_ID",
            value=os.environ.get("TELEGRAM_CHAT_ID", ""),
            placeholder="123456789",
        )
        if st.form_submit_button("💾 Guardar en .env", use_container_width=True):
            if token:  guardar_env("TELEGRAM_TOKEN", token)
            if chat_id: guardar_env("TELEGRAM_CHAT_ID", chat_id)
            st.success("✅ Credenciales guardadas en `.env`.")

    st.markdown("---")
    st.markdown("#### 🧪 Test de conexión")
    if st.button("📤 Enviar mensaje de prueba"):
        t  = os.environ.get("TELEGRAM_TOKEN")
        ci = os.environ.get("TELEGRAM_CHAT_ID")
        if not t or not ci:
            st.error("⚠️ Configurá primero el token y el chat ID.")
        else:
            try:
                import httpx
                resp = httpx.post(
                    f"https://api.telegram.org/bot{t}/sendMessage",
                    json={
                        "chat_id":    ci,
                        "text":       "🤖 <b>Test exitoso</b> desde el Panel de Asistencia Pro!\n"
                                      f"🕐 {ahora_art().strftime('%H:%M:%S')} ART",
                        "parse_mode": "HTML",
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                st.success("✅ Mensaje de prueba enviado correctamente.")
            except Exception as e:
                st.error(f"❌ Error: {e}")


# ─── Página: Historial ────────────────────────────────────────────────────────

def pagina_historial():
    st.markdown('<p class="sec-header">// Historial de Asistencias</p>', unsafe_allow_html=True)

    log_data = cargar_json(LOG_FILE, [])

    if not log_data:
        st.info("📭 No hay registros todavía. El bot los genera automáticamente.")
        return

    df = pd.DataFrame(log_data)
    df["fecha"] = pd.to_datetime(df["fecha"])

    # ── Filtros ────────────────────────────────────────────────────────────
    col1, col2 = st.columns([2, 3])
    with col1:
        opts = ["Todas"] + sorted(df["materia"].unique().tolist())
        filtro_materia = st.selectbox("Materia", opts)
    with col2:
        fecha_min = df["fecha"].min().date()
        fecha_max = df["fecha"].max().date()
        rango = st.date_input("Rango de fechas", value=(fecha_min, fecha_max))

    df_f = df.copy()
    if filtro_materia != "Todas":
        df_f = df_f[df_f["materia"] == filtro_materia]
    if isinstance(rango, (list, tuple)) and len(rango) == 2:
        df_f = df_f[(df_f["fecha"].dt.date >= rango[0]) & (df_f["fecha"].dt.date <= rango[1])]

    col_a, col_b, col_c = st.columns([2, 2, 1])
    with col_a:
        st.metric("Registros encontrados", len(df_f))
    with col_b:
        st.metric("Total en log", len(df))
    with col_c:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🗑️ Limpiar log"):
            if st.session_state.get("confirm_clear"):
                guardar_json(LOG_FILE, [])
                st.session_state["confirm_clear"] = False
                st.success("Log limpiado.")
                st.rerun()
            else:
                st.session_state["confirm_clear"] = True
                st.warning("Hacé clic de nuevo para confirmar.")

    st.markdown("---")

    if not df_f.empty:
        cols_show = [c for c in ["fecha", "materia", "comision", "alumno", "hora"] if c in df_f.columns]
        st.dataframe(
            df_f[cols_show].sort_values("fecha", ascending=False).reset_index(drop=True),
            use_container_width=True, hide_index=True,
        )
        csv = df_f.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Descargar CSV", csv,
            file_name=f"asistencias_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )

    if len(df) >= 2:
        st.markdown("---")
        st.markdown("#### 📊 Firmas por materia")
        conteo = df["materia"].value_counts().reset_index()
        conteo.columns = ["Materia", "Firmas"]
        st.bar_chart(conteo.set_index("Materia"))


# ─── App Principal ────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Asistencia Pro",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    aplicar_estilos()

    with st.sidebar:
        st.markdown("# 🎓 Asistencia Pro")
        st.markdown(
            '<p style="color:#6e7681;font-size:.78rem;font-family:\'JetBrains Mono\',monospace">'
            'Set & Forget v2.0</p>',
            unsafe_allow_html=True,
        )
        st.markdown("---")
        hora = ahora_art().strftime("%H:%M:%S")
        dia  = ahora_art().strftime("%A")
        st.markdown(
            f'<p style="color:#58a6ff;font-family:\'JetBrains Mono\',monospace;font-size:.85rem">'
            f'🕐 {hora} ART<br>'
            f'<span style="color:#6e7681;font-size:.75rem">{dia}</span></p>',
            unsafe_allow_html=True,
        )
        st.markdown("---")
        pagina = st.radio(
            "nav", ["📊 Dashboard", "📚 Materias", "💬 Telegram", "📋 Historial"],
            label_visibility="collapsed",
        )
        st.markdown("---")
        st.markdown(
            '<p style="color:#3d444d;font-size:.68rem">'
            'Correr bot localmente:<br>'
            '<code style="color:#79c0ff">python bot.py</code></p>',
            unsafe_allow_html=True,
        )

    if "Dashboard" in pagina:   pagina_dashboard()
    elif "Materias" in pagina:  pagina_materias()
    elif "Telegram" in pagina:  pagina_telegram()
    elif "Historial" in pagina: pagina_historial()


if __name__ == "__main__":
    main()