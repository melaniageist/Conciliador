"""
Conciliador Mercado Pago vs Mayor de liquidaciones
Ejecutar con:  streamlit run conciliador_mp.py
Requiere:      pip install streamlit pandas openpyxl
"""
import io
import itertools
from collections import defaultdict

import pandas as pd
import streamlit as st

F_COL = "__fecha_norm"
C_COL = "__centavos"
MAX_CANDIDATOS = 20  # tope de filas por fecha al probar combinaciones de suma


# --------------------------------------------------------------------------
# Utilidades de limpieza
# --------------------------------------------------------------------------
def a_numero(serie: pd.Series) -> pd.Series:
    """Convierte una columna a float. Soporta formatos '1.234,56' y '1,234.56'."""
    if pd.api.types.is_numeric_dtype(serie):
        return serie.astype(float)

    def parse(v):
        if pd.isna(v):
            return float("nan")
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace("$", "").replace(" ", "").replace("\u00a0", "")
        if s == "":
            return float("nan")
        neg = s.startswith("(") and s.endswith(")")
        s = s.strip("()")
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):  # 1.234,56
                s = s.replace(".", "").replace(",", ".")
            else:  # 1,234.56
                s = s.replace(",", "")
        elif "," in s:  # 1234,56
            s = s.replace(",", ".")
        try:
            x = float(s)
        except ValueError:
            return float("nan")
        return -x if neg else x

    return serie.map(parse)


def preparar(df: pd.DataFrame, col_fecha: str, col_monto: str) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)
    df[F_COL] = pd.to_datetime(df[col_fecha], dayfirst=True, errors="coerce").dt.normalize()
    df[C_COL] = (a_numero(df[col_monto]) * 100).round().astype("Int64")
    return df


# --------------------------------------------------------------------------
# Lógica de cruce
# --------------------------------------------------------------------------
def conciliar(mp, ml, tol_centavos=0, usar_sumas=True, max_comb=6):
    """
    Devuelve una lista de grupos: (tipo, [idx_mp], [idx_mayor]).
    Pasos:
      1) 1 a 1 exacto por fecha + monto (los duplicados se emparejan de a uno).
      2) 1 a 1 con tolerancia (si tol > 0).
      3) 1 MP = varios del mayor (suma de movimientos del mismo día).
      4) varios MP = 1 del mayor.
    """
    grupos = []
    valido = lambda df, i: pd.notna(df.at[i, F_COL]) and pd.notna(df.at[i, C_COL])
    pend_mp = {i for i in mp.index if valido(mp, i)}
    pend_ml = {j for j in ml.index if valido(ml, j)}

    def pasada_uno_a_uno(t):
        por_fecha = defaultdict(list)
        for j in sorted(pend_ml):
            por_fecha[ml.at[j, F_COL]].append(j)
        for i in sorted(pend_mp):
            monto = int(mp.at[i, C_COL])
            cand = [
                j for j in por_fecha.get(mp.at[i, F_COL], [])
                if abs(int(ml.at[j, C_COL]) - monto) <= t
            ]
            if cand:
                j = min(cand, key=lambda j: (abs(int(ml.at[j, C_COL]) - monto), j))
                por_fecha[mp.at[i, F_COL]].remove(j)
                pend_mp.discard(i)
                pend_ml.discard(j)
                grupos.append(("1 a 1", [i], [j]))

    def pasada_sumas(a, b, pend_a, pend_b, tipo, t):
        """Cada fila de 'a' contra combinaciones de filas de 'b' del mismo día."""
        por_fecha = defaultdict(list)
        for j in sorted(pend_b):
            por_fecha[b.at[j, F_COL]].append(j)
        for i in sorted(pend_a):
            objetivo = int(a.at[i, C_COL])
            cands = [j for j in por_fecha.get(a.at[i, F_COL], []) if j in pend_b][:MAX_CANDIDATOS]
            hallado = None
            for n in range(2, min(max_comb, len(cands)) + 1):
                for comb in itertools.combinations(cands, n):
                    if abs(sum(int(b.at[j, C_COL]) for j in comb) - objetivo) <= t:
                        hallado = comb
                        break
                if hallado:
                    break
            if hallado:
                pend_a.discard(i)
                for j in hallado:
                    pend_b.discard(j)
                grupos.append((tipo, [i], list(hallado)) if a is mp else (tipo, list(hallado), [i]))

    pasada_uno_a_uno(0)
    if tol_centavos > 0:
        pasada_uno_a_uno(tol_centavos)
    if usar_sumas:
        pasada_sumas(mp, ml, pend_mp, pend_ml, "1 MP = varios Mayor", tol_centavos)
        pasada_sumas(ml, mp, pend_ml, pend_mp, "varios MP = 1 Mayor", tol_centavos)

    # No conciliados
    for i in mp.index:
        if i in pend_mp:
            grupos.append(("Solo MP", [i], []))
        elif not valido(mp, i):
            grupos.append(("Dato inválido MP", [i], []))
    for j in ml.index:
        if j in pend_ml:
            grupos.append(("Solo Mayor", [], [j]))
        elif not valido(ml, j):
            grupos.append(("Dato inválido Mayor", [], [j]))
    return grupos


