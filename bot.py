"""
bot.py - Sistema de Automatización de Asistencia Pro
Automatiza la firma de asistencia en Microsoft Forms con comportamiento
humano, logging detallado, retry inteligente y notificaciones por Telegram.
"""

import json
import os
import random
import subprocess
import sys
import time
import traceback
import unicodedata
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ─── Configuración ────────────────────────────────────────────────────────────

load_dotenv()

TIMEZONE        = ZoneInfo("America/Argentina/Buenos_Aires")
MATERIAS_FILE   = Path("materias.json")
LOG_FILE        = Path("log.json")
SCREENSHOT_FILE = Path("error.png")

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Espera humanizada: mínimo 30s, máximo el 40% del tiempo restante en la ventana
MIN_WAIT_SECONDS = 30
MAX_WAIT_SECONDS = 480  # 8 min tope absoluto

# Ventana de gracia ANTES de hora_inicio (minutos).
# Compensa el delay variable del cron de GitHub Actions (hasta ~10-15 min).
# Si el bot corre a las 11:17 y la clase arranca a las 11:20, igual la procesa.
GRACE_MINUTES = 15

# Playwright
PAGE_TIMEOUT    = 30_000   # ms para operaciones normales
NAV_TIMEOUT     = 45_000   # ms para navegación (MS Forms puede tardar)
ELEMENT_TIMEOUT = 8_000    # ms para esperar elementos individuales

# Reintentos ante errores transitorios dentro del mismo run
MAX_REINTENTOS  = 2


# ─── Logger con timestamps ────────────────────────────────────────────────────

class Logger:
    """Logger simple con niveles y timestamps ART para GitHub Actions."""

    LEVELS = {"DEBUG": "🔍", "INFO": "ℹ️ ", "OK": "✅", "WARN": "⚠️ ", "ERROR": "❌", "TRACE": "🔎"}

    def __init__(self, nombre: str = "BOT"):
        self.nombre = nombre

    def _log(self, nivel: str, msg: str) -> None:
        ts = datetime.now(tz=TIMEZONE).strftime("%H:%M:%S")
        icono = self.LEVELS.get(nivel, "  ")
        print(f"[{ts}] {icono} [{nivel:5}] {msg}", flush=True)

    def debug(self, msg: str) -> None: self._log("DEBUG", msg)
    def info(self,  msg: str) -> None: self._log("INFO",  msg)
    def ok(self,    msg: str) -> None: self._log("OK",    msg)
    def warn(self,  msg: str) -> None: self._log("WARN",  msg)
    def error(self, msg: str) -> None: self._log("ERROR", msg)
    def trace(self, msg: str) -> None: self._log("TRACE", msg)

    def separador(self, titulo: str = "") -> None:
        linea = "─" * 55
        if titulo:
            print(f"\n┌{linea}┐", flush=True)
            print(f"│  {titulo:<53}│", flush=True)
            print(f"└{linea}┘", flush=True)
        else:
            print(f"{'─'*57}", flush=True)


log = Logger()


# ─── Utilidades ───────────────────────────────────────────────────────────────

def cargar_json(path: Path, default=None):
    """Carga un archivo JSON de forma segura con valor por defecto."""
    if default is None:
        default = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        log.debug(f"JSON cargado: {path} ({len(data)} entradas)")
        return data
    except FileNotFoundError:
        log.warn(f"{path} no existe. Usando valor por defecto.")
        return default
    except json.JSONDecodeError as e:
        log.error(f"{path} tiene JSON inválido: {e}")
        return default


