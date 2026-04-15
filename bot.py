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
from datetime import datetime, time as dt_time
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
# (evita esperar más de lo que queda de clase)
MIN_WAIT_SECONDS = 30
MAX_WAIT_SECONDS = 480  # 8 min tope absoluto

# Playwright
PAGE_TIMEOUT    = 30_000   # ms para operaciones normales
NAV_TIMEOUT     = 45_000   # ms para navegación (MS Forms puede tardar)
ELEMENT_TIMEOUT = 8_000    # ms para esperar elementos individuales

# Reintentos ante errores transitorios (red, timeout)
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


# ─── Normalización y coincidencia fuzzy ──────────────────────────────────────

def normalizar_texto(texto: str) -> str:
    """
    Normalización canónica para comparación tolerante:
      - Descompone caracteres Unicode (NFD) y elimina diacríticos (tildes, diéresis).
      - Pasa a minúsculas.
      - Colapsa espacios múltiples.
    Ejemplo: "Administración de Sistemas" → "administracion de sistemas"
    """
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sin_tildes.lower().split())


def _similitud_simple(a: str, b: str) -> float:
    """
    Similitud de bigramas entre dos strings normalizados.
    Devuelve un valor entre 0.0 (nada en común) y 1.0 (idénticos).
    No requiere librerías externas.
    """
    def bigramas(s: str) -> set:
        return {s[i:i+2] for i in range(len(s) - 1)} if len(s) > 1 else {s}

    bg_a = bigramas(a)
    bg_b = bigramas(b)
    if not bg_a or not bg_b:
        return 1.0 if a == b else 0.0
    interseccion = len(bg_a & bg_b)
    return (2.0 * interseccion) / (len(bg_a) + len(bg_b))


def encontrar_mejor_match(texto_buscado: str, candidatos: list[str], umbral: float = 0.60) -> tuple[str | None, float]:
    """
    Dado un texto buscado y una lista de candidatos (leídos del DOM),
    devuelve (mejor_match, score) si supera el umbral, o (None, 0.0).

    Estrategia en capas:
      1. Coincidencia exacta (normalizada) → score 1.0
      2. Uno contiene al otro (normalizado) → score 0.95
      3. Similitud de bigramas → score variable
    """
    norm_buscado = normalizar_texto(texto_buscado)

    mejor_match = None
    mejor_score = 0.0

    for candidato in candidatos:
        norm_candidato = normalizar_texto(candidato)

        # Capa 1: exacto normalizado
        if norm_candidato == norm_buscado:
            log.debug(f"  ✔ Match exacto normalizado: '{candidato}'")
            return candidato, 1.0

        # Capa 2: contención (útil cuando el form agrega "- Comisión 401" al nombre)
        if norm_buscado in norm_candidato or norm_candidato in norm_buscado:
            score = 0.95
            if score > mejor_score:
                mejor_score = score
                mejor_match = candidato

        # Capa 3: bigramas
        score = _similitud_simple(norm_buscado, norm_candidato)
        if score > mejor_score:
            mejor_score = score
            mejor_match = candidato

    if mejor_score >= umbral:
        log.info(
            f"  ✔ Mejor match fuzzy para '{texto_buscado}': "
            f"'{mejor_match}' (score={mejor_score:.2f})"
        )
        return mejor_match, mejor_score

    log.warn(
        f"  ✘ Sin match aceptable para '{texto_buscado}'. "
        f"Mejor fue '{mejor_match}' con score={mejor_score:.2f} (umbral={umbral}). "
        f"Candidatos disponibles: {candidatos}"
    )
    return None, mejor_score


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


def validar_materia(m: dict, idx: int) -> list[str]:
    """Valida los campos requeridos de una entrada de materias.json."""
    errores = []
    campos  = ["nombre_materia", "comision", "link", "dia", "hora_inicio", "hora_fin", "nombre_alumno"]
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
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": mensaje, "parse_mode": "HTML"},
                    files={"photo": foto},
                    timeout=20,
                )
        else:
            resp = httpx.post(
                f"{base}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"},
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
        run(["git", "config", "user.name",  "asistencia-bot"])
        run(["git", "config", "user.email", "bot@asistencia.local"])
        run(["git", "add", str(LOG_FILE)])

        # ¿Hay cambios staged?
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
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


# ─── Automatización Microsoft Forms ───────────────────────────────────────────

