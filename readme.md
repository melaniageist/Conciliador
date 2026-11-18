# Conciliador Mercado Pago vs Mayor de liquidaciones

Aplicación web hecha con **Python + Streamlit** que concilia la cuenta de Mercado Pago (MP) contra el mayor de liquidaciones. Cruza por **fecha de aprobación** y **monto bruto**, y devuelve un Excel con todos los datos de ambos archivos.

## Requisitos

- Python 3.9 o superior
- Librerías: `streamlit`, `pandas`, `openpyxl`

```bash
pip install streamlit pandas openpyxl
```

> Si tus archivos están en formato `.xls` (antiguo), instalá también `xlrd`. Se recomienda usar `.xlsx`.

## Ejecución

```bash
streamlit run conciliador_mp.py
```

Se abre en el navegador (por defecto en `http://localhost:8501`).

## Archivos de entrada

| Archivo | Columnas esperadas |
|---|---|
| **Excel de MP** | ID · Fecha de aprobación · Fecha de liberación · Descripción · Monto bruto |
| **Excel del Mayor** | Fecha (equivale a la fecha de aprobación) · Descripción · Monto bruto |

Los nombres de columna no tienen que ser exactos: la app sugiere automáticamente las columnas de fecha y monto, y podés cambiarlas manualmente. También podés elegir la **hoja** y la **fila de encabezados** de cada archivo.

Formatos admitidos:

- **Fechas:** se interpretan como día/mes/año (también acepta fechas nativas de Excel). Si traen hora, se usa solo el día para el cruce.
- **Montos:** números de Excel o texto con formato `1.234,56` / `1,234.56`, con o sin `$`. Los montos entre paréntesis se toman como negativos.

## Uso

1. Subí el Excel de MP y el del Mayor.
2. Verificá la hoja, la fila de encabezados y las columnas de fecha y monto.
3. (Opcional) Ajustá las opciones de cruce.
4. Presioná **Conciliar**.
5. Revisá el resumen y descargá el Excel con el resultado.

## Cómo funciona el cruce

El cruce se hace en pasos, y cada movimiento se usa una sola vez:

1. **Uno a uno exacto:** misma fecha de aprobación y mismo monto bruto (al centavo). Si hay varios movimientos con la misma fecha y monto, se emparejan de a uno, sin duplicar ni perder ninguno.
2. **Uno a uno con tolerancia:** solo si configurás una tolerancia mayor a 0. Toma el candidato de menor diferencia.
3. **Uno a varios** (opcional): un movimiento de MP cuyo monto es igual a la **suma de varios movimientos del mayor del mismo día** (tipo `1 MP = varios Mayor`).
4. **Varios a uno** (opcional): el caso inverso (tipo `varios MP = 1 Mayor`).
5. Lo que no se cruza queda como **Solo MP** o **Solo Mayor**. Las filas con fecha o monto no interpretables se marcan como **Dato inválido**.

### Opciones de cruce

| Opción | Descripción | Por defecto |
|---|---|---|
| Tolerancia de monto | Diferencia máxima aceptada, en pesos | 0 (exacto) |
| Cruces uno-a-varios | Activa los pasos 3 y 4 | Activado |
| Máx. de movimientos por combinación | Cantidad máxima de movimientos a sumar (2 a 8) | 6 |

## Excel de salida

Archivo `conciliacion_mp_vs_mayor.xlsx` con cuatro hojas:

| Hoja | Contenido |
|---|---|
| **Resumen** | Cantidad y monto de movimientos conciliados (1 a 1, uno a varios) y no conciliados |
| **Conciliación** | Todas las filas de ambos archivos, lado a lado |
| **Solo MP** | Movimientos de MP sin contrapartida en el mayor |
| **Solo Mayor** | Movimientos del mayor sin contrapartida en MP |

En la hoja **Conciliación**, las columnas originales se mantienen con prefijo `MP | …` y `Mayor | …`, y se agregan:

- **Grupo:** número que agrupa las filas que se concilian entre sí.
- **Tipo de cruce:** `1 a 1`, `1 MP = varios Mayor`, `varios MP = 1 Mayor`, `Solo MP`, `Solo Mayor` o dato inválido.
- **Estado:** `Conciliado` o el motivo por el que no se cruzó.
- **Diferencia (MP - Mayor):** diferencia de montos del grupo, en la primera fila de cada grupo.

Las filas se colorean según el estado (verde: conciliado, naranja: solo MP, amarillo: solo mayor).

> En los cruces uno-a-varios, los datos del lado "uno" aparecen solo en la primera fila del grupo y las siguientes quedan en blanco de ese lado. Así no se duplican los montos si sumás una columna.

## Limitaciones

- Para armar combinaciones de suma, se consideran como máximo **20 movimientos sin cruzar por día** (por rendimiento).
- Las fechas del Excel de salida se muestran sin hora (`dd/mm/aaaa`).
- La columna **Fecha de liberación** de MP no interviene en el cruce, pero se conserva en el resultado.
- El cruce uno-a-varios es una coincidencia por suma en el mismo día. Conviene revisar esos grupos, ya que sin una clave común (referencia, lote, cliente) pueden darse coincidencias casuales.

## Estructura del código

| Función | Rol |
|---|---|
| `a_numero` / `preparar` | Limpieza de fechas y montos (los montos se pasan a centavos enteros para evitar errores de redondeo) |
| `conciliar` | Lógica de cruce |
| `armar_resultado` / `armar_resumen` | Construcción de las tablas de salida |
| `a_excel` | Generación del Excel con formato |
| `main` | Interfaz de Streamlit |