def guardar_json(path: Path, data) -> None:
    """Guarda datos en JSON con formato legible."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.ok(f"{path} guardado ({len(data)} entradas).")


def ahora() -> datetime:
    return datetime.now(tz=TIMEZONE)


def normalizar_dia(dia: str) -> str:
    """Elimina tildes y pasa a minúsculas para comparación robusta."""
    tabla = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")
    return dia.lower().translate(tabla)


def dia_semana_actual() -> str:
    nombres = {0: "lunes", 1: "martes", 2: "miercoles",
               3: "jueves", 4: "viernes", 5: "sabado", 6: "domingo"}
    return nombres[ahora().weekday()]


def segundos_restantes_en_ventana(hora_fin: dt_time) -> int:
    """Calcula cuántos segundos faltan para que cierre la ventana horaria."""
    ahora_dt = ahora()
    fin_dt   = ahora_dt.replace(
        hour=hora_fin.hour, minute=hora_fin.minute, second=0, microsecond=0
    )
    delta = (fin_dt - ahora_dt).total_seconds()
    return max(0, int(delta))


def en_ventana(hora_actual: dt_time, h_inicio: dt_time, h_fin: dt_time) -> bool:
    """
    Verifica si hora_actual está dentro de la ventana [h_inicio - GRACE_MINUTES, h_fin].
    La ventana de gracia compensa los delays del cron de GitHub Actions.
    """
    # Calcular inicio con gracia (restar GRACE_MINUTES)
    dt_dummy  = datetime(2000, 1, 1, h_inicio.hour, h_inicio.minute)
    dt_gracia = dt_dummy - timedelta(minutes=GRACE_MINUTES)
    h_inicio_con_gracia = dt_gracia.time()

    return h_inicio_con_gracia <= hora_actual <= h_fin


def validar_materia(m: dict, idx: int) -> list[str]:
    """Valida los campos requeridos de una entrada de materias.json."""
    errores = []
    campos  = ["nombre_materia", "carrera", "comision", "link", "dia",
               "hora_inicio", "hora_fin", "nombre_alumno"]
    for campo in campos:
        if not m.get(campo):
            errores.append(f"campo '{campo}' vacío o ausente")
    for campo_hora in ["hora_inicio", "hora_fin"]:
        valor = m.get(campo_hora, "")
        try:
            datetime.strptime(valor, "%H:%M")
        except ValueError:
            errores.append(f"'{campo_hora}' = '{valor}' no es formato HH:MM")
    if errores:
        log.warn(f"Materia [{idx}] '{m.get('nombre_materia','?')}': {'; '.join(errores)}")
    return errores


# ─── Normalización y coincidencia fuzzy ──────────────────────────────────────

def normalizar_texto(texto: str) -> str:
    """
    Normalización canónica: elimina diacríticos, pasa a minúsculas,
    colapsa espacios múltiples.
    Ejemplo: "Administración de Sistemas" → "administracion de sistemas"
    """
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sin_tildes.lower().split())


def _similitud_bigramas(a: str, b: str) -> float:
    """
    Similitud de bigramas entre dos strings normalizados.
    Devuelve un valor entre 0.0 y 1.0. No requiere librerías externas.
    """
    def bigramas(s: str) -> set:
        return {s[i:i+2] for i in range(len(s) - 1)} if len(s) > 1 else {s}

    bg_a, bg_b = bigramas(a), bigramas(b)
    if not bg_a or not bg_b:
        return 1.0 if a == b else 0.0
    return (2.0 * len(bg_a & bg_b)) / (len(bg_a) + len(bg_b))


def encontrar_mejor_match(
    texto_buscado: str,
    candidatos: list[str],
    umbral: float = 0.60
) -> tuple[str | None, float]:
    """
    Dado un texto buscado y una lista de candidatos leídos del DOM,
    devuelve (mejor_match, score) si supera el umbral, o (None, 0.0).

    Estrategia en capas:
      1. Coincidencia exacta normalizada → score 1.0
      2. Contención: uno está dentro del otro → score 0.95
         (útil cuando el form agrega prefijos como "4K1 - Legislación")
      3. Similitud de bigramas → score variable
    """
    norm_buscado = normalizar_texto(texto_buscado)
    mejor_match  = None
    mejor_score  = 0.0

    for candidato in candidatos:
        norm_cand = normalizar_texto(candidato)

        # Capa 1: exacto normalizado
        if norm_cand == norm_buscado:
            log.debug(f"  ✔ Match exacto: '{candidato}'")
            return candidato, 1.0

        # Capa 2: contención
        if norm_buscado in norm_cand or norm_cand in norm_buscado:
            score = 0.95
        else:
            # Capa 3: bigramas
            score = _similitud_bigramas(norm_buscado, norm_cand)

        if score > mejor_score:
            mejor_score = score
            mejor_match = candidato

    if mejor_score >= umbral:
        log.info(
            f"  ✔ Fuzzy match: '{texto_buscado}' → '{mejor_match}' "
            f"(score={mejor_score:.2f})"
        )
        return mejor_match, mejor_score

    log.warn(
        f"  ✘ Sin match para '{texto_buscado}'. "
        f"Mejor fue '{mejor_match}' con score={mejor_score:.2f} (umbral={umbral}). "
        f"Candidatos disponibles: {candidatos}"
    )
    return None, mejor_score


# ─── Telegram ─────────────────────────────────────────────────────────────────

def enviar_telegram(mensaje: str, foto_path: Path | None = None) -> bool:
    """Envía mensaje (con foto opcional) por Telegram. No lanza excepciones."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warn("Telegram no configurado (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID vacíos).")
        return False

    base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    try:
        if foto_path and foto_path.exists():
            with open(foto_path, "rb") as foto:
                resp = httpx.post(
                    f"{base}/sendPhoto",
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": mensaje,
                          "parse_mode": "HTML"},
                    files={"photo": foto},
                    timeout=20,
                )
        else:
            resp = httpx.post(
                f"{base}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje,
                      "parse_mode": "HTML"},
                timeout=20,
            )
        resp.raise_for_status()
        log.ok(f"Telegram enviado: {mensaje[:70].replace(chr(10),' ')}…")
        return True
    except httpx.HTTPStatusError as e:
        log.error(f"Telegram HTTP {e.response.status_code}: {e.response.text[:200]}")
    except httpx.RequestError as e:
        log.error(f"Telegram red: {type(e).__name__}: {e}")
    return False


