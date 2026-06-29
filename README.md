# TEFIIS Admin — Panel de Administración FIIS UNI

Panel de gestión de reclamos, malla curricular y datos académicos de estudiantes de la FIIS-UNI. Construido con React + Vite + Supabase.

---

## Arquitectura general del sistema

```
Formulario Estudiante (app móvil/web)
        │
        ▼
 tefiis-m2 (FastAPI + PostgreSQL)   ──►  Supabase (tabla reclamos)
                                               │
                                               ▼
                                    Panel Admin (este repo)
                                    React + Vite + Firebase Auth
```

---

## Requisitos previos

| Herramienta | Versión mínima |
|-------------|----------------|
| Node.js     | 18+            |
| npm         | 9+             |
| Python      | 3.10+          |
| Docker + Docker Compose | cualquiera |
| Cuenta Firebase | —          |
| Proyecto Supabase | —        |

---

## PARTE 1 — Panel Admin (este repo)

### 1.1 Clonar e instalar dependencias

```bash
git clone https://github.com/Christopher-Albino/Tefiis_Admin.git
cd Tefiis_Admin
npm install
```

### 1.2 Crear el archivo `.env`

Crea un archivo `.env` en la raíz del proyecto (nunca lo subas a GitHub):

```env
VITE_SUPABASE_URL=https://TU_PROYECTO.supabase.co
VITE_SUPABASE_KEY=TU_SERVICE_ROLE_KEY

EMAIL_USER=tu_correo@gmail.com
EMAIL_PASS=tu_app_password_gmail
```

