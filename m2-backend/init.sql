-- ============================================================
-- SCRIPT DE INICIALIZACIÓN — Módulo 2: Reclamos y Trazabilidad
-- Coherente con el modelo de datos de la PC3 (Sección 9.2 y 10.2)
-- ============================================================

-- Habilitar extensión UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── TABLA: EXPEDIENTE ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS expediente (
    id_expediente           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    codigo_estudiante       VARCHAR(20) NOT NULL,
    motivo_reclamo          VARCHAR(50) NOT NULL CHECK (motivo_reclamo IN ('Cruce', 'Vacante', 'Otros')),
    prioridad_asignada      VARCHAR(20) NOT NULL CHECK (prioridad_asignada IN ('Alta', 'Media', 'Baja')),
    estado_actual           VARCHAR(30) NOT NULL CHECK (estado_actual IN ('Registrado', 'Recibido', 'Observado', 'Resuelto', 'Pendiente de Validación Manual')),
    fecha_creacion          TIMESTAMP NOT NULL DEFAULT NOW(),
    reporte_academico_snapshot JSONB,
    idempotency_key         VARCHAR(100) UNIQUE  -- Para control de idempotencia
);

CREATE INDEX IF NOT EXISTS idx_expediente_estado ON expediente(estado_actual);
CREATE INDEX IF NOT EXISTS idx_expediente_estudiante ON expediente(codigo_estudiante);

-- ─── TABLA: EVIDENCIA ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS evidencia (
    id_evidencia            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    id_expediente           UUID NOT NULL REFERENCES expediente(id_expediente) ON DELETE CASCADE,
    url_archivo_adjunto     VARCHAR(255) NOT NULL,
    tipo_documento          VARCHAR(50),
    fecha_subida            TIMESTAMP DEFAULT NOW(),
    metadatos_dinamicos     JSONB
);

-- ─── TABLA: HISTORIAL_ESTADO (Auditoría inmutable - AOP) ─────
CREATE TABLE IF NOT EXISTS historial_estado (
    id_historial            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    id_expediente           UUID NOT NULL REFERENCES expediente(id_expediente),
    estado_anterior         VARCHAR(30),
    estado_nuevo            VARCHAR(30) NOT NULL,
    fecha_cambio            TIMESTAMP NOT NULL DEFAULT NOW(),
    actor_responsable_id    VARCHAR(100) NOT NULL  -- ID o código del actor (evaluador/sistema)
);

-- ─── TABLA: NOTIFICACION ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS notificacion (
    id_notificacion         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    id_expediente           UUID NOT NULL REFERENCES expediente(id_expediente),
    tipo_mensaje            VARCHAR(50) NOT NULL CHECK (tipo_mensaje IN ('Email', 'Sistema')),
    contenido               TEXT,
    fecha_envio             TIMESTAMP DEFAULT NOW(),
    fue_leida               BOOLEAN NOT NULL DEFAULT FALSE
);

-- ============================================================
-- SEED DATA — Coherente con el poblamiento de la PC3 (Sección 10.2)
-- ============================================================

-- ─── EXPEDIENTES (3 registros) ───────────────────────────────
INSERT INTO expediente (id_expediente, codigo_estudiante, motivo_reclamo, prioridad_asignada, estado_actual, fecha_creacion, reporte_academico_snapshot) VALUES
(
    'e1a4b5c6-7d8e-9f0a-1b2c-3d4e5f6a7b8c',
    '20201011A',
    'Cruce',
    'Alta',
    'Registrado',
    NOW(),
    '{"condicionAcademica": "Regular", "creditosAprobados": 125, "cursosDesaprobados": 0, "tieneMatriculaActiva": true}'
),
(
    'f2b5c6d7-8e9f-0a1b-2c3d-4e5f6a7b8c9d',
    '20192022B',
    'Vacante',
    'Media',
    'Observado',
    NOW() - INTERVAL '2 days',
    '{"condicionAcademica": "Riesgo", "creditosAprobados": 80, "cursosDesaprobados": 2, "tieneMatriculaActiva": true}'
),
(
    'a3c6d7e8-9f0a-1b2c-3d4e-5f6a7b8c9d0e',
    '20210033C',
    'Otros',
    'Baja',
    'Resuelto',
    NOW() - INTERVAL '5 days',
    '{"condicionAcademica": "Regular", "creditosAprobados": 160, "cursosDesaprobados": 0, "tieneMatriculaActiva": false}'
);

