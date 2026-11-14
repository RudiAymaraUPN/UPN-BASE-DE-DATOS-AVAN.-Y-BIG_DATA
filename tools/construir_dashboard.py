# -*- coding: utf-8 -*-
r"""
Construye el tablero de gestion a partir de los CSV del data mart (salida de: python -m etl.datamart --origen csv --destino csv).
Genera en --salida: kpi_resumen.json, 5 paginas PNG (resumen, agenda, capacidad y espera, ingresos, farmacia) y Dashboard_Clinica_G13.html (version estatica).
Uso:  python tools/construir_dashboard.py --dw data/salida_pruebas --salida docs/dashboard_referencia
Requiere: pandas, matplotlib.
"""
import argparse, base64, json, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

AZUL, NARANJA, VERDE, AMBAR, ROJO, GRIS, TINTA = "#2563eb", "#ea580c", "#16a34a", "#d97706", "#dc2626", "#9ca3af", "#111827"
SEM = {"ok": VERDE, "cerca": AMBAR, "fuera": ROJO}
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#cbd5e1", "axes.titleweight": "bold",
                     "axes.titlesize": 11, "axes.labelsize": 9, "xtick.labelsize": 8, "ytick.labelsize": 8, "axes.titlelocation": "left"})
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]
etq = lambda am: f"{MESES[int(am[5:]) - 1]}-{am[2:4]}"


def estado(valor, meta, mayor_mejor):
    if valor is None or meta is None or pd.isna(valor): return "fuera"
    if (mayor_mejor and valor >= meta) or (not mayor_mejor and valor <= meta): return "ok"
    cerca = valor >= 0.9 * meta if mayor_mejor else valor <= 1.1 * meta
    return "cerca" if cerca else "fuera"


def cargar(dw):
    rd = lambda n: pd.read_csv(os.path.join(dw, n + ".csv"), encoding="utf-8-sig")
    return {n: rd(n) for n in ["DimFecha", "DimEspecialidad", "DimPersonal", "DimDiagnostico", "DimFarmaco", "DimLote", "DimServicio", "DimMetodoPago", "DimIndicador",
                               "FactCita", "FactCapacidad", "FactPrescripcion", "FactFacturacionLinea", "FactInventarioLote", "FactMeta"]}


def calcular(T, desde="2025-11", hasta="2026-10", esp=None, corte=None):
    f = T["DimFecha"][["fecha_key", "anio_mes", "dia_semana"]]
    c = T["FactCita"].merge(f, on="fecha_key"); k = T["FactCapacidad"].merge(f, on="fecha_key"); l = T["FactFacturacionLinea"].merge(f, on="fecha_key")
    en = lambda d: d[(d.anio_mes >= desde) & (d.anio_mes <= hasta)]
    c, k, l = en(c), en(k), en(l)
    if esp is not None: c, k = c[c.especialidad_key == esp], k[k.especialidad_key == esp]
    r = {}
    r["atendidas"], r["no_asistidas"] = int(c.flag_atendida.sum()), int(c.flag_no_asistida.sum())
    r["inasistencia"] = 100 * r["no_asistidas"] / max(1, r["atendidas"] + r["no_asistidas"])
    r["cupos"], r["turnos"] = int(k.cupos_disponibles.sum()), int(k.turnos_programados.sum())
    r["ocupacion"] = 100 * r["atendidas"] / max(1, r["cupos"]); r["productividad"] = r["atendidas"] / max(1, r["turnos"])
    r["espera"] = float(c.minutos_espera.mean()); r["esperas_validas"] = int(c.flag_espera_valida.sum())
    r["ingresos"] = float(l.monto.sum()); r["comprobantes"] = int(l.id_factura.nunique()); r["ticket"] = r["ingresos"] / max(1, r["comprobantes"])
    m = T["FactMeta"]; ind = T["DimIndicador"].set_index("indicador").indicador_key
    mm = m[(m.anio_mes >= desde) & (m.anio_mes <= hasta)]
    r["meta_ingresos"] = float(mm[mm.indicador_key == ind["Ingresos totales"]].valor_meta.sum())
    r["cumplimiento"] = 100 * r["ingresos"] / r["meta_ingresos"]
    if esp is not None: r["ingresos"] = r["ticket"] = r["cumplimiento"] = float("nan")      # la factura no se vincula a la atencion: no se atribuye a una especialidad
    i = T["FactInventarioLote"].merge(f.drop_duplicates("fecha_key"), left_on="fecha_corte_key", right_on="fecha_key")
    corte = corte or hasta; ic = i[i.anio_mes == corte]
    r["corte"] = corte; r["riesgo"] = float(ic[ic.dias_para_vencer <= 90].valor_stock.sum())
    fm = T["DimFarmaco"]; fm = fm[fm.farmaco_key > 0].set_index("farmaco_key")
    vig = ic[ic.dias_para_vencer >= 0].groupby("farmaco_key").stock_fisico.sum().reindex(fm.index, fill_value=0)
    bajo = vig[vig < fm.stock_minimo]
    r["bajo_minimo"] = int(len(bajo)); r["_bajo"] = (fm.loc[bajo.index].assign(stock=bajo)[["farmaco", "presentacion", "stock_minimo", "stock"]])
    return r, c, k, l