def _dump_diagnostico(page) -> None:
    """
    Volcado de diagnóstico completo cuando algo falla.
    Imprime todo lo que hay en el DOM para facilitar el debug,
    incluyendo los valores normalizados para detectar diferencias de tildes/mayúsculas.
    """
    log.trace("═══ INICIO DIAGNÓSTICO DE PÁGINA ═══")
    try:
        url_actual = page.url
        titulo     = page.title()
        log.trace(f"URL actual : {url_actual}")
        log.trace(f"Título     : {titulo}")
    except Exception:
        log.trace("No se pudo obtener URL/título.")

    try:
        # Todos los aria-labels disponibles (opciones de radio/checkbox)
        labels = page.locator("span[aria-label]").all_attribute_values("aria-label")
        labels_limpios = [l for l in labels if l and l.strip()]
        if labels_limpios:
            log.trace(f"aria-labels encontrados ({len(labels_limpios)}):")
            for lbl in labels_limpios:
                norm = normalizar_texto(lbl)
                # Mostrar original Y normalizado para detectar diferencias ocultas
                log.trace(f"  · '{lbl}'  →  norm: '{norm}'")
        else:
            log.trace("No se encontró ningún span[aria-label] en la página.")
    except Exception as e:
        log.trace(f"Error al leer aria-labels: {e}")

    try:
        # Textos visibles de botones
        botones = page.locator("button, [role='button']").all_text_contents()
        botones_limpios = [b.strip() for b in botones if b.strip()]
        if botones_limpios:
            log.trace(f"Botones visibles: {botones_limpios}")
    except Exception:
        pass

    try:
        # Mensajes de error del formulario
        errores_form = page.locator("[data-automation-id='error-message'], .office-form-error").all_text_contents()
        if errores_form:
            log.trace(f"⚠️ Errores del formulario: {errores_form}")
    except Exception:
        pass

    try:
        # Pregunta actual (heading del formulario)
        headings = page.locator("h1, h2, [role='heading']").all_text_contents()
        headings_limpios = [h.strip() for h in headings if h.strip()]
        if headings_limpios:
            log.trace(f"Headings en página: {headings_limpios}")
    except Exception:
        pass

    log.trace("═══ FIN DIAGNÓSTICO ═══")


