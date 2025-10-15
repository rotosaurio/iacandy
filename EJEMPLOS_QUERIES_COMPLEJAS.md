# 🚀 Ejemplos de Queries Complejas - MicroSIP

El sistema ahora puede generar queries SQL complejas que combinan múltiples tablas y realizan análisis avanzados.

## 📊 ANÁLISIS DE VENTAS

### 1. Top 10 clientes por ventas del año
```
¿Quiénes son los 10 mejores clientes de 2025 por importe total?
```

### 2. Ventas por mes con comparativa
```
Dame las ventas totales por mes de 2025 comparadas con 2024
```

### 3. Análisis de facturación por cliente
```
Muestra el total facturado, cantidad de facturas y ticket promedio por cliente este año
```

### 4. Productos más vendidos por categoría
```
¿Cuáles son los 5 productos más vendidos por cada línea de artículos en 2025?
```

### 5. Análisis de devoluciones
```
Dame los productos con más devoluciones y su porcentaje sobre las ventas totales
```

## 📦 INVENTARIO Y STOCK

### 6. Artículos con stock bajo
```
¿Qué artículos activos tienen existencia por debajo del mínimo?
```

### 7. Rotación de inventario
```
Muestra los productos con mayor rotación (más ventas vs stock promedio) en los últimos 3 meses
```

### 8. Valorización de inventario
```
Dame la valorización total del inventario por almacén (existencia * costo)
```

### 9. Artículos sin movimiento
```
¿Cuáles artículos no han tenido ventas ni compras en los últimos 6 meses?
```

### 10. Stock por almacén y proveedor
```
Muestra el inventario agrupado por almacén y proveedor con sus valores
```

## 💰 ANÁLISIS FINANCIERO

### 11. Rentabilidad por producto
```
Dame los 20 productos más rentables (diferencia entre precio de venta y costo)
```

### 12. Margen de utilidad
```
Calcula el margen de utilidad promedio por línea de artículos
```

### 13. Análisis de cobros
```
¿Cuál es el saldo pendiente de cobro por cliente ordenado de mayor a menor?
```

### 14. Ventas vs Compras
```
Compara el total de ventas vs compras por mes de este año
```

### 15. Análisis de descuentos
```
¿Cuánto se ha descontado en total por cliente en 2025?
```

## 👥 ANÁLISIS DE CLIENTES

### 16. Clientes por zona con estadísticas
```
Dame las ventas totales, ticket promedio y frecuencia de compra por zona de clientes
```

### 17. Nuevos clientes por mes
```
¿Cuántos clientes nuevos se han dado de alta cada mes en 2025?
```

### 18. Análisis de comportamiento
```
Muestra los clientes que compraron este mes pero no el mes pasado
```

### 19. Productos por cliente
```
¿Qué productos compra más cada uno de mis top 10 clientes?
```

### 20. Clientes inactivos
```
Lista los clientes que no han comprado en los últimos 3 meses
```

## 🏪 ANÁLISIS DE PROVEEDORES

### 21. Compras por proveedor
```
Dame el total de compras por proveedor en 2025 con cantidad de órdenes
```

### 22. Artículos por proveedor
```
¿Cuántos artículos activos tengo de cada proveedor?
```

### 23. Análisis de tiempos de entrega
```
Muestra el tiempo promedio entre orden de compra y recepción por proveedor
```

### 24. Proveedores más utilizados
```
¿Cuáles son los 5 proveedores con más movimientos en los últimos 6 meses?
```

## 📈 ANÁLISIS AVANZADOS

### 25. Análisis ABC de productos
```
Clasifica los productos en categoría A (80% ventas), B (15%) y C (5%)
```

### 26. Tendencia de ventas
```
Muestra la tendencia de ventas de los últimos 12 meses con porcentaje de crecimiento mes a mes
```

### 27. Cross-selling
```
¿Qué productos se venden juntos frecuentemente? (productos en las mismas facturas)
```

### 28. Análisis por vendedor
```
Compara el desempeño de ventas por vendedor incluyendo total, cantidad y ticket promedio
```

### 29. Estacionalidad
```
¿En qué meses del año vendemos más de cada línea de productos?
```

### 30. Análisis de precios
```
Compara los precios de venta actuales con los costos y muestra productos con margen negativo
```

## 🔍 CONSULTAS CON MÚLTIPLES CONDICIONES

### 31. Productos específicos por múltiples criterios
```
Dame los artículos de la línea "ELECTRÓNICOS" que tengan existencia mayor a 10, precio mayor a $1000 y se hayan vendido más de 5 veces este mes
```

### 32. Análisis combinado
```
Muestra los clientes de la zona "NORTE" que han comprado más de $50,000 este año, con su producto más comprado y el total de facturas
```

### 33. Comparativa compleja
```
Compara las ventas de este mes vs el mismo mes del año pasado por línea de producto, mostrando diferencia y porcentaje de variación
```

## 💡 TIPS PARA QUERIES COMPLEJAS

1. **Sé específico con las fechas**: "en enero 2025", "últimos 3 meses", "este año"
2. **Menciona las relaciones**: "por cliente", "por producto", "por almacén"
3. **Pide métricas**: "total", "promedio", "porcentaje", "diferencia"
4. **Indica ordenamiento**: "top 10", "los mejores", "de mayor a menor"
5. **Combina conceptos**: "ventas por cliente y producto", "inventario valorizado por proveedor"

## ⚡ El sistema automáticamente:
- ✅ Combina las tablas necesarias (JOINs)
- ✅ Agrega filtros de optimización (fechas, estados activos)
- ✅ Incluye nombres descriptivos (no solo IDs)
- ✅ Calcula métricas derivadas (totales, promedios, porcentajes)
- ✅ Ordena por relevancia
- ✅ Optimiza para que sea rápido

## 🎯 ¡PRUEBA TUS PROPIAS QUERIES!

El sistema entiende lenguaje natural, así que puedes preguntar lo que necesites. Ejemplos:

- "Quiero saber qué productos no han rotado en 6 meses"
- "Dame un análisis de las ventas por vendedor este trimestre"
- "Necesito los clientes morosos con más de 30 días de atraso"
- "Muestra la evolución mensual del inventario"
- "¿Qué artículos tienen el mejor margen de ganancia?"

**¡El límite es tu imaginación!** 🚀


