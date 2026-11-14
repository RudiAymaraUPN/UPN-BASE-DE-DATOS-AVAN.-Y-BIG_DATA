# -*- coding: utf-8 -*-
r"""
ETL - CARGA MASIVA INICIAL  |  CSV  ->  SQL Server (BDClinica, esquema clinica)

Flujo:  1) EXTRACCION      lee los 15 CSV de RUTA_DATA
        2) TRANSFORMACION  limpia, convierte tipos y valida (llaves, dominios, reglas)
        3) CARGA           inserta todo en UNA transaccion (si algo falla, no queda nada a medias)

CONFIGURACION SENSIBLE: servidor, base, usuario y clave NO van en el codigo. Se leen del archivo
.env de la raiz del repositorio (ignorado por git). Copia .env.example a .env y completalo.

Uso (terminal en la RAIZ del repositorio; no usar el boton de VS Code si la ruta tiene espacios):
    python -m etl.carga_inicial --solo-validar      # prueba: valida los CSV sin tocar la base
    python -m etl.carga_inicial                     # carga inicial (aborta si las tablas ya tienen datos)
    python -m etl.carga_inicial --recargar          # borra el destino y vuelve a cargar
    python -m etl.carga_inicial --ruta "D:\otra\carpeta" --server "localhost\SQLEXPRESS"   # sobrescriben el .env

Requisitos:  pip install -r requirements.txt   +   ODBC Driver 18 for SQL Server (Microsoft).
Origen por defecto: data/inicial/*.csv.  Cada ejecucion guarda un log en logs/ (ignorado por git).
"""

# ============================ 1. EXTRACCION ============================
import argparse
import os
import sys
import time
import traceback
from decimal import Decimal

import pandas as pd

# Permite ejecutar el archivo directamente desde cualquier carpeta (py etl\carga_inicial.py o py .\carga_inicial.py)
import sys as _sys
from pathlib import Path as _Path
_raiz = str(_Path(__file__).resolve().parent.parent)
if _raiz not in _sys.path:
    _sys.path.insert(0, _raiz)

# ---------- CONFIGURACION (se lee del archivo .env de la raiz del repositorio, NUNCA se escribe en el codigo) ----------
from etl.config import cargar_env, carpeta_logs, ruta


cargar_env()
RUTA_DATA = ruta("ETL_RUTA_DATA", "data/inicial")        # carpeta con los CSV
SERVER    = os.environ.get("DB_SERVER")                # ej. SERVIDOR\INSTANCIA
DATABASE  = os.environ.get("DB_NAME")                  # ej. BDClinica
SCHEMA    = os.environ.get("DB_SCHEMA", "clinica")
USUARIO   = os.environ.get("DB_USER") or None          # vacio = autenticacion de Windows
CLAVE     = os.environ.get("DB_PASSWORD") or None
MODO_CARGA   = "ABORTAR"  # "ABORTAR": si el destino ya tiene datos, no hace nada | "RECARGAR": borra y vuelve a cargar
SOLO_VALIDAR = False      # True = solo extrae y valida los CSV, SIN conectarse a la base de datos
# (estos dos tambien se cambian desde la terminal: --recargar / --solo-validar)
LOG_FILE = None           # se asigna en main()

