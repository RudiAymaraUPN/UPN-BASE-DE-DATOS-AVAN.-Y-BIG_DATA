/* ============================================================
   BASE DE DATOS : BDClinica
   ESQUEMA       : clinica
   MOTOR         : SQL Server (T-SQL)
   Generado a partir del diagrama entidad-relacion de la clinica
   v2: todas las tablas incluyen created_at (fecha/hora de carga del proceso ETL
       diario desde Excel). Si no se envia en la carga, toma GETDATE().
   ============================================================ */

-- ============================================================
-- 1. BASE DE DATOS
-- ============================================================
IF DB_ID('BDClinica') IS NULL
    CREATE DATABASE BDClinica;
GO

USE BDClinica;
GO

-- ============================================================
-- 2. ESQUEMA
-- ============================================================
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'clinica')
    EXEC('CREATE SCHEMA clinica');
GO

-- ============================================================
-- 3. TABLAS (en orden de dependencia)
-- ============================================================

-- ---------- PACIENTES ----------
CREATE TABLE clinica.PACIENTES (
    id_paciente      INT IDENTITY(1,1) NOT NULL,
    dni              VARCHAR(8)   NOT NULL,
    nombres          VARCHAR(100) NOT NULL,
    apellidos        VARCHAR(100) NOT NULL,
    fecha_nacimiento DATE         NOT NULL,
    sexo             VARCHAR(10)  NOT NULL,
    estado_civil     VARCHAR(15)  NULL,
    tipo_sangre      VARCHAR(3)   NULL,
    telefono         VARCHAR(15)  NULL,
    correo           VARCHAR(100) NULL,
    direccion        VARCHAR(200) NULL,
    created_at       DATETIME NOT NULL CONSTRAINT DF_PACIENTES_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_PACIENTES PRIMARY KEY (id_paciente),
    CONSTRAINT UQ_PACIENTES_dni UNIQUE (dni),
    CONSTRAINT CK_PACIENTES_sexo CHECK (sexo IN ('M','F')),
    CONSTRAINT CK_PACIENTES_estado_civil CHECK (estado_civil IN ('Soltero','Casado','Conviviente','Divorciado','Viudo')),
    CONSTRAINT CK_PACIENTES_tipo_sangre CHECK (tipo_sangre IN ('A+','A-','B+','B-','AB+','AB-','O+','O-'))
);
GO

-- ---------- CARGOS ----------
CREATE TABLE clinica.CARGOS (
    id_cargo     INT IDENTITY(1,1) NOT NULL,
    nombre_cargo VARCHAR(80) NOT NULL,
    created_at       DATETIME NOT NULL CONSTRAINT DF_CARGOS_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_CARGOS PRIMARY KEY (id_cargo),
    CONSTRAINT UQ_CARGOS_nombre UNIQUE (nombre_cargo)
);
GO

-- ---------- ESPECIALIDADES ----------
CREATE TABLE clinica.ESPECIALIDADES (
    id_especialidad     INT IDENTITY(1,1) NOT NULL,
    nombre_especialidad VARCHAR(100) NOT NULL,
    descripcion         VARCHAR(250) NULL,
    created_at       DATETIME NOT NULL CONSTRAINT DF_ESPECIALIDADES_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_ESPECIALIDADES PRIMARY KEY (id_especialidad),
    CONSTRAINT UQ_ESPECIALIDADES_nombre UNIQUE (nombre_especialidad)
);
GO

-- ---------- PERSONAL ----------
CREATE TABLE clinica.PERSONAL (
    id_personal      INT IDENTITY(1,1) NOT NULL,
    id_cargo         INT          NOT NULL,
    dni              VARCHAR(8)   NOT NULL,
    nombres          VARCHAR(100) NOT NULL,
    apellidos        VARCHAR(100) NOT NULL,
    fecha_nacimiento DATE         NULL,
    telefono         VARCHAR(15)  NULL,
    correo           VARCHAR(100) NULL,
    nro_colegiatura  VARCHAR(20)  NULL,
    created_at       DATETIME NOT NULL CONSTRAINT DF_PERSONAL_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_PERSONAL PRIMARY KEY (id_personal),
    CONSTRAINT UQ_PERSONAL_dni UNIQUE (dni),
    CONSTRAINT FK_PERSONAL_CARGOS FOREIGN KEY (id_cargo)
        REFERENCES clinica.CARGOS (id_cargo)
);
GO

