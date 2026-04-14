"""
bot.py - Sistema de Automatización de Asistencia Pro
Autor: Set & Forget Attendance Bot
Descripción: Automatiza la firma de asistencia en Google Forms con comportamiento
             humano, gestión de errores y notificaciones por Telegram.
"""

import json
import os
import random
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ─── Configuración ────────────────────────────────────────────────────────────

load_dotenv()  # No hace nada en GitHub Actions (usa os.environ directo)

TIMEZONE        = ZoneInfo("America/Argentina/Buenos_Aires")
MATERIAS_FILE   = Path("materias.json")
LOG_FILE        = Path("log.json")
SCREENSHOT_FILE = Path("error.png")

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
GITHUB_TOKEN     = os.environ.get("GITHUB_TOKEN", "")

# Espera aleatoria entre 1 y 10 minutos (en segundos)
MIN_WAIT_SECONDS = 60
MAX_WAIT_SECONDS = 600

# Timeout de Playwright en ms
PAGE_TIMEOUT = 30_000


# ─── Utilidades ───────────────────────────────────────────────────────────────

def cargar_json(path: Path) -> list | dict:
    """Carga un archivo JSON de forma segura."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[WARN] No se pudo leer {path}: {e}. Usando valor por defecto.")
        return [] if path == LOG_FILE else {}


def guardar_json(path: Path, data) -> None:
    """Guarda datos en un archivo JSON con formato legible."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[OK] {path} actualizado.")


def ahora() -> datetime:
    """Retorna la hora actual en la zona horaria de Argentina."""
    return datetime.now(tz=TIMEZONE)


def normalizar_dia(dia: str) -> str:
    """Normaliza el nombre del día eliminando tildes y pasando a minúsculas."""
    reemplazos = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "Á": "a", "É": "e", "Í": "i", "Ó": "o", "Ú": "u",
    }
    dia = dia.lower()
    for orig, rep in reemplazos.items():
        dia = dia.replace(orig, rep)
    return dia


def dia_semana_actual() -> str:
    """Retorna el nombre del día de la semana actual en español (sin tildes)."""
    dias = {
        0: "lunes",
        1: "martes",
        2: "miercoles",
        3: "jueves",
        4: "viernes",
        5: "sabado",
        6: "domingo",
    }
    return dias[ahora().weekday()]


# ─── Telegram ─────────────────────────────────────────────────────────────────