# --------------------------------------------------------------------------
# Armado del resultado
# --------------------------------------------------------------------------
def armar_resultado(mp, ml, grupos, cols_mp, cols_ml):
    def fecha_grupo(g):
        fechas = [mp.at[i, F_COL] for i in g[1]] + [ml.at[j, F_COL] for j in g[2]]
        fechas = [f for f in fechas if pd.notna(f)]
        return min(fechas) if fechas else pd.Timestamp.max

    grupos = sorted(grupos, key=fecha_grupo)
    pref_mp = {c: f"MP | {c}" for c in cols_mp}
    pref_ml = {c: f"Mayor | {c}" for c in cols_ml}

    filas = []
    for n, (tipo, imp, iml) in enumerate(grupos, 1):
        conciliado = tipo in ("1 a 1", "1 MP = varios Mayor", "varios MP = 1 Mayor")
        estado = "Conciliado" if conciliado else tipo
        dif = None
        if conciliado:
            dif = (sum(int(mp.at[i, C_COL]) for i in imp) - sum(int(ml.at[j, C_COL]) for j in iml)) / 100
        for k in range(max(len(imp), len(iml))):
            fila = {"Grupo": n, "Tipo de cruce": tipo, "Estado": estado,
                    "Diferencia (MP - Mayor)": dif if k == 0 else None}
            for c in cols_mp:
                fila[pref_mp[c]] = mp.at[imp[k], c] if k < len(imp) else None
            for c in cols_ml:
                fila[pref_ml[c]] = ml.at[iml[k], c] if k < len(iml) else None
            filas.append(fila)
    return pd.DataFrame(filas)


def armar_resumen(mp, ml, grupos, col_monto_mp, col_monto_ml):
    def cuenta(tipos):
        return [g for g in grupos if g[0] in tipos]

    def total(df, idxs):
        return float(sum(int(df.at[i, C_COL]) for i in idxs if pd.notna(df.at[i, C_COL]))) / 100

    uno = cuenta(["1 a 1"])
    mpvm = cuenta(["1 MP = varios Mayor"])
    vmpm = cuenta(["varios MP = 1 Mayor"])
    solo_mp = cuenta(["Solo MP"])
    solo_ml = cuenta(["Solo Mayor"])
    inv = cuenta(["Dato inválido MP", "Dato inválido Mayor"])

    filas = [
        ("Movimientos en MP", len(mp), total(mp, mp.index)),
        ("Movimientos en Mayor", len(ml), total(ml, ml.index)),
        ("Conciliados 1 a 1", len(uno), total(mp, [i for g in uno for i in g[1]])),
        ("Conciliados 1 MP = varios Mayor (grupos)", len(mpvm), total(mp, [i for g in mpvm for i in g[1]])),
        ("Conciliados varios MP = 1 Mayor (grupos)", len(vmpm), total(ml, [j for g in vmpm for j in g[2]])),
        ("Solo en MP (sin match en Mayor)", len(solo_mp), total(mp, [i for g in solo_mp for i in g[1]])),
        ("Solo en Mayor (sin match en MP)", len(solo_ml), total(ml, [j for g in solo_ml for j in g[2]])),
        ("Filas con fecha o monto inválido", len(inv), None),
    ]
    return pd.DataFrame(filas, columns=["Concepto", "Cantidad", "Monto bruto"])


def a_excel(resumen, resultado) -> bytes:
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    hojas = {
        "Resumen": resumen,
        "Conciliación": resultado,
        "Solo MP": resultado[resultado["Estado"] == "Solo MP"],
        "Solo Mayor": resultado[resultado["Estado"] == "Solo Mayor"],
    }
    colores = {
        "Conciliado": "E2EFDA",
        "Solo MP": "FCE4D6",
        "Solo Mayor": "FFF2CC",
    }
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl", date_format="dd/mm/yyyy",
                        datetime_format="dd/mm/yyyy") as xw:
        for nombre, df in hojas.items():
            df.to_excel(xw, sheet_name=nombre, index=False)
            ws = xw.sheets[nombre]
            ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="305496")
            for idx, col in enumerate(df.columns, 1):
                largo = max([len(str(col))] + [len(str(v)) for v in df[col].head(300)])
                ws.column_dimensions[get_column_letter(idx)].width = min(max(largo + 2, 10), 45)
            if "Estado" in df.columns:
                col_estado = list(df.columns).index("Estado")
                for fila in ws.iter_rows(min_row=2):
                    color = colores.get(fila[col_estado].value)
                    if color:
                        for cell in fila[:4]:
                            cell.fill = PatternFill("solid", fgColor=color)
            if nombre == "Resumen":
                for fila in ws.iter_rows(min_row=2, min_col=3, max_col=3):
                    fila[0].number_format = "#,##0.00"
            else:
                for idx, col in enumerate(df.columns, 1):
                    if "Monto" in str(col) or "Diferencia" in str(col):
                        for fila in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
                            fila[0].number_format = "#,##0.00"
    return buf.getvalue()