-- ---------- HORARIOS_PERSONAL ----------
CREATE TABLE clinica.HORARIOS_PERSONAL (
    id_horario  INT IDENTITY(1,1) NOT NULL,
    id_personal INT         NOT NULL,
    dia_semana  VARCHAR(10) NOT NULL,
    hora_inicio TIME        NOT NULL,
    hora_fin    TIME        NOT NULL,
    created_at       DATETIME NOT NULL CONSTRAINT DF_HORARIOS_PERSONAL_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_HORARIOS_PERSONAL PRIMARY KEY (id_horario),
    CONSTRAINT FK_HORARIOS_PERSONAL_PERSONAL FOREIGN KEY (id_personal)
        REFERENCES clinica.PERSONAL (id_personal),
    CONSTRAINT CK_HORARIOS_dia CHECK (dia_semana IN ('Lunes','Martes','Miercoles','Jueves','Viernes','Sabado','Domingo')),
    CONSTRAINT CK_HORARIOS_horas CHECK (hora_fin > hora_inicio)
);
GO

-- ---------- PERSONAL_ESPECIALIDAD (tabla intermedia N:M) ----------
CREATE TABLE clinica.PERSONAL_ESPECIALIDAD (
    id_personal     INT NOT NULL,
    id_especialidad INT NOT NULL,
    created_at       DATETIME NOT NULL CONSTRAINT DF_PERSONAL_ESPECIALIDAD_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_PERSONAL_ESPECIALIDAD PRIMARY KEY (id_personal, id_especialidad),
    CONSTRAINT FK_PERSESP_PERSONAL FOREIGN KEY (id_personal)
        REFERENCES clinica.PERSONAL (id_personal),
    CONSTRAINT FK_PERSESP_ESPECIALIDADES FOREIGN KEY (id_especialidad)
        REFERENCES clinica.ESPECIALIDADES (id_especialidad)
);
GO

-- ---------- CITAS ----------
CREATE TABLE clinica.CITAS (
    id_cita     INT IDENTITY(1,1) NOT NULL,
    id_paciente INT          NOT NULL,
    id_personal INT          NOT NULL,
    fecha       DATE         NOT NULL,
    hora        TIME         NOT NULL,
    estado      VARCHAR(15)  NOT NULL CONSTRAINT DF_CITAS_estado DEFAULT 'Programada',
    motivo      VARCHAR(250) NULL,
    created_at       DATETIME NOT NULL CONSTRAINT DF_CITAS_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_CITAS PRIMARY KEY (id_cita),
    CONSTRAINT FK_CITAS_PACIENTES FOREIGN KEY (id_paciente)
        REFERENCES clinica.PACIENTES (id_paciente),
    CONSTRAINT FK_CITAS_PERSONAL FOREIGN KEY (id_personal)
        REFERENCES clinica.PERSONAL (id_personal),
    CONSTRAINT CK_CITAS_estado CHECK (estado IN ('Programada','Confirmada','Atendida','Cancelada','No asistio'))
);
GO

-- ---------- ATENCIONES (1 cita genera 0 o 1 atencion) ----------
CREATE TABLE clinica.ATENCIONES (
    id_atencion    INT IDENTITY(1,1) NOT NULL,
    id_cita        INT          NOT NULL,
    diagnostico    VARCHAR(MAX) NULL,
    observaciones  VARCHAR(MAX) NULL,
    fecha_atencion DATETIME     NOT NULL CONSTRAINT DF_ATENCIONES_fecha DEFAULT GETDATE(),
    created_at       DATETIME NOT NULL CONSTRAINT DF_ATENCIONES_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_ATENCIONES PRIMARY KEY (id_atencion),
    CONSTRAINT UQ_ATENCIONES_cita UNIQUE (id_cita),
    CONSTRAINT FK_ATENCIONES_CITAS FOREIGN KEY (id_cita)
        REFERENCES clinica.CITAS (id_cita)
);
GO

-- ---------- RECETAS ----------
CREATE TABLE clinica.RECETAS (
    id_receta     INT IDENTITY(1,1) NOT NULL,
    id_atencion   INT          NOT NULL,
    fecha_emision DATE         NOT NULL CONSTRAINT DF_RECETAS_fecha DEFAULT CAST(GETDATE() AS DATE),
    indicaciones  VARCHAR(MAX) NULL,
    created_at       DATETIME NOT NULL CONSTRAINT DF_RECETAS_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_RECETAS PRIMARY KEY (id_receta),
    CONSTRAINT FK_RECETAS_ATENCIONES FOREIGN KEY (id_atencion)
        REFERENCES clinica.ATENCIONES (id_atencion)
);
GO