-- ─── EVIDENCIAS (3 registros) ─────────────────────────────────
INSERT INTO evidencia (id_evidencia, id_expediente, url_archivo_adjunto, tipo_documento, metadatos_dinamicos) VALUES
(
    'b1c2d3e4-f5a6-7b8c-9d0e-1f2a3b4c5d6e',
    'e1a4b5c6-7d8e-9f0a-1b2c-3d4e5f6a7b8c',
    'https://s3.fiis.edu/evidencias/cruce_20201011A.pdf',
    'Captura de Pantalla',
    '{"cursos_cruzados": ["FB401","SI302"], "franja_horaria": "Martes 10:00-12:00", "es_ultima_matricula": false}'
),
(
    'c2d3e4f5-a67b-8c9d-0e1f-2a3b4c5d6e7f',
    'f2b5c6d7-8e9f-0a1b-2c3d-4e5f6a7b8c9d',
    'https://s3.fiis.edu/evidencias/vacante_20192022B.pdf',
    'Solicitud Firmada',
    '{"curso_solicitado": "SI405", "seccion_llena": "V", "justificacion": "Curso es pre-requisito para Tesis"}'
),
(
    'd3e4f5a6-7b8c-9d0e-1f2a-3b4c5d6e7f8a',
    'a3c6d7e8-9f0a-1b2c-3d4e-5f6a7b8c9d0e',
    'https://s3.fiis.edu/evidencias/prereq_20210033C.pdf',
    'Carta de Justificación',
    '{"curso_objetivo": "FB401", "pre_requisito_faltante": "FB301", "motivo": "Ultimo curso para egresar"}'
);

-- ─── HISTORIAL_ESTADO (3 registros de auditoría) ──────────────
INSERT INTO historial_estado (id_historial, id_expediente, estado_anterior, estado_nuevo, fecha_cambio, actor_responsable_id) VALUES
(
    '11111111-2222-3333-4444-555555555555',
    'f2b5c6d7-8e9f-0a1b-2c3d-4e5f6a7b8c9d',
    'Registrado',
    'Recibido',
    NOW() - INTERVAL '1 day',
    '99999999-8888-7777-6666-555555555555'
),
(
    '22222222-3333-4444-5555-666666666666',
    'f2b5c6d7-8e9f-0a1b-2c3d-4e5f6a7b8c9d',
    'Recibido',
    'Observado',
    NOW() - INTERVAL '12 hours',
    '99999999-8888-7777-6666-555555555555'
),
(
    '33333333-4444-5555-6666-777777777777',
    'a3c6d7e8-9f0a-1b2c-3d4e-5f6a7b8c9d0e',
    'Recibido',
    'Resuelto',
    NOW() - INTERVAL '1 hour',
    '88888888-7777-6666-5555-444444444444'
);

-- ─── NOTIFICACIONES (3 registros) ─────────────────────────────
INSERT INTO notificacion (id_notificacion, id_expediente, tipo_mensaje, contenido, fue_leida) VALUES
(
    '44444444-5555-6666-7777-888888888888',
    'e1a4b5c6-7d8e-9f0a-1b2c-3d4e5f6a7b8c',
    'Email',
    'Su reclamo por Cruce de Horarios ha sido registrado con éxito. Ticket: e1a4b5c6',
    TRUE
),
(
    '55555555-6666-7777-8888-999999999999',
    'f2b5c6d7-8e9f-0a1b-2c3d-4e5f6a7b8c9d',
    'Sistema',
    'ATENCIÓN: Su reclamo fue observado. Adjunte la captura legible del curso SI405.',
    FALSE
),
(
    '66666666-7777-8888-9999-000000000000',
    'a3c6d7e8-9f0a-1b2c-3d4e-5f6a7b8c9d0e',
    'Email',
    'Resolución Final: Su levantamiento de pre-requisito ha sido APROBADO.',
    TRUE
);