# ---------- ESQUEMA DESTINO (en orden de carga: primero padres, luego hijos) ----------
# cols: (columna, tipo)  tipos: int | str | dec | date | time | dt
SPEC = {
    "CARGOS": dict(cols=[("id_cargo", "int"), ("nombre_cargo", "str"), ("created_at", "dt")],
                   pk=["id_cargo"], uk=["nombre_cargo"], identity=True, nullable=[], fks=[]),
    "ESPECIALIDADES": dict(cols=[("id_especialidad", "int"), ("nombre_especialidad", "str"), ("descripcion", "str"), ("created_at", "dt")],
                           pk=["id_especialidad"], uk=["nombre_especialidad"], identity=True, nullable=["descripcion"], fks=[]),
    "PACIENTES": dict(cols=[("id_paciente", "int"), ("dni", "str"), ("nombres", "str"), ("apellidos", "str"), ("fecha_nacimiento", "date"), ("sexo", "str"),
                            ("estado_civil", "str"), ("tipo_sangre", "str"), ("telefono", "str"), ("correo", "str"), ("direccion", "str"), ("created_at", "dt")],
                      pk=["id_paciente"], uk=["dni"], identity=True,
                      nullable=["estado_civil", "tipo_sangre", "telefono", "correo", "direccion"], fks=[]),
    "PERSONAL": dict(cols=[("id_personal", "int"), ("id_cargo", "int"), ("dni", "str"), ("nombres", "str"), ("apellidos", "str"), ("fecha_nacimiento", "date"),
                           ("telefono", "str"), ("correo", "str"), ("nro_colegiatura", "str"), ("created_at", "dt")],
                     pk=["id_personal"], uk=["dni"], identity=True,
                     nullable=["fecha_nacimiento", "telefono", "correo", "nro_colegiatura"], fks=[("id_cargo", "CARGOS", "id_cargo")]),
    "HORARIOS_PERSONAL": dict(cols=[("id_horario", "int"), ("id_personal", "int"), ("dia_semana", "str"), ("hora_inicio", "time"), ("hora_fin", "time"), ("created_at", "dt")],
                              pk=["id_horario"], uk=[], identity=True, nullable=[], fks=[("id_personal", "PERSONAL", "id_personal")]),
    "PERSONAL_ESPECIALIDAD": dict(cols=[("id_personal", "int"), ("id_especialidad", "int"), ("created_at", "dt")],
                                  pk=["id_personal", "id_especialidad"], uk=[], identity=False, nullable=[],
                                  fks=[("id_personal", "PERSONAL", "id_personal"), ("id_especialidad", "ESPECIALIDADES", "id_especialidad")]),
    "SERVICIOS": dict(cols=[("id_servicio", "int"), ("nombre_servicio", "str"), ("descripcion", "str"), ("precio", "dec"), ("created_at", "dt")],
                      pk=["id_servicio"], uk=[], identity=True, nullable=["descripcion"], fks=[]),
    "FARMACOS": dict(cols=[("id_farmaco", "int"), ("nombre_farmaco", "str"), ("presentacion", "str"), ("precio_unitario", "dec"), ("stock_minimo", "int"), ("created_at", "dt")],
                     pk=["id_farmaco"], uk=[], identity=True, nullable=["presentacion"], fks=[]),
    "LOTES_FARMACOS": dict(cols=[("id_lote", "int"), ("id_farmaco", "int"), ("nro_lote", "str"), ("fec_lote", "date"), ("fec_vencimiento", "date"), ("stock", "int"), ("created_at", "dt")],
                           pk=["id_lote"], uk=[], identity=True, nullable=[], fks=[("id_farmaco", "FARMACOS", "id_farmaco")]),
    "CITAS": dict(cols=[("id_cita", "int"), ("id_paciente", "int"), ("id_personal", "int"), ("fecha", "date"), ("hora", "time"), ("estado", "str"), ("motivo", "str"), ("created_at", "dt")],
                  pk=["id_cita"], uk=[], identity=True, nullable=["motivo"],
                  fks=[("id_paciente", "PACIENTES", "id_paciente"), ("id_personal", "PERSONAL", "id_personal")]),
    "ATENCIONES": dict(cols=[("id_atencion", "int"), ("id_cita", "int"), ("diagnostico", "str"), ("observaciones", "str"), ("fecha_atencion", "dt"), ("created_at", "dt")],
                       pk=["id_atencion"], uk=["id_cita"], identity=True, nullable=["diagnostico", "observaciones"], fks=[("id_cita", "CITAS", "id_cita")]),
    "RECETAS": dict(cols=[("id_receta", "int"), ("id_atencion", "int"), ("fecha_emision", "date"), ("indicaciones", "str"), ("created_at", "dt")],
                    pk=["id_receta"], uk=[], identity=True, nullable=["indicaciones"], fks=[("id_atencion", "ATENCIONES", "id_atencion")]),
    "DETALLE_RECETA": dict(cols=[("id_detalle", "int"), ("id_receta", "int"), ("id_farmaco", "int"), ("dosis", "str"), ("cantidad", "int"), ("duracion", "str"), ("created_at", "dt")],
                           pk=["id_detalle"], uk=[], identity=True, nullable=["duracion"],
                           fks=[("id_receta", "RECETAS", "id_receta"), ("id_farmaco", "FARMACOS", "id_farmaco")]),
    "FACTURACION": dict(cols=[("id_factura", "int"), ("id_paciente", "int"), ("fecha", "date"), ("metodo_pago", "str"), ("total", "dec"), ("created_at", "dt")],
                        pk=["id_factura"], uk=[], identity=True, nullable=[], fks=[("id_paciente", "PACIENTES", "id_paciente")]),
    "DETALLE_FACTURACION": dict(cols=[("id_detalle", "int"), ("id_factura", "int"), ("id_servicio", "int"), ("id_farmaco", "int"), ("cantidad", "int"),
                                      ("precio_unitario", "dec"), ("subtotal", "dec"), ("created_at", "dt")],
                                pk=["id_detalle"], uk=[], identity=True, nullable=["id_servicio", "id_farmaco"],
                                fks=[("id_factura", "FACTURACION", "id_factura"), ("id_servicio", "SERVICIOS", "id_servicio"), ("id_farmaco", "FARMACOS", "id_farmaco")]),
}
ORDEN = list(SPEC)