-- ---------- FARMACOS ----------
CREATE TABLE clinica.FARMACOS (
    id_farmaco      INT IDENTITY(1,1) NOT NULL,
    nombre_farmaco  VARCHAR(120) NOT NULL,
    presentacion    VARCHAR(80)  NULL,
    precio_unitario DECIMAL(10,2) NOT NULL,
    stock_minimo    INT          NOT NULL CONSTRAINT DF_FARMACOS_stock_min DEFAULT 0,
    created_at       DATETIME NOT NULL CONSTRAINT DF_FARMACOS_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_FARMACOS PRIMARY KEY (id_farmaco),
    CONSTRAINT CK_FARMACOS_precio CHECK (precio_unitario >= 0),
    CONSTRAINT CK_FARMACOS_stock_min CHECK (stock_minimo >= 0)
);
GO

-- ---------- LOTES_FARMACOS ----------
CREATE TABLE clinica.LOTES_FARMACOS (
    id_lote         INT IDENTITY(1,1) NOT NULL,
    id_farmaco      INT         NOT NULL,
    nro_lote        VARCHAR(30) NOT NULL,
    fec_lote        DATE        NOT NULL,
    fec_vencimiento DATE        NOT NULL,
    stock           INT         NOT NULL CONSTRAINT DF_LOTES_stock DEFAULT 0,
    created_at       DATETIME NOT NULL CONSTRAINT DF_LOTES_FARMACOS_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_LOTES_FARMACOS PRIMARY KEY (id_lote),
    CONSTRAINT FK_LOTES_FARMACOS FOREIGN KEY (id_farmaco)
        REFERENCES clinica.FARMACOS (id_farmaco),
    CONSTRAINT CK_LOTES_stock CHECK (stock >= 0),
    CONSTRAINT CK_LOTES_fechas CHECK (fec_vencimiento > fec_lote)
);
GO

-- ---------- DETALLE_RECETA ----------
CREATE TABLE clinica.DETALLE_RECETA (
    id_detalle INT IDENTITY(1,1) NOT NULL,
    id_receta  INT         NOT NULL,
    id_farmaco INT         NOT NULL,
    dosis      VARCHAR(80) NOT NULL,
    cantidad   INT         NOT NULL,
    duracion   VARCHAR(50) NULL,
    created_at       DATETIME NOT NULL CONSTRAINT DF_DETALLE_RECETA_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_DETALLE_RECETA PRIMARY KEY (id_detalle),
    CONSTRAINT FK_DETRECETA_RECETAS FOREIGN KEY (id_receta)
        REFERENCES clinica.RECETAS (id_receta),
    CONSTRAINT FK_DETRECETA_FARMACOS FOREIGN KEY (id_farmaco)
        REFERENCES clinica.FARMACOS (id_farmaco),
    CONSTRAINT CK_DETRECETA_cantidad CHECK (cantidad > 0)
);
GO

-- ---------- SERVICIOS ----------
CREATE TABLE clinica.SERVICIOS (
    id_servicio     INT IDENTITY(1,1) NOT NULL,
    nombre_servicio VARCHAR(120) NOT NULL,
    descripcion     VARCHAR(250) NULL,
    precio          DECIMAL(10,2) NOT NULL,
    created_at       DATETIME NOT NULL CONSTRAINT DF_SERVICIOS_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_SERVICIOS PRIMARY KEY (id_servicio),
    CONSTRAINT CK_SERVICIOS_precio CHECK (precio >= 0)
);
GO

-- ---------- FACTURACION ----------
CREATE TABLE clinica.FACTURACION (
    id_factura  INT IDENTITY(1,1) NOT NULL,
    id_paciente INT          NOT NULL,
    fecha       DATE         NOT NULL CONSTRAINT DF_FACTURACION_fecha DEFAULT CAST(GETDATE() AS DATE),
    metodo_pago VARCHAR(15)  NOT NULL,
    total       DECIMAL(12,2) NOT NULL CONSTRAINT DF_FACTURACION_total DEFAULT 0,
    created_at       DATETIME NOT NULL CONSTRAINT DF_FACTURACION_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_FACTURACION PRIMARY KEY (id_factura),
    CONSTRAINT FK_FACTURACION_PACIENTES FOREIGN KEY (id_paciente)
        REFERENCES clinica.PACIENTES (id_paciente),
    CONSTRAINT CK_FACTURACION_metodo CHECK (metodo_pago IN ('Efectivo','Tarjeta','Transferencia','Yape/Plin','Seguro')),
    CONSTRAINT CK_FACTURACION_total CHECK (total >= 0)
);
GO