# ─── Log de Asistencias ───────────────────────────────────────────────────────

def ya_firmado_hoy(registro: list, nombre_materia: str) -> bool:
    hoy = ahora().strftime("%Y-%m-%d")
    for entrada in registro:
        if entrada.get("materia") == nombre_materia and entrada.get("fecha") == hoy:
            log.info(f"'{nombre_materia}' ya fue firmada hoy ({hoy}). Saltando.")
            return True
    return False


def registrar_asistencia(registro: list, materia: dict) -> list:
    ahora_dt = ahora()
    entrada  = {
        "materia":       materia["nombre_materia"],
        "comision":      materia["comision"],
        "alumno":        materia["nombre_alumno"],
        "fecha":         ahora_dt.strftime("%Y-%m-%d"),
        "hora":          ahora_dt.strftime("%H:%M:%S"),
        "timestamp_iso": ahora_dt.isoformat(),
    }
    registro.append(entrada)
    log.ok(f"Asistencia registrada: {entrada}")
    return registro


# ─── Git Commit & Push ────────────────────────────────────────────────────────

def git_commit_push(mensaje: str = "bot: actualizar log.json") -> bool:
    """Hace commit + push del log.json. Solo activo en GitHub Actions."""
    if not os.environ.get("GITHUB_ACTIONS"):
        log.info("Entorno local: git push omitido.")
        return True

    def run(cmd: list) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)

    try:
        git_name  = os.environ.get("GIT_USER_NAME",  "asistencia-bot")
        git_email = os.environ.get("GIT_USER_EMAIL", "bot@asistencia.local")
        run(["git", "config", "user.name",  git_name])
        run(["git", "config", "user.email", git_email])
        run(["git", "add", str(LOG_FILE)])

        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], capture_output=True
        )
        if diff.returncode == 0:
            log.info("log.json sin cambios. Nada que commitear.")
            return True

        run(["git", "commit", "-m", mensaje])
        run(["git", "push"])
        log.ok("log.json commiteado y pusheado.")
        return True

    except subprocess.CalledProcessError as e:
        log.error(f"Git falló (cmd: {' '.join(e.cmd)}): {e.stderr.strip()}")
        return False


# ─── Excepción específica para formulario cerrado ────────────────────────────

class FormularioCerradoError(Exception):
    """
    Se lanza cuando el formulario no acepta respuestas.
    No es un error del bot — no se reintenta ni se marca el job como fallido.
    """


# ─── Mensajes de cierre conocidos (MS Forms, multilenguaje) ──────────────────

_MENSAJES_FORMULARIO_CERRADO = [
    "ya no se aceptan respuestas",
    "este formulario ya no acepta",
    "el formulario está cerrado",
    "no se aceptan más respuestas",
    "this form is no longer accepting responses",
    "form is closed",
    "no longer accepting responses",
]

_SELECTOR_ERROR_MSFORMS = (
    "[data-automation-id='errorTitle'],"
    "[data-automation-id='error-title'],"
    ".office-form-closed-message,"
    "[class*='form-closed']"
)


# ─── Automatización Microsoft Forms ───────────────────────────────────────────

_RADIO_BASE = "span[data-automation-id='radio']"