METAS_KPI = {"inasistencia": (10, False), "ocupacion": (75, True), "espera": (20, False), "productividad": (8, True), "riesgo": (1500, False), "bajo_minimo": (3, False)}


def tarjetas(ax_list, r):
    items = [("Inasistencia", f"{r['inasistencia']:.1f} %", "inasistencia", "≤ 10 %"), ("Ocupación de horarios", f"{r['ocupacion']:.2f} %", "ocupacion", "≥ 75 %"),
             ("Espera promedio", f"{r['espera']:.1f} min", "espera", "≤ 20 min"), ("Atenciones por turno", f"{r['productividad']:.3f}", "productividad", "≥ 8"),
             ("Ingresos", f"S/ {r['ingresos']:,.0f}".replace(",", " "), None, f"meta S/ {r['meta_ingresos']:,.0f}".replace(",", " ")),
             ("Stock en riesgo", f"S/ {r['riesgo']:,.0f}".replace(",", " "), "riesgo", "≤ S/ 1 500"), ("Fármacos bajo mínimo", f"{r['bajo_minimo']}", "bajo_minimo", "≤ 3")]
    for ax, (tit, val, key, meta) in zip(ax_list, items):
        if key is None and np.isnan(r["cumplimiento"]):
            ax.axis("off"); ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, fc="#f8fafc", ec="#e2e8f0", lw=1)); ax.add_patch(plt.Rectangle((0, 0), 0.04, 1, transform=ax.transAxes, fc=GRIS, ec="none"))
            ax.text(0.1, 0.78, tit, fontsize=7.5, color="#475569", transform=ax.transAxes); ax.text(0.1, 0.42, "n/d", fontsize=13, weight="bold", color=TINTA, transform=ax.transAxes)
            ax.text(0.1, 0.12, "no atribuible a la especialidad", fontsize=6.5, color="#64748b", transform=ax.transAxes); continue
        e = estado(r["cumplimiento"], 100, True) if key is None else estado(r[key], *METAS_KPI[key])
        if key is None: e = "ok" if r["cumplimiento"] >= 100 else ("cerca" if r["cumplimiento"] >= 90 else "fuera")
        ax.axis("off"); ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, fc="#f8fafc", ec="#e2e8f0", lw=1))
        ax.add_patch(plt.Rectangle((0, 0), 0.04, 1, transform=ax.transAxes, fc=SEM[e], ec="none"))
        ax.text(0.1, 0.78, tit, fontsize=7.5, color="#475569", transform=ax.transAxes); ax.text(0.1, 0.42, val, fontsize=13, weight="bold", color=TINTA, transform=ax.transAxes)
        ax.text(0.1, 0.12, meta + (f" · {r['cumplimiento']:.0f} %" if key is None else ""), fontsize=7, color="#64748b", transform=ax.transAxes)