def p(msg=""):
    """print + archivo de log"""
    print(msg)
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(str(msg) + "\n")


def log(msg):
    p(f"[{time.strftime('%H:%M:%S')}] {msg}")


def extraer():
    """Lee los CSV como texto (sin interpretar nada todavia)."""
    if not os.path.isdir(RUTA_DATA):
        raise FileNotFoundError(f"No encuentro la carpeta de los CSV:\n  {RUTA_DATA}\nRevisa RUTA_DATA o usa --ruta.")
    faltan = [t for t in ORDEN if not os.path.isfile(os.path.join(RUTA_DATA, f"{t}.csv"))]
    if faltan:
        raise FileNotFoundError(f"Faltan archivos CSV en {RUTA_DATA}: {', '.join(t + '.csv' for t in faltan)}")
    crudos = {}
    for t in ORDEN:
        df = pd.read_csv(os.path.join(RUTA_DATA, f"{t}.csv"), dtype=str, keep_default_na=False, encoding="utf-8-sig")
        df = df.apply(lambda s: s.str.strip())
        df = df.where(df != "", None)                       # vacio -> NULL
        crudos[t] = df
        log(f"EXTRACCION  {t:24s} {len(df):5d} filas")
    return crudos



# ============================ 2. TRANSFORMACION ============================
DOMINIOS = {
    ("PACIENTES", "sexo"): {"M", "F"},
    ("PACIENTES", "estado_civil"): {"Soltero", "Casado", "Conviviente", "Divorciado", "Viudo"},
    ("PACIENTES", "tipo_sangre"): {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"},
    ("CITAS", "estado"): {"Programada", "Confirmada", "Atendida", "Cancelada", "No asistio"},
    ("HORARIOS_PERSONAL", "dia_semana"): {"Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"},
    ("FACTURACION", "metodo_pago"): {"Efectivo", "Tarjeta", "Transferencia", "Yape/Plin", "Seguro"},
}
# Reglas de negocio = los CHECK de la base. Cada funcion devuelve True en las filas que las VIOLAN.
REGLAS = {
    "SERVICIOS": [("precio >= 0", lambda d: d.precio < 0)],
    "FARMACOS": [("precio_unitario >= 0", lambda d: d.precio_unitario < 0), ("stock_minimo >= 0", lambda d: d.stock_minimo < 0)],
    "LOTES_FARMACOS": [("stock >= 0", lambda d: d.stock < 0), ("fec_vencimiento > fec_lote", lambda d: d.fec_vencimiento <= d.fec_lote)],
    "HORARIOS_PERSONAL": [("hora_fin > hora_inicio", lambda d: d.hora_fin <= d.hora_inicio)],
    "DETALLE_RECETA": [("cantidad > 0", lambda d: d.cantidad <= 0)],
    "FACTURACION": [("total >= 0", lambda d: d.total < 0)],
    "DETALLE_FACTURACION": [("servicio XOR farmaco", lambda d: d.id_servicio.notna() == d.id_farmaco.notna()),
                            ("cantidad > 0", lambda d: d.cantidad <= 0), ("precio_unitario >= 0", lambda d: d.precio_unitario < 0),
                            ("subtotal >= 0", lambda d: d.subtotal < 0)],
}
FORMATOS = {"date": "%Y-%m-%d", "time": "%H:%M:%S", "dt": "%Y-%m-%d %H:%M:%S"}


def _ejemplos(df, mask, col):
    return ", ".join(str(x) for x in df.loc[mask, col].head(5).tolist())


def transformar(crudos):
    errores, dfs = [], {}
    ahora = pd.Timestamp.now().floor("s")
    for t in ORDEN:
        spec, df = SPEC[t], crudos[t].copy()
        faltan = [c for c, _ in spec["cols"] if c not in df.columns]
        if faltan:
            errores.append(f"{t}: faltan columnas {faltan}")
            continue
        extra = [c for c in df.columns if c not in dict(spec["cols"])]
        if extra:
            log(f"AVISO {t}: columnas extra ignoradas {extra}")
        df = df[[c for c, _ in spec["cols"]]].copy()

        # --- tipos ---
        for c, tipo in spec["cols"]:
            s, vacio = df[c], df[c].isna()
            if tipo in ("int", "dec"):
                conv = pd.to_numeric(s, errors="coerce")
            elif tipo in FORMATOS:
                conv = pd.to_datetime(s, format=FORMATOS[tipo], errors="coerce")
            else:
                conv = s
            malos = conv.isna() & ~vacio
            if malos.any():
                errores.append(f"{t}.{c}: {malos.sum()} valores con formato invalido (ej. {_ejemplos(df, malos, c)})")
            df[c] = conv.astype("Int64") if tipo == "int" else conv
        if "created_at" in df and df["created_at"].isna().any():       # igual que el DEFAULT GETDATE()
            log(f"AVISO {t}: {df['created_at'].isna().sum()} filas sin created_at -> se asigna la hora actual")
            df["created_at"] = df["created_at"].fillna(ahora)

        # --- obligatorios ---
        for c, _ in spec["cols"]:
            if c not in spec["nullable"] and df[c].isna().any():
                errores.append(f"{t}.{c}: {df[c].isna().sum()} valores vacios en columna obligatoria")
        # --- PK / UK ---
        if df.duplicated(spec["pk"]).any():
            errores.append(f"{t}: PK duplicada {spec['pk']}")
        for u in spec["uk"]:
            if df[u].dropna().duplicated().any():
                errores.append(f"{t}.{u}: valores duplicados (UNIQUE)")
        # --- dominios y reglas ---
        for (tt, c), valores in DOMINIOS.items():
            if tt == t:
                malos = df[c].notna() & ~df[c].isin(valores)
                if malos.any():
                    errores.append(f"{t}.{c}: valores fuera de dominio (ej. {_ejemplos(df, malos, c)})")
        for desc, f in REGLAS.get(t, []):
            try:
                malos = f(df).fillna(False)
            except Exception as e:                                       # columna ya invalida por tipos
                continue
            if malos.any():
                errores.append(f"{t}: {malos.sum()} filas incumplen la regla [{desc}]")
        dfs[t] = df

    # --- integridad referencial (FK) ---
    for t in ORDEN:
        if t not in dfs:
            continue
        for col, ref, refcol in SPEC[t]["fks"]:
            if ref not in dfs:
                continue
            valores = dfs[t][col].dropna()
            huerfanos = ~valores.isin(dfs[ref][refcol])
            if huerfanos.any():
                errores.append(f"{t}.{col}: {huerfanos.sum()} valores sin padre en {ref}.{refcol} (ej. {valores[huerfanos].head(5).tolist()})")

    if errores:
        raise ValueError("TRANSFORMACION: se encontraron errores, NO se carga nada:\n - " + "\n - ".join(errores))
    log("TRANSFORMACION OK: tipos, obligatorios, PK/UK, dominios, reglas y FK validados")
    return dfs



# ============================ 3. CARGA ============================
def _a_python(v, tipo):
    if v is None or pd.isna(v):
        return None
    if tipo == "int":
        return int(v)
    if tipo == "dec":
        return Decimal(f"{float(v):.2f}")
    if tipo == "date":
        return v.date()
    if tipo == "time":
        return v.time()
    if tipo == "dt":
        return v.to_pydatetime()
    return v


def _odbc(valor):
    """Escapa un valor para la cadena ODBC (clave con ; } = etc.)."""
    return "{" + str(valor).replace("}", "}}") + "}"


def armar_cadena(driver):
    cs = f"DRIVER={{{driver}}};SERVER={SERVER};DATABASE={DATABASE};"
    cs += f"UID={_odbc(USUARIO)};PWD={_odbc(CLAVE or '')};" if USUARIO else "Trusted_Connection=yes;"
    if "ODBC Driver" in driver:
        cs += "TrustServerCertificate=yes;"
    return cs


def conectar():
    import pyodbc                                                        # se importa aqui para poder usar SOLO_VALIDAR sin pyodbc
    instalados = pyodbc.drivers()
    driver = next((d for d in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server") if d in instalados), None)
    if not driver:
        raise RuntimeError("No hay driver ODBC para SQL Server. Instala 'ODBC Driver 18 for SQL Server' (Microsoft). Drivers vistos: " + str(instalados))
    log(f"Conectando a {SERVER} / {DATABASE}  driver='{driver}'  autenticacion={'SQL login ' + USUARIO if USUARIO else 'Windows'} ...")
    return pyodbc.connect(armar_cadena(driver), autocommit=False)        # la cadena (con la clave) nunca se escribe en el log


def cargar(dfs):
    conn = conectar()
    cur = conn.cursor()
    t0 = time.time()
    try:
        cur.execute("SELECT @@SERVERNAME, DB_NAME(), SUSER_SNAME()")
        srv, bd, usr = cur.fetchone()
        log(f"Conexion OK  servidor={srv}  bd={bd}  usuario={usr}")

        # --- estado del destino ---
        existentes = {t: cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.{t}").fetchone()[0] for t in ORDEN}
        con_datos = {t: n for t, n in existentes.items() if n}
        if con_datos:
            if MODO_CARGA != "RECARGAR":
                raise RuntimeError(f"El destino ya tiene datos {con_datos}. Es una CARGA INICIAL: usa MODO_CARGA='RECARGAR' si quieres borrar y volver a cargar.")
            log("MODO RECARGAR: vaciando tablas destino (hijos primero) ...")
            for t in reversed(ORDEN):
                cur.execute(f"DELETE FROM {SCHEMA}.{t}")
                if SPEC[t]["identity"]:
                    cur.execute(f"DBCC CHECKIDENT ('{SCHEMA}.{t}', RESEED, 0) WITH NO_INFOMSGS")

        # --- insercion masiva, padres primero ---
        for t in ORDEN:
            spec, df = SPEC[t], dfs[t]
            cols = spec["cols"]
            filas = [tuple(_a_python(v, tipo) for v, (_, tipo) in zip(fila, cols)) for fila in df.itertuples(index=False, name=None)]
            sql = f"INSERT INTO {SCHEMA}.{t} ({', '.join(c for c, _ in cols)}) VALUES ({', '.join('?' * len(cols))})"
            cur.fast_executemany = not any(tipo == "time" for _, tipo in cols)   # tipo TIME: modo normal (mas compatible)
            if spec["identity"]:
                cur.execute(f"SET IDENTITY_INSERT {SCHEMA}.{t} ON")              # conserva los id_* del CSV (las FK los necesitan)
            for i in range(0, len(filas), 5000):
                cur.executemany(sql, filas[i:i + 5000])
            if spec["identity"]:
                cur.execute(f"SET IDENTITY_INSERT {SCHEMA}.{t} OFF")
            log(f"CARGA       {t:24s} {len(filas):5d} filas")

        conn.commit()
        log(f"COMMIT OK  ({time.time() - t0:.1f} s)")

        # --- verificacion: filas del CSV vs filas en la base ---
        p("\n" + "=" * 62 + f"\n{'TABLA':26s}{'CSV':>8s}{'BD':>8s}   ESTADO\n" + "=" * 62)
        todo_ok = True
        for t in ORDEN:
            n_bd = cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.{t}").fetchone()[0]
            ok = n_bd == len(dfs[t])
            todo_ok &= ok
            p(f"{t:26s}{len(dfs[t]):8d}{n_bd:8d}   {'OK' if ok else 'DIFERENCIA'}")
        p("=" * 62)
        p("CARGA INICIAL COMPLETA Y VERIFICADA" if todo_ok else "ATENCION: hay diferencias, revisa el detalle")
    except Exception:
        conn.rollback()
        log("ERROR: se hizo ROLLBACK, la base quedo como estaba.")
        raise
    finally:
        conn.close()


# ============================ MAIN ============================
def main():
    global RUTA_DATA, SERVER, DATABASE, MODO_CARGA, SOLO_VALIDAR, LOG_FILE
    ap = argparse.ArgumentParser(description="ETL carga inicial CSV -> SQL Server (BDClinica)")
    ap.add_argument("--ruta", default=RUTA_DATA, help="carpeta con los CSV")
    ap.add_argument("--server", default=SERVER, help="instancia de SQL Server")
    ap.add_argument("--database", default=DATABASE)
    ap.add_argument("--recargar", action="store_true", help="borra las tablas destino y recarga")
    ap.add_argument("--solo-validar", action="store_true", help="valida los CSV sin conectarse a la base")
    a = ap.parse_args()
    RUTA_DATA, SERVER, DATABASE = a.ruta, a.server, a.database
    MODO_CARGA = "RECARGAR" if a.recargar else MODO_CARGA
    SOLO_VALIDAR = a.solo_validar or SOLO_VALIDAR

    LOG_FILE = os.path.join(carpeta_logs(), f"etl_clinica_{time.strftime('%Y%m%d_%H%M%S')}.log")

    try:
        requeridas = [("ETL_RUTA_DATA / --ruta", RUTA_DATA)] + ([] if SOLO_VALIDAR else [("DB_SERVER / --server", SERVER), ("DB_NAME / --database", DATABASE)])
        faltan = [n for n, v in requeridas if not v]
        if faltan:
            raise ValueError("Falta configuracion: " + ", ".join(faltan) + ".\nCopia .env.example a .env y completalo (o usa los argumentos de la terminal).")
        log(f"INICIO  origen={RUTA_DATA}  destino={SERVER or '-'}/{DATABASE or '-'}.{SCHEMA}  modo={'SOLO_VALIDAR' if SOLO_VALIDAR else MODO_CARGA}")
        crudos = extraer()
        dfs = transformar(crudos)
        if SOLO_VALIDAR:
            log("SOLO_VALIDAR: no se toco la base de datos.")
        else:
            cargar(dfs)
        log(f"FIN OK  (log: {LOG_FILE})")
    except Exception as e:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(traceback.format_exc())
        p(f"\n*** ETL DETENIDO ***\n{e}\n(detalle tecnico en {LOG_FILE})")
        sys.exit(1)


if __name__ == "__main__":
    main()