def _dump_diagnostico(page) -> None:
    """
    Volcado de diagnóstico completo al fallar.
    Imprime URL, aria-labels disponibles (con versión normalizada),
    botones visibles, errores del formulario y headings.
    """
    log.trace("═══ INICIO DIAGNÓSTICO DE PÁGINA ═══")
    try:
        log.trace(f"URL    : {page.url}")
        log.trace(f"Título : {page.title()}")
    except Exception:
        log.trace("No se pudo obtener URL/título.")

    try:
        labels = page.locator("span[aria-label]").evaluate_all(
            "elements => elements.map(e => e.getAttribute('aria-label'))"
        )
        labels_limpios = [l for l in labels if l and l.strip()]
        if labels_limpios:
            log.trace(f"aria-labels encontrados ({len(labels_limpios)}):")
            for lbl in labels_limpios:
                log.trace(f"  · '{lbl}'  →  norm: '{normalizar_texto(lbl)}'")
        else:
            log.trace("No se encontró ningún span[aria-label].")
    except Exception as e:
        log.trace(f"Error al leer aria-labels: {e}")

    # data-automation-value (fuente primaria de radio buttons)
    try:
        dav = page.locator(_RADIO_BASE).evaluate_all(
            "elements => elements.map(e => e.getAttribute('data-automation-value'))"
        )
        dav_limpios = [v for v in dav if v and v.strip()]
        if dav_limpios:
            log.trace(f"data-automation-value encontrados ({len(dav_limpios)}):")
            for v in dav_limpios:
                log.trace(f"  · '{v}'")
        else:
            log.trace("No se encontró ningún span[data-automation-id='radio'].")
    except Exception as e:
        log.trace(f"Error al leer data-automation-value: {e}")

    try:
        botones = [b.strip() for b in
                   page.locator("button, [role='button']").all_text_contents()
                   if b.strip()]
        if botones:
            log.trace(f"Botones visibles: {botones}")
    except Exception:
        pass

    try:
        errores = page.locator(
            "[data-automation-id='error-message'], .office-form-error"
        ).all_text_contents()
        if errores:
            log.trace(f"Errores del formulario: {errores}")
    except Exception:
        pass

    try:
        headings = [h.strip() for h in
                    page.locator("h1, h2, [role='heading']").all_text_contents()
                    if h.strip()]
        if headings:
            log.trace(f"Headings: {headings}")
    except Exception:
        pass

    log.trace("═══ FIN DIAGNÓSTICO ═══")


def _leer_radios_visibles(page) -> list[str]:
    """
    Lee los valores de todos los radio buttons visibles.
    Fuente primaria: data-automation-value. Fallback: aria-label.

    NOTA: Playwright Python NO tiene all_attribute_values().
    La forma correcta es evaluate_all() con una función JS.
    """
    valores: list[str] = []

    # Fuente primaria: data-automation-value en span[data-automation-id="radio"]
    try:
        raw = page.locator(_RADIO_BASE).evaluate_all(
            "elements => elements.map(e => e.getAttribute('data-automation-value'))"
        )
        valores = [v.strip() for v in raw if v and v.strip()]
    except Exception:
        pass

    # Fallback: aria-label en los spans de texto del label
    if not valores:
        try:
            raw2 = page.locator("span[aria-label]").evaluate_all(
                "elements => elements.map(e => e.getAttribute('aria-label'))"
            )
            valores = [v.strip() for v in raw2 if v and v.strip()]
        except Exception:
            pass

    return valores


def _contar_radios_visibles(page) -> int:
    try:
        return page.locator(_RADIO_BASE).count()
    except Exception:
        return 0


def _esperar_nuevos_radios(page, cuenta_previa: int, timeout_ms: int = 10_000) -> bool:
    """
    Espera hasta que aparezcan MÁS radio buttons que los previos.
    Señal de que el form renderizó la siguiente pregunta.
    """
    intervalo    = 300
    transcurrido = 0
    while transcurrido < timeout_ms:
        if _contar_radios_visibles(page) > cuenta_previa:
            return True
        page.wait_for_timeout(intervalo)
        transcurrido += intervalo
    return False