def mensual(T, hasta="2026-10"):
    f = T["DimFecha"][["fecha_key", "anio_mes"]]
    c = T["FactCita"].merge(f, on="fecha_key"); l = T["FactFacturacionLinea"].merge(f, on="fecha_key"); k = T["FactCapacidad"].merge(f, on="fecha_key")
    g = c.groupby("anio_mes").agg(ate=("flag_atendida", "sum"), nas=("flag_no_asistida", "sum"), can=("flag_cancelada", "sum"), espera=("minutos_espera", "mean"))
    g["inas"] = 100 * g.nas / (g.ate + g.nas); g["ing"] = l.groupby("anio_mes").monto.sum(); g["cupos"] = k.groupby("anio_mes").cupos_disponibles.sum(); g["ocup"] = 100 * g.ate / g.cupos
    mt = T["FactMeta"].merge(T["DimIndicador"][["indicador_key", "indicador"]], on="indicador_key")
    g["meta_ing"] = mt[mt.indicador == "Ingresos totales"].set_index("anio_mes").valor_meta
    return g[g.index <= hasta]


def pagina_resumen(T, r, M, ruta, titulo="Resumen gerencial (nov-25 a oct-26)", subt=""):
    fig = plt.figure(figsize=(13, 7.4)); gs = fig.add_gridspec(3, 7, height_ratios=[0.9, 2.4, 2.4], hspace=0.55, wspace=0.25)
    fig.suptitle(titulo + subt, x=0.01, ha="left", fontsize=14, weight="bold")
    tarjetas([fig.add_subplot(gs[0, i]) for i in range(7)], r)
    ax = fig.add_subplot(gs[1, :4]); x = np.arange(len(M)); ax.bar(x, M.ing, color=AZUL, width=.6, label="Ingresos"); ax.plot(x, M.meta_ing, color=NARANJA, marker="o", ms=4, label="Meta")
    ax.set_xticks(x, [etq(a) for a in M.index]); ax.set_title("Ingresos mensuales vs meta (S/)"); ax.legend(frameon=False, fontsize=8)
    ax = fig.add_subplot(gs[1, 4:]); ax.plot(x, M.inas, color=ROJO, marker="o", ms=4); ax.axhline(10, color=GRIS, ls="--"); ax.text(len(M) - 1, 10.4, "meta 10 %", ha="right", fontsize=8, color="#64748b")
    ax.set_xticks(x, [etq(a) for a in M.index]); ax.set_title("Tasa de inasistencia (%)")
    ax = fig.add_subplot(gs[2, :4]); ax.bar(x, M.ate, color=VERDE, label="Atendidas", width=.6); ax.bar(x, M.nas, bottom=M.ate, color=ROJO, label="No asistió", width=.6); ax.bar(x, M.can, bottom=M.ate + M.nas, color=GRIS, label="Canceladas", width=.6)
    ax.set_xticks(x, [etq(a) for a in M.index]); ax.set_title("Citas por estado"); ax.legend(frameon=False, fontsize=8, ncol=3)
    ax = fig.add_subplot(gs[2, 4:]); ax.bar(x, M.espera, color=AZUL, width=.6); ax.axhline(20, color=NARANJA, ls="--"); ax.text(len(M) - 1, 20.6, "meta 20 min", ha="right", fontsize=8, color="#64748b")
    ax.set_xticks(x, [etq(a) for a in M.index]); ax.set_title("Espera promedio (min)")
    for a in fig.axes: a.tick_params(axis="x", rotation=45)
    fig.savefig(ruta, dpi=150, bbox_inches="tight", facecolor="white"); plt.close(fig)


