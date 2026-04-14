# 🎓 Sistema de Automatización de Asistencia Pro
### *Set & Forget — Firma tu asistencia automáticamente, sin hacer nada*

---

## 📋 Descripción

Bot inteligente que firma tu asistencia en Google Forms automáticamente mediante GitHub Actions. Solo configurás tus materias una vez y el sistema se encarga de todo, con notificaciones por Telegram y registro histórico.

## 🏗️ Arquitectura

```
asistencia-pro/
├── bot.py                          # Motor de automatización principal
├── app.py                          # Panel de control Streamlit (local)
├── materias.json                   # Configuración de materias
├── log.json                        # Historial de asistencias (auto-actualizado)
├── requirements.txt
├── .env.example                    # Plantilla de variables de entorno
├── .gitignore
└── .github/
    └── workflows/
        └── asistencia.yml          # GitHub Actions (cron automático)
```

---

## ⚡ Instalación Rápida

### 1. Clonar y configurar el entorno

```bash
git clone https://github.com/TU_USUARIO/asistencia-pro.git
cd asistencia-pro

python -m venv .venv
source .venv/bin/activate        # Linux/Mac
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env con tus credenciales reales
```

### 3. Agregar tus materias

Editá `materias.json` directamente o usá el panel:

```bash
streamlit run app.py
```

---

## 🔐 Configuración de GitHub Secrets

Ir a tu repositorio → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret | Descripción | Cómo obtenerlo |
|--------|-------------|----------------|
| `TELEGRAM_TOKEN` | Token del bot de Telegram | Hablar con [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_CHAT_ID` | Tu Chat ID personal | Hablar con [@userinfobot](https://t.me/userinfobot) |

> **Nota:** El `GITHUB_TOKEN` se provee automáticamente por GitHub Actions, no necesitás configurarlo.

---

## 📁 Formato de `materias.json`

```json
[
  {
    "nombre_materia": "Sistemas Operativos",
    "comision": "Comisión 01",
    "link": "https://docs.google.com/forms/d/e/ID_DEL_FORM/viewform",
    "dia": "lunes",
    "hora_inicio": "18:00",
    "hora_fin": "21:00",
    "nombre_alumno": "Juan Pérez"
  }
]
```

**Campos:**
- `dia`: `lunes`, `martes`, `miercoles`, `jueves`, `viernes`, `sabado`, `domingo` (sin tildes)
- `hora_inicio` / `hora_fin`: Formato 24hs `HH:MM`. La ventana define cuándo puede firmar.
- `comision` y `nombre_alumno`: Deben coincidir **exactamente** con el texto del formulario.

---

## 🤖 Lógica del Bot

```
┌─ Cron dispara cada 15 min (L-V)
│
├─ Para cada materia en materias.json:
│   ├─ ¿Es el día correcto?          → NO → Skip
│   ├─ ¿Estamos en el horario?       → NO → Skip
│   ├─ ¿Ya firmamos hoy?             → SI → Skip
│   │
│   └─ ✅ Condiciones OK:
│       ├─ Esperar tiempo aleatorio (1-10 min)   ← Comportamiento humano
│       ├─ Abrir Playwright (headless Chromium)
│       ├─ Navegar al formulario
│       ├─ Seleccionar Comisión, Materia, Nombre
│       ├─ Manejar múltiples páginas (botón "Siguiente")
│       └─ Enviar formulario
│
├─ ÉXITO:
│   ├─ Actualizar log.json
│   ├─ git commit + push (log.json)
│   └─ Notificación Telegram: ✅ Asistencia exitosa: [Materia]
│
└─ ERROR:
    ├─ Captura de pantalla (error.png → Artefacto de GitHub)
    └─ Notificación Telegram: ⚠️ Error al firmar [Materia]
```

---

## 📱 Panel de Control (Streamlit)

```bash
streamlit run app.py
# Abre en http://localhost:8501
```

**Funcionalidades:**
- **Dashboard:** KPIs en tiempo real, estado de materias del día
- **Materias:** Agregar, editar y eliminar materias con formulario visual
- **Telegram:** Configurar credenciales y enviar mensaje de prueba
- **Historial:** Tabla filtrable, gráfico de actividad y exportación a CSV

---

## ⏰ Horario del Cron

El workflow corre cada 15 minutos de **lunes a viernes** en el rango horario argentino (07:00-23:00 ART).

El bot internamente verifica si hay una materia activa en ese momento exacto, por lo que es completamente seguro que corra en horarios sin cursada.

---

## 🔧 Ejecución Manual

**Desde GitHub Actions:**
1. Ir al repositorio → **Actions** → **🎓 Firmar Asistencia Automática**
2. **Run workflow** → Opcionalmente activar *Debug mode*

**Local:**
```bash
python bot.py
```

---

## 🛠️ Troubleshooting

| Problema | Solución |
|----------|----------|
| El formulario no se completa | Verificar que `comision` y `nombre_alumno` coincidan exactamente con el texto del form |
| Error de Playwright | Correr `playwright install chromium && playwright install-deps chromium` |
| No llegan notificaciones | Verificar `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` en GitHub Secrets |
| El log no se actualiza | Verificar que `permissions: contents: write` esté en el workflow |
| Timeout en el formulario | Aumentar `PAGE_TIMEOUT` en `bot.py` |

---

## 🔒 Seguridad

- Las credenciales **nunca** se almacenan en el código ni en archivos tracked por Git
- `.env` está en `.gitignore`
- El `GITHUB_TOKEN` se usa con permisos mínimos (`contents: write` únicamente)
- El bot usa User-Agent de Chrome real para evitar detección

---

*Desarrollado con ❤️ · Python + Playwright + GitHub Actions + Streamlit*