def _seleccionar_radio(page, texto: str, paso: str) -> None:
    """
    Selecciona un radio button en MS Forms usando fuzzy matching.

    Flujo:
      1. Lee todos los data-automation-value visibles.
      2. Encuentra el mejor match fuzzy contra `texto`.
      3. Intenta click con 4 estrategias de selector en cascada.
      4. Como último recurso: label con texto visible (filtro has_text).

    Lanza RuntimeError si ninguna estrategia funciona.
    """
    log.info(f"  [{paso}] Buscando: '{texto}'")

    candidatos = _leer_radios_visibles(page)
    log.debug(f"    Radios visibles ({len(candidatos)}): {candidatos}")

    if not candidatos:
        _dump_diagnostico(page)
        raise RuntimeError(f"[{paso}] No se encontraron radio buttons en el DOM.")

    texto_real, score = encontrar_mejor_match(texto, candidatos)

    if texto_real is None:
        _dump_diagnostico(page)
        raise RuntimeError(
            f"[{paso}] Sin match para '{texto}'. "
            f"Candidatos disponibles: {candidatos}"
        )

    if texto_real != texto:
        log.info(f"    Fuzzy: '{texto}' → '{texto_real}' (score={score:.2f})")

    # Estrategias principales (en orden de preferencia)
    estrategias = [
        (f"{_RADIO_BASE}[data-automation-value='{texto_real}']",
         "data-automation-value"),
        (f"span[aria-label='{texto_real}']",
         "aria-label"),
        (f"label:has(span[aria-label='{texto_real}'])",
         "label>aria-label"),
        (f"label:has({_RADIO_BASE}[data-automation-value='{texto_real}'])",
         "label>data-value"),
    ]

    for selector, nombre_estrategia in estrategias:
        try:
            elem = page.locator(selector).first
            elem.wait_for(state="attached", timeout=ELEMENT_TIMEOUT)
            if not elem.is_visible():
                elem.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
            elem.click(timeout=ELEMENT_TIMEOUT)
            page.wait_for_timeout(500)

            # Verificar que quedó checked
            try:
                label_parent = page.locator(
                    f"label:has({_RADIO_BASE}"
                    f"[data-automation-value='{texto_real}'])"
                ).first
                inp = label_parent.locator("input[role='radio']").first
                if inp.is_checked():
                    log.ok(
                        f"    [{paso}] '{texto_real}' seleccionado ✔ "
                        f"({nombre_estrategia})"
                    )
                else:
                    log.warn(
                        f"    [{paso}] Click OK pero input no reporta "
                        f"checked ({nombre_estrategia})."
                    )
            except Exception:
                log.ok(
                    f"    [{paso}] '{texto_real}' clickeado "
                    f"({nombre_estrategia}, sin verificar checked)."
                )
            return  # ← Éxito

        except PlaywrightTimeoutError:
            log.debug(f"    Estrategia '{nombre_estrategia}': timeout.")
        except Exception as e:
            log.debug(f"    Estrategia '{nombre_estrategia}': {type(e).__name__}.")

    # ── Estrategia 5 (último recurso): label por texto visible ───────────────
    try:
        elem = page.locator("label").filter(has_text=texto_real).first
        elem.wait_for(state="attached", timeout=ELEMENT_TIMEOUT)
        elem.click(timeout=ELEMENT_TIMEOUT)
        page.wait_for_timeout(500)
        log.ok(f"    [{paso}] '{texto_real}' clickeado vía label fallback.")
        return
    except Exception as e:
        log.debug(f"    Fallback label: {type(e).__name__}.")

    # Ninguna estrategia funcionó
    _dump_diagnostico(page)
    raise RuntimeError(
        f"[{paso}] No se pudo seleccionar '{texto}' (match='{texto_real}'). "
        "Revisá el log de diagnóstico arriba."
    )


def _verificar_formulario_activo(page, nombre_materia: str) -> None:
    """
    Detecta si el formulario está cerrado antes de intentar completarlo.
    Lanza FormularioCerradoError si no acepta respuestas.
    """
    # Capa 1: selector estructural de MS Forms
    try:
        error_elem = page.locator(_SELECTOR_ERROR_MSFORMS).first
        if error_elem.is_visible(timeout=3_000):
            texto_error = error_elem.text_content(timeout=2_000) or ""
            raise FormularioCerradoError(
                f"Mensaje del formulario: \"{texto_error.strip()}\""
            )
    except PlaywrightTimeoutError:
        pass
    except FormularioCerradoError:
        raise
    except Exception as e:
        log.debug(f"  Verificación estructural: {type(e).__name__} (ignorado)")

    # Capa 2: texto visible de la página
    try:
        texto_pagina = normalizar_texto(
            page.locator("body").text_content(timeout=3_000) or ""
        )
        for msg in _MENSAJES_FORMULARIO_CERRADO:
            if normalizar_texto(msg) in texto_pagina:
                raise FormularioCerradoError(
                    f"Texto de cierre detectado: \"{msg}\""
                )
    except FormularioCerradoError:
        raise
    except Exception as e:
        log.debug(f"  Verificación textual: {type(e).__name__} (ignorado)")

    log.ok(f"Formulario activo: '{nombre_materia}'")