def enviar_telegram(mensaje: str, foto_path: Path | None = None) -> bool:
    """
    Envía un mensaje (y opcionalmente una foto) por Telegram.
    Retorna True si tuvo éxito, False si falló.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram no configurado. Saltando notificación.")
        return False

    base_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

    try:
        if foto_path and foto_path.exists():
            url = f"{base_url}/sendPhoto"
            with open(foto_path, "rb") as foto:
                resp = httpx.post(
                    url,
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": mensaje},
                    files={"photo": foto},
                    timeout=15,
                )
        else:
            url = f"{base_url}/sendMessage"
            resp = httpx.post(
                url,
                json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"},
                timeout=15,
            )

        resp.raise_for_status()
        print(f"[OK] Notificación Telegram enviada: {mensaje[:60]}...")
        return True

    except Exception as e:
        print(f"[ERROR] Fallo al enviar Telegram: {e}")
        return False


# ─── Log de Asistencias ───────────────────────────────────────────────────────

def ya_firmado_hoy(log: list, nombre_materia: str) -> bool:
    """
    Verifica si ya existe una firma exitosa para la materia en el día de hoy.
    """
    hoy = ahora().strftime("%Y-%m-%d")
    for entrada in log:
        if entrada.get("materia") == nombre_materia and entrada.get("fecha") == hoy:
            print(f"[SKIP] '{nombre_materia}' ya fue firmada hoy ({hoy}).")
            return True
    return False


def registrar_asistencia(log: list, materia: dict) -> list:
    """Agrega una entrada exitosa al log de asistencias."""
    ahora_dt = ahora()
    nueva_entrada = {
        "materia": materia["nombre_materia"],
        "comision": materia["comision"],
        "alumno": materia["nombre_alumno"],
        "fecha": ahora_dt.strftime("%Y-%m-%d"),
        "hora": ahora_dt.strftime("%H:%M:%S"),
        "timestamp_iso": ahora_dt.isoformat(),
    }
    log.append(nueva_entrada)
    print(f"[LOG] Registrado: {nueva_entrada}")
    return log


# ─── Git Commit & Push ────────────────────────────────────────────────────────

def git_commit_push(mensaje: str = "bot: actualizar log.json de asistencias") -> bool:
    """
    Realiza commit y push del log.json usando el GITHUB_TOKEN.
    Solo se ejecuta en entorno CI (GitHub Actions).
    """
    if not os.environ.get("GITHUB_ACTIONS"):
        print("[INFO] No estamos en GitHub Actions. Saltando git push.")
        return True

    try:
        subprocess.run(
            ["git", "config", "user.name", "asistencia-bot"],
            check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "bot@asistencia.local"],
            check=True, capture_output=True
        )
        subprocess.run(
            ["git", "add", str(LOG_FILE)],
            check=True, capture_output=True
        )

        # Verificar si hay cambios para commitear
        status = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True
        )
        if status.returncode == 0:
            print("[INFO] No hay cambios en log.json para commitear.")
            return True

        subprocess.run(
            ["git", "commit", "-m", mensaje],
            check=True, capture_output=True
        )
        subprocess.run(
            ["git", "push"],
            check=True, capture_output=True
        )
        print("[OK] log.json commiteado y pusheado al repositorio.")
        return True

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Git falló: {e.stderr.decode()}")
        return False


# ─── Automatización Playwright ────────────────────────────────────────────────

def completar_formulario(page, materia: dict) -> None:
    """
    Navega y completa el formulario de Google Forms.
    Maneja formularios simples y con múltiples secciones (botón 'Siguiente').
    """
    nombre_materia = materia["nombre_materia"]
    comision       = materia["comision"]
    nombre_alumno  = materia["nombre_alumno"]
    link           = materia["link"]

    print(f"[BOT] Navegando a: {link}")
    page.goto(link, wait_until="networkidle", timeout=PAGE_TIMEOUT)
    page.wait_for_timeout(2000)  # Pausa natural al cargar

    pagina_actual = 1
    max_paginas   = 10  # Límite de seguridad para no bucle infinito

    while pagina_actual <= max_paginas:
        print(f"[BOT] Procesando página {pagina_actual} del formulario...")

        # ── Intentar seleccionar Comisión ──────────────────────────────────
        try:
            _seleccionar_opcion_radio(page, comision)
        except Exception:
            pass  # No todas las páginas tienen este campo

        # ── Intentar seleccionar Materia ───────────────────────────────────
        try:
            _seleccionar_opcion_radio(page, nombre_materia)
        except Exception:
            pass

        # ── Intentar seleccionar Nombre ────────────────────────────────────
        try:
            _seleccionar_opcion_radio(page, nombre_alumno)
        except Exception:
            pass

        # ── Intentar completar campos de texto con el nombre ───────────────
        try:
            _completar_campo_texto(page, nombre_alumno)
        except Exception:
            pass

        # ── Verificar si existe botón 'Siguiente' ──────────────────────────
        boton_siguiente = page.locator(
            "//div[@role='button'][contains(., 'Siguiente') or contains(., 'Next')]"
        ).first

        if boton_siguiente.is_visible(timeout=3000):
            print("[BOT] Botón 'Siguiente' encontrado. Avanzando sección...")
            boton_siguiente.click()
            page.wait_for_timeout(1500)
            pagina_actual += 1
            continue

        # ── Buscar y clickear botón 'Enviar' ──────────────────────────────
        boton_enviar = page.locator(
            "//div[@role='button'][contains(., 'Enviar') or contains(., 'Submit')]"
        ).first

        if boton_enviar.is_visible(timeout=5000):
            print("[BOT] Botón 'Enviar' encontrado. Enviando formulario...")
            boton_enviar.click()
            page.wait_for_timeout(3000)
            print("[BOT] Formulario enviado exitosamente.")
            return
        else:
            raise RuntimeError(
                "No se encontró ni 'Siguiente' ni 'Enviar'. "
                "Verificar estructura del formulario."
            )

    raise RuntimeError(f"Se alcanzó el límite de {max_paginas} páginas sin enviar.")


def _seleccionar_opcion_radio(page, texto: str) -> None:
    """
    Busca y selecciona un radio button o checkbox cuya etiqueta
    contenga el texto exacto especificado.
    """
    selector = (
        f"//div[@role='radio' or @role='checkbox']"
        f"[.//span[normalize-space(text())='{texto}']]"
    )
    elemento = page.locator(selector).first
    if elemento.is_visible(timeout=3000):
        elemento.click()
        print(f"[BOT] Opción seleccionada: '{texto}'")
        page.wait_for_timeout(500)
    else:
        raise ValueError(f"Opción no encontrada: '{texto}'")


def _completar_campo_texto(page, texto: str) -> None:
    """
    Busca campos de texto (input/textarea) visibles y vacíos,
    y los completa con el texto dado.
    """
    inputs = page.locator("input[type='text']:visible, textarea:visible").all()
    for inp in inputs:
        try:
            if inp.input_value() == "":
                inp.fill(texto)
                print(f"[BOT] Campo de texto completado con: '{texto}'")
                page.wait_for_timeout(300)
                break
        except Exception:
            continue


# ─── Motor Principal ───────────────────────────────────────────────────────────

def procesar_materia(materia: dict, log: list) -> tuple[bool, list]:
    """
    Intenta firmar la asistencia para una materia específica.
    Retorna (éxito: bool, log_actualizado: list).
    """
    nombre = materia["nombre_materia"]

    # Verificar si ya fue firmada hoy
    if ya_firmado_hoy(log, nombre):
        return True, log  # No es un error, simplemente ya está hecha

    # Espera aleatoria humanizada
    espera = random.randint(MIN_WAIT_SECONDS, MAX_WAIT_SECONDS)
    print(f"[BOT] Esperando {espera // 60}m {espera % 60}s antes de firmar '{nombre}'...")
    time.sleep(espera)

    # Lanzar Playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.set_default_timeout(PAGE_TIMEOUT)

            try:
                completar_formulario(page, materia)

                # ── ÉXITO ──────────────────────────────────────────────────
                log = registrar_asistencia(log, materia)
                guardar_json(LOG_FILE, log)
                git_commit_push(f"bot: asistencia firmada - {nombre}")
                enviar_telegram(f"✅ Asistencia exitosa: <b>{nombre}</b>\n👤 {materia['nombre_alumno']}")
                return True, log

            except Exception as e:
                # ── ERROR: captura de pantalla ─────────────────────────────
                print(f"[ERROR] Fallo al procesar '{nombre}': {e}")
                traceback.print_exc()
                try:
                    page.screenshot(path=str(SCREENSHOT_FILE), full_page=True)
                    print(f"[BOT] Captura guardada en {SCREENSHOT_FILE}")
                except Exception as se:
                    print(f"[WARN] No se pudo tomar captura: {se}")

                enviar_telegram(
                    f"⚠️ Error al firmar <b>{nombre}</b>\n"
                    f"🔍 Revisar logs de GitHub Actions\n"
                    f"<code>{str(e)[:200]}</code>",
                    foto_path=SCREENSHOT_FILE,
                )
                return False, log

            finally:
                context.close()
                browser.close()

    except Exception as e:
        print(f"[ERROR CRÍTICO] Playwright falló: {e}")
        traceback.print_exc()
        enviar_telegram(
            f"🔴 Error crítico en el bot\n"
            f"Materia: <b>{nombre}</b>\n"
            f"<code>{str(e)[:200]}</code>"
        )
        return False, log


def main():
    """Punto de entrada principal del bot."""
    print("=" * 60)
    print(f"[BOT] Iniciando — {ahora().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("=" * 60)

    # Cargar datos
    materias: list = cargar_json(MATERIAS_FILE)
    log: list      = cargar_json(LOG_FILE)

    if not materias:
        print("[ERROR] materias.json está vacío o no existe. Abortando.")
        sys.exit(1)

    ahora_dt      = ahora()
    dia_actual    = dia_semana_actual()
    hora_actual   = ahora_dt.time()
    hubo_trabajos = False
    hubo_errores  = False

    for materia in materias:
        nombre = materia.get("nombre_materia", "Desconocida")

        # ── Validar día ────────────────────────────────────────────────────
        dia_materia = normalizar_dia(materia.get("dia", ""))
        if dia_materia != dia_actual:
            print(f"[SKIP] '{nombre}' no es hoy (hoy={dia_actual}, materia={dia_materia}).")
            continue

        # ── Validar ventana horaria ────────────────────────────────────────
        try:
            h_inicio = datetime.strptime(materia["hora_inicio"], "%H:%M").time()
            h_fin    = datetime.strptime(materia["hora_fin"],    "%H:%M").time()
        except (KeyError, ValueError) as e:
            print(f"[ERROR] Formato de hora inválido en '{nombre}': {e}")
            continue

        if not (h_inicio <= hora_actual <= h_fin):
            print(
                f"[SKIP] '{nombre}' fuera de horario "
                f"(ahora={hora_actual.strftime('%H:%M')}, "
                f"ventana={materia['hora_inicio']}-{materia['hora_fin']})."
            )
            continue

        print(f"\n[BOT] 🎯 Materia en ventana: '{nombre}' — procesando...")
        hubo_trabajos = True
        exito, log = procesar_materia(materia, log)

        if not exito:
            hubo_errores = True

    if not hubo_trabajos:
        print("\n[BOT] Sin materias activas en este momento. Nada que hacer.")

    print("\n" + "=" * 60)
    print(f"[BOT] Finalizado — {ahora().strftime('%H:%M:%S')}")
    print("=" * 60)

    # Salir con código de error si hubo fallos (GitHub Actions lo detecta)
    if hubo_errores:
        sys.exit(1)


if __name__ == "__main__":
    main()
