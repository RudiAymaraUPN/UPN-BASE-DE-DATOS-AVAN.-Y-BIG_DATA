# -*- coding: utf-8 -*-
r"""
ETL BDClinica (+ Excel inventario, Excel metas, CSV feriados)  ->  DWClinica (data mart dimensional)

Etapas: extraccion -> perfilamiento -> transformacion -> validacion (14 pruebas de cuadre) -> carga (una transaccion) -> bitacora.
Si alguna prueba de cuadre falla, NO se carga nada.

Modulos (--modulos) para programar cada fuente con su propia frecuencia:
  transaccional  FactCita, FactPrescripcion, FactFacturacionLinea, FactCapacidad (+ todas las dimensiones de BDClinica)   DIARIO
  inventario     FactInventarioLote  (Excel de farmacia)                                                                    MENSUAL
  metas          DimIndicador + FactMeta (Excel de gerencia)                                                                 ANUAL / cuando gerencia cambie metas
  feriados       DimFecha.es_feriado + FactCapacidad (CSV de feriados)                                                       ANUAL

Destino de reporteria: DWClinica (dw.* = modelo dimensional, rpt.* = KPI, calidad y pruebas ya calculados). Power BI se conecta a esa base; no se generan archivos.

Uso (terminal en la RAIZ del repositorio):
  python -m etl.datamart                                       # BDClinica -> DWClinica (todos los modulos)
  python -m etl.datamart --modulos transaccional              # solo la carga diaria
  python -m etl.datamart --origen csv --destino csv            # PRUEBA sin servidor: lee data/inicial y escribe CSV en data/salida_pruebas (no se versiona)
Configuracion sensible en .env (ver .env.example): DB_SERVER, DB_NAME, DW_NAME, DB_USER, DB_PASSWORD, DW_SAL_HASH, rutas.
"""
import argparse, hashlib, os, sys, time, traceback
from decimal import Decimal

import numpy as np
import pandas as pd

# Permite ejecutar el archivo directamente desde cualquier carpeta (py etl\carga_inicial.py o py .\carga_inicial.py)
import sys as _sys
from pathlib import Path as _Path
_raiz = str(_Path(__file__).resolve().parent.parent)
if _raiz not in _sys.path:
    _sys.path.insert(0, _raiz)

from etl import carga_inicial as base           # reutiliza el esquema de BDClinica y el criterio de conexion
from etl.config import cargar_env, carpeta_logs, ruta

cargar_env()
E = os.environ.get
SERVER, DB_ORIGEN, DB_DW = E("DB_SERVER"), E("DB_NAME", "BDClinica"), E("DW_NAME", "DWClinica")
SCHEMA, USUARIO, CLAVE = E("DB_SCHEMA", "clinica"), E("DB_USER") or None, E("DB_PASSWORD") or None
RUTA_CSV_BD = ruta("ETL_RUTA_DATA", "data/inicial")           # CSV de BDClinica (solo para --origen csv)
RUTA_FUENTES = ruta("DW_RUTA_FUENTES", "data/fuentes")        # Excel de inventario, Excel de metas y CSV de feriados
RUTA_SALIDA = ruta("DW_RUTA_SALIDA", "data/salida_pruebas")   # solo para --destino csv (pruebas sin servidor)
SAL = E("DW_SAL_HASH")                                # sal del hash SHA-256 del DNI (secreto: va en .env)
DURACION_CITA_MIN = int(E("DW_DURACION_CITA_MIN", "30"))   # BDClinica no guarda la duracion de la cita: parametro del DW
FECHA_CORTE = pd.Timestamp(E("ETL_FECHA_CORTE") or pd.Timestamp.now().normalize())
MODULOS_TODOS = ["transaccional", "inventario", "metas", "feriados"]
LOG_FILE = None
DIAS = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
MESES_ES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Setiembre", "Octubre", "Noviembre", "Diciembre"]
CAMPOS_IDENTIFICATORIOS = {"dni", "nombres", "apellidos", "telefono", "correo", "direccion", "fecha_nacimiento"}


def p(msg=""):
    print(msg)
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(str(msg) + "\n")


def log(msg):
    p(f"[{time.strftime('%H:%M:%S')}] {msg}")