def pagina_agenda(T, r, c, ruta):
    fig, axs = plt.subplots(2, 2, figsize=(13, 7.4)); fig.suptitle("Agenda y asistencia (nov-25 a oct-26)", x=0.01, ha="left", fontsize=14, weight="bold"); fig.subplots_adjust(hspace=0.5, wspace=0.35)
    es = T["DimEspecialidad"].set_index("especialidad_key").especialidad
    g = c.groupby("especialidad_key").agg(ate=("flag_atendida", "sum"), nas=("flag_no_asistida", "sum")); g["n"] = g.ate + g.nas; g["inas"] = 100 * g.nas / g.n
    top = g.sort_values("n", ascending=False).head(8)
    ax = axs[0, 0]; ax.barh([es[i] for i in top.index][::-1], top.n[::-1], color=AZUL); ax.set_title("Citas atendidas + no asistidas por especialidad (top 8)")
    ax = axs[0, 1]; t2 = top.sort_values("inas"); ax.barh([es[i] for i in t2.index], t2.inas, color=[SEM[estado(v, 10, False)] for v in t2.inas]); ax.axvline(10, color=GRIS, ls="--"); ax.set_title("Inasistencia por especialidad (%) — mismas 8")
    ax = axs[1, 0]; d = c.groupby("dia_semana").agg(ate=("flag_atendida", "sum"), nas=("flag_no_asistida", "sum")); d["inas"] = 100 * d.nas / (d.ate + d.nas)
    orden = [x for x in ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"] if x in d.index]; d = d.loc[orden]
    ax.bar(d.index, d.inas, color=[SEM[estado(v, 10, False)] for v in d.inas]); ax.axhline(10, color=GRIS, ls="--"); ax.set_title("Inasistencia por día de la semana (%)")
    ax = axs[1, 1]; est = {"Atendida": c.flag_atendida.sum(), "No asistió": c.flag_no_asistida.sum(), "Cancelada": c.flag_cancelada.sum()}
    ax.pie(est.values(), labels=[f"{k}\n{v}" for k, v in est.items()], colors=[VERDE, ROJO, GRIS], startangle=90, wedgeprops=dict(width=.45), textprops={"fontsize": 9}); ax.set_title("Estado de las citas")
    fig.savefig(ruta, dpi=150, bbox_inches="tight", facecolor="white"); plt.close(fig)


def pagina_capacidad(T, r, c, k, M, ruta):
    fig, axs = plt.subplots(2, 2, figsize=(13, 7.4)); fig.suptitle("Ocupación, productividad y espera (nov-25 a oct-26)", x=0.01, ha="left", fontsize=14, weight="bold"); fig.subplots_adjust(hspace=0.5, wspace=0.35)
    x = np.arange(len(M)); ax = axs[0, 0]; ax.bar(x, M.ocup, color=AZUL, width=.6); ax.set_xticks(x, [etq(a) for a in M.index], rotation=45); ax.set_title("Ocupación mensual de horarios (%) — meta 75 %"); ax.set_ylim(0, 75)
    ax = axs[0, 1]; ax.bar(x - .2, M.cupos, width=.4, color=GRIS, label="Cupos disponibles"); ax.bar(x + .2, M.ate, width=.4, color=VERDE, label="Atendidas"); ax.set_yscale("log"); ax.set_xticks(x, [etq(a) for a in M.index], rotation=45)
    ax.set_title("Cupos ofrecidos vs citas atendidas (escala log)"); ax.legend(frameon=False, fontsize=8)
    ax = axs[1, 0]; cc = c.dropna(subset=["minutos_espera"]).copy(); cc["franja"] = np.where(pd.to_datetime(cc.fecha_key.astype(str)).dt.dayofweek >= 0, "", "")
    ate = T["FactCita"]; hm = c.merge(T["DimPersonal"][["personal_key"]], on="personal_key")
    orden = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]; p = c.dropna(subset=["minutos_espera"]).groupby("dia_semana").minutos_espera.mean().reindex(orden).dropna()
    ax.bar(p.index, p.values, color=[SEM[estado(v, 20, False)] for v in p.values]); ax.axhline(20, color=GRIS, ls="--"); ax.set_title("Espera promedio por día de la semana (min) — meta 20 min")
    ax = axs[1, 1]; es = T["DimEspecialidad"].set_index("especialidad_key").especialidad
    e = c.dropna(subset=["minutos_espera"]).groupby("especialidad_key").minutos_espera.agg(["mean", "count"]); e = e[e["count"] >= 8].sort_values("mean")
    ax.barh([es[i] for i in e.index], e["mean"], color=AZUL); ax.set_title("Espera promedio por especialidad (≥ 8 atenciones)")
    fig.savefig(ruta, dpi=150, bbox_inches="tight", facecolor="white"); plt.close(fig)