def _seleccionar_opcion_radio(page, texto: str) -> bool:
    """
    Selecciona una opción en Microsoft Forms con tolerancia a variaciones
    de mayúsculas, tildes y diferencias tipográficas menores.

    Flujo:
      1. Recolecta TODOS los aria-labels visibles del DOM actual.
      2. Busca el mejor match fuzzy contra `texto` (normalizado).
      3. Si lo encuentra, intenta seleccionarlo con múltiples estrategias de selector.
      4. Si el match exacto falla (aria-label cambió), recae en get_by_text fuzzy.

    Retorna True si tuvo éxito, False si no encontró la opción.
    """
    log.trace(f"Buscando opción (fuzzy): '{texto}'")

    # ── Paso 1: leer todos los aria-labels disponibles en el DOM ─────────────
    candidatos: list[str] = []
    try:
        raw = page.locator("span[aria-label]").all_attribute_values("aria-label")
        candidatos = [v for v in raw if v and v.strip()]
    except Exception as e:
        log.debug(f"  No se pudieron leer aria-labels: {e}")

    # También incluir textos visibles de labels y spans (fallback más amplio)
    if not candidatos:
        try:
            raw2 = page.locator("label, span, div[role='radio']").all_text_contents()
            candidatos = [v.strip() for v in raw2 if v and v.strip() and len(v.strip()) > 1]
        except Exception:
            pass

    log.debug(f"  Candidatos en DOM ({len(candidatos)}): {candidatos[:10]}{'...' if len(candidatos) > 10 else ''}")

    # ── Paso 2: encontrar el mejor match ─────────────────────────────────────
    texto_real, score = encontrar_mejor_match(texto, candidatos)

    if texto_real is None:
        # Sin candidatos válidos o score muy bajo — dump de diagnóstico
        log.warn(f"Opción '{texto}' no encontrada con fuzzy matching.")
        _dump_diagnostico(page)
        return False

    # Si el texto_real difiere del buscado, loguear la sustitución
    if texto_real != texto:
        log.info(f"  Sustituyendo '{texto}' → '{texto_real}' (score={score:.2f})")

    # ── Paso 3: intentar seleccionar con el texto_real encontrado ────────────
    estrategias = [
        f"label:has(span[aria-label='{texto_real}'])",
        f"div[aria-label='{texto_real}']",
        f"span[aria-label='{texto_real}']",
        f"span:text-is('{texto_real}')",
        f"label:has-text('{texto_real}')",
    ]

    for i, selector in enumerate(estrategias, 1):
        try:
            elemento = page.locator(selector).first
            elemento.wait_for(state="attached", timeout=ELEMENT_TIMEOUT)

            if not elemento.is_visible():
                log.debug(f"  Estrategia {i}: encontrado pero no visible, haciendo scroll...")
                elemento.scroll_into_view_if_needed()
                page.wait_for_timeout(400)

            elemento.click(timeout=ELEMENT_TIMEOUT)
            page.wait_for_timeout(600)

            # Verificar si quedó seleccionado
            try:
                input_interno = elemento.locator("input")
                marcado = input_interno.is_checked()
                if marcado:
                    log.ok(f"Opción '{texto_real}' seleccionada y verificada (estrategia {i}).")
                else:
                    log.warn(f"Clic en '{texto_real}' OK pero el input no reporta checked.")
                return True
            except Exception:
                log.ok(f"Opción '{texto_real}' clickeada (verificación de checked no disponible).")
                return True

        except PlaywrightTimeoutError:
            log.debug(f"  Estrategia {i} '{selector[:60]}': timeout.")
        except Exception as e:
            log.debug(f"  Estrategia {i} '{selector[:60]}': {type(e).__name__}.")

    # ── Paso 4: fallback — get_by_text con el texto normalizado ──────────────
    log.warn(f"Selectores exactos fallaron para '{texto_real}'. Intentando get_by_text fuzzy...")
    norm = normalizar_texto(texto_real)
    try:
        # Buscar elementos que contengan el texto normalizado (case-insensitive via JS)
        elemento = page.locator(
            f"label, span, div[role='radio'], div[role='option']"
        ).filter(has_text=texto_real).first
        elemento.wait_for(state="attached", timeout=ELEMENT_TIMEOUT)
        elemento.click(timeout=ELEMENT_TIMEOUT)
        page.wait_for_timeout(600)
        log.ok(f"Opción '{texto_real}' clickeada via fallback get_by_text.")
        return True
    except Exception as e:
        log.error(f"Fallback get_by_text también falló para '{texto_real}': {e}")

    _dump_diagnostico(page)
    return False


def _completar_campo_texto(page, texto: str) -> bool:
    """
    Busca campos de texto vacíos y completa el primero disponible.
    Retorna True si completó alguno.
    """
    selectores = [
        "input[type='text']:visible",
        "input[type='search']:visible",
        "textarea:visible",
    ]
    for selector in selectores:
        try:
            inputs = page.locator(selector).all()
            for inp in inputs:
                try:
                    if inp.is_visible() and inp.input_value() == "":
                        inp.fill(texto)
                        log.debug(f"Campo de texto completado con '{texto}'.")
                        page.wait_for_timeout(400)
                        return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


# ─── Excepción específica para formulario cerrado ────────────────────────────

class FormularioCerradoError(Exception):
    """
    Se lanza cuando el formulario ya no acepta respuestas.
    A diferencia de un error de red/timeout, este estado es definitivo:
    no tiene sentido reintentar, y NO debe contar como fallo del bot.
    """


# ─── Mensajes de cierre conocidos (MS Forms, multilenguaje) ──────────────────

_MENSAJES_FORMULARIO_CERRADO = [
    # Español
    "ya no se aceptan respuestas",
    "este formulario ya no acepta",
    "el formulario está cerrado",
    "no se aceptan más respuestas",
    # Inglés (por si el tenant tiene otro idioma)
    "this form is no longer accepting responses",
    "form is closed",
    "no longer accepting responses",
    # Portugués (raro, pero por si acaso)
    "este formulário não está mais aceitando respostas",
]

# Selector exacto del elemento que Microsoft Forms usa para el error
_SELECTOR_ERROR_MSFORMS = (
    "[data-automation-id='errorTitle'],"
    "[data-automation-id='error-title'],"
    ".office-form-closed-message,"
    "[class*='form-closed']"
)


