# -*- coding: utf-8 -*-
r"""
Simula el programa de la clinica: cada dia deja en una carpeta CSV con los registros nuevos (nombre TABLA_AAAAMMDD.csv).
Sirve para probar el ETL diario (python -m etl.carga_diaria). Datos sinteticos, semilla fija. El ultimo dia incluye errores a proposito.
Uso:  python tools/simular_programa_clinica.py --ref data/inicial --salida data/entrada_diaria --desde 2026-11-12 --dias 2
"""
import argparse, os, random
import pandas as pd

NOMBRES = ["Luis", "Maria", "Carlos", "Ana", "Jorge", "Rosa", "Miguel", "Lucia", "Pedro", "Carmen", "Diego", "Elena", "Raul", "Julia", "Mario"]
APELLIDOS = ["Quispe Huaman", "Flores Rojas", "Garcia Perez", "Torres Vega", "Ramos Soto", "Mendoza Cruz", "Castillo Diaz", "Salazar Rios", "Vargas Leon", "Paredes Luna"]
DISTRITOS = ["Miraflores", "San Isidro", "Surco", "Barranco", "Comas", "Brena", "La Molina", "Lince", "San Borja", "Jesus Maria"]
CALLES = ["Av. Grau", "Calle Sucre", "Av. Los Cedros", "Jr. Cusco", "Av. Brasil", "Calle Lima"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="carpeta con los CSV de BDClinica (para continuar los id y reutilizar catalogos)")
    ap.add_argument("--salida", default="data/entrada_diaria"); ap.add_argument("--desde", default="2026-11-12"); ap.add_argument("--dias", type=int, default=2)
    ap.add_argument("--con-errores", action="store_true", default=True)
    a = ap.parse_args()
    rd = lambda n: pd.read_csv(os.path.join(a.ref, n + ".csv"), encoding="utf-8-sig", dtype=str, keep_default_na=False)
    T = {n: rd(n) for n in ["PACIENTES", "CITAS", "ATENCIONES", "RECETAS", "DETALLE_RECETA", "FACTURACION", "DETALLE_FACTURACION", "LOTES_FARMACOS", "PERSONAL_ESPECIALIDAD", "SERVICIOS", "FARMACOS"]}
    sig = {n: int(T[n][T[n].columns[0]].astype(int).max()) + 1 for n in ["PACIENTES", "CITAS", "ATENCIONES", "RECETAS", "DETALLE_RECETA", "FACTURACION", "DETALLE_FACTURACION", "LOTES_FARMACOS"]}
    dnis = set(T["PACIENTES"].dni); rnd = random.Random(77)
    medicos = sorted(set(T["PERSONAL_ESPECIALIDAD"].id_personal.astype(int)))
    pac_ids = [int(x) for x in T["PACIENTES"].id_paciente]
    serv = T["SERVICIOS"]; farm = T["FARMACOS"]
    diags = [d for d in T["ATENCIONES"].diagnostico.unique() if d]
    horas = ["08:00:00", "09:00:00", "10:00:00", "11:00:00", "12:00:00", "15:00:00", "16:00:00"]
    os.makedirs(a.salida, exist_ok=True)
    f = lambda d: d.strftime("%Y%m%d")
    for k in range(a.dias):
        dia = pd.Timestamp(a.desde) + pd.Timedelta(days=k); ultimo = (k == a.dias - 1)
        lote_dt = dia + pd.Timedelta(hours=18, minutes=rnd.randint(0, 40))
        ca = lambda: (lote_dt + pd.Timedelta(minutes=rnd.randint(0, 20))).strftime("%Y-%m-%d %H:%M:%S")
        out = {n: [] for n in ["PACIENTES", "CITAS", "ATENCIONES", "RECETAS", "DETALLE_RECETA", "FACTURACION", "DETALLE_FACTURACION", "LOTES_FARMACOS"]}
        nuevos = []
        for _ in range(rnd.randint(3, 5)):                                   # pacientes nuevos
            dni = str(rnd.randint(10000000, 79999999))
            while dni in dnis: dni = str(rnd.randint(10000000, 79999999))
            dnis.add(dni); pid = sig["PACIENTES"]; sig["PACIENTES"] += 1; nuevos.append(pid); pac_ids.append(pid)
            out["PACIENTES"].append(dict(id_paciente=pid, dni=dni, nombres=rnd.choice(NOMBRES), apellidos=rnd.choice(APELLIDOS),
                                         fecha_nacimiento=str(pd.Timestamp("1950-01-01") + pd.Timedelta(days=rnd.randint(0, 25000)))[:10], sexo=rnd.choice("MF"),
                                         estado_civil=rnd.choice(["Soltero", "Casado", "Conviviente", ""]), tipo_sangre=rnd.choice(["O+", "A+", "B+", ""]),
                                         telefono=str(rnd.randint(900000000, 999999999)), correo="", direccion=f"{rnd.choice(CALLES)} {rnd.randint(100, 1900)}, {rnd.choice(DISTRITOS)}", created_at=ca()))
        for i in range(rnd.randint(6, 9)):                                   # citas del dia (algunas de los pacientes nuevos)
            cid = sig["CITAS"]; sig["CITAS"] += 1
            pid = nuevos[i] if i < len(nuevos) else rnd.choice(pac_ids); med = rnd.choice(medicos); hora = rnd.choice(horas)
            est = rnd.choices(["Atendida", "No asistio", "Cancelada"], [80, 12, 8])[0]
            out["CITAS"].append(dict(id_cita=cid, id_paciente=pid, id_personal=med, fecha=str(dia.date()), hora=hora, estado=est, motivo="Consulta", created_at=ca()))
            if est != "Atendida": continue
            aid = sig["ATENCIONES"]; sig["ATENCIONES"] += 1
            fa = pd.Timestamp(f"{dia.date()} {hora}") + pd.Timedelta(minutes=rnd.randint(2, 20))
            out["ATENCIONES"].append(dict(id_atencion=aid, id_cita=cid, diagnostico=rnd.choice(diags), observaciones="Control", fecha_atencion=fa.strftime("%Y-%m-%d %H:%M:%S"), created_at=ca()))
            fid = sig["FACTURACION"]; sig["FACTURACION"] += 1; lineas = []
            sv = serv.sample(1, random_state=rnd.randint(0, 9999)).iloc[0]
            lineas.append(dict(id_servicio=sv.id_servicio, id_farmaco="", cantidad=1, precio=float(sv.precio)))
            if rnd.random() < .55:                                           # receta con 1-2 farmacos, que tambien se factura
                rid = sig["RECETAS"]; sig["RECETAS"] += 1
                out["RECETAS"].append(dict(id_receta=rid, id_atencion=aid, fecha_emision=str(dia.date()), indicaciones="Segun indicacion", created_at=ca()))
                for fm in farm.sample(rnd.randint(1, 2), random_state=rnd.randint(0, 9999)).itertuples():
                    q = rnd.randint(5, 30); did = sig["DETALLE_RECETA"]; sig["DETALLE_RECETA"] += 1
                    out["DETALLE_RECETA"].append(dict(id_detalle=did, id_receta=rid, id_farmaco=fm.id_farmaco, dosis="1 cada 8 h", cantidad=q, duracion="5 dias", created_at=ca()))
                    lineas.append(dict(id_servicio="", id_farmaco=fm.id_farmaco, cantidad=q, precio=float(fm.precio_unitario)))
            out["FACTURACION"].append(dict(id_factura=fid, id_paciente=pid, fecha=str(dia.date()), metodo_pago=rnd.choice(["Efectivo", "Tarjeta", "Yape/Plin", "Transferencia", "Seguro"]),
                                           total=round(sum(l["cantidad"] * l["precio"] for l in lineas), 2), created_at=ca()))
            for l in lineas:
                did = sig["DETALLE_FACTURACION"]; sig["DETALLE_FACTURACION"] += 1
                out["DETALLE_FACTURACION"].append(dict(id_detalle=did, id_factura=fid, id_servicio=l["id_servicio"], id_farmaco=l["id_farmaco"], cantidad=l["cantidad"],
                                                       precio_unitario=l["precio"], subtotal=round(l["cantidad"] * l["precio"], 2), created_at=ca()))
        for _ in range(rnd.randint(1, 2)):                                   # ingreso de lotes
            lid = sig["LOTES_FARMACOS"]; sig["LOTES_FARMACOS"] += 1
            out["LOTES_FARMACOS"].append(dict(id_lote=lid, id_farmaco=rnd.choice(farm.id_farmaco.tolist()), nro_lote="LNP" + str(rnd.randint(100000, 999999)),
                                              fec_lote=str(dia.date()), fec_vencimiento=str((dia + pd.Timedelta(days=rnd.randint(500, 1000))).date()), stock=rnd.randint(100, 400), created_at=ca()))
        if ultimo and a.con_errores:                                         # errores a proposito para probar los rechazos
            p0 = T["PACIENTES"].iloc[0]
            out["PACIENTES"].append(dict(id_paciente=sig["PACIENTES"], dni=p0.dni, nombres="Dni", apellidos="Repetido", fecha_nacimiento="1990-05-05", sexo="M", estado_civil="", tipo_sangre="", telefono="999111222", correo="", direccion="Jr. Cusco 10, Lince", created_at=ca()))
            sig["PACIENTES"] += 1                                            # DNI duplicado de un paciente existente
            out["PACIENTES"].append({**out["PACIENTES"][0]})                 # reproceso del mismo paciente (ya existente: se omite, no se duplica)
            out["CITAS"].append(dict(id_cita=sig["CITAS"], id_paciente=99999, id_personal=medicos[0], fecha=str(dia.date()), hora="09:00:00", estado="Atendida", motivo="", created_at=ca())); sig["CITAS"] += 1   # paciente inexistente
            out["CITAS"].append(dict(id_cita=sig["CITAS"], id_paciente=pac_ids[0], id_personal=medicos[0], fecha=str(dia.date()), hora="10:00:00", estado="Reprogramada", motivo="", created_at=ca())); sig["CITAS"] += 1  # estado fuera de dominio
            out["FACTURACION"].append(dict(id_factura=sig["FACTURACION"], id_paciente=pac_ids[1], fecha=str(dia.date()), metodo_pago="Efectivo", total=-50, created_at=ca())); sig["FACTURACION"] += 1       # total negativo
        for n, filas in out.items():
            if filas:
                pd.DataFrame(filas).to_csv(os.path.join(a.salida, f"{n}_{f(dia)}.csv"), index=False, encoding="utf-8-sig")
        print(dia.date(), {n: len(v) for n, v in out.items() if v})


if __name__ == "__main__":
    main()