def pagina_ingresos(T, r, l, M, ruta):
    fig, axs = plt.subplots(2, 2, figsize=(13, 7.4)); fig.suptitle("Ingresos y medios de pago (nov-25 a oct-26)", x=0.01, ha="left", fontsize=14, weight="bold"); fig.subplots_adjust(hspace=0.5, wspace=0.35)
    x = np.arange(len(M)); ax = axs[0, 0]; ax.bar(x, M.ing, color=[SEM["ok" if v >= m else ("cerca" if v >= .9 * m else "fuera")] for v, m in zip(M.ing, M.meta_ing)], width=.6); ax.plot(x, M.meta_ing, color=TINTA, marker="o", ms=3)
    ax.set_xticks(x, [etq(a) for a in M.index], rotation=45); ax.set_title("Ingresos vs meta mensual (S/) — color = semáforo")
    ax = axs[0, 1]; tipo = np.where(l.servicio_key > 0, "Servicios", "Farmacia"); m = l.groupby(tipo).monto.sum(); ax.pie(m.values, labels=[f"{k}\nS/ {v:,.0f}".replace(",", " ") for k, v in m.items()], colors=[AZUL, NARANJA], startangle=90, wedgeprops=dict(width=.45)); ax.set_title("Mezcla de ingresos")
    ax = axs[1, 0]; mp = T["DimMetodoPago"].set_index("metodo_key").metodo_pago; g = l.groupby("metodo_key").monto.sum().sort_values(); ax.barh([mp[i] for i in g.index], g.values, color=AZUL); ax.set_title("Ingresos por método de pago (S/)")
    ax = axs[1, 1]; sv = T["DimServicio"].set_index("servicio_key").servicio; g = l[l.servicio_key > 0].groupby("servicio_key").monto.sum().sort_values().tail(8); ax.barh([sv[i][:32] for i in g.index], g.values, color=NARANJA); ax.set_title("Top 8 servicios por ingreso (S/)")
    fig.savefig(ruta, dpi=150, bbox_inches="tight", facecolor="white"); plt.close(fig)