def completar_formulario(page, materia: dict) -> None:
    """
    Navega y completa el formulario de Microsoft Forms de forma secuencial.

    El form tiene 4 preguntas encadenadas — cada una aparece solo después
    de responder la anterior:

        Paso 1 · Carrera   → habilita ↓
        Paso 2 · Comisión  → habilita ↓
        Paso 3 · Materia   → habilita ↓
        Paso 4 · Alumno    → habilita ↓
        Paso 5 · Enviar

    Lanza FormularioCerradoError si el form no acepta respuestas.
    Lanza RuntimeError ante fallos de navegación o selección.
    """
    nombre_materia = materia["nombre_materia"]
    carrera        = materia["carrera"]
    comision       = materia["comision"]
    nombre_alumno  = materia["nombre_alumno"]
    link           = materia["link"]

    log.separador(f"FORMULARIO: {nombre_materia}")
    log.info(f"Navegando → {link}")

    # ── 0. Cargar página ──────────────────────────────────────────────────────
    try:
        page.goto(link, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    except PlaywrightTimeoutError:
        log.warn("Timeout en domcontentloaded, continuando...")

    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeoutError:
        log.warn("networkidle no alcanzado en 15s, continuando...")

    _verificar_formulario_activo(page, nombre_materia)
    page.wait_for_timeout(1_500)
    log.debug(f"Página lista. URL: {page.url} | Título: {page.title()}")

    # ── Paso 1: Carrera ───────────────────────────────────────────────────────
    log.separador("Paso 1 · Carrera")

    # Esperar a que el primer radio sea visible Y tenga su atributo cargado.
    # Se usan dos condiciones: visible en DOM + evaluate_all devuelve al menos 1 valor.
    try:
        page.locator(_RADIO_BASE).first.wait_for(state="visible", timeout=12_000)
    except PlaywrightTimeoutError:
        _dump_diagnostico(page)
        raise RuntimeError("Paso 1: no aparecieron radio buttons al cargar el form.")

    # Pequeña pausa extra para que el JS del form termine de poblar los atributos
    page.wait_for_timeout(600)

    radios_antes = _contar_radios_visibles(page)
    _seleccionar_radio(page, carrera, "Carrera")

    # ── Paso 2: Comisión ──────────────────────────────────────────────────────
    # Nota: el JSON guarda "401" pero el form puede mostrar "Comisión 401".
    # El fuzzy matching por contención lo resuelve automáticamente.
    log.separador("Paso 2 · Comisión")
    if not _esperar_nuevos_radios(page, radios_antes):
        _dump_diagnostico(page)
        raise RuntimeError("Paso 2: la pregunta de Comisión no apareció.")

    radios_antes = _contar_radios_visibles(page)
    _seleccionar_radio(page, comision, "Comisión")

    # ── Paso 3: Materia ───────────────────────────────────────────────────────
    # El form puede mostrar prefijos de plan: "4K1 - Legislación".
    # El matching por contención encuentra "Legislación" dentro de ese texto.
    log.separador("Paso 3 · Materia")
    if not _esperar_nuevos_radios(page, radios_antes):
        _dump_diagnostico(page)
        raise RuntimeError("Paso 3: la pregunta de Materia no apareció.")

    radios_antes = _contar_radios_visibles(page)
    _seleccionar_radio(page, nombre_materia, "Materia")

    # ── Paso 4: Alumno ────────────────────────────────────────────────────────
    log.separador("Paso 4 · Alumno")
    if not _esperar_nuevos_radios(page, radios_antes):
        _dump_diagnostico(page)
        raise RuntimeError("Paso 4: la lista de alumnos no apareció.")

    _seleccionar_radio(page, nombre_alumno, "Alumno")

    # ── Paso 5: Enviar ────────────────────────────────────────────────────────
    log.separador("Paso 5 · Enviar")
    page.wait_for_timeout(800)

    selector_submit = (
        "[data-automation-id='submitButton'], "
        "button:has-text('Enviar'), "
        "button:has-text('Submit')"
    )
    enviar = page.locator(selector_submit).first
    try:
        enviar.wait_for(state="visible", timeout=8_000)
    except PlaywrightTimeoutError:
        _dump_diagnostico(page)
        raise RuntimeError(
            "Paso 5: el botón Enviar no apareció. "
            "Puede que falte completar algún campo anterior."
        )

    log.info("  Botón Enviar encontrado → haciendo clic...")
    enviar.click()
    page.wait_for_timeout(3_500)

    # Verificar confirmación
    confirmaciones = [
        "Gracias", "Thank you", "Response recorded",
        "Respuesta registrada", "Se ha enviado", "Your response",
        "Formulario enviado", "form submitted",
    ]
    for conf in confirmaciones:
        try:
            if page.locator(f"text={conf}").first.is_visible(timeout=2_500):
                log.ok(f"  Confirmación detectada: '{conf}' ✅")
                return
        except PlaywrightTimeoutError:
            continue

    log.warn("  Formulario enviado (sin texto de confirmación explícito — asumir OK).")


# ─── Motor Principal ───────────────────────────────────────────────────────────

def procesar_materia_con_retry(materia: dict, registro: list) -> tuple[bool, list]:
    """
    Wrapper con reintentos ante errores transitorios.
    - FormularioCerradoError: no reintenta (el form está cerrado, es normal).
    - Otros errores: reintenta hasta MAX_REINTENTOS veces.
    """
    nombre = materia["nombre_materia"]

    for intento in range(1, MAX_REINTENTOS + 1):
        if intento > 1:
            espera_retry = 45 * intento
            log.warn(
                f"Reintento {intento}/{MAX_REINTENTOS} para '{nombre}' "
                f"en {espera_retry}s..."
            )
            time.sleep(espera_retry)

        exito, registro = _procesar_materia(materia, registro, intento)
        if exito:
            return True, registro

        if intento == MAX_REINTENTOS:
            log.error(f"Todos los intentos fallaron para '{nombre}'.")

    return False, registro


def _procesar_materia(materia: dict, registro: list, intento: int = 1) -> tuple[bool, list]:
    """Intento individual de firma."""
    nombre   = materia["nombre_materia"]
    hora_fin = datetime.strptime(materia["hora_fin"], "%H:%M").time()

    # ── Espera humanizada ──────────────────────────────────────────────────────
    restantes        = segundos_restantes_en_ventana(hora_fin)
    tope_inteligente = max(MIN_WAIT_SECONDS, min(MAX_WAIT_SECONDS, int(restantes * 0.40)))
    espera           = random.randint(MIN_WAIT_SECONDS, tope_inteligente)

    if restantes < MIN_WAIT_SECONDS + 60:
        log.warn(f"Ventana casi cerrada ({restantes}s). Firmando sin espera.")
        espera = 5

    log.info(
        f"[Intento {intento}] Esperando {espera//60}m {espera%60}s "
        f"(ventana cierra en {restantes//60}m {restantes%60}s)."
    )
    time.sleep(espera)

    # ── Lanzar Playwright ──────────────────────────────────────────────────────
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1366, "height": 768},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="es-AR",
            )
            page = context.new_page()
            page.set_default_timeout(PAGE_TIMEOUT)

            try:
                completar_formulario(page, materia)

                # ── ÉXITO ──────────────────────────────────────────────────────
                registro = registrar_asistencia(registro, materia)
                guardar_json(LOG_FILE, registro)
                git_commit_push(f"bot: asistencia firmada — {nombre}")
                enviar_telegram(
                    f"✅ <b>Asistencia firmada</b>\n"
                    f"📚 {nombre}\n"
                    f"👤 {materia['nombre_alumno']}\n"
                    f"🕐 {ahora().strftime('%H:%M')} ART"
                )
                return True, registro

            except FormularioCerradoError as e:
                # El form está cerrado — no es un error del bot
                log.warn(f"⏸ Formulario cerrado: '{nombre}': {e}")
                enviar_telegram(
                    f"⏸ <b>Formulario cerrado</b>\n"
                    f"📚 {nombre}\n"
                    f"ℹ️ {str(e)}\n"
                    f"🕐 {ahora().strftime('%H:%M')} ART\n"
                    f"<i>No se reintentará en esta ventana.</i>"
                )
                # Retorna True para no activar retry ni marcar el job rojo
                return True, registro

            except Exception as e:
                log.error(f"Error en formulario: {e}")
                traceback.print_exc()

                screenshot_path = Path(
                    f"error_{ahora().strftime('%H%M%S')}_intento{intento}.png"
                )
                try:
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    page.screenshot(path=str(SCREENSHOT_FILE), full_page=True)
                    log.ok(f"Captura guardada: {screenshot_path}")
                except Exception as se:
                    log.warn(f"No se pudo tomar captura: {se}")

                enviar_telegram(
                    f"⚠️ <b>Error al firmar</b> "
                    f"(intento {intento}/{MAX_REINTENTOS})\n"
                    f"📚 {nombre}\n"
                    f"🔍 Revisar logs de GitHub Actions\n"
                    f"<code>{str(e)[:250]}</code>",
                    foto_path=screenshot_path,
                )
                return False, registro

            finally:
                context.close()
                browser.close()

    except FormularioCerradoError:
        raise

    except Exception as e:
        log.error(f"Error crítico de Playwright: {type(e).__name__}: {e}")
        traceback.print_exc()
        enviar_telegram(
            f"🔴 <b>Error crítico del bot</b>\n"
            f"📚 {nombre} (intento {intento})\n"
            f"<code>{type(e).__name__}: {str(e)[:200]}</code>"
        )
        return False, registro


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.separador(f"ASISTENCIA BOT — {ahora().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    log.info(f"Python {sys.version.split()[0]} | PID {os.getpid()}")
    log.info(f"Entorno: {'GitHub Actions' if os.environ.get('GITHUB_ACTIONS') else 'Local'}")
    log.info(f"Ventana de gracia: {GRACE_MINUTES} min antes de hora_inicio")
    log.separador()

    materias: list = cargar_json(MATERIAS_FILE, [])
    registro: list = cargar_json(LOG_FILE, [])

    if not materias:
        log.error("materias.json vacío o inexistente. Abortando.")
        sys.exit(1)

    # Validar estructura
    log.info(f"{len(materias)} materias cargadas. Validando...")
    materias_validas = []
    for idx, m in enumerate(materias):
        if not validar_materia(m, idx):
            materias_validas.append(m)
        else:
            log.warn(f"Materia [{idx}] omitida por errores de validación.")
    log.info(f"{len(materias_validas)}/{len(materias)} materias válidas.")

    ahora_dt    = ahora()
    dia_actual  = dia_semana_actual()
    hora_actual = ahora_dt.time()

    log.separador(f"Evaluando {dia_actual.upper()} {hora_actual.strftime('%H:%M')} ART")

    procesadas   = 0
    hubo_errores = False

    for materia in materias_validas:
        nombre      = materia["nombre_materia"]
        dia_materia = normalizar_dia(materia.get("dia", ""))

        # Filtro por día
        if dia_materia != dia_actual:
            log.debug(f"SKIP [{nombre}] — día {dia_materia} ≠ hoy {dia_actual}")
            continue

        # Filtro por ventana horaria (con gracia)
        h_inicio = datetime.strptime(materia["hora_inicio"], "%H:%M").time()
        h_fin    = datetime.strptime(materia["hora_fin"],    "%H:%M").time()

        if not en_ventana(hora_actual, h_inicio, h_fin):
            # Calcular cuándo abre la ventana con gracia para informar
            dt_dummy  = datetime(2000, 1, 1, h_inicio.hour, h_inicio.minute)
            dt_gracia = dt_dummy - timedelta(minutes=GRACE_MINUTES)
            log.debug(
                f"SKIP [{nombre}] — fuera de ventana "
                f"(ventana con gracia: {dt_gracia.strftime('%H:%M')}–"
                f"{materia['hora_fin']}, ahora: {hora_actual.strftime('%H:%M')})"
            )
            continue

        # Filtro por duplicado
        if ya_firmado_hoy(registro, nombre):
            continue

        # Procesar
        log.separador(f"ACTIVA → {nombre}")
        log.info(
            f"Ventana: {materia['hora_inicio']}–{materia['hora_fin']} "
            f"(gracia desde {(datetime(2000,1,1,h_inicio.hour,h_inicio.minute)-timedelta(minutes=GRACE_MINUTES)).strftime('%H:%M')}) "
            f"| Alumno: {materia['nombre_alumno']}"
        )
        procesadas += 1

        exito, registro = procesar_materia_con_retry(materia, registro)
        if not exito:
            hubo_errores = True

    log.separador(f"FIN — {ahora().strftime('%H:%M:%S')}")
    if procesadas == 0:
        log.info("Sin materias activas en este momento.")
    else:
        log.info(
            f"{procesadas} materia(s) procesadas — "
            f"{'con errores ❌' if hubo_errores else 'exitoso ✅'}."
        )

    if hubo_errores:
        sys.exit(1)


if __name__ == "__main__":
    main()