-- ---------- DETALLE_FACTURACION ----------
-- Cada linea cobra un servicio O un farmaco (uno de los dos, nunca ambos)
CREATE TABLE clinica.DETALLE_FACTURACION (
    id_detalle      INT IDENTITY(1,1) NOT NULL,
    id_factura      INT           NOT NULL,
    id_servicio     INT           NULL,
    id_farmaco      INT           NULL,
    cantidad        INT           NOT NULL,
    precio_unitario DECIMAL(10,2) NOT NULL,
    subtotal        DECIMAL(12,2) NOT NULL,
    created_at       DATETIME NOT NULL CONSTRAINT DF_DETALLE_FACTURACION_created_at DEFAULT GETDATE(),   -- fecha/hora de carga ETL
    CONSTRAINT PK_DETALLE_FACTURACION PRIMARY KEY (id_detalle),
    CONSTRAINT FK_DETFACT_FACTURACION FOREIGN KEY (id_factura)
        REFERENCES clinica.FACTURACION (id_factura),
    CONSTRAINT FK_DETFACT_SERVICIOS FOREIGN KEY (id_servicio)
        REFERENCES clinica.SERVICIOS (id_servicio),
    CONSTRAINT FK_DETFACT_FARMACOS FOREIGN KEY (id_farmaco)
        REFERENCES clinica.FARMACOS (id_farmaco),
    CONSTRAINT CK_DETFACT_item CHECK (
        (id_servicio IS NOT NULL AND id_farmaco IS NULL) OR
        (id_servicio IS NULL AND id_farmaco IS NOT NULL)),
    CONSTRAINT CK_DETFACT_cantidad CHECK (cantidad > 0),
    CONSTRAINT CK_DETFACT_precio CHECK (precio_unitario >= 0),
    CONSTRAINT CK_DETFACT_subtotal CHECK (subtotal >= 0)
);
GO

-- ============================================================
-- 4. INDICES SOBRE LLAVES FORANEAS (mejoran joins y consultas BI)
-- ============================================================
CREATE INDEX IX_PERSONAL_cargo        ON clinica.PERSONAL (id_cargo);
CREATE INDEX IX_HORARIOS_personal     ON clinica.HORARIOS_PERSONAL (id_personal);
CREATE INDEX IX_PERSESP_especialidad  ON clinica.PERSONAL_ESPECIALIDAD (id_especialidad);
CREATE INDEX IX_CITAS_paciente        ON clinica.CITAS (id_paciente);
CREATE INDEX IX_CITAS_personal        ON clinica.CITAS (id_personal);
CREATE INDEX IX_CITAS_fecha           ON clinica.CITAS (fecha);
CREATE INDEX IX_RECETAS_atencion      ON clinica.RECETAS (id_atencion);
CREATE INDEX IX_LOTES_farmaco         ON clinica.LOTES_FARMACOS (id_farmaco);
CREATE INDEX IX_DETRECETA_receta      ON clinica.DETALLE_RECETA (id_receta);
CREATE INDEX IX_DETRECETA_farmaco     ON clinica.DETALLE_RECETA (id_farmaco);
CREATE INDEX IX_FACTURACION_paciente  ON clinica.FACTURACION (id_paciente);
CREATE INDEX IX_DETFACT_factura       ON clinica.DETALLE_FACTURACION (id_factura);
CREATE INDEX IX_DETFACT_servicio      ON clinica.DETALLE_FACTURACION (id_servicio);
CREATE INDEX IX_DETFACT_farmaco       ON clinica.DETALLE_FACTURACION (id_farmaco);
GO

-- ============================================================
-- 5. VERIFICACION: debe listar las 15 tablas del esquema clinica
-- ============================================================
SELECT TABLE_SCHEMA, TABLE_NAME
FROM   INFORMATION_SCHEMA.TABLES
WHERE  TABLE_SCHEMA = 'clinica'
ORDER  BY TABLE_NAME;
GO