> **Cómo obtener las keys de Supabase:**
> 1. Ve a [supabase.com](https://supabase.com) → tu proyecto
> 2. Settings → API
> 3. Copia **Project URL** → `VITE_SUPABASE_URL`
> 4. Copia **service_role** (secret) → `VITE_SUPABASE_KEY`

> **Cómo obtener el App Password de Gmail:**
> 1. Cuenta Google → Seguridad → Verificación en 2 pasos (activar)
> 2. Seguridad → Contraseñas de aplicaciones → Generar
> 3. Copia la contraseña de 16 caracteres → `EMAIL_PASS`

### 1.3 Crear las tablas en Supabase

Ve a **Supabase → SQL Editor** y ejecuta:

```sql
-- Tabla principal de reclamos
CREATE TABLE IF NOT EXISTS reclamos (
  id                  TEXT PRIMARY KEY,
  email               TEXT,
  nombre              TEXT,
  codigo_estudiante   TEXT,
  categoria           TEXT,
  descripcion         TEXT,
  estado              TEXT DEFAULT 'PENDIENTE',
  respuesta           TEXT,
  comentario          TEXT,
  expediente_id_m2    TEXT,          -- referencia cruzada con tefiis-m2
  created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla de documentos de estudiantes (PDFs procesados)
CREATE TABLE IF NOT EXISTS documentos_estudiante (
  email               TEXT PRIMARY KEY,
  codigo_estudiante   TEXT,
  datos_parseados     JSONB,
  record_matricula_url TEXT,
  boleta_url          TEXT,
  record_notas_url    TEXT,
  updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Índices útiles
CREATE INDEX IF NOT EXISTS idx_reclamos_email   ON reclamos(email);
CREATE INDEX IF NOT EXISTS idx_reclamos_estado  ON reclamos(estado);
CREATE INDEX IF NOT EXISTS idx_reclamos_created ON reclamos(created_at DESC);
```

> Si la tabla `reclamos` ya existe y le falta alguna columna, ejecuta solo lo que falta:
> ```sql
> ALTER TABLE reclamos ADD COLUMN IF NOT EXISTS comentario        TEXT;
> ALTER TABLE reclamos ADD COLUMN IF NOT EXISTS respuesta         TEXT;
> ALTER TABLE reclamos ADD COLUMN IF NOT EXISTS expediente_id_m2 TEXT;
> ```

### 1.4 Configurar Firebase Auth

1. Ve a [console.firebase.google.com](https://console.firebase.google.com)
2. Crea un proyecto → **Authentication** → Habilitar **Email/Password**
3. Agrega el correo administrador en **Authentication → Users**
4. El archivo `src/firebase.js` ya tiene la configuración del proyecto TEFIIS (no requiere cambios)

### 1.5 Correr en desarrollo

```bash
npm run dev
```

El panel estará en `http://localhost:5173`

El servidor de correo (Nodemailer) corre integrado en Vite como middleware — no necesitas un proceso separado.

### 1.6 Build para producción

```bash
npm run build
```

Los archivos quedan en `/dist`. Puedes deployar a Firebase Hosting:

```bash
npm install -g firebase-tools
firebase login
firebase deploy
```

---

## PARTE 2 — Backend tefiis-m2 (repo del compañero)

Repositorio: `https://github.com/AngelVarP/tefiis-m2`

### 2.1 Clonar

```bash
git clone https://github.com/AngelVarP/tefiis-m2.git
cd tefiis-m2
```

### 2.2 Crear el `.env` local del backend

```env
SUPABASE_KEY=TU_SERVICE_ROLE_KEY
```

> Esta es la misma `service_role` key de Supabase del paso 1.2. NO la commits.

### 2.3 Aplicar los cambios de integración

Los archivos modificados para integrar con Supabase son:

**`main.py`** — reemplazar con la versión integrada que:
- Acepta campos `email`, `nombre`, `descripcion` en el request
- Al crear un expediente, crea automáticamente el reclamo en Supabase
- Al emitir veredicto (Aceptado/Rechazado), actualiza el estado en Supabase
- Mapeo de estados: `Registrado→PENDIENTE` · `Recibido/Observado→EN_REVISION` · `Resuelto(Aceptado)→RESUELTO` · `Resuelto(Rechazado)→RECHAZADO`

**`docker-compose.yml`** — agregar en `m2-backend → environment`:
```yaml
SUPABASE_URL: https://TU_PROYECTO.supabase.co
SUPABASE_KEY: ${SUPABASE_KEY}
```

> Los archivos completos están disponibles en el repo del panel admin bajo `/docs/integracion-m2/`.

### 2.4 Levantar el backend

```bash
docker compose up --build
```

Servicios que levanta:
| Servicio    | Puerto | Descripción |
|-------------|--------|-------------|
| m2-backend  | 8000   | API FastAPI  |
| postgres-m2 | 5433   | Base de datos propia de M2 |
| redis-m2    | 6380   | Cache + rate limiting |
| rabbitmq-m2 | 5673 / 15673 | Broker de mensajería |

La API estará en `http://localhost:8000`  
Documentación Swagger: `http://localhost:8000/docs`

---

## PARTE 3 — Integración completa (flujo de datos)

### 3.1 Cómo debe enviar el formulario del estudiante

El formulario debe hacer `POST` a `tefiis-m2`, no directamente a Supabase:

```
POST http://localhost:8000/api/v1/m2/expedientes
Content-Type: application/json

{
  "codigoEstudiante": "20231158C",
  "email":            "estudiante@uni.pe",
  "nombre":           "Apellido Nombre Completo",
  "motivoReclamo":    "Cruce",          // "Cruce" | "Vacante" | "Otros"
  "descripcion":      "Detalle del problema...",
  "evidencias":       ["url_archivo1.pdf"]
}
```

`tefiis-m2` guardará el expediente en su PostgreSQL **y** creará automáticamente el reclamo en Supabase (visible en el panel admin).

### 3.2 Flujo completo paso a paso

```
1. Estudiante llena formulario
        │
        ▼
2. POST /api/v1/m2/expedientes
   → Crea expediente en PostgreSQL M2
   → Crea reclamo en Supabase (estado: PENDIENTE)
        │
        ▼
3. Admin ve el reclamo en el Panel Admin
   → Cambia estado, agrega comentario
   → Envía respuesta por email
        │
        ▼
4. POST /api/v1/m2/expedientes/{id}/veredicto
   → Actualiza expediente en PostgreSQL M2
   → Actualiza reclamo en Supabase (RESUELTO / RECHAZADO)
```

### 3.3 Verificar que la integración funciona

```bash
# Crear un expediente de prueba
curl -X POST http://localhost:8000/api/v1/m2/expedientes \
  -H "Content-Type: application/json" \
  -d '{
    "codigoEstudiante": "20231158C",
    "email": "test@uni.pe",
    "nombre": "Test Estudiante",
    "motivoReclamo": "Cruce",
    "descripcion": "Prueba de integración"
  }'
```

Luego ve al Panel Admin — debe aparecer el reclamo con estado **PENDIENTE**.

---

## Variables de entorno — resumen

### Panel Admin (`.env`)
| Variable | Descripción |
|----------|-------------|
| `VITE_SUPABASE_URL` | URL del proyecto Supabase |
| `VITE_SUPABASE_KEY` | service_role key de Supabase |
| `EMAIL_USER` | Correo Gmail del remitente |
| `EMAIL_PASS` | App Password de Gmail (16 chars) |

### tefiis-m2 (`.env`)
| Variable | Descripción |
|----------|-------------|
| `SUPABASE_URL` | Misma URL del proyecto Supabase |
| `SUPABASE_KEY` | Misma service_role key |

---

## Estructura del proyecto (Panel Admin)

```
src/
├── App.jsx                    # Componente principal, lógica del panel
├── App.css                    # Estilos globales
├── supabase.js                # Cliente Supabase (fetch wrapper)
├── firebase.js                # Configuración Firebase Auth
├── index.css                  # Variables CSS + Tailwind
├── main.jsx                   # Entry point
├── carga_horaria_2026.json    # Horarios del semestre 2026
├── plan_software_2026.json    # Plan de estudios Ingeniería de Software
├── components/
│   ├── MallaCurricular.tsx    # Grafo de malla curricular + modal de curso
│   └── HorarioCursos.jsx     # Grilla de horarios (actual + habilitados)
└── data/
    └── planEstudios.js        # Re-exporta plan_software_2026.json
```

---

## Troubleshooting frecuente

| Problema | Solución |
|----------|----------|
| Error 400 al guardar reclamo | Verificar que las columnas `comentario` y `respuesta` existen en la tabla `reclamos` (ver SQL del paso 1.3) |
| No llega el correo | Verificar `EMAIL_PASS` — debe ser App Password, no la contraseña normal de Gmail |
| Panel muestra "Sin parsear" | Los PDFs del estudiante no fueron procesados aún por el parser |
| tefiis-m2 no sincroniza con Supabase | Verificar que `SUPABASE_URL` y `SUPABASE_KEY` están en el `.env` del repo m2 y que el `docker-compose.yml` referencia `${SUPABASE_KEY}` |
| Reclamo sin nombre/código | El formulario no está enviando `email` y `nombre` al endpoint de tefiis-m2 |