# =============================== 1. EXTRACCION ===============================
def conectar(bd):
    import pyodbc
    inst = pyodbc.drivers()
    drv = next((d for d in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server") if d in inst), None)
    if not drv:
        raise RuntimeError("No hay driver ODBC para SQL Server. Instala 'ODBC Driver 18 for SQL Server'.")
    cs = f"DRIVER={{{drv}}};SERVER={SERVER};DATABASE={bd};"
    cs += f"UID={base._odbc(USUARIO)};PWD={base._odbc(CLAVE or '')};" if USUARIO else "Trusted_Connection=yes;"
    if "ODBC Driver" in drv:
        cs += "TrustServerCertificate=yes;"
    log(f"Conectando a {SERVER} / {bd} (autenticacion {'SQL login ' + USUARIO if USUARIO else 'Windows'})")
    return pyodbc.connect(cs, autocommit=False)


def extraer_bdclinica(origen):
    """F1. Lee las 15 tablas en modo solo lectura (SQL Server) o los CSV exportados."""
    out = {}
    if origen == "sqlserver":
        conn = conectar(DB_ORIGEN)
        for t in base.ORDEN:
            out[t] = pd.read_sql(f"SELECT * FROM {SCHEMA}.{t}", conn)
        conn.close()
    else:
        for t in base.ORDEN:
            out[t] = pd.read_csv(os.path.join(RUTA_CSV_BD, f"{t}.csv"), encoding="utf-8-sig")
    for t, df in out.items():
        for c, tipo in base.SPEC[t]["cols"]:
            if tipo == "date": df[c] = pd.to_datetime(df[c])
            elif tipo == "dt": df[c] = pd.to_datetime(df[c])
            elif tipo == "time": df[c] = df[c].astype(str).str.slice(0, 8)
    for t, df in out.items():
        log(f"EXTRACCION F1  {t:24s} {len(df):6d} filas")
    return out


def extraer_inventario():
    """F2. Todas las hojas como texto (dtype=object) para no perder el formato original; trazabilidad HOJA_ORIGEN / FILA_EXCEL."""
    ruta = os.path.join(RUTA_FUENTES, "Inventario_Fisico_Farmacia_2025-2026.xlsx")
    libro = pd.read_excel(ruta, sheet_name=None, dtype=object)
    partes = []
    for hoja, df in libro.items():
        df = df.copy(); df["HOJA_ORIGEN"] = hoja; df["FILA_EXCEL"] = np.arange(len(df)) + 2
        partes.append(df)
    inv = pd.concat(partes, ignore_index=True)
    log(f"EXTRACCION F2  Inventario fisico        {len(inv):6d} filas en {len(libro)} hojas")
    return inv


def extraer_metas():
    m = pd.read_excel(os.path.join(RUTA_FUENTES, "Metas_Indicadores_Gerencia_2026.xlsx"), sheet_name="Metas")
    log(f"EXTRACCION F3  Metas de gerencia        {len(m):6d} filas")
    return m


def extraer_feriados():
    f = pd.read_csv(os.path.join(RUTA_FUENTES, "feriados_peru_2025_2026.csv"), parse_dates=["fecha"], encoding="utf-8")
    log(f"EXTRACCION F4  Feriados                 {len(f):6d} filas")
    return f


# =============================== 2. PERFILAMIENTO ===============================
def _txt_fecha(v):
    return isinstance(v, str)


def _num_stock(v):
    """'23 und' -> 23 ; vacio -> NaN ; numero -> numero."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    d = "".join(ch for ch in str(v) if ch.isdigit() or ch == "-")
    return float(d) if d not in ("", "-") else np.nan


def _parse_fecha(v):
    if isinstance(v, str):
        return pd.to_datetime(v.strip(), format="%d/%m/%Y", errors="coerce")
    return pd.to_datetime(v, errors="coerce")


def _norm_lote(v):
    return str(v).upper().replace("-", "").replace(" ", "").strip()


def _esperas(bd):
    """minutos entre la hora programada de la cita y la hora real de atencion."""
    a, c = bd["ATENCIONES"], bd["CITAS"]
    m = a.merge(c[["id_cita", "fecha", "hora"]], on="id_cita")
    prog = pd.to_datetime(m["fecha"].dt.strftime("%Y-%m-%d") + " " + m["hora"])
    m["espera"] = (m["fecha_atencion"] - prog).dt.total_seconds() / 60
    return m[["id_atencion", "id_cita", "espera"]]


def _norm_diag(s):
    s = " ".join(str(s).split())
    return s.capitalize() if (s.islower() or s.isupper()) else s


def perfilar(bd, inv=None):
    """Controles de calidad con conteo y %: cada fila = (fuente, tabla, problema, registros, total, tratamiento)."""
    r = []
    add = lambda f, t, prob, n, tot, trat: r.append(dict(fuente=f, tabla=t, problema=prob, registros=int(n), total=int(tot), pct=round(100 * n / tot, 2) if tot else 0, tratamiento=trat))
    c, a, pa, fa, df_ = bd["CITAS"], bd["ATENCIONES"], bd["PACIENTES"], bd["FACTURACION"], bd["DETALLE_FACTURACION"]
    lot, pe = bd["LOTES_FARMACOS"], bd["PERSONAL_ESPECIALIDAD"]
    pend = c.estado.isin(["Programada", "Confirmada"]) & (c.fecha < FECHA_CORTE)
    add("F1", "CITAS", "Cita Programada/Confirmada con fecha anterior al corte (sin cierre)", pend.sum(), len(c), "Se clasifica como 'Sin cierre' y se excluye del calculo de inasistencia")
    add("F1", "CITAS", "Cita Atendida sin atencion registrada", (c.estado.eq("Atendida") & ~c.id_cita.isin(a.id_cita)).sum(), len(c), "Se carga con diagnostico 'Sin atencion'; se reporta")
    add("F1", "CITAS", "Cita con atencion pero estado distinto de Atendida", (~c.estado.eq("Atendida") & c.id_cita.isin(a.id_cita)).sum(), len(c), "Se carga tal cual; se reporta al area de admision")
    sin_esp = ~c.id_personal.isin(pe.id_personal)
    add("F1", "CITAS", "Profesional de la cita sin especialidad registrada", sin_esp.sum(), len(c), "Especialidad 'No aplica' (clave -1)")
    mult = pe.groupby("id_personal").size()
    add("F1", "CITAS", "Profesional con mas de una especialidad (la cita no indica cual)", c.id_personal.isin(mult[mult > 1].index).sum(), len(c), "Se usa la especialidad de menor id (principal)")
    nulos = a.diagnostico.isna() | a.diagnostico.astype(str).str.strip().eq("")
    add("F1", "ATENCIONES", "Diagnostico nulo o vacio", nulos.sum(), len(a), "Diagnostico 'No codificado' (clave -1)")
    nonstd = a.diagnostico.notna() & (a.diagnostico.astype(str) != a.diagnostico.astype(str).map(_norm_diag))
    add("F1", "ATENCIONES", "Diagnostico con espacios o mayusculas no estandar", nonstd.sum(), len(a), "Se estandariza (espacios y mayusculas) para agrupar")
    e = _esperas(bd)
    add("F1", "ATENCIONES", "Hora de atencion anterior a la hora de la cita (espera negativa)", (e.espera < 0).sum(), len(a), "Se excluye del promedio de espera")
    add("F1", "ATENCIONES", "Espera atipica mayor a 240 minutos", (e.espera > 240).sum(), len(a), "Se excluye del promedio de espera")
    dup = pa.assign(k=pa.nombres.str.upper().str.strip() + "|" + pa.apellidos.str.upper().str.strip() + "|" + pa.fecha_nacimiento.astype(str)).groupby("k").dni.nunique()
    add("F1", "PACIENTES", "Posible paciente duplicado (mismo nombre y fecha de nacimiento, distinto DNI)", (dup > 1).sum(), len(pa), "Se carga y se reporta a Admision (no se fusiona sin validar)")
    add("F1", "PACIENTES", "Estado civil nulo", pa.estado_civil.isna().sum(), len(pa), "No se usa en el analisis")
    add("F1", "PACIENTES", "Tipo de sangre nulo", pa.tipo_sangre.isna().sum(), len(pa), "No se usa en el analisis")
    add("F1", "PACIENTES", "Telefono nulo", pa.telefono.isna().sum(), len(pa), "No se usa (dato de contacto, no pasa al DW)")
    add("F1", "PACIENTES", "Telefono con formato no estandar (no son 9 digitos)", (pa.telefono.notna() & ~pa.telefono.astype(str).str.fullmatch(r"\d{9}")).sum(), len(pa), "No se usa (dato de contacto, no pasa al DW)")
    add("F1", "PACIENTES", "Direccion sin distrito (sin coma)", (~pa.direccion.fillna("").str.contains(",")).sum(), len(pa), "Distrito 'Sin distrito'")
    suma = df_.groupby("id_factura").subtotal.sum()
    desc = fa.set_index("id_factura").total.sub(suma, fill_value=0).abs().round(2) > 0.01
    add("F1", "FACTURACION", "Total de cabecera distinto a la suma de sus lineas", desc.sum(), len(fa), "Los ingresos se calculan con las lineas (RN-16); se reporta")
    add("F1", "FACTURACION", "Comprobante sin lineas de detalle", (~fa.id_factura.isin(df_.id_factura)).sum(), len(fa), "No genera filas en FactFacturacionLinea; se reporta")
    add("F1", "DETALLE_FACTURACION", "Subtotal distinto de cantidad x precio unitario", ((df_.cantidad * df_.precio_unitario - df_.subtotal).abs() > 0.011).sum(), len(df_), "monto = cantidad x precio_unitario")
    add("F1", "LOTES_FARMACOS", "Lote con stock en cero", (lot.stock == 0).sum(), len(lot), "Se carga; no cuenta como stock vigente")
    add("F1", "LOTES_FARMACOS", "Lote vencido a la fecha de corte", (lot.fec_vencimiento < FECHA_CORTE).sum(), len(lot), "Se marca estado 'Vencido' en el inventario")
    if inv is not None:
        n = len(inv); s = inv["STOCK FÍSICO"]
        isnum = s.map(lambda v: isinstance(v, (int, float, np.integer, np.floating)) and not (isinstance(v, float) and np.isnan(v)))
        vacio = s.isna()
        add("F2", "Inventario", "Stock fisico vacio", vacio.sum(), n, "Fila rechazada")
        add("F2", "Inventario", "Stock con texto (p. ej. '12 und')", (s.map(lambda v: isinstance(v, str))).sum(), n, "Se extrae el numero ('23 und' -> 23)")
        add("F2", "Inventario", "Stock negativo", (s.map(_num_stock) < 0).sum(), n, "Fila rechazada")
        add("F2", "Inventario", "Fecha de corte como texto dd/mm/aaaa", inv["FECHA CORTE"].map(_txt_fecha).sum(), n, "Se convierte a fecha")
        add("F2", "Inventario", "Fecha de vencimiento como texto dd/mm/aaaa", inv["F. VENCIMIENTO"].map(_txt_fecha).sum(), n, "Se convierte a fecha")
        prod = inv["PRODUCTO"].astype(str)
        add("F2", "Inventario", "Producto con mayusculas o espacios extra", ((prod != prod.str.strip()) | prod.str.strip().str.isupper()).sum(), n, "Se recorta y se compara en mayusculas")
        lt = inv["N° LOTE"].astype(str)
        add("F2", "Inventario", "N° de lote en minusculas o con guion", (lt != lt.map(_norm_lote)).sum(), n, "Se pasa a mayusculas y se retira el guion")
        add("F2", "Inventario", "Fila duplicada exacta", inv.drop(columns=["FILA_EXCEL"]).astype(str).duplicated().sum(), n, "Se conserva la primera; el resto se rechaza")
        add("F2", "Inventario", "Lote inexistente en LOTES_FARMACOS (muestra medica)", (~inv["N° LOTE"].map(_norm_lote).isin(lot.nro_lote.map(_norm_lote))).sum(), n, "Fila rechazada")
    prof = pd.DataFrame(r)
    log(f"PERFILAMIENTO  {len(prof)} controles ejecutados, {int((prof.registros > 0).sum())} con hallazgos")
    return prof


# =============================== 3. TRANSFORMACION ===============================
def _claves_estables(existentes, textos):
    """Conserva la clave de lo ya cargado y asigna max+1 a lo nuevo (claves sustitutas estables entre cargas)."""
    mapa = dict(existentes or {})
    sig = max([k for k in mapa.values()] + [0]) + 1
    for t in sorted(set(textos) - set(mapa)):
        mapa[t] = sig; sig += 1
    return mapa


def construir_dimfecha(feriados):
    f = pd.DataFrame({"fecha": pd.date_range("2024-01-01", "2028-12-31")})
    f["fecha_key"] = f.fecha.dt.strftime("%Y%m%d").astype(int)
    f["anio"], f["mes"], f["trimestre"] = f.fecha.dt.year, f.fecha.dt.month, f.fecha.dt.quarter
    f["nombre_mes"] = f.mes.map(lambda m: MESES_ES[m])
    f["anio_mes"] = f.fecha.dt.strftime("%Y-%m")
    f["semana_iso"] = f.fecha.dt.isocalendar().week.astype(int)
    f["dia_semana"] = f.fecha.dt.dayofweek.map(lambda i: DIAS[i])
    ferm = dict(zip(feriados.fecha, feriados.descripcion)) if feriados is not None else {}
    f["es_feriado"] = f.fecha.isin(ferm).astype(int)
    f["descripcion_feriado"] = f.fecha.map(ferm)
    return f[["fecha_key", "fecha", "anio", "trimestre", "mes", "nombre_mes", "anio_mes", "semana_iso", "dia_semana", "es_feriado", "descripcion_feriado"]]


def _grupo_etario(fnac, ref):
    edad = (ref - fnac).dt.days // 365.25
    return pd.cut(edad, [-1, 11, 17, 29, 59, 200], labels=["Nino (0-11)", "Adolescente (12-17)", "Joven (18-29)", "Adulto (30-59)", "Adulto mayor (60+)"]).astype(str)


def transformar(bd, feriados, metas, inv, modulos, existentes=None):
    """Devuelve (dims, hechos, rechazos, mapa_paciente, info). Nada se escribe aun."""
    existentes = existentes or {}
    if SAL is None:
        raise ValueError("Falta DW_SAL_HASH en el .env (sal secreta del hash SHA-256 del DNI).")
    D, F, rech, ahora = {}, {}, [], FECHA_CORTE
    pa, pers, cit, ate = bd["PACIENTES"], bd["PERSONAL"], bd["CITAS"], bd["ATENCIONES"]

    # ----- dimensiones -----
    D["DimFecha"] = construir_dimfecha(feriados)
    D["DimPaciente"] = pd.DataFrame({
        "paciente_key": pa.id_paciente, "sexo": pa.sexo.map({"M": "Masculino", "F": "Femenino"}),
        "grupo_etario_actual": _grupo_etario(pa.fecha_nacimiento, ahora),
        "distrito": pa.direccion.fillna("").map(lambda s: s.split(",")[-1].strip() if "," in s else "Sin distrito")})
    mapa = pd.DataFrame({"paciente_key": pa.id_paciente, "id_paciente_origen": pa.id_paciente,
                         "dni_hash": pa.dni.astype(str).map(lambda d: hashlib.sha256((SAL + d).encode()).hexdigest())})
    esp = bd["ESPECIALIDADES"]
    D["DimEspecialidad"] = pd.concat([pd.DataFrame({"especialidad_key": [-1], "especialidad": ["No aplica"], "duracion_cita_min": [DURACION_CITA_MIN]}),
                                      pd.DataFrame({"especialidad_key": esp.id_especialidad, "especialidad": esp.nombre_especialidad, "duracion_cita_min": DURACION_CITA_MIN})], ignore_index=True)
    pe = bd["PERSONAL_ESPECIALIDAD"].sort_values(["id_personal", "id_especialidad"]).drop_duplicates("id_personal")
    esp_pers = dict(zip(pe.id_personal, pe.id_especialidad))
    nom_esp = dict(zip(esp.id_especialidad, esp.nombre_especialidad)); nom_car = dict(zip(bd["CARGOS"].id_cargo, bd["CARGOS"].nombre_cargo))
    D["DimPersonal"] = pd.DataFrame({
        "personal_key": pers.id_personal, "profesional": (pers.nombres + " " + pers.apellidos), "cargo": pers.id_cargo.map(nom_car),
        "especialidad_principal": pers.id_personal.map(lambda i: nom_esp.get(esp_pers.get(i), "No aplica")), "nro_colegiatura": pers.nro_colegiatura})
    D["DimEstadoCita"] = pd.DataFrame({"estado_key": [1, 2, 3, 4, 5, 6], "estado": ["Atendida", "No asistio", "Cancelada", "Programada", "Confirmada", "Sin cierre"],
                                       "cuenta_para_inasistencia": [1, 1, 0, 0, 0, 0]})
    ate = ate.copy(); ate["diag"] = ate.diagnostico.map(lambda s: _norm_diag(s) if pd.notna(s) and str(s).strip() else None)
    textos = ate.diag.dropna().unique().tolist()
    mp = _claves_estables(existentes.get("DimDiagnostico"), textos)
    D["DimDiagnostico"] = pd.concat([pd.DataFrame({"diagnostico_key": [-1, 0], "diagnostico": ["No codificado", "Sin atencion"]}),
                                     pd.DataFrame({"diagnostico_key": list(mp.values()), "diagnostico": list(mp.keys())}).query("diagnostico in @textos")], ignore_index=True)
    far = bd["FARMACOS"]
    D["DimFarmaco"] = pd.concat([pd.DataFrame({"farmaco_key": [-1], "farmaco": ["No aplica"], "presentacion": [None], "precio_vigente": [0.0], "stock_minimo": [0]}),
                                 pd.DataFrame({"farmaco_key": far.id_farmaco, "farmaco": far.nombre_farmaco, "presentacion": far.presentacion, "precio_vigente": far.precio_unitario, "stock_minimo": far.stock_minimo})], ignore_index=True)
    lot = bd["LOTES_FARMACOS"]
    D["DimLote"] = pd.DataFrame({"lote_key": lot.id_lote, "nro_lote": lot.nro_lote, "fec_lote": lot.fec_lote, "fec_vencimiento": lot.fec_vencimiento, "farmaco_key": lot.id_farmaco})
    sv = bd["SERVICIOS"]
    D["DimServicio"] = pd.concat([pd.DataFrame({"servicio_key": [-1], "servicio": ["No aplica"], "precio_vigente": [0.0]}),
                                  pd.DataFrame({"servicio_key": sv.id_servicio, "servicio": sv.nombre_servicio, "precio_vigente": sv.precio})], ignore_index=True)
    D["DimMetodoPago"] = pd.DataFrame({"metodo_key": [1, 2, 3, 4, 5], "metodo_pago": ["Efectivo", "Tarjeta", "Transferencia", "Yape/Plin", "Seguro"],
                                       "tipo": ["Efectivo", "Electronico", "Electronico", "Billetera digital", "Seguro"]})
    if metas is not None:
        ind = metas[["INDICADOR", "UNIDAD", "SENTIDO", "AREA"]].drop_duplicates("INDICADOR").reset_index(drop=True)
        D["DimIndicador"] = pd.DataFrame({"indicador_key": np.arange(1, len(ind) + 1), "indicador": ind.INDICADOR, "unidad": ind.UNIDAD, "sentido": ind.SENTIDO, "area_responsable": ind.AREA})

    # ----- FactCita -----
    ek = dict(zip(D["DimEstadoCita"].estado, D["DimEstadoCita"].estado_key))
    c = cit.copy()
    c["estado_dw"] = np.where(c.estado.isin(["Programada", "Confirmada"]) & (c.fecha < ahora), "Sin cierre", c.estado)
    c["espera"] = c.id_cita.map(_esperas(bd).set_index("id_cita").espera)
    dk = dict(zip(D["DimDiagnostico"].diagnostico, D["DimDiagnostico"].diagnostico_key))
    c["diag_key"] = c.id_cita.map(ate.set_index("id_cita").diag.map(lambda s: dk[s] if s in dk else -1)).fillna(0).astype(int)
    c["esp_key"] = c.id_personal.map(lambda i: esp_pers.get(i, -1))
    valida = c.espera.between(0, 240)
    hecho = pd.DataFrame({
        "id_cita": c.id_cita, "fecha_key": c.fecha.dt.strftime("%Y%m%d").astype(int), "paciente_key": c.id_paciente, "personal_key": c.id_personal,
        "especialidad_key": c.esp_key, "estado_key": c.estado_dw.map(ek), "diagnostico_key": c.diag_key, "cantidad_cita": 1,
        "flag_atendida": (c.estado_dw == "Atendida").astype(int), "flag_no_asistida": (c.estado_dw == "No asistio").astype(int),
        "flag_cancelada": (c.estado_dw == "Cancelada").astype(int), "flag_sin_cierre": (c.estado_dw == "Sin cierre").astype(int),
        "flag_pendiente": c.estado_dw.isin(["Programada", "Confirmada"]).astype(int), "minutos_programados": DURACION_CITA_MIN,
        "minutos_espera": c.espera.where(valida).round(0), "flag_espera_valida": valida.astype(int)})
    hecho["minutos_espera"] = hecho["minutos_espera"].astype("Int64")      # entero o NULL (pyodbc no mezcla enteros y decimales en una columna)
    F["FactCita"] = hecho

    # ----- FactCapacidad (turnos de profesionales con especialidad, dias no feriados) -----
    hor = bd["HORARIOS_PERSONAL"]; hor = hor[hor.id_personal.isin(esp_pers)]
    fechas = D["DimFecha"][(D["DimFecha"].fecha >= cit.fecha.min()) & (D["DimFecha"].fecha <= cit.fecha.max()) & (D["DimFecha"].es_feriado == 0)]
    hor = hor.assign(min_turno=[(pd.to_timedelta(f) - pd.to_timedelta(i)).total_seconds() // 60 for i, f in zip(hor.hora_inicio, hor.hora_fin)])
    cap = fechas[["fecha_key", "dia_semana"]].merge(hor[["id_horario", "id_personal", "dia_semana", "min_turno"]], on="dia_semana")
    F["FactCapacidad"] = pd.DataFrame({"fecha_key": cap.fecha_key, "id_horario": cap.id_horario, "personal_key": cap.id_personal,
                                       "especialidad_key": cap.id_personal.map(esp_pers), "turnos_programados": 1,
                                       "minutos_disponibles": cap.min_turno.astype(int), "cupos_disponibles": (cap.min_turno // DURACION_CITA_MIN).astype(int)})

    # ----- FactPrescripcion -----
    dr, rc = bd["DETALLE_RECETA"], bd["RECETAS"]
    m = dr.merge(rc[["id_receta", "id_atencion", "fecha_emision"]], on="id_receta").merge(ate[["id_atencion", "id_cita"]], on="id_atencion").merge(
        c[["id_cita", "id_paciente", "id_personal", "esp_key", "diag_key"]], on="id_cita")
    F["FactPrescripcion"] = pd.DataFrame({"id_detalle_receta": m.id_detalle, "id_receta": m.id_receta, "fecha_key": m.fecha_emision.dt.strftime("%Y%m%d").astype(int),
                                          "paciente_key": m.id_paciente, "personal_key": m.id_personal, "especialidad_key": m.esp_key, "diagnostico_key": m.diag_key,
                                          "farmaco_key": m.id_farmaco, "cantidad_prescrita": m.cantidad})

    # ----- FactFacturacionLinea -----
    dfc, fc = bd["DETALLE_FACTURACION"], bd["FACTURACION"]
    mk = {"Efectivo": 1, "Tarjeta": 2, "Transferencia": 3, "Yape/Plin": 4, "Seguro": 5}
    m = dfc.merge(fc[["id_factura", "id_paciente", "fecha", "metodo_pago"]], on="id_factura")
    F["FactFacturacionLinea"] = pd.DataFrame({
        "id_detalle_factura": m.id_detalle, "id_factura": m.id_factura, "fecha_key": m.fecha.dt.strftime("%Y%m%d").astype(int), "paciente_key": m.id_paciente,
        "servicio_key": m.id_servicio.fillna(-1).astype(int), "farmaco_key": m.id_farmaco.fillna(-1).astype(int), "metodo_key": m.metodo_pago.map(mk),
        "cantidad": m.cantidad, "precio_unitario": m.precio_unitario, "monto": (m.cantidad * m.precio_unitario).round(2)})

    # ----- FactInventarioLote (F2) -----
    if inv is not None:
        i = inv.copy()
        i["motivo"] = None
        i["corte"] = i["FECHA CORTE"].map(_parse_fecha); i["venc_x"] = i["F. VENCIMIENTO"].map(_parse_fecha)
        i["lote_n"] = i["N° LOTE"].map(_norm_lote); i["stock_n"] = i["STOCK FÍSICO"].map(_num_stock)
        i.loc[i["STOCK FÍSICO"].isna(), "motivo"] = "Stock fisico vacio"
        i.loc[i.motivo.isna() & (i.stock_n < 0), "motivo"] = "Stock negativo"
        i.loc[i.motivo.isna() & ~i.lote_n.isin(lot.nro_lote.map(_norm_lote)), "motivo"] = "Lote inexistente en LOTES_FARMACOS"
        i.loc[i.motivo.isna() & i.duplicated(["corte", "lote_n"], keep="first"), "motivo"] = "Fila duplicada en el inventario (mismo corte y lote)"
        for r_ in i[i.motivo.notna()].itertuples():
            rech.append(dict(fuente="F2", tabla="Inventario", clave_origen=f"{r_.HOJA_ORIGEN}!fila {r_.FILA_EXCEL}", motivo=r_.motivo, nivel="RECHAZO"))
        ok = i[i.motivo.isna()].merge(lot.assign(lote_n=lot.nro_lote.map(_norm_lote))[["lote_n", "id_lote", "id_farmaco", "fec_vencimiento"]], on="lote_n")
        ok = ok.merge(far[["id_farmaco", "precio_unitario"]], on="id_farmaco")
        dias = (ok.fec_vencimiento - ok.corte).dt.days
        F["FactInventarioLote"] = pd.DataFrame({
            "fecha_corte_key": ok.corte.dt.strftime("%Y%m%d").astype(int), "lote_key": ok.id_lote, "farmaco_key": ok.id_farmaco,
            "stock_fisico": ok.stock_n.astype(int), "valor_stock": (ok.stock_n * ok.precio_unitario).round(2), "dias_para_vencer": dias,
            "estado_vencimiento": np.select([dias < 0, dias <= 30, dias <= 90], ["Vencido", "0-30 dias", "31-90 dias"], "Mas de 90 dias")})
    # ----- FactMeta (F3) -----
    if metas is not None:
        ik = dict(zip(D["DimIndicador"].indicador, D["DimIndicador"].indicador_key))
        F["FactMeta"] = pd.DataFrame({"indicador_key": metas.INDICADOR.map(ik), "anio_mes": metas.PERIODO.astype(str), "valor_meta": metas.META.astype(float)})

    # ----- advertencias (se cargan y se reportan) -----
    for t, mask, motivo, col in [
        ("CITAS", c.estado_dw == "Sin cierre", "Cita Programada/Confirmada con fecha pasada -> 'Sin cierre'", "id_cita"),
        ("CITAS", c.espera.notna() & ~valida, "Espera fuera de rango (<0 o >240 min), excluida del promedio", "id_cita"),
        ("CITAS", c.diag_key.eq(-1), "Diagnostico nulo -> 'No codificado'", "id_cita")]:
        for k in c.loc[mask, col]:
            rech.append(dict(fuente="F1", tabla=t, clave_origen=str(k), motivo=motivo, nivel="ADVERTENCIA"))
    suma = dfc.groupby("id_factura").subtotal.sum()
    for k, v in (fc.set_index("id_factura").total.sub(suma, fill_value=0).abs().round(2) > 0.01).items():
        if v: rech.append(dict(fuente="F1", tabla="FACTURACION", clave_origen=str(k), motivo="Total de cabecera distinto a la suma de lineas", nivel="ADVERTENCIA"))
    log("TRANSFORMACION OK  " + ", ".join(f"{k}={len(v)}" for k, v in {**D, **F}.items()))
    return D, F, pd.DataFrame(rech, columns=["fuente", "tabla", "clave_origen", "motivo", "nivel"]), mapa


# =============================== 4. VALIDACION ===============================
def validar(bd, D, F, mapa, rech, inv, modulos):
    """14 pruebas de cuadre fuente vs data mart. Devuelve DataFrame(prueba, descripcion, fuente, data_mart, resultado)."""
    t, res = {}, []
    c, a, dr, dfc, fa = bd["CITAS"], bd["ATENCIONES"], bd["DETALLE_RECETA"], bd["DETALLE_FACTURACION"], bd["FACTURACION"]
    fc = F["FactCita"]; fcap = F.get("FactCapacidad")
    pend = c.estado.isin(["Programada", "Confirmada"]) & (c.fecha < FECHA_CORTE)
    def prueba(n, desc, src, dm, tol=0.005):
        ok = abs(float(src) - float(dm)) <= tol
        res.append(dict(prueba=n, descripcion=desc, fuente=src, data_mart=dm, resultado="OK" if ok else "ERROR"))
    prueba("P01", "N.° de citas", len(c), len(fc))
    prueba("P02", "Citas atendidas", (c.estado == "Atendida").sum(), fc.flag_atendida.sum())
    prueba("P03", "Citas no asistidas", (c.estado == "No asistio").sum(), fc.flag_no_asistida.sum())
    prueba("P04", "Atenciones registradas vs citas con diagnostico distinto de 'Sin atencion'", len(a), (fc.diagnostico_key != 0).sum())
    prueba("P05", "Lineas de receta", len(dr), len(F["FactPrescripcion"]))
    prueba("P06", "Unidades prescritas", dr.cantidad.sum(), F["FactPrescripcion"].cantidad_prescrita.sum())
    prueba("P07", "Lineas de comprobante", len(dfc), len(F["FactFacturacionLinea"]))
    prueba("P08", "Ingresos (S/) suma de lineas", dfc.subtotal.sum(), F["FactFacturacionLinea"].monto.sum(), tol=0.01)
    prueba("P09", "N.° de comprobantes con lineas", dfc.id_factura.nunique(), F["FactFacturacionLinea"].id_factura.nunique())
    if inv is not None:
        rej = (rech.tabla == "Inventario") & (rech.nivel == "RECHAZO")
        prueba("P10", "Filas inventario: entrada - rechazos = cargadas", len(inv) - rej.sum(), len(F["FactInventarioLote"]))
    else:
        res.append(dict(prueba="P10", descripcion="Filas inventario: entrada - rechazos = cargadas", fuente="-", data_mart="-", resultado="OMITIDA"))
    prueba("P11", "Columnas identificatorias en DimPaciente", 0, len(CAMPOS_IDENTIFICATORIOS & set(D["DimPaciente"].columns)))
    huerfanas = 0
    refs = {"FactCita": [("fecha_key", "DimFecha", "fecha_key"), ("paciente_key", "DimPaciente", "paciente_key"), ("personal_key", "DimPersonal", "personal_key"),
                         ("especialidad_key", "DimEspecialidad", "especialidad_key"), ("estado_key", "DimEstadoCita", "estado_key"), ("diagnostico_key", "DimDiagnostico", "diagnostico_key")],
            "FactCapacidad": [("fecha_key", "DimFecha", "fecha_key"), ("personal_key", "DimPersonal", "personal_key"), ("especialidad_key", "DimEspecialidad", "especialidad_key")],
            "FactPrescripcion": [("fecha_key", "DimFecha", "fecha_key"), ("paciente_key", "DimPaciente", "paciente_key"), ("personal_key", "DimPersonal", "personal_key"),
                                 ("especialidad_key", "DimEspecialidad", "especialidad_key"), ("diagnostico_key", "DimDiagnostico", "diagnostico_key"), ("farmaco_key", "DimFarmaco", "farmaco_key")],
            "FactFacturacionLinea": [("fecha_key", "DimFecha", "fecha_key"), ("paciente_key", "DimPaciente", "paciente_key"), ("servicio_key", "DimServicio", "servicio_key"),
                                     ("farmaco_key", "DimFarmaco", "farmaco_key"), ("metodo_key", "DimMetodoPago", "metodo_key")],
            "FactInventarioLote": [("fecha_corte_key", "DimFecha", "fecha_key"), ("lote_key", "DimLote", "lote_key"), ("farmaco_key", "DimFarmaco", "farmaco_key")],
            "FactMeta": [("indicador_key", "DimIndicador", "indicador_key")]}
    for h, lst in refs.items():
        if h in F:
            for col, dim, k in lst:
                huerfanas += int((~F[h][col].isin(D[dim][k])).sum())
    prueba("P12", "Claves foraneas huerfanas en los hechos", 0, huerfanas)
    prueba("P13", "Citas duplicadas en FactCita", 0, int(fc.id_cita.duplicated().sum()))
    ate_c = c[c.id_cita.isin(a.id_cita)]
    excl = int(((fc.flag_espera_valida == 0) & fc.id_cita.isin(ate_c.id_cita)).sum()); val = int(((fc.flag_espera_valida == 1)).sum())
    prueba("P14", "Atenciones con espera valida + excluidas = atenciones", len(a), val + excl)
    df = pd.DataFrame(res)
    for r in df.itertuples():
        log(f"CUADRE {r.prueba}  {r.descripcion:62s} fuente={r.fuente}  dw={r.data_mart}  {r.resultado}")
    return df


# =============================== 5. INDICADORES ===============================
def calcular_kpis(D, F):
    """Los 7 KPI por mes (mismas formulas que las vistas de 02_vistas_kpi.sql)."""
    fc = F["FactCita"].merge(D["DimFecha"][["fecha_key", "anio_mes"]], on="fecha_key")
    g = fc.groupby("anio_mes")
    k = pd.DataFrame({"atendidas": g.flag_atendida.sum(), "no_asistidas": g.flag_no_asistida.sum(), "espera_prom": g.apply(lambda x: x.minutos_espera.mean()),
                      "esperas_validas": g.flag_espera_valida.sum()})
    k["inasistencia_pct"] = 100 * k.no_asistidas / (k.atendidas + k.no_asistidas)
    cap = F["FactCapacidad"].merge(D["DimFecha"][["fecha_key", "anio_mes"]], on="fecha_key").groupby("anio_mes")[["turnos_programados", "cupos_disponibles"]].sum()
    k = k.join(cap)
    k["ocupacion_pct"] = 100 * k.atendidas / k.cupos_disponibles
    k["atenciones_por_turno"] = k.atendidas / k.turnos_programados
    ing = F["FactFacturacionLinea"].merge(D["DimFecha"][["fecha_key", "anio_mes"]], on="fecha_key").groupby("anio_mes").agg(ingresos=("monto", "sum"), comprobantes=("id_factura", "nunique"))
    k = k.join(ing)
    k["ticket_prom"] = k.ingresos / k.comprobantes
    if "FactInventarioLote" in F:
        inv = F["FactInventarioLote"].merge(D["DimFecha"][["fecha_key", "anio_mes"]], left_on="fecha_corte_key", right_on="fecha_key")
        riesgo = inv[inv.dias_para_vencer <= 90].groupby("anio_mes").valor_stock.sum()
        vig = inv[inv.dias_para_vencer >= 0].groupby(["anio_mes", "farmaco_key"]).stock_fisico.sum().unstack(fill_value=0)
        minimos = D["DimFarmaco"].set_index("farmaco_key").stock_minimo; minimos = minimos[minimos.index > 0]
        vig = vig.reindex(columns=minimos.index, fill_value=0)
        k["riesgo_vencimiento"] = riesgo.reindex(inv.anio_mes.unique()).fillna(0)       # 0 = hubo corte y nada en riesgo; NaN = sin corte
        k["farmacos_bajo_minimo"] = (vig < minimos).sum(axis=1)
    if "FactMeta" in F:
        ind = D["DimIndicador"].set_index("indicador_key").indicador
        mt = F["FactMeta"].assign(ind=lambda d: d.indicador_key.map(ind)).pivot(index="anio_mes", columns="ind", values="valor_meta")
        k["meta_ingresos"] = mt.get("Ingresos totales")
    return k.round(4)


# =============================== 6. CARGA ===============================
HECHOS_POR_MODULO = {"transaccional": ["FactCita", "FactPrescripcion", "FactFacturacionLinea", "FactCapacidad"], "inventario": ["FactInventarioLote"],
                     "metas": ["FactMeta"], "feriados": ["FactCapacidad"]}
DIMS_ORDEN = ["DimFecha", "DimPaciente", "DimEspecialidad", "DimPersonal", "DimEstadoCita", "DimDiagnostico", "DimFarmaco", "DimLote", "DimServicio", "DimMetodoPago", "DimIndicador"]
HECHOS_ORDEN = ["FactCita", "FactCapacidad", "FactPrescripcion", "FactFacturacionLinea", "FactInventarioLote", "FactMeta"]
CLAVES = {"DimFecha": "fecha_key", "DimPaciente": "paciente_key", "DimEspecialidad": "especialidad_key", "DimPersonal": "personal_key", "DimEstadoCita": "estado_key",
          "DimDiagnostico": "diagnostico_key", "DimFarmaco": "farmaco_key", "DimLote": "lote_key", "DimServicio": "servicio_key", "DimMetodoPago": "metodo_key", "DimIndicador": "indicador_key"}


def _py(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating, float)): return Decimal(f"{float(v):.4f}")
    if isinstance(v, pd.Timestamp): return v.to_pydatetime()
    if isinstance(v, np.bool_): return bool(v)
    return v


def _insertar(cur, tabla, df, schema="dw"):
    cols = list(df.columns)
    filas = [tuple(_py(v) for v in fila) for fila in df.itertuples(index=False, name=None)]
    cur.fast_executemany = True
    sql = f"INSERT INTO {schema}.{tabla} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
    for i in range(0, len(filas), 5000):
        cur.executemany(sql, filas[i:i + 5000])
    return len(filas)


def _upsert_dim(cur, tabla, df):
    """Inserta claves nuevas y actualiza atributos de las existentes (los hechos que apuntan a la dimension no se tocan)."""
    k = CLAVES[tabla]
    existentes = {r[0] for r in cur.execute(f"SELECT {k} FROM dw.{tabla}").fetchall()}
    nuevas = df[~df[k].isin(existentes)]
    if len(nuevas): _insertar(cur, tabla, nuevas)
    resto = df[df[k].isin(existentes)]
    if len(resto) and len(df.columns) > 1:
        sets = [c for c in df.columns if c != k]
        sql = f"UPDATE dw.{tabla} SET {', '.join(c + '=?' for c in sets)} WHERE {k}=?"
        cur.fast_executemany = True
        cur.executemany(sql, [tuple(_py(v) for v in fila[1:]) + (_py(fila[0]),) for fila in resto[[k] + sets].itertuples(index=False, name=None)])
    return len(nuevas), len(resto)


def leer_existentes():
    conn = conectar(DB_DW)
    try:
        d = pd.read_sql("SELECT diagnostico_key, diagnostico FROM dw.DimDiagnostico WHERE diagnostico_key > 0", conn)
    finally:
        conn.close()
    return {"DimDiagnostico": dict(zip(d.diagnostico, d.diagnostico_key))}


def _txt_num(v):
    if isinstance(v, str): return v
    return str(int(v)) if float(v).is_integer() else f"{float(v):.2f}"


def cargar_reporteria(cur, id_carga, prof, pruebas):
    """Tablas de reporteria para Power BI (esquema rpt), dentro de la misma transaccion de la carga:
       calidad y pruebas de ESTA carga (historial por id_carga) + KPI mensuales recalculados desde dw.* con rpt.usp_refrescar_kpi."""
    c = prof.assign(id_carga=id_carga)[["id_carga", "fuente", "tabla", "problema", "registros", "total", "pct", "tratamiento"]]
    _insertar(cur, "CalidadDatos", c, schema="rpt")
    t = pruebas.assign(id_carga=id_carga, fuente=pruebas.fuente.map(_txt_num), data_mart=pruebas.data_mart.map(_txt_num))[["id_carga", "prueba", "descripcion", "fuente", "data_mart", "resultado"]]
    _insertar(cur, "PruebasCuadre", t, schema="rpt")
    cur.execute("EXEC rpt.usp_refrescar_kpi ?", id_carga)
    log("CARGA rpt  CalidadDatos, PruebasCuadre y KPI mensuales (rpt.KpiMensual, rpt.KpiMensualEspecialidad)")


def cargar_sqlserver(D, F, mapa, prof, rech, pruebas, resumen, modulos):
    conn = conectar(DB_DW); cur = conn.cursor(); t0 = time.time()
    id_carga = "ETL-" + time.strftime("%Y%m%d-%H%M%S")
    try:
        a_refrescar = [h for m in modulos for h in HECHOS_POR_MODULO[m] if h in F]
        a_refrescar = [h for h in HECHOS_ORDEN if h in set(a_refrescar)]
        for h in reversed(HECHOS_ORDEN):                                           # hijos primero
            if h in a_refrescar:
                cur.execute(f"DELETE FROM dw.{h}")
        if "transaccional" in modulos:
            cur.execute("DELETE FROM seg.MapaPaciente")
        for dname in DIMS_ORDEN:
            if dname in D and (dname != "DimIndicador" or "metas" in modulos):
                n_nue, n_act = _upsert_dim(cur, dname, D[dname])
                log(f"CARGA dim  {dname:22s} nuevas={n_nue:5d} actualizadas={n_act:5d}")
        if "transaccional" in modulos:
            _insertar(cur, "MapaPaciente", mapa, schema="seg")
        for h in a_refrescar:
            n = _insertar(cur, h, F[h]); log(f"CARGA hecho {h:22s} {n:6d} filas")
        cargadas = sum(len(F[h]) for h in a_refrescar)
        cur.execute("INSERT INTO etl.BitacoraCarga (id_carga, inicio, fin, modulos, filas_leidas, filas_cargadas, rechazos, advertencias, pruebas_ok, pruebas_total, estado) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", id_carga, pd.Timestamp.now().to_pydatetime() - pd.Timedelta(seconds=time.time() - t0), pd.Timestamp.now().to_pydatetime(),
                    ",".join(modulos), resumen["leidas"], cargadas, int((rech.nivel == "RECHAZO").sum()), int((rech.nivel == "ADVERTENCIA").sum()),
                    int((pruebas.resultado == "OK").sum()), int((pruebas.resultado != "OMITIDA").sum()), "EXITOSO")
        rech_i = rech.assign(id_carga=id_carga)[["id_carga", "fuente", "tabla", "clave_origen", "motivo", "nivel"]]      # despues de la bitacora (FK)
        if len(rech_i): _insertar(cur, "RechazoCarga", rech_i, schema="etl")
        cargar_reporteria(cur, id_carga, prof, pruebas)                                                                  # esquema rpt (Power BI)
        conn.commit()
        log(f"COMMIT OK  {id_carga}  ({time.time() - t0:.1f} s)  filas cargadas={cargadas}")
    except Exception:
        conn.rollback(); log("ERROR: se hizo ROLLBACK, el data mart quedo como estaba."); raise
    finally:
        conn.close()
    return id_carga


def cargar_csv(D, F, mapa, prof, rech, pruebas, resumen, modulos):
    os.makedirs(RUTA_SALIDA, exist_ok=True)
    id_carga = "ETL-" + time.strftime("%Y%m%d-%H%M%S")
    for nom, df in {**D, **F}.items():
        df.to_csv(os.path.join(RUTA_SALIDA, f"{nom}.csv"), index=False, encoding="utf-8-sig")
    mapa.to_csv(os.path.join(RUTA_SALIDA, "MapaPaciente.csv"), index=False, encoding="utf-8-sig")
    prof.to_csv(os.path.join(RUTA_SALIDA, "perfilamiento_calidad.csv"), index=False, encoding="utf-8-sig")
    pruebas.to_csv(os.path.join(RUTA_SALIDA, "pruebas_cuadre.csv"), index=False, encoding="utf-8-sig")
    rech.assign(id_carga=id_carga).to_csv(os.path.join(RUTA_SALIDA, "etl_RechazoCarga.csv"), index=False, encoding="utf-8-sig")
    calcular_kpis(D, F).to_csv(os.path.join(RUTA_SALIDA, "kpi_mensual.csv"), encoding="utf-8-sig")
    cargadas = sum(len(v) for v in {**D, **F}.values())
    pd.DataFrame([dict(id_carga=id_carga, inicio=time.strftime("%Y-%m-%d %H:%M:%S"), modulos=",".join(modulos), filas_leidas=resumen["leidas"], filas_cargadas=cargadas,
                       rechazos=int((rech.nivel == "RECHAZO").sum()), advertencias=int((rech.nivel == "ADVERTENCIA").sum()),
                       pruebas_ok=int((pruebas.resultado == "OK").sum()), pruebas_total=int((pruebas.resultado != "OMITIDA").sum()), estado="EXITOSO")]
                 ).to_csv(os.path.join(RUTA_SALIDA, "etl_BitacoraCarga.csv"), index=False, encoding="utf-8-sig")
    log(f"SALIDA CSV en {RUTA_SALIDA}  ({cargadas} filas en 17 tablas)")
    return id_carga


# =============================== MAIN ===============================
def main():
    global LOG_FILE, RUTA_CSV_BD, RUTA_FUENTES, RUTA_SALIDA, SERVER
    ap = argparse.ArgumentParser(description="ETL BDClinica -> DWClinica")
    ap.add_argument("--origen", choices=["sqlserver", "csv"], default="sqlserver")
    ap.add_argument("--destino", choices=["sqlserver", "csv"], default="sqlserver")
    ap.add_argument("--modulos", default=",".join(MODULOS_TODOS), help="lista separada por comas: " + ", ".join(MODULOS_TODOS))
    ap.add_argument("--csv-bd", default=RUTA_CSV_BD); ap.add_argument("--fuentes", default=RUTA_FUENTES); ap.add_argument("--salida", default=RUTA_SALIDA)
    ap.add_argument("--server", default=SERVER)
    a = ap.parse_args()
    RUTA_CSV_BD, RUTA_FUENTES, RUTA_SALIDA, SERVER = a.csv_bd, a.fuentes, a.salida, a.server
    modulos = [m.strip() for m in a.modulos.split(",") if m.strip()]
    mal = [m for m in modulos if m not in MODULOS_TODOS]
    LOG_FILE = os.path.join(carpeta_logs(), f"etl_dw_{time.strftime('%Y%m%d_%H%M%S')}.log")
    try:
        if mal: raise ValueError(f"Modulo desconocido: {mal}")
        if (a.origen == "sqlserver" or a.destino == "sqlserver") and not SERVER: raise ValueError("Falta DB_SERVER en el .env o --server.")
        if a.origen == "csv" and not RUTA_CSV_BD: raise ValueError("Con --origen csv falta ETL_RUTA_DATA o --csv-bd.")
        log(f"INICIO  origen={a.origen}  destino={a.destino}  modulos={modulos}  corte={FECHA_CORTE.date()}")
        bd = extraer_bdclinica(a.origen)
        inv = extraer_inventario() if "inventario" in modulos else None
        metas = extraer_metas() if "metas" in modulos or a.destino == "csv" else None
        fer = extraer_feriados()
        leidas = sum(len(d) for d in bd.values()) + (len(inv) if inv is not None else 0) + (len(metas) if metas is not None else 0) + len(fer)
        prof = perfilar(bd, inv)
        existentes = leer_existentes() if a.destino == "sqlserver" else None
        D, F, rech, mapa = transformar(bd, fer, metas, inv, modulos, existentes)
        pruebas = validar(bd, D, F, mapa, rech, inv, modulos)
        if (pruebas.resultado == "ERROR").any():
            raise RuntimeError("Fallaron pruebas de cuadre: " + ", ".join(pruebas[pruebas.resultado == "ERROR"].prueba) + ". NO se carga nada.")
        resumen = dict(leidas=leidas)
        (cargar_sqlserver if a.destino == "sqlserver" else cargar_csv)(D, F, mapa, prof, rech, pruebas, resumen, modulos)
        log(f"FIN OK  (log: {LOG_FILE})")
    except Exception as e:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(traceback.format_exc())
        p(f"\n*** ETL DETENIDO ***\n{e}\n(detalle tecnico en {LOG_FILE})")
        sys.exit(1)


if __name__ == "__main__":
    main()
