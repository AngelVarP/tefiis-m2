import os
import json
import uuid
import httpx
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Header, Depends, Request, status
from pydantic import BaseModel, Field
from databases import Database
import redis.asyncio as redis
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt, JWTError

# ─── CONFIGURACIÓN DE ENTORNO Y DEPENDENCIAS ───
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://m2_user:m2_password@localhost:5433/tefiis_m2")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380")
JWT_SECRET = os.getenv("JWT_SECRET", "tefiis_m2_jwt_secret_academico_2024")
SIGA_URL = os.getenv("SIGA_URL", "http://mock-siga:8080")
SIGA_TIMEOUT = int(os.getenv("SIGA_TIMEOUT_SECONDS", "2"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

database = Database(DATABASE_URL)
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

app = FastAPI(
    title="TEFIIS Módulo 2 API",
    description="API de Gestión y Trazabilidad del Reclamo",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── MODELOS PYDANTIC (Según openapi-m2.yaml) ───
class ExpedienteRequest(BaseModel):
    codigoEstudiante: str
    email: Optional[str] = None
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    motivoReclamo: str
    evidencias: Optional[List[str]] = []

class ExpedienteResponse(BaseModel):
    idExpediente: str
    estadoActual: str
    prioridadAsignada: str
    fechaCreacion: str

class HistorialItem(BaseModel):
    estadoAnterior: Optional[str]
    estadoNuevo: str
    fechaCambio: str
    actorResponsableId: str

class ExpedienteDetailResponse(BaseModel):
    idExpediente: str
    codigoEstudiante: str
    motivoReclamo: str
    estadoActual: str
    prioridadAsignada: str
    historial: List[HistorialItem]

class VeredictoRequest(BaseModel):
    resultado: str = Field(..., pattern="^(Aceptado|Rechazado|Observado)$")
    justificacion: str

class SubsanarRequest(BaseModel):
    comentarioSubsanacion: str

class ErrorResponse(BaseModel):
    error: str
    mensaje: str
    traceId: str

# ─── FUNCIONES AUXILIARES ───
async def get_current_user_role(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado o inválido")
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("role"), payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

async def require_tercio(role_user: tuple = Depends(get_current_user_role)):
    role, user_id = role_user
    if role != "TERCIO":
        raise HTTPException(status_code=403, detail="Requiere rol TERCIO")
    return user_id

def generate_trace_id():
    return str(uuid.uuid4())

async def sync_create_reclamo_supabase(id_expediente: str, request: ExpedienteRequest, estado: str):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("WARNING: SUPABASE_URL or SUPABASE_KEY not set. Supabase sync skipped.")
        return
        
    supabase_state = "PENDIENTE"
    if estado in ["Registrado", "Pendiente de Validación Manual"]:
        supabase_state = "PENDIENTE"
    elif estado in ["Recibido", "Observado"]:
        supabase_state = "EN_REVISION"
        
    payload = {
        "id": id_expediente,
        "email": request.email,
        "nombre": request.nombre,
        "codigo_estudiante": request.codigoEstudiante,
        "categoria": request.motivoReclamo,
        "descripcion": request.descripcion,
        "estado": supabase_state,
        "expediente_id_m2": id_expediente
    }
    
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/reclamos"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=5.0)
            resp.raise_for_status()
        except Exception as e:
            print(f"ERROR syncing claim to Supabase: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Error al sincronizar con Supabase: {str(e)}"
            )

async def sync_update_reclamo_supabase(id_expediente: str, estado_m2: str, resultado_veredicto: Optional[str] = None, justificacion: Optional[str] = None):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("WARNING: SUPABASE_URL or SUPABASE_KEY not set. Supabase sync skipped.")
        return

    supabase_state = "PENDIENTE"
    if estado_m2 in ["Registrado", "Pendiente de Validación Manual"]:
        supabase_state = "PENDIENTE"
    elif estado_m2 in ["Recibido", "Observado"]:
        supabase_state = "EN_REVISION"
    elif estado_m2 == "Resuelto":
        if resultado_veredicto == "Aceptado":
            supabase_state = "RESUELTO"
        elif resultado_veredicto == "Rechazado":
            supabase_state = "RECHAZADO"
        else:
            supabase_state = "RESUELTO"

    payload = {
        "estado": supabase_state
    }
    if justificacion is not None:
        payload["respuesta"] = justificacion
        payload["comentario"] = justificacion

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/reclamos?id=eq.{id_expediente}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.patch(url, json=payload, headers=headers, timeout=5.0)
            resp.raise_for_status()
        except Exception as e:
            print(f"ERROR updating claim in Supabase: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Error al actualizar en Supabase: {str(e)}"
            )

# ─── EVENTOS DE LIFECYCLE ───
@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
    await redis_client.close()

# ─── ENDPOINTS PRINCIPALES ───

@app.get("/health")
async def health_check():
    """RNF-M2-06: Monitoreo de dependencias"""
    return {"status": "ok", "service": "m2-backend"}

@app.post("/api/v1/m2/expedientes", response_model=ExpedienteResponse, status_code=status.HTTP_201_CREATED)
async def crear_expediente(request: ExpedienteRequest, idempotency_key: Optional[str] = Header(None)):
    trace_id = generate_trace_id()
    
    # 1. Idempotencia
    if idempotency_key:
        query_idem = "SELECT id_expediente, estado_actual, prioridad_asignada, fecha_creacion FROM expediente WHERE idempotency_key = :key"
        existing = await database.fetch_one(query=query_idem, values={"key": idempotency_key})
        if existing:
            # Retornamos el mismo resultado sin fallar (200 OK)
            return ExpedienteResponse(
                idExpediente=str(existing["id_expediente"]),
                estadoActual=existing["estado_actual"],
                prioridadAsignada=existing["prioridad_asignada"],
                fechaCreacion=existing["fecha_creacion"].isoformat()
            )

    # 2. Rate Limiting (Redis)
    rate_key = f"ratelimit:crear_expediente:{request.codigoEstudiante}"
    current_reqs = await redis_client.incr(rate_key)
    if current_reqs == 1:
        await redis_client.expire(rate_key, 60) # 1 minuto ventana
    elif current_reqs > 3: # Límite: 3 peticiones por minuto
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limit_exceeded", "mensaje": "Demasiadas peticiones. Intente más tarde.", "traceId": trace_id}
        )
    
    # 3. Fallback de SIGA
    siga_cache_key = f"cache:siga_riesgo:{request.codigoEstudiante}"
    condicion_academica = await redis_client.get(siga_cache_key)
    estado_inicial = "Registrado"
    reporte_snapshot = {"condicionAcademica": "Desconocido"}
    
    if condicion_academica is None:
        try:
            # Simulamos llamada HTTP a SIGA
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{SIGA_URL}/alumno/{request.codigoEstudiante}", timeout=SIGA_TIMEOUT)
                if resp.status_code == 200:
                    reporte_snapshot = resp.json()
                    await redis_client.setex(siga_cache_key, 300, json.dumps(reporte_snapshot))
                else:
                    estado_inicial = "Pendiente de Validación Manual"
        except (httpx.TimeoutException, httpx.RequestError):
            estado_inicial = "Pendiente de Validación Manual"
    else:
        reporte_snapshot = json.loads(condicion_academica)

    prioridad = "Alta" if request.motivoReclamo == "Cruce" else "Media"

    # 4. Transacción de Creación
    async with database.transaction():
        query = """
            INSERT INTO expediente (codigo_estudiante, motivo_reclamo, prioridad_asignada, estado_actual, reporte_academico_snapshot, idempotency_key)
            VALUES (:codigo, :motivo, :prioridad, :estado, :reporte, :idempotency)
            RETURNING id_expediente, fecha_creacion
        """
        values = {
            "codigo": request.codigoEstudiante,
            "motivo": request.motivoReclamo,
            "prioridad": prioridad,
            "estado": estado_inicial,
            "reporte": json.dumps(reporte_snapshot),
            "idempotency": idempotency_key
        }
        record = await database.fetch_one(query=query, values=values)
        id_expediente = record["id_expediente"]
        fecha_creacion = record["fecha_creacion"]

        # Auditoría inicial (AOP simulado)
        query_audit = """
            INSERT INTO historial_estado (id_expediente, estado_nuevo, actor_responsable_id)
            VALUES (:id_exp, :estado, :actor)
        """
        await database.execute(query=query_audit, values={"id_exp": id_expediente, "estado": estado_inicial, "actor": request.codigoEstudiante})

        # Evidencias
        for url in request.evidencias:
            query_evid = "INSERT INTO evidencia (id_expediente, url_archivo_adjunto) VALUES (:id_exp, :url)"
            await database.execute(query=query_evid, values={"id_exp": id_expediente, "url": url})
            
        # Sincronización con Supabase (dentro de la transacción)
        await sync_create_reclamo_supabase(str(id_expediente), request, estado_inicial)
            
    return ExpedienteResponse(
        idExpediente=str(id_expediente),
        estadoActual=estado_inicial,
        prioridadAsignada=prioridad,
        fechaCreacion=fecha_creacion.isoformat()
    )


@app.get("/api/v1/m2/expedientes")
async def listar_expedientes(offset: int = 0, limite: int = 20, estado: Optional[str] = None, user_id: str = Depends(require_tercio)):
    query = "SELECT id_expediente, estado_actual, prioridad_asignada, fecha_creacion FROM expediente"
    values = {}
    if estado:
        query += " WHERE estado_actual = :estado"
        values["estado"] = estado
    query += " ORDER BY fecha_creacion DESC LIMIT :limite OFFSET :offset"
    values.update({"limite": limite, "offset": offset})
    
    records = await database.fetch_all(query=query, values=values)
    return [
        {
            "idExpediente": str(r["id_expediente"]),
            "estadoActual": r["estado_actual"],
            "prioridadAsignada": r["prioridad_asignada"],
            "fechaCreacion": r["fecha_creacion"].isoformat()
        }
        for r in records
    ]

@app.get("/api/v1/m2/expedientes/{id}", response_model=ExpedienteDetailResponse)
async def obtener_expediente(id: str):
    query_exp = "SELECT * FROM expediente WHERE id_expediente = :id"
    exp = await database.fetch_one(query=query_exp, values={"id": id})
    if not exp:
        raise HTTPException(status_code=404, detail="Expediente no encontrado")
        
    query_hist = "SELECT * FROM historial_estado WHERE id_expediente = :id ORDER BY fecha_cambio ASC"
    hist_records = await database.fetch_all(query=query_hist, values={"id": id})
    
    historial = [
        HistorialItem(
            estadoAnterior=h["estado_anterior"],
            estadoNuevo=h["estado_nuevo"],
            fechaCambio=h["fecha_cambio"].isoformat(),
            actorResponsableId=h["actor_responsable_id"]
        ) for h in hist_records
    ]
    
    return ExpedienteDetailResponse(
        idExpediente=str(exp["id_expediente"]),
        codigoEstudiante=exp["codigo_estudiante"],
        motivoReclamo=exp["motivo_reclamo"],
        estadoActual=exp["estado_actual"],
        prioridadAsignada=exp["prioridad_asignada"],
        historial=historial
    )

@app.post("/api/v1/m2/expedientes/{id}/veredicto")
async def emitir_veredicto(id: str, request: VeredictoRequest, idempotency_key: Optional[str] = Header(None), user_id: str = Depends(require_tercio)):
    trace_id = generate_trace_id()
    
    # 1. Idempotencia simple (evitar doble evaluación)
    idem_key = f"idem:veredicto:{id}:{idempotency_key}" if idempotency_key else None
    if idem_key:
        if await redis_client.get(idem_key):
            raise HTTPException(status_code=409, detail="Conflicto: Veredicto ya procesado para esta clave de idempotencia")
    
    # Obtener expediente
    exp = await database.fetch_one("SELECT * FROM expediente WHERE id_expediente = :id", {"id": id})
    if not exp:
        raise HTTPException(status_code=404, detail="Expediente no encontrado")
        
    estado_anterior = exp["estado_actual"]
    estado_nuevo = "Resuelto" if request.resultado in ["Aceptado", "Rechazado"] else "Observado"
    
    if estado_anterior == "Resuelto":
        raise HTTPException(status_code=400, detail="El expediente ya está resuelto.")

    async with database.transaction():
        # Actualizar estado
        await database.execute(
            "UPDATE expediente SET estado_actual = :est WHERE id_expediente = :id",
            {"est": estado_nuevo, "id": id}
        )
        # Auditoría
        await database.execute(
            """INSERT INTO historial_estado (id_expediente, estado_anterior, estado_nuevo, actor_responsable_id) 
               VALUES (:id, :est_ant, :est_nuevo, :actor)""",
            {"id": id, "est_ant": estado_anterior, "est_nuevo": estado_nuevo, "actor": user_id}
        )
        
        # Sincronizar actualización con Supabase
        await sync_update_reclamo_supabase(
            id_expediente=id,
            estado_m2=estado_nuevo,
            resultado_veredicto=request.resultado,
            justificacion=request.justificacion
        )
        
    if idem_key:
        await redis_client.setex(idem_key, 3600, "procesado")
        
    exp_actualizado = await database.fetch_one("SELECT id_expediente, estado_actual, prioridad_asignada, fecha_creacion FROM expediente WHERE id_expediente = :id", {"id": id})
    return {
        "idExpediente": str(exp_actualizado["id_expediente"]),
        "estadoActual": exp_actualizado["estado_actual"],
        "prioridadAsignada": exp_actualizado["prioridad_asignada"],
        "fechaCreacion": exp_actualizado["fecha_creacion"].isoformat()
    }

@app.post("/api/v1/m2/expedientes/{id}/subsanar")
async def subsanar_expediente(id: str, request: SubsanarRequest):
    exp = await database.fetch_one("SELECT * FROM expediente WHERE id_expediente = :id", {"id": id})
    if not exp:
        raise HTTPException(status_code=404, detail="Expediente no encontrado")
        
    if exp["estado_actual"] != "Observado":
        raise HTTPException(status_code=400, detail="Solo se pueden subsanar expedientes en estado Observado")

    estado_anterior = "Observado"
    estado_nuevo = "Recibido"

    async with database.transaction():
        await database.execute(
            "UPDATE expediente SET estado_actual = :est WHERE id_expediente = :id",
            {"est": estado_nuevo, "id": id}
        )
        await database.execute(
            """INSERT INTO historial_estado (id_expediente, estado_anterior, estado_nuevo, actor_responsable_id) 
               VALUES (:id, :est_ant, :est_nuevo, :actor)""",
            {"id": id, "est_ant": estado_anterior, "est_nuevo": estado_nuevo, "actor": exp["codigo_estudiante"]}
        )
        # Sincronizar subsanación con Supabase
        await sync_update_reclamo_supabase(
            id_expediente=id,
            estado_m2=estado_nuevo
        )
        
    exp_actualizado = await database.fetch_one("SELECT id_expediente, estado_actual, prioridad_asignada, fecha_creacion FROM expediente WHERE id_expediente = :id", {"id": id})
    return {
        "idExpediente": str(exp_actualizado["id_expediente"]),
        "estadoActual": exp_actualizado["estado_actual"],
        "prioridadAsignada": exp_actualizado["prioridad_asignada"],
        "fechaCreacion": exp_actualizado["fecha_creacion"].isoformat()
    }

# Mock endpoints para análisis y Neo4j
@app.get("/api/v1/m2/cursos/{codigo}/impacto")
async def impacto_curso(codigo: str):
    # Mock Neo4j Graph Response
    return {
        "cursosBloqueados": 2,
        "listaCursos": ["FB301", "SI302"]
    }

@app.get("/api/v1/m2/reportes/tiempos-atencion")
async def reporte_tiempos():
    # Mock ClickHouse Response
    return [
        {"motivo_reclamo": "Cruce", "horas_promedio": 45.5},
        {"motivo_reclamo": "Vacante", "horas_promedio": 77.2}
    ]
