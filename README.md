# Automation System

Sistema de **automatización web basado en Python**, diseñado para ejecutar tareas programadas mediante un navegador automatizado y gestionar su configuración, ejecución, persistencia y monitoreo.

El proyecto combina **browser automation, ejecución serverless mediante GitHub Actions, configuración basada en JSON, notificaciones externas y un dashboard administrativo desarrollado con Streamlit**.

---

## Tecnologías

* **Python 3**
* **Playwright**
* **Chromium**
* **Streamlit**
* **GitHub Actions**
* **Telegram Bot API**
* JSON
* CSV
* Git / GitHub
* Environment Variables / GitHub Secrets

---

## Arquitectura

```text
automation-system/
├── bot.py
│   └── Motor principal de automatización
│
├── app.py
│   └── Dashboard de administración con Streamlit
│
├── materias.json
│   └── Configuración dinámica de tareas
│
├── log.json
│   └── Persistencia del historial de ejecuciones
│
├── requirements.txt
│   └── Dependencias Python
│
├── .env.example
│   └── Plantilla de configuración
│
└── .github/
    └── workflows/
        └── asistencia.yml
            └── Workflow de ejecución programada
```

---

## Componentes principales

### Browser Automation

El motor principal utiliza **Playwright** para controlar Chromium en modo headless.

El sistema permite:

* Inicializar un navegador automatizado.
* Navegar entre páginas.
* Interactuar con formularios web.
* Seleccionar y completar campos.
* Gestionar formularios multipágina.
* Detectar estados de la interfaz.
* Configurar timeouts.
* Capturar screenshots ante errores.

La automatización se ejecuta de forma programática sin necesidad de interacción manual.

---

### Motor de ejecución

`bot.py` contiene la lógica principal del sistema.

El flujo general es:

```text
Configuración
     │
     ▼
Validación de condiciones
     │
     ▼
Determinación de tareas activas
     │
     ▼
Playwright / Chromium
     │
     ▼
Ejecución de automatización
     │
     ├───────────────┐
     ▼               ▼
  Success           Error
     │               │
     ▼               ▼
Persistencia     Screenshot
     │               │
     └───────┬───────┘
             ▼
       Notificación
```

El motor incorpora:

* Validación de fechas y horarios.
* Prevención de ejecuciones duplicadas.
* Manejo de excepciones.
* Timeouts.
* Reintentos.
* Logging.
* Captura de evidencia ante errores.

---

## Ejecución programada

El proyecto utiliza **GitHub Actions** para ejecutar automáticamente el proceso.

El workflow se encuentra en:

```text
.github/workflows/asistencia.yml
```

La ejecución está basada en un **cron schedule**, permitiendo ejecutar el proceso periódicamente sin mantener un servidor permanentemente activo.

El workflow también puede ejecutarse manualmente mediante `workflow_dispatch`, facilitando tareas de debugging y pruebas.

---

## Configuración dinámica

Las tareas son definidas mediante `materias.json`, evitando modificar el código fuente para cambiar parámetros de ejecución.

Ejemplo:

```json
[
  {
    "nombre_materia": "Sistemas Operativos",
    "comision": "Comisión 01",
    "link": "https://docs.google.com/forms/d/e/FORM_ID/viewform",
    "dia": "lunes",
    "hora_inicio": "18:00",
    "hora_fin": "21:00",
    "nombre_alumno": "Juan Pérez"
  }
]
```

La configuración permite definir:

* Identificador de la tarea.
* Parámetros de selección.
* URL objetivo.
* Día de ejecución.
* Ventana horaria.
* Datos necesarios para completar el formulario.

Esta separación permite mantener la **lógica de negocio independiente de la configuración**.

---

## Dashboard

El proyecto incluye un dashboard desarrollado con **Streamlit**.

```bash
streamlit run app.py
```

Disponible localmente en:

```text
http://localhost:8501
```

El dashboard permite:

* Visualizar el estado de las tareas.
* Crear, editar y eliminar configuraciones.
* Consultar el historial de ejecuciones.
* Filtrar registros.
* Visualizar estadísticas.
* Exportar información a CSV.
* Configurar integraciones de notificación.
* Ejecutar pruebas de conectividad.

---

## Persistencia y logging

El proyecto utiliza archivos JSON para mantener la información necesaria sin depender de una base de datos externa.

### `materias.json`

Contiene la configuración de las tareas automatizadas.

### `log.json`

Mantiene el historial de ejecuciones y permite:

* Registrar ejecuciones exitosas.
* Registrar errores.
* Evitar ejecuciones duplicadas.
* Consultar actividad histórica.

El historial puede visualizarse desde el dashboard y exportarse a CSV.

---

## Notificaciones

El sistema integra la **Telegram Bot API** para enviar notificaciones relacionadas con el estado de las ejecuciones.

Se contemplan diferentes escenarios:

```text
Ejecución exitosa
       ↓
Notificación de éxito

Ejecución fallida
       ↓
Notificación de error
       +
Screenshot para debugging
```

Las credenciales se obtienen mediante variables de entorno y GitHub Secrets.

---

## Manejo de errores

El sistema incorpora mecanismos para facilitar el diagnóstico de fallos:

* Exception handling.
* Timeouts configurables.
* Retry logic.
* Screenshots ante errores.
* Logs de ejecución.
* Notificaciones externas.
* Artefactos generados por GitHub Actions.

En caso de error durante una automatización, el workflow puede conservar la evidencia generada para facilitar el debugging.

---

## Seguridad y configuración

Las credenciales y configuraciones sensibles no forman parte del código fuente.

Se utilizan:

* `.env` para ejecución local.
* `.env.example` como plantilla.
* **GitHub Secrets** para ejecución en Actions.
* `GITHUB_TOKEN` proporcionado por GitHub Actions.

El workflow utiliza únicamente los permisos necesarios para actualizar el historial de ejecución.

---

## Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/ShakirChaya0/automation-system.git
cd automation-system
```

### 2. Crear entorno virtual

```bash
python -m venv .venv
```

Activar en Linux/macOS:

```bash
source .venv/bin/activate
```

Windows:

```bash
.venv\Scripts\activate
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Instalar Chromium

```bash
playwright install chromium
```

Linux:

```bash
playwright install-deps chromium
```

### 5. Configurar variables de entorno

Crear `.env` a partir de `.env.example`:

```bash
cp .env.example .env
```

Configurar las variables requeridas.

---

## Ejecución

### Motor de automatización

```bash
python bot.py
```

### Dashboard

```bash
streamlit run app.py
```

### GitHub Actions

El workflow puede ejecutarse automáticamente mediante el schedule configurado o manualmente utilizando `workflow_dispatch`.

---

## Configuración de GitHub Secrets

Para la ejecución en GitHub Actions se utilizan Secrets para las credenciales de servicios externos.

| Secret             | Descripción                    |
| ------------------ | ------------------------------ |
| `TELEGRAM_TOKEN`   | Token de autenticación del bot |
| `TELEGRAM_CHAT_ID` | Identificador del destinatario |

`GITHUB_TOKEN` es proporcionado automáticamente por GitHub Actions.

---

## Conceptos técnicos aplicados

El proyecto permite trabajar con diferentes conceptos de desarrollo de software:

* **Web Automation**
* Browser Automation
* Headless Browsers
* Python
* Playwright
* Event/Condition-based execution
* Scheduled Jobs
* Cron
* GitHub Actions
* CI/CD automation
* Environment Variables
* GitHub Secrets
* REST/API integrations
* Error Handling
* Retry Logic
* Logging
* JSON persistence
* CSV data export
* Dashboard development
* Streamlit
* External Notifications
* Cloud execution

---

## Flujo de ejecución en GitHub Actions

```text
GitHub Actions
      │
      ▼
Scheduled Workflow
      │
      ▼
Python Environment
      │
      ▼
Load Configuration
      │
      ▼
Validate Active Tasks
      │
      ▼
Playwright + Chromium
      │
      ▼
Execute Automation
      │
      ├───────────────┐
      ▼               ▼
   Success           Error
      │               │
      ▼               ▼
 Update Log       Screenshot
      │               │
      └───────┬───────┘
              ▼
       Telegram API
```

---

## Objetivos técnicos

El proyecto fue desarrollado como una implementación práctica de un sistema de **automatización web ejecutado de forma programada**, con foco en:

* Automatización de tareas repetitivas.
* Ejecución sin infraestructura dedicada.
* Separación entre configuración y lógica.
* Tolerancia a errores.
* Observabilidad de las ejecuciones.
* Integración con servicios externos.
* Administración mediante una interfaz web.
* Automatización de workflows mediante GitHub Actions.
* Manejo seguro de credenciales.

---

## Stack

```text
Python
├── Playwright
├── Streamlit
└── python-dotenv

Automation / Cloud
├── GitHub Actions
├── Cron
└── GitHub Secrets

Integrations
└── Telegram Bot API

Data
├── JSON

└── CSV
```