# --------------------------------------------------------------------------
# Interfaz Streamlit
# --------------------------------------------------------------------------
def sugerir(columnas, claves, default=0):
    norm = [str(c).lower() for c in columnas]
    for clave in claves:
        for i, c in enumerate(norm):
            if all(p in c for p in clave):
                return i
    return default


def cargar(etiqueta, key):
    archivo = st.file_uploader(etiqueta, type=["xlsx", "xls"], key=key)
    if archivo is None:
        return None
    xl = pd.ExcelFile(archivo)
    c1, c2 = st.columns(2)
    hoja = c1.selectbox("Hoja", xl.sheet_names, key=f"{key}_hoja")
    fila = c2.number_input("Fila de encabezados", 1, 100, 1, key=f"{key}_fila")
    df = xl.parse(hoja, header=int(fila) - 1).dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    st.caption(f"{len(df)} filas · {len(df.columns)} columnas")
    return df


def main():
    st.set_page_config(page_title="Conciliación MP vs Mayor", page_icon="🧾", layout="wide")
    st.title("🧾 Conciliación Mercado Pago vs Mayor de liquidaciones")
    st.write("Cruza por **fecha de aprobación** y **monto bruto** y devuelve un Excel con todos los datos de ambos archivos.")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Excel de Mercado Pago")
        mp_df = cargar("Subí el Excel de MP", "mp")
    with col2:
        st.subheader("Excel del Mayor")
        ml_df = cargar("Subí el Excel del mayor de liquidaciones", "ml")

    if mp_df is None or ml_df is None:
        st.info("Cargá ambos archivos para continuar.")
        return

    st.subheader("Columnas a cruzar")
    a, b = st.columns(2)
    cols_mp, cols_ml = list(mp_df.columns), list(ml_df.columns)
    mp_fecha = a.selectbox("MP · Fecha de aprobación", cols_mp,
                           index=sugerir(cols_mp, [("aprob",), ("fecha",)]))
    mp_monto = a.selectbox("MP · Monto bruto", cols_mp,
                           index=sugerir(cols_mp, [("monto", "bruto"), ("bruto",), ("monto",)]))
    ml_fecha = b.selectbox("Mayor · Fecha", cols_ml, index=sugerir(cols_ml, [("fecha",)]))
    ml_monto = b.selectbox("Mayor · Monto bruto", cols_ml,
                           index=sugerir(cols_ml, [("monto", "bruto"), ("bruto",), ("monto",), ("importe",)]))

    with st.expander("Opciones de cruce"):
        tol = st.number_input("Tolerancia de monto (en $)", 0.0, 1000.0, 0.0, 0.01,
                              help="0 = el monto debe coincidir exacto al centavo.")
        usar_sumas = st.checkbox(
            "Intentar también cruces uno-a-varios (la suma de varios movimientos del mismo día = un movimiento del otro lado)",
            value=True,
        )
        max_comb = st.slider("Máximo de movimientos por combinación", 2, 8, 6, disabled=not usar_sumas)

    if st.button("Conciliar", type="primary"):
        with st.spinner("Cruzando..."):
            mp = preparar(mp_df, mp_fecha, mp_monto)
            ml = preparar(ml_df, ml_fecha, ml_monto)
            grupos = conciliar(mp, ml, int(round(tol * 100)), usar_sumas, max_comb)
            resultado = armar_resultado(mp, ml, grupos, cols_mp, cols_ml)
            resumen = armar_resumen(mp, ml, grupos, mp_monto, ml_monto)
            st.session_state["salida"] = (resumen, resultado, a_excel(resumen, resultado))

    if "salida" in st.session_state:
        resumen, resultado, excel = st.session_state["salida"]
        st.subheader("Resultado")
        st.dataframe(resumen, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Descargar Excel con el cruce",
            data=excel,
            file_name="conciliacion_mp_vs_mayor.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        t1, t2, t3 = st.tabs(["Todo", "Solo MP", "Solo Mayor"])
        t1.dataframe(resultado, use_container_width=True, hide_index=True)
        t2.dataframe(resultado[resultado["Estado"] == "Solo MP"], use_container_width=True, hide_index=True)
        t3.dataframe(resultado[resultado["Estado"] == "Solo Mayor"], use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()