def pagina_farmacia(T, r, ruta, titulo="Farmacia (corte oct-26)"):
    fig, axs = plt.subplots(2, 2, figsize=(13, 7.4)); fig.suptitle(titulo, x=0.01, ha="left", fontsize=14, weight="bold"); fig.subplots_adjust(hspace=0.5, wspace=0.45)
    f = T["DimFecha"][["fecha_key", "anio_mes"]].drop_duplicates("fecha_key"); i = T["FactInventarioLote"].merge(f, left_on="fecha_corte_key", right_on="fecha_key")
    fm = T["DimFarmaco"]; fm = fm[fm.farmaco_key > 0].set_index("farmaco_key"); cortes = sorted(i.anio_mes.unique()); cortes = [c for c in cortes if c <= r["corte"]]
    serie = []
    for cm in cortes:
        ic = i[i.anio_mes == cm]; vig = ic[ic.dias_para_vencer >= 0].groupby("farmaco_key").stock_fisico.sum().reindex(fm.index, fill_value=0); serie.append(int((vig < fm.stock_minimo).sum()))
    x = np.arange(len(cortes)); ax = axs[0, 0]; ax.bar(x, serie, color=[SEM[estado(v, 3, False)] for v in serie], width=.6); ax.axhline(3, color=GRIS, ls="--"); ax.set_xticks(x, [etq(a) for a in cortes], rotation=45); ax.set_title("Fármacos bajo stock mínimo por corte — meta ≤ 3")
    ax = axs[0, 1]; tr = i[i.anio_mes == r["corte"]].assign(t=lambda d: pd.cut(d.dias_para_vencer, [-10**6, -1, 30, 90, 10**6], labels=["Vencido", "0-30 días", "31-90 días", "> 90 días"])).groupby("t", observed=False).valor_stock.sum()
    ax.bar(tr.index.astype(str), tr.values, color=[ROJO, ROJO, AMBAR, VERDE]); ax.set_title(f"Valor del stock por tramo de vencimiento (S/) — corte {etq(r['corte'])}")
    ax = axs[1, 0]; b = r["_bajo"].assign(falta=lambda d: d.stock_minimo - d.stock).sort_values("falta").tail(8); ax.barh([f"{a} {p}"[:30] for a, p in zip(b.farmaco, b.presentacion.fillna(""))], b.falta, color=ROJO); ax.set_title("Fármacos con mayor faltante (mínimo − stock vigente)")
    ax = axs[1, 1]; pr = T["FactPrescripcion"].groupby("farmaco_key").cantidad_prescrita.sum().sort_values().tail(8); ax.barh([f"{fm.farmaco[k]} {fm.presentacion[k]}"[:30] for k in pr.index], pr.values, color=AZUL); ax.set_title("Top 8 fármacos más prescritos (unidades)")
    fig.savefig(ruta, dpi=150, bbox_inches="tight", facecolor="white"); plt.close(fig)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dw", default="data/salida_pruebas"); ap.add_argument("--salida", default="docs/dashboard_referencia"); a = ap.parse_args()
    os.makedirs(a.salida, exist_ok=True); T = cargar(a.dw); M = mensual(T)
    r, c, k, l = calcular(T)
    pagina_resumen(T, r, M, os.path.join(a.salida, "pag1_resumen.png")); pagina_agenda(T, r, c, os.path.join(a.salida, "pag2_agenda.png"))
    pagina_capacidad(T, r, c, k, M, os.path.join(a.salida, "pag3_capacidad_espera.png")); pagina_ingresos(T, r, l, M, os.path.join(a.salida, "pag4_ingresos.png")); pagina_farmacia(T, r, os.path.join(a.salida, "pag5_farmacia.png"))
    # vistas con filtros combinados (anexo E): una especialidad y un corte anterior
    cc = c.groupby("especialidad_key").size().idxmax(); nom_esp = T["DimEspecialidad"].set_index("especialidad_key").especialidad[cc]
    r2, c2, k2, l2 = calcular(T, esp=cc); r2["especialidad"] = nom_esp
    pagina_resumen(T, r2, M, os.path.join(a.salida, "filtro_especialidad.png"), titulo=f"Resumen gerencial filtrado: {nom_esp}", subt=" (nov-25 a oct-26)")
    r3, *_ = calcular(T, corte="2026-07"); pagina_farmacia(T, r3, os.path.join(a.salida, "filtro_farmacia_jul26.png"), titulo="Farmacia con corte en jul-26")
    out = {k_: v for k_, v in r.items() if not k_.startswith("_")}
    out["filtro_especialidad"] = {k_: v for k_, v in r2.items() if not k_.startswith("_")}; out["corte_jul26"] = {k_: v for k_, v in r3.items() if not k_.startswith("_")}
    json.dump(out, open(os.path.join(a.salida, "kpi_resumen.json"), "w"), indent=1, default=float)
    imgs = ["pag1_resumen", "pag2_agenda", "pag3_capacidad_espera", "pag4_ingresos", "pag5_farmacia"]
    html = ["<!DOCTYPE html><html lang='es'><meta charset='utf-8'><title>Tablero de gestión – Clínica G13</title><body style='font-family:Segoe UI,Arial;background:#f1f5f9;margin:0;padding:24px'>",
            "<h1 style='margin:0 0 4px'>Tablero de gestión – Clínica (Grupo 13)</h1><p style='color:#475569'>Versión estática generada desde DWClinica (nov-25 a oct-26). Datos sintéticos.</p>"]
    for n in imgs:
        b64 = base64.b64encode(open(os.path.join(a.salida, n + ".png"), "rb").read()).decode()
        html.append(f"<div style='background:white;border-radius:8px;padding:12px;margin:0 0 20px'><img style='max-width:100%' src='data:image/png;base64,{b64}'></div>")
    open(os.path.join(a.salida, "Dashboard_Clinica_G13.html"), "w", encoding="utf-8").write("".join(html) + "</body></html>")
    print(json.dumps({k_: (round(v, 3) if isinstance(v, float) else v) for k_, v in out.items() if not isinstance(v, dict)}, indent=1))


if __name__ == "__main__":
    main()