def _verificar_formulario_activo(page, nombre_materia: str) -> None:
    """
    Analiza el DOM recién cargado en busca de indicadores de formulario cerrado.

    Estrategia en dos capas:
      1. Selector estructural: busca el elemento exacto que MS Forms usa
         (`data-automation-id='errorTitle'`). Es el más fiable.
      2. Texto visible: escanea todo el contenido de la página normalizado
         contra los mensajes conocidos. Cubre variantes de idioma y versiones
         futuras del componente.

    Lanza FormularioCerradoError si el formulario no acepta respuestas,
    lo que impide que el bot siga intentando completar campos inexistentes.
    """
    # ── Capa 1: selector estructural ─────────────────────────────────────────
    try:
        error_elem = page.locator(_SELECTOR_ERROR_MSFORMS).first
        if error_elem.is_visible(timeout=3_000):
            texto_error = error_elem.text_content(timeout=2_000) or ""
            raise FormularioCerradoError(
                f"El formulario rechazó la entrada · Mensaje del Form: \"{texto_error.strip()}\""
            )
    except PlaywrightTimeoutError:
        pass  # El selector no existe → formulario activo, seguir
    except FormularioCerradoError:
        raise  # Re-propagar la excepción que acabamos de crear
    except Exception as e:
        log.debug(f"  Verificación estructural: {type(e).__name__} (ignorado)")

    # ── Capa 2: texto visible de la página ───────────────────────────────────
    try:
        texto_pagina = normalizar_texto(page.locator("body").text_content(timeout=3_000) or "")
        for msg in _MENSAJES_FORMULARIO_CERRADO:
            if normalizar_texto(msg) in texto_pagina:
                raise FormularioCerradoError(
                    f"Texto de cierre detectado en página: \"{msg}\""
                )
    except FormularioCerradoError:
        raise
    except Exception as e:
        log.debug(f"  Verificación textual: {type(e).__name__} (ignorado)")

    log.ok(f"Formulario activo y listo para completar: '{nombre_materia}'")


