-- Consulta corregida para ventas de BOLITO LISTON NEGRO NUM5 en septiembre 2025
-- Esta consulta usa los filtros correctos para documentos válidos en MicroSIP

SELECT
    pvd.ARTICULO_ID,
    a.NOMBRE AS ARTICULO,
    SUM(pvd.UNIDADES) AS UNIDADES_VENDIDAS,
    SUM(pvd.PRECIO_TOTAL_NETO) AS IMPORTE_TOTAL
FROM DOCTOS_PV pv
INNER JOIN DOCTOS_PV_DET pvd ON pvd.DOCTO_PV_ID = pv.DOCTO_PV_ID
INNER JOIN ARTICULOS a ON a.ARTICULO_ID = pvd.ARTICULO_ID
WHERE pv.FECHA >= DATE '2025-09-01'
    AND pv.FECHA < DATE '2025-10-01'
    AND pv.CANCELADO = 'N'  -- ← Filtro correcto para documentos válidos (NO ESTATUS = 'A')
    AND pv.TIPO_DOCTO = 'V'  -- ← Tipo de documento para ventas (NO 'F' o 'T')
    AND a.NOMBRE = 'BOLITO LISTON NEGRO NUM5'
    AND pvd.UNIDADES > 0
    AND pvd.PRECIO_TOTAL_NETO > 0
GROUP BY pvd.ARTICULO_ID, a.NOMBRE;