def completar_formulario(page, materia: dict) -> None:
    """
    Navega y completa el formulario de Microsoft Forms.
    Maneja formularios simples y multipágina (botón Siguiente/Next).
    Lanza FormularioCerradoError si el form no acepta respuestas (sin reintentar).
    Lanza RuntimeError ante otros fallos de navegación o envío.
    """
    nombre_materia = materia["nombre_materia"]
    comision       = materia["comision"]
    nombre_alumno  = materia["nombre_alumno"]
    link           = materia["link"]

    log.separador(f"FORMULARIO: {nombre_materia}")
    log.info(f"Navegando → {link}")

    # Cargar la página con timeout extendido
    try:
        page.goto(link, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    except PlaywrightTimeoutError:
        log.warn("Timeout en domcontentloaded, continuando de todas formas...")

    # Espera activa hasta que el formulario sea interactuable
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeoutError:
        log.warn("networkidle no alcanzado en 15s, continuando...")

    # ── VALIDACIÓN TEMPRANA: ¿el form acepta respuestas? ─────────────────────
    # Se ejecuta ANTES de intentar interactuar con cualquier campo.
    # Si el form está cerrado, lanza FormularioCerradoError y se aborta limpiamente.
    _verificar_formulario_activo(page, nombre_materia)

    page.wait_for_timeout(2500)  # Pausa natural post-carga
    log.debug(f"Página cargada. URL: {page.url} | Título: {page.title()}")

    paginas_procesadas = 0
    max_paginas        = 15

    while paginas_procesadas < max_paginas:
        paginas_procesadas += 1
        log.separador(f"Sección {paginas_procesadas}")

        # ── Intentar completar campos ──────────────────────────────────────
        # El orden importa: primero los más específicos
        encontrado_comision = _seleccionar_opcion_radio(page, comision)
        encontrado_materia  = _seleccionar_opcion_radio(page, nombre_materia)
        encontrado_nombre   = _seleccionar_opcion_radio(page, nombre_alumno)
        encontrado_texto    = _completar_campo_texto(page, nombre_alumno)

        log.debug(
            f"Resultados sección {paginas_procesadas}: "
            f"comision={encontrado_comision} | materia={encontrado_materia} | "
            f"nombre_radio={encontrado_nombre} | nombre_texto={encontrado_texto}"
        )

        page.wait_for_timeout(800)

        # ── ¿Hay botón Siguiente? ──────────────────────────────────────────
        selector_siguiente = (
            "button:has-text('Siguiente'), button:has-text('Next'), "
            "[role='button']:has-text('Siguiente'), [role='button']:has-text('Next')"
        )
        siguiente = page.locator(selector_siguiente).first
        try:
            siguiente.wait_for(state="visible", timeout=3000)
            log.info("Botón 'Siguiente' detectado → avanzando sección.")
            siguiente.click()
            page.wait_for_timeout(2000)
            continue
        except PlaywrightTimeoutError:
            pass  # No hay Siguiente, buscar Enviar

        # ── ¿Hay botón Enviar? ────────────────────────────────────────────
        selector_enviar = (
            "button:has-text('Enviar'), button:has-text('Submit'), "
            "[role='button']:has-text('Enviar'), [role='button']:has-text('Submit')"
        )
        enviar = page.locator(selector_enviar).first
        try:
            enviar.wait_for(state="visible", timeout=5000)
            log.info("Botón 'Enviar' detectado → enviando formulario.")
            enviar.click()
            page.wait_for_timeout(3500)

            # Verificar confirmación de envío exitoso
            confirmaciones = [
                "Gracias", "Thank you", "Response recorded",
                "Respuesta registrada", "Se ha enviado", "Your response"
            ]
            for conf in confirmaciones:
                try:
                    if page.locator(f"text={conf}").first.is_visible(timeout=3000):
                        log.ok(f"Confirmación de envío detectada: '{conf}'")
                        return
                except PlaywrightTimeoutError:
                    continue

            log.warn("Formulario enviado pero no se detectó mensaje de confirmación explícita.")
            return

        except PlaywrightTimeoutError:
            log.error("No se encontró ni 'Siguiente' ni 'Enviar'.")
            _dump_diagnostico(page)
            raise RuntimeError(
                f"Sección {paginas_procesadas}: no se encontró botón de navegación. "
                "Revisar el log de diagnóstico arriba."
            )

    raise RuntimeError(f"Límite de {max_paginas} secciones alcanzado sin enviar.")


# ─── Motor Principal ───────────────────────────────────────────────────────────

def procesar_materia_con_retry(materia: dict, registro: list) -> tuple[bool, list]:
    """
    Wrapper con reintentos ante errores transitorios (red, timeout).
    Distingue errores recuperables de errores lógicos (opción no encontrada).
    """
    nombre = materia["nombre_materia"]

    for intento in range(1, MAX_REINTENTOS + 1):
        if intento > 1:
            espera_retry = 45 * intento
            log.warn(f"Reintento {intento}/{MAX_REINTENTOS} en {espera_retry}s...")
            time.sleep(espera_retry)

        exito, registro = _procesar_materia(materia, registro, intento)
        if exito:
            return True, registro

        # Si fue el último intento, no reintentar errores lógicos
        if intento == MAX_REINTENTOS:
            log.error(f"Todos los intentos fallaron para '{nombre}'.")

    return False, registro


def _procesar_materia(materia: dict, registro: list, intento: int = 1) -> tuple[bool, list]:
    """Intento individual de firma."""
    nombre   = materia["nombre_materia"]
    hora_fin = datetime.strptime(materia["hora_fin"], "%H:%M").time()

    # ── Espera humanizada ──────────────────────────────────────────────────
    restantes        = segundos_restantes_en_ventana(hora_fin)
    tope_inteligente = max(MIN_WAIT_SECONDS, min(MAX_WAIT_SECONDS, int(restantes * 0.40)))
    espera           = random.randint(MIN_WAIT_SECONDS, tope_inteligente)

    if restantes < MIN_WAIT_SECONDS + 60:
        log.warn(f"Ventana casi cerrada ({restantes}s restantes). Firmando sin espera.")
        espera = 5

    log.info(
        f"[Intento {intento}] Esperando {espera//60}m {espera%60}s "
        f"(ventana cierra en {restantes//60}m {restantes%60}s)."
    )
    time.sleep(espera)

    # ── Lanzar Playwright ──────────────────────────────────────────────────
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

                # ── ÉXITO ──────────────────────────────────────────────────
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
                # ── FORMULARIO CERRADO — no es un error del bot ────────────
                # El form no acepta respuestas. No reintentar, no capturar
                # screenshot, no marcar el job como fallido.
                log.warn(f"⏸ Formulario cerrado para '{nombre}': {e}")
                enviar_telegram(
                    f"⏸ <b>Formulario cerrado</b>\n"
                    f"📚 {nombre}\n"
                    f"ℹ️ {str(e)}\n"
                    f"🕐 {ahora().strftime('%H:%M')} ART\n"
                    f"<i>No se reintentará hasta la próxima ventana horaria.</i>"
                )
                # Retornar "éxito" para que el retry no se active y el job
                # no quede rojo en GitHub Actions. La asistencia no se firma
                # (correcto: si el form está cerrado, nada que hacer).
                return True, registro

            except Exception as e:
                log.error(f"Error en formulario: {e}")
                traceback.print_exc()

                # Captura de pantalla para el artefacto de GitHub
                screenshot_path = Path(
                    f"error_{ahora().strftime('%H%M%S')}_intento{intento}.png"
                )
                try:
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    # Crear/sobreescribir error.png para el artefacto del workflow
                    page.screenshot(path=str(SCREENSHOT_FILE), full_page=True)
                    log.ok(f"Captura guardada: {screenshot_path}")
                except Exception as se:
                    log.warn(f"No se pudo tomar captura: {se}")

                enviar_telegram(
                    f"⚠️ <b>Error al firmar</b> (intento {intento}/{MAX_REINTENTOS})\n"
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
        raise  # Dejar que suba: ya fue manejado en el bloque interno

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
    log.separador()

    # ── Cargar datos ───────────────────────────────────────────────────────
    materias: list = cargar_json(MATERIAS_FILE, [])
    registro: list = cargar_json(LOG_FILE, [])

    if not materias:
        log.error("materias.json vacío o inexistente. Abortando.")
        sys.exit(1)

    # ── Validar estructura de materias.json ────────────────────────────────
    log.info(f"{len(materias)} materias cargadas. Validando estructura...")
    materias_validas = []
    for idx, m in enumerate(materias):
        errores = validar_materia(m, idx)
        if not errores:
            materias_validas.append(m)
        else:
            log.warn(f"Materia [{idx}] omitida por errores de validación.")
    log.info(f"{len(materias_validas)}/{len(materias)} materias válidas.")

    # ── Evaluar ventana horaria ────────────────────────────────────────────
    ahora_dt    = ahora()
    dia_actual  = dia_semana_actual()
    hora_actual = ahora_dt.time()

    log.separador(f"Evaluando {dia_actual.upper()} {hora_actual.strftime('%H:%M')} ART")

    procesadas    = 0
    hubo_errores  = False

    for materia in materias_validas:
        nombre      = materia["nombre_materia"]
        dia_materia = normalizar_dia(materia.get("dia", ""))

        # ── Filtro por día ─────────────────────────────────────────────────
        if dia_materia != dia_actual:
            log.debug(f"SKIP [{nombre}] — día: {dia_materia} ≠ hoy: {dia_actual}")
            continue

        # ── Filtro por hora ────────────────────────────────────────────────
        h_inicio = datetime.strptime(materia["hora_inicio"], "%H:%M").time()
        h_fin    = datetime.strptime(materia["hora_fin"],    "%H:%M").time()

        if not (h_inicio <= hora_actual <= h_fin):
            log.debug(
                f"SKIP [{nombre}] — fuera de ventana "
                f"({materia['hora_inicio']}–{materia['hora_fin']}, "
                f"ahora {hora_actual.strftime('%H:%M')})"
            )
            continue

        # ── Filtro por duplicado ───────────────────────────────────────────
        if ya_firmado_hoy(registro, nombre):
            continue

        # ── Procesar ───────────────────────────────────────────────────────
        log.separador(f"ACTIVA → {nombre}")
        log.info(f"Ventana: {materia['hora_inicio']}–{materia['hora_fin']} | Alumno: {materia['nombre_alumno']}")
        procesadas += 1

        exito, registro = procesar_materia_con_retry(materia, registro)
        if not exito:
            hubo_errores = True

    # ── Resumen final ──────────────────────────────────────────────────────
    log.separador(f"FIN — {ahora().strftime('%H:%M:%S')}")
    if procesadas == 0:
        log.info("Sin materias activas en este momento. Nada que hacer.")
    else:
        estado = "con errores ❌" if hubo_errores else "exitoso ✅"
        log.info(f"{procesadas} materia(s) procesadas — {estado}.")

    if hubo_errores:
        sys.exit(1)


if __name__ == "__main__":
    main()