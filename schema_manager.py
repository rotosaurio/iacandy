"""
Gestor de esquema con sistema RAG para identificar tablas relevantes.

Este módulo implementa un sistema de Retrieval-Augmented Generation (RAG)
que utiliza embeddings vectoriales para encontrar las tablas más relevantes
para una consulta específica.
"""

import json
import os
import time
import threading
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from openai import OpenAI

from config import config, StatusMessages
from database import db, TableInfo
from utils import logger, timing_decorator, cache_manager, DataFormatter


# ============================================================================
# DICCIONARIO DE SEMÁNTICA DE COLUMNAS PARA ENRIQUECER CONTEXTO RAG
# ============================================================================
# Este diccionario proporciona contexto semántico detallado de columnas comunes
# en bases de datos de MicroSIP para mejorar la generación de SQL por IA.
# Incluye: valores válidos, casos especiales, relaciones FK, y ejemplos de uso.
# ============================================================================

COLUMN_SEMANTICS = {
    # ===== IDENTIFICADORES Y CLAVES PRIMARIAS =====
    'ARTICULO_ID': 'PK: Identificador único de artículo. FK en DOCTOS_PV_DET, DOCTOS_VE_DET, DOCTOS_CM_DET, DOCTOS_IN_DET, PRECIOS_ARTICULOS. Usar para JOIN con tabla ARTICULOS. Consultas: COUNT(DISTINCT ARTICULO_ID) para contar productos únicos',
    'CLIENTE_ID': 'PK: Identificador único de cliente. FK en DOCTOS_PV, DOCTOS_VE, DOCTOS_CC. Usar para JOIN con tabla CLIENTES. Filtrar CLIENTE_ID > 0 para excluir clientes especiales',
    'PROVEEDOR_ID': 'PK: Identificador único de proveedor. FK en DOCTOS_CM, PRECIOS_COMPRA. Usar para JOIN con tabla PROVEEDORES',
    'EMPLEADO_ID': 'PK: Identificador único de empleado. FK en DOCTOS_PV, NOMINAS, PAGOS_NOMINA. Usar para JOIN con tabla EMPLEADOS',
    'ALMACEN_ID': 'PK: Identificador único de almacén. FK en DOCTOS_IN_DET, SALDOS_IN, TRASPASOS_IN. Usar para JOIN con tabla ALMACENES',
    'SUCURSAL_ID': 'PK: Identificador de sucursal. FK en DOCTOS_PV, DOCTOS_VE, DOCTOS_CM. Usar para JOIN con tabla SUCURSALES para análisis multisucursal',
    'AGENTE_ID': 'PK: Identificador de agente/vendedor. FK en DOCTOS_PV, DOCTOS_VE, CLIENTES. Usar para análisis de desempeño por vendedor',
    'LINEA_ARTICULO_ID': 'PK: Identificador de línea de productos. FK en ARTICULOS. Usar para JOIN con LINEAS_ARTICULOS para agrupar por categoría',

    # ===== CLAVES Y CÓDIGOS ALFANUMÉRICOS =====
    'CVE_ART': 'Código alfanumérico de artículo (VARCHAR). IMPORTANTE: puede contener valores especiales del sistema como "GLOBAL", "CORTE", "VENTA GLOBAL". Filtrar WHERE CVE_ART NOT LIKE "%GLOBAL%" para excluir artículos de sistema. Usar para búsquedas por código',
    'CVE_CLPV': 'Código de cliente en Punto de Venta (VARCHAR). Similar a CVE_ART, puede tener valores especiales como "MOSTRADOR", "PUBLICO GENERAL". Filtrar clientes mostrador si se necesitan clientes reales',
    'FOLIO': 'Número de documento/factura (INTEGER). Usar con TIPO_DOCTO para identificar documentos únicos. Ejemplo: WHERE TIPO_DOCTO = "F" AND FOLIO BETWEEN 1000 AND 2000',
    'UUID': 'Folio fiscal del SAT (VARCHAR 36). Identificador único de CFDI para facturación electrónica. NULL = documento sin timbrar',

    # ===== TIPOS Y ESTADOS =====
    'TIPO_DOCTO': 'Tipo de documento (CHAR 1). Valores: F=Factura, T=Ticket, D=Devolución, N=Nota de crédito, P=Pedido, C=Cotización. Usar para filtrar por tipo de transacción. Ejemplo: WHERE TIPO_DOCTO IN ("F", "T") para ventas válidas',
    'ESTATUS': 'Estado del registro (CHAR 1). Valores comunes: A=Activo, I=Inactivo, S=Suspendido, C=Cancelado. Usar WHERE ESTATUS = "A" para registros activos. Crítico para contar elementos válidos',
    'STATUS_DOCTO': 'Estado del documento (VARCHAR). Valores: CONCLUIDO, PENDIENTE, CANCELADO, BORRADOR. Filtrar CANCELADO para transacciones válidas',
    'APLICADO': 'Indicador de aplicación contable (CHAR 1). S=Aplicado, N=No aplicado. Filtrar WHERE APLICADO = "S" para documentos contabilizados',
    'CANCELADO': 'Indicador de cancelación (CHAR 1). S=Cancelado, N=Vigente. IMPORTANTE: Filtrar WHERE CANCELADO = "N" para transacciones válidas',

    # ===== NOMBRES Y DESCRIPCIONES =====
    'NOMBRE': 'Nombre descriptivo (VARCHAR). ADVERTENCIA: puede contener valores de sistema como "VENTA GLOBAL", "CORTE DE CAJA", "AJUSTE INVENTARIO". Filtrar WHERE NOMBRE NOT LIKE "%GLOBAL%" AND NOMBRE NOT LIKE "%CORTE%" para datos reales',
    'DESCRIPCION1': 'Descripción principal del artículo (VARCHAR). Igual que NOMBRE, puede incluir artículos de sistema. Usar para búsquedas de texto con LIKE',
    'DESCRIPCION2': 'Descripción secundaria del artículo (VARCHAR). Información adicional del producto',
    'RAZON_SOCIAL': 'Razón social de cliente/proveedor (VARCHAR). Nombre fiscal para facturación',

    # ===== CANTIDADES Y UNIDADES =====
    'UNIDADES': 'Cantidad de unidades en la transacción (DECIMAL). IMPORTANTE: Debe ser > 0 para ventas/compras reales. Valores negativos = devoluciones. Usar SUM(UNIDADES) para totales',
    'CANTIDAD': 'Cantidad genérica (DECIMAL). Similar a UNIDADES. Verificar > 0 para transacciones válidas',
    'EXISTENCIA': 'Cantidad disponible en inventario (DECIMAL). Usar para consultas de stock disponible. Puede ser negativo en casos de sobregiro',
    'UNIDAD_VENTA': 'Unidad de medida para ventas (VARCHAR). Ej: PZA, KG, LT, M, CAJA',
    'UNIDAD_COMPRA': 'Unidad de medida para compras (VARCHAR). Puede diferir de UNIDAD_VENTA',
    'CONTENIDO_UNIDAD_COMPRA': 'Factor de conversión entre unidad de compra y venta (INTEGER). Ej: 1 CAJA = 12 PZA',

    # ===== VALORES MONETARIOS =====
    'IMPORTE': 'Monto total de la transacción (DECIMAL). CRÍTICO: Debe ser > 0 para transacciones válidas. Usar SUM(IMPORTE) para totales de ventas. Incluye impuestos según configuración',
    'PRECIO': 'Precio unitario sin impuestos (DECIMAL). Usar para cálculos de precio promedio',
    'PRECIO_TOTAL_NETO': 'Precio con todos los descuentos aplicados (DECIMAL). Usar para cálculo de márgenes',
    'COSTO': 'Costo unitario del artículo (DECIMAL). Usar para cálculo de utilidad bruta',
    'COSTO_PROMEDIO': 'Costo promedio ponderado (DECIMAL). Método de valuación UEPS/PEPS',
    'SUBTOTAL': 'Subtotal antes de impuestos (DECIMAL). SUBTOTAL + IMPUESTOS = TOTAL',
    'TOTAL': 'Monto total con impuestos (DECIMAL). Monto final pagado/cobrado',
    'IMPUESTOS': 'Suma de IVA + IEPS + otros impuestos (DECIMAL). Desglosar si necesitas impuestos específicos',
    'IVA': 'Impuesto al Valor Agregado (DECIMAL). Generalmente 16% en México',
    'DESCUENTO': 'Descuento aplicado en importe (DECIMAL). Puede ser monto fijo o porcentaje',
    'PCTJE_DESCUENTO': 'Porcentaje de descuento (DECIMAL 0-100). 0 = sin descuento',

    # ===== FECHAS Y TIEMPOS =====
    'FECHA': 'Fecha de la transacción (DATE). Usar para filtros temporales. Formato: YYYY-MM-DD. Ejemplo: WHERE FECHA >= CURRENT_DATE - 30 para últimos 30 días',
    'FECHA_HORA': 'Fecha y hora exacta (TIMESTAMP). Más preciso que FECHA para análisis por hora del día',
    'FECHA_HORA_CREACION': 'Timestamp de creación del registro (TIMESTAMP). Útil para auditoría',
    'FECHA_HORA_ULT_MODIF': 'Timestamp de última modificación (TIMESTAMP). Para tracking de cambios',
    'FECHA_ENTREGA': 'Fecha comprometida de entrega (DATE). Para pedidos y órdenes',
    'FECHA_VENCIMIENTO': 'Fecha de vencimiento de pago/documento (DATE). Para CxC y CxP',
    'FECHA_SUSP': 'Fecha de suspensión (DATE). Si tiene valor, el registro está suspendido',
    'YEAR': 'Año fiscal (INTEGER). Para reportes anuales sin necesidad de EXTRACT(YEAR FROM FECHA)',
    'MONTH': 'Mes (INTEGER 1-12). Para análisis mensual',

    # ===== PRECIOS Y LISTAS =====
    'PRECIO_LISTA': 'Precio de lista oficial (DECIMAL). Precio base antes de descuentos',
    'PRECIO_PUBLICO': 'Precio al público general (DECIMAL). Generalmente incluye IVA',
    'PRECIO_ECONOMICO': 'Precio promocional (DECIMAL). Precio especial o de oferta',
    'LISTA_PRECIOS': 'Identificador de lista de precios (VARCHAR). Ej: GENERAL, MAYOREO, DISTRIBUIDOR',
    'ES_PRECIO_VARIABLE': 'Indicador de precio variable (CHAR). S=Precio se puede modificar, N=Precio fijo',

    # ===== CAMPOS CALCULADOS Y AGREGADOS =====
    'UTILIDAD': 'Utilidad bruta (DECIMAL). Generalmente = PRECIO - COSTO o calculado dinámicamente',
    'PCTJE_UTILIDAD': 'Porcentaje de utilidad (DECIMAL). = (PRECIO - COSTO) / COSTO * 100',
    'SALDO': 'Saldo pendiente (DECIMAL). En CxC/CxP, TOTAL - PAGOS = SALDO',
    'IMPORTE_PAGADO': 'Monto ya pagado (DECIMAL). Para control de pagos parciales',
    'IMPORTE_PENDIENTE': 'Monto pendiente de pago (DECIMAL). = TOTAL - IMPORTE_PAGADO',

    # ===== UBICACIÓN Y GEOGRAFÍA =====
    'CODIGO_POSTAL': 'Código postal (VARCHAR). Para análisis geográfico',
    'CIUDAD': 'Ciudad (VARCHAR). Para segmentación por ubicación',
    'ESTADO': 'Estado/Provincia (VARCHAR). Usar con cuidado, puede confundirse con ESTATUS',
    'PAIS': 'País (VARCHAR). Para ventas internacionales',
    'ZONA': 'Zona de ventas (VARCHAR). Segmentación comercial',
    'RUTA': 'Ruta de reparto (VARCHAR). Para logística',

    # ===== FISCALES Y LEGALES =====
    'RFC': 'Registro Federal de Contribuyentes (VARCHAR 13). Identificador fiscal en México',
    'REGIMEN_FISCAL': 'Régimen fiscal del contribuyente (VARCHAR). Ej: 601, 612, 626',
    'USO_CFDI': 'Uso del CFDI (VARCHAR). Ej: G01, G03, P01 según catálogo SAT',
    'FORMA_PAGO': 'Forma de pago SAT (VARCHAR). Ej: 01=Efectivo, 03=Transferencia, 04=Tarjeta',
    'METODO_PAGO': 'Método de pago SAT (VARCHAR). PUE=Pago en una exhibición, PPD=Pago diferido',

    # ===== CAMPOS DE AUDITORÍA =====
    'USUARIO_CREADOR': 'Usuario que creó el registro (VARCHAR). Para auditoría de operaciones',
    'USUARIO_ULT_MODIF': 'Usuario que modificó por última vez (VARCHAR). Tracking de cambios',
    'USUARIO_AUT_CREACION': 'Usuario que autorizó la creación (VARCHAR). Para procesos con autorización',
    'USUARIO_CANCELACION': 'Usuario que canceló el documento (VARCHAR). Si tiene valor, doc está cancelado',

    # ===== RELACIONES Y REFERENCIAS =====
    'DOCTO_PV_ID': 'FK a documento de punto de venta. Usar para JOIN con DOCTOS_PV (encabezado)',
    'DOCTO_VE_ID': 'FK a documento de ventas. Usar para JOIN con DOCTOS_VE',
    'DOCTO_CM_ID': 'FK a documento de compras. Usar para JOIN con DOCTOS_CM',
    'DOCTO_CC_ID': 'FK a documento de CxC. Usar para JOIN con DOCTOS_CC',
    'MOVTO_ID': 'FK a movimiento de inventario. Usar para JOIN con DOCTOS_IN',
    'PARTIDA': 'Número de partida/línea en detalle (INTEGER). Para identificar líneas en _DET',

    # ===== INDICADORES BOOLEANOS (CHAR 1) =====
    'ES_ALMACENABLE': 'Indicador si el artículo es almacenable (CHAR). S=Sí almacenable, N=Servicio/No almacenable',
    'ES_JUEGO': 'Indicador si es un juego/kit (CHAR). S=Kit de productos, N=Producto simple',
    'ES_PESO_VARIABLE': 'Indicador de peso variable (CHAR). S=Se vende por peso (ej: carnes), N=Peso fijo',
    'ES_IMPORTADO': 'Indicador de producto importado (CHAR). S=Importado, N=Nacional',
    'INCLUYE_IMPUESTO': 'Indicador si precio incluye IVA (CHAR). S=Precio con IVA, N=Precio sin IVA',
    'APLICA_COMISION': 'Indicador si aplica comisión a vendedor (CHAR). S=Comisionable, N=Sin comisión',

    # ===== CAMPOS ESPECIALES Y ADVERTENCIAS =====
    'SERIE': 'ADVERTENCIA: NO existe en DOCTOS_PV, DOCTOS_VE, DOCTOS_CC. Usar solo TIPO_DOCTO + FOLIO. En otras tablas, Serie de documento',
    'FECHA_DOCUMENTO': 'ADVERTENCIA: NO existe en DOCTOS_PV, DOCTOS_VE. Usar solo FECHA',
    'GRUPO_ARTICULO_ID': 'FK a grupo de artículos. DIFERENTE de LINEA_ARTICULO_ID. Subclasificación dentro de línea',
    'FAMILIA_ARTICULO_ID': 'FK a familia de artículos. Nivel superior a LINEA. Jerarquía: FAMILIA > LINEA > GRUPO',

    # ===== CONSULTAS COMUNES Y EJEMPLOS =====
    '__QUERY_EXAMPLES': {
        'ventas_periodo': 'SELECT SUM(IMPORTE) FROM DOCTOS_PV WHERE FECHA BETWEEN X AND Y AND CANCELADO = "N"',
        'articulos_activos': 'SELECT COUNT(*) FROM ARTICULOS WHERE ESTATUS = "A"',
        'top_clientes': 'SELECT CLIENTE_ID, SUM(IMPORTE) FROM DOCTOS_PV WHERE CANCELADO = "N" GROUP BY CLIENTE_ID ORDER BY 2 DESC FIRST 10',
        'inventario_bajo': 'SELECT ARTICULO_ID, EXISTENCIA FROM SALDOS_IN WHERE EXISTENCIA < MINIMO',
        'productos_vendidos': 'SELECT COUNT(DISTINCT ARTICULO_ID) FROM DOCTOS_PV_DET WHERE DOCTO_PV_ID IN (SELECT DOCTO_PV_ID FROM DOCTOS_PV WHERE CANCELADO = "N")',
    }
}


class EmbeddingGenerator:
    """Generador de embeddings usando OpenAI API directamente (hardcodeado)."""

    def __init__(self):
        self.openai_client = None
        self._model_lock = threading.Lock()

    def _load_model(self):
        """Cargar cliente de OpenAI lazy loading."""
        if self.openai_client is None:
            with self._model_lock:
                if self.openai_client is None:
                    logger.info("Inicializando cliente OpenAI para embeddings (text-embedding-3-small)")
                    # HARDCODED: Usar API key de config
                    self.openai_client = OpenAI(api_key=config.ai.api_key)
                    logger.info("Cliente OpenAI inicializado correctamente")

    def generate_embedding(self, text: str) -> List[float]:
        """Generar embedding para un texto usando OpenAI API."""
        self._load_model()

        if not text or not text.strip():
            return [0.0] * 1536  # Dimensiones de text-embedding-3-small

        try:
            # Llamada directa a OpenAI API v1.0+
            response = self.openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=text.strip()
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Error generando embedding: {e}")
            return [0.0] * 1536

    def generate_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generar embeddings para múltiples textos usando OpenAI API (hasta 100 textos por batch)."""
        self._load_model()

        if not texts:
            return []

        # Filtrar textos vacíos
        clean_texts = [text.strip() if text else " " for text in texts]

        try:
            # OpenAI permite hasta 100 embeddings por request
            all_embeddings = []
            batch_size = 100

            for i in range(0, len(clean_texts), batch_size):
                batch = clean_texts[i:i + batch_size]

                response = self.openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=batch
                )

                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)

            return all_embeddings

        except Exception as e:
            logger.error(f"Error generando batch de embeddings: {e}")
            return [[0.0] * 1536 for _ in clean_texts]


class TableDescriptor:
    """Generador de descripciones semánticas de tablas."""
    
    # Cargar diccionario de MicroSIP si existe
    _microsip_dict = None
    
    @classmethod
    def _load_microsip_dict(cls):
        """Cargar diccionario de MicroSIP una sola vez."""
        if cls._microsip_dict is None:
            try:
                import os
                dict_path = os.path.join(os.path.dirname(__file__), 'microsip_dictionary.json')
                if os.path.exists(dict_path):
                    with open(dict_path, 'r', encoding='utf-8') as f:
                        cls._microsip_dict = json.load(f)
                        logger.info("Diccionario de MicroSIP cargado exitosamente")
                else:
                    cls._microsip_dict = {}
            except Exception as e:
                logger.warning(f"No se pudo cargar diccionario de MicroSIP: {e}")
                cls._microsip_dict = {}
        return cls._microsip_dict
    
    @classmethod
    def describe_table(cls, table_info: TableInfo, sample_data: List[List[Any]] = None) -> str:
        """Generar descripción semántica enriquecida de una tabla."""
        description_parts = []

        # Cargar diccionario de MicroSIP
        microsip_dict = cls._load_microsip_dict()

        # Nombre de tabla procesado
        table_name = table_info.name.lower()
        table_name_upper = table_info.name.upper()

        # === PARTE 1: PROPÓSITO DE NEGOCIO (lo más importante para embeddings) ===
        business_purpose = cls._infer_business_purpose(table_name, table_info.columns)
        if business_purpose:
            description_parts.append(business_purpose)

        # Información de MicroSIP para keywords adicionales
        if microsip_dict and 'tablas' in microsip_dict and table_name_upper in microsip_dict['tablas']:
            ms_info = microsip_dict['tablas'][table_name_upper]
            categoria = ms_info.get('categoria', '')

            if categoria and categoria != 'OTROS':
                description_parts.append(f"Categoría: {categoria.lower().replace('_', ' ')}")

            # Agregar keywords de búsqueda de MicroSIP
            if 'keywords_busqueda' in microsip_dict and table_name_upper in microsip_dict['keywords_busqueda']:
                keywords = microsip_dict['keywords_busqueda'][table_name_upper][:10]
                description_parts.append(f"Búsquedas comunes: {', '.join(keywords)}")

        # === PARTE 2: ANÁLISIS SEMÁNTICO DE CONTENIDO ===
        semantic_summary = cls._generate_semantic_summary(table_info.columns)
        if semantic_summary:
            description_parts.append(semantic_summary)

        # === PARTE 3: DATOS DE MUESTRA (si están disponibles) ===
        if sample_data and table_info.columns:
            sample_desc = cls._describe_sample_data_enriched(table_info.columns, sample_data)
            if sample_desc:
                description_parts.append(f"Ejemplos: {sample_desc}")

            # Análisis de patrones avanzados
            patterns = cls._analyze_data_patterns(table_info.columns, sample_data)
            if patterns:
                description_parts.append(f"Características: {patterns}")

        # === PARTE 4: RELACIONES Y CONTEXTO ===
        relationship_desc = cls._describe_relationships(table_info.foreign_keys)
        if relationship_desc:
            description_parts.append(relationship_desc)

        # === PARTE 5: CAMPOS CLAVE ===
        key_fields_desc = cls._describe_key_fields(table_info.columns, table_info.primary_keys)
        if key_fields_desc:
            description_parts.append(key_fields_desc)

        # === PARTE 6: PATRONES DE CONSULTA SQL COMUNES ===
        query_patterns = cls._generate_query_patterns(table_info.name, table_info.columns, table_info.primary_keys)
        if query_patterns:
            description_parts.append(query_patterns)

        # === PARTE 7: METADATOS TÉCNICOS (menos peso para embeddings) ===
        if table_info.row_count > 0:
            volume_desc = cls._describe_data_volume(table_info.row_count)
            description_parts.append(f"Volumen: {volume_desc}")

        # === PARTE 8: OPTIMIZACIÓN PARA EMBEDDINGS ===
        # Unir con separadores optimizados para modelos de embeddings
        # El separador " | " ayuda a que el modelo sentence-transformer
        # mantenga la estructura semántica de cada segmento
        full_description = " | ".join(description_parts)

        # Agregar sinónimos y términos de búsqueda para mejorar recall
        search_terms = cls._generate_search_terms(table_name, table_info.columns)
        if search_terms:
            full_description += f" | Términos: {search_terms}"

        return full_description
    
    @staticmethod
    def _infer_business_purpose(table_name: str, columns: List[Dict[str, Any]]) -> str:
        """
        Inferir el propósito de negocio combinando nombre de tabla y análisis de columnas.
        Genera descripciones orientadas al negocio, no técnicas.
        """
        name_lower = table_name.lower()
        col_names = [col['name'].lower() for col in columns]
        col_names_str = ' '.join(col_names)

        # Detectar tipo de tabla por patrón de columnas + nombre
        purposes = []

        # Transacciones de venta
        if any(k in name_lower for k in ['venta', 'factura', 'ticket', 'pos', 'doctos_pv', 'doctos_ve']):
            if any(k in col_names_str for k in ['importe', 'precio', 'unidades', 'cantidad']):
                purposes.append("Registra transacciones de venta")
                if 'det' in name_lower or 'detalle' in name_lower:
                    purposes.append("Detalle de productos vendidos en cada operación")
                else:
                    purposes.append("Encabezado de documentos de venta con cliente, fecha y totales")

        # Clientes
        elif any(k in name_lower for k in ['cliente', 'customer']):
            purposes.append("Información de clientes y compradores")
            if 'direccion' in col_names_str or 'domicilio' in col_names_str:
                purposes.append("Incluye datos de contacto y ubicación")

        # Productos/Artículos
        elif any(k in name_lower for k in ['articulo', 'producto', 'item']):
            purposes.append("Catálogo de productos y artículos comercializados")
            if 'precio' in col_names_str:
                purposes.append("Contiene precios y características de venta")
            if 'existencia' in col_names_str or 'stock' in col_names_str:
                purposes.append("Incluye información de inventario disponible")

        # Inventario y existencias
        elif any(k in name_lower for k in ['existencia', 'inventario', 'stock']):
            purposes.append("Control de inventario y cantidades disponibles por almacén")
            if 'movimiento' in name_lower or 'movto' in name_lower:
                purposes.append("Registra movimientos de entrada y salida de mercancía")

        # Compras
        elif any(k in name_lower for k in ['compra', 'purchase', 'orden_compra']):
            purposes.append("Gestión de compras y adquisiciones")
            if 'proveedor' in col_names_str:
                purposes.append("Relaciona órdenes con proveedores")

        # Proveedores
        elif any(k in name_lower for k in ['proveedor', 'vendor', 'supplier']):
            purposes.append("Información de proveedores y vendedores")

        # Empleados/Personal
        elif any(k in name_lower for k in ['empleado', 'employee', 'personal', 'vendedor']):
            purposes.append("Datos de empleados y personal de la empresa")

        # Pagos y cobranza
        elif any(k in name_lower for k in ['pago', 'cobranza', 'abono']):
            purposes.append("Gestión de pagos y cobranzas")
            if 'saldo' in col_names_str:
                purposes.append("Incluye seguimiento de saldos y deudas")

        # Catálogos
        elif any(k in name_lower for k in ['categoria', 'grupo', 'familia', 'linea', 'marca', 'tipo']):
            purposes.append("Catálogo de clasificación y agrupación")

        # Configuración
        elif any(k in name_lower for k in ['config', 'parametro', 'param']):
            purposes.append("Configuración y parámetros del sistema")

        # Si no detectamos nada específico, análisis genérico
        if not purposes:
            if 'fecha' in col_names_str and ('importe' in col_names_str or 'monto' in col_names_str):
                purposes.append("Registros transaccionales con fechas y valores monetarios")
            elif 'nombre' in col_names_str or 'descripcion' in col_names_str:
                purposes.append("Catálogo o maestro de datos")
            else:
                purposes.append(f"Tabla {table_name}")

        return ". ".join(purposes)

    @staticmethod
    def _generate_semantic_summary(columns: List[Dict[str, Any]]) -> str:
        """
        Generar resumen semántico enfocado en QUÉ información contiene, no cómo se estructura.
        """
        col_names = [col['name'].lower() for col in columns]
        col_names_str = ' '.join(col_names)

        semantic_elements = []

        # Identificadores
        ids = [col['name'] for col in columns if any(k in col['name'].lower() for k in ['_id', 'codigo', 'cve_', 'clave'])]
        if ids:
            semantic_elements.append(f"Identificadores: {', '.join(ids[:5])}")

        # Datos monetarios
        monetary = [col['name'] for col in columns if any(k in col['name'].lower() for k in ['precio', 'importe', 'costo', 'monto', 'total', 'subtotal'])]
        if monetary:
            semantic_elements.append(f"Valores monetarios: {', '.join(monetary[:5])}")

        # Cantidades
        quantities = [col['name'] for col in columns if any(k in col['name'].lower() for k in ['cantidad', 'unidades', 'qty', 'existencia', 'stock'])]
        if quantities:
            semantic_elements.append(f"Cantidades: {', '.join(quantities[:3])}")

        # Fechas
        dates = [col['name'] for col in columns if any(k in col['name'].lower() for k in ['fecha', 'date', 'timestamp', 'hora'])]
        if dates:
            semantic_elements.append(f"Fechas: {', '.join(dates[:3])}")

        # Personas
        persons = [col['name'] for col in columns if any(k in col['name'].lower() for k in ['cliente', 'proveedor', 'empleado', 'vendedor', 'usuario'])]
        if persons:
            semantic_elements.append(f"Personas/Entidades: {', '.join(persons[:3])}")

        # Descripciones/Nombres
        descriptions = [col['name'] for col in columns if any(k in col['name'].lower() for k in ['nombre', 'descripcion', 'name', 'desc'])]
        if descriptions:
            semantic_elements.append(f"Descripciones: {', '.join(descriptions[:3])}")

        return " | ".join(semantic_elements)

    @staticmethod
    def _describe_sample_data_enriched(columns: List[Dict[str, Any]], sample_data: List[List[Any]]) -> str:
        """
        Describir datos de muestra con enfoque en PATRONES y CONTENIDO real, no estadísticas.
        """
        if not sample_data or not columns:
            return ""

        descriptions = []

        for i, col in enumerate(columns[:8]):  # Primeras 8 columnas
            if i >= len(sample_data[0]):
                continue

            col_name = col['name']
            sample_values = [row[i] for row in sample_data[:10] if i < len(row) and row[i] is not None]

            if not sample_values:
                continue

            # Para textos, mostrar ejemplos reales
            if col['data_type'] in ['VARCHAR', 'CHAR']:
                unique_values = list(set(str(v) for v in sample_values))[:5]
                if len(unique_values) <= 5 and all(len(str(v)) < 50 for v in unique_values):
                    descriptions.append(f"{col_name}: \"{', '.join(unique_values)}\"")
                elif unique_values:
                    # Mostrar patrón
                    first_val = str(unique_values[0])
                    if first_val:
                        descriptions.append(f"{col_name} ejemplo: \"{first_val[:40]}\"")

            # Para números, mostrar rango significativo
            elif col['data_type'] in ['INTEGER', 'SMALLINT', 'BIGINT', 'DECIMAL', 'NUMERIC']:
                try:
                    numeric_vals = [float(v) for v in sample_values if v is not None]
                    if numeric_vals:
                        min_val = min(numeric_vals)
                        max_val = max(numeric_vals)
                        avg_val = sum(numeric_vals) / len(numeric_vals)
                        if min_val == max_val:
                            descriptions.append(f"{col_name}: {min_val}")
                        else:
                            descriptions.append(f"{col_name}: rango {min_val:.2f} a {max_val:.2f}")
                except:
                    pass

            # Para fechas, mostrar rango temporal
            elif col['data_type'] in ['DATE', 'TIMESTAMP']:
                try:
                    date_strs = [str(v) for v in sample_values if v]
                    if date_strs:
                        first_date = date_strs[0][:10] if len(date_strs[0]) >= 10 else date_strs[0]
                        last_date = date_strs[-1][:10] if len(date_strs[-1]) >= 10 else date_strs[-1]
                        if first_date == last_date:
                            descriptions.append(f"{col_name}: {first_date}")
                        else:
                            descriptions.append(f"{col_name}: desde {first_date}")
                except:
                    pass

        return " | ".join(descriptions[:6])  # Máximo 6 descripciones

    @staticmethod
    def _describe_relationships(foreign_keys: List[Dict[str, Any]]) -> str:
        """
        Describir relaciones FK en lenguaje de negocio con DETALLES EXPLÍCITOS.
        CRÍTICO: Esto ayuda a la IA a generar JOINs correctos.
        """
        if not foreign_keys:
            return ""

        relationships = []
        for fk in foreign_keys[:8]:  # Aumentado a 8 FKs para más contexto
            ref_table = fk.get('referenced_table', '')
            columns = fk.get('columns', [])
            ref_columns = fk.get('referenced_columns', [])

            if ref_table and columns:
                col_name = columns[0] if columns else ''
                ref_col_name = ref_columns[0] if ref_columns else ''
                col_lower = col_name.lower()

                # FORMATO MEJORADO: Incluir columnas explícitas para JOINs
                # Ejemplo: "FK: ARTICULO_ID → ARTICULOS.ARTICULO_ID (productos)"

                # Traducir a lenguaje de negocio
                if 'cliente' in col_lower:
                    business_name = "clientes"
                elif 'articulo' in col_lower or 'producto' in col_lower:
                    business_name = "productos"
                elif 'proveedor' in col_lower:
                    business_name = "proveedores"
                elif 'almacen' in col_lower:
                    business_name = "almacenes"
                elif 'empleado' in col_lower or 'vendedor' in col_lower:
                    business_name = "empleados"
                elif 'sucursal' in col_lower:
                    business_name = "sucursales"
                elif 'docto' in col_lower or 'documento' in col_lower:
                    business_name = "documentos"
                else:
                    business_name = ref_table.lower().replace('_', ' ')

                # Formato explícito con columnas para ayudar en generación de SQL
                if ref_col_name:
                    relationships.append(f"FK: {col_name} → {ref_table}.{ref_col_name} ({business_name})")
                else:
                    relationships.append(f"FK: {col_name} → {ref_table} ({business_name})")

        if relationships:
            return "Relaciones: " + " | ".join(relationships)
        return ""

    @staticmethod
    def _describe_key_fields(columns: List[Dict[str, Any]], primary_keys: List[str]) -> str:
        """
        Describir campos clave con contexto semántico EXPLÍCITO.
        Incluye PK, campos obligatorios, y su propósito.
        """
        key_desc = []

        # Primary keys con tipo de dato
        if primary_keys:
            pk_info = []
            for pk in primary_keys[:3]:
                pk_col = next((c for c in columns if c['name'] == pk), None)
                if pk_col:
                    data_type = pk_col.get('data_type', 'UNKNOWN')
                    pk_info.append(f"{pk} ({data_type})")
            key_desc.append(f"PK: {', '.join(pk_info)}")

        # Campos requeridos importantes (NOT NULL) con contexto
        required = [col for col in columns if not col.get('nullable', True)]
        important_required = [col for col in required if col['name'] not in primary_keys and len(col['name']) < 30][:6]

        if important_required:
            req_names = []
            for col in important_required:
                col_name = col['name']
                col_lower = col_name.lower()

                # Agregar contexto semántico a campos importantes
                if 'estatus' in col_lower or 'status' in col_lower:
                    req_names.append(f"{col_name} (estado/filtrar activos)")
                elif 'cancelado' in col_lower:
                    req_names.append(f"{col_name} (filtrar cancelados)")
                elif 'nombre' in col_lower or 'descripcion' in col_lower:
                    req_names.append(f"{col_name} (identificación)")
                elif 'fecha' in col_lower:
                    req_names.append(f"{col_name} (temporal)")
                elif 'tipo' in col_lower:
                    req_names.append(f"{col_name} (clasificación)")
                else:
                    req_names.append(col_name)

            key_desc.append(f"Obligatorios: {', '.join(req_names)}")

        # Índices importantes para búsquedas comunes
        search_fields = []
        for col in columns[:15]:  # Primeras 15 columnas
            col_lower = col['name'].lower()
            if any(k in col_lower for k in ['codigo', 'cve_', 'folio', 'numero']):
                search_fields.append(col['name'])

        if search_fields and len(search_fields) <= 4:
            key_desc.append(f"Búsqueda por: {', '.join(search_fields)}")

        return " | ".join(key_desc)

    @staticmethod
    def _describe_data_volume(row_count: int) -> str:
        """Describir volumen de datos en términos de negocio."""
        if row_count < 100:
            return f"catálogo pequeño ({row_count} registros)"
        elif row_count < 1000:
            return f"catálogo mediano ({row_count} registros)"
        elif row_count < 10000:
            return f"volumen moderado ({DataFormatter.format_number(row_count)} registros)"
        elif row_count < 100000:
            return f"volumen alto ({DataFormatter.format_number(row_count)} registros)"
        else:
            return f"volumen muy alto ({DataFormatter.format_number(row_count)} registros)"

    @staticmethod
    def _generate_query_patterns(table_name: str, columns: List[Dict[str, Any]], primary_keys: List[str]) -> str:
        """
        Generar patrones de consulta SQL comunes para esta tabla.
        CRÍTICO: Esto entrena a la IA con ejemplos de cómo consultar cada tabla.
        """
        name_lower = table_name.lower()
        col_names = {col['name'].lower(): col['name'] for col in columns}
        patterns = []

        # === PATRONES PARA TABLAS DE VENTAS ===
        if any(k in name_lower for k in ['doctos_pv', 'ventas', 'factura', 'ticket']):
            if 'fecha' in col_names and 'importe' in col_names:
                patterns.append("Ventas por período: SUM(IMPORTE) WHERE FECHA BETWEEN X AND Y")
            if 'cancelado' in col_names:
                patterns.append("Filtrar cancelados: WHERE CANCELADO = 'N'")
            if 'cliente_id' in col_names:
                patterns.append("Ventas por cliente: GROUP BY CLIENTE_ID")
            if 'tipo_docto' in col_names:
                patterns.append("Por tipo: WHERE TIPO_DOCTO IN ('F', 'T')")

        # === PATRONES PARA DETALLE DE VENTAS ===
        elif '_det' in name_lower and any(k in name_lower for k in ['pv', 'ventas']):
            if 'articulo_id' in col_names and 'unidades' in col_names:
                patterns.append("Productos vendidos: COUNT(DISTINCT ARTICULO_ID)")
                patterns.append("Unidades totales: SUM(UNIDADES)")
            if 'docto_pv_id' in col_names:
                patterns.append("JOIN con encabezado: JOIN DOCTOS_PV ON DOCTO_PV_ID")

        # === PATRONES PARA ARTÍCULOS/PRODUCTOS ===
        elif any(k in name_lower for k in ['articulo', 'producto']):
            if 'estatus' in col_names:
                patterns.append("Activos: WHERE ESTATUS = 'A'")
                patterns.append("Contar activos: COUNT(*) WHERE ESTATUS = 'A'")
            if 'nombre' in col_names:
                patterns.append("Buscar por nombre: WHERE NOMBRE LIKE '%texto%'")
            if 'linea_articulo_id' in col_names:
                patterns.append("Por línea: GROUP BY LINEA_ARTICULO_ID")
            if 'precio' in col_names:
                patterns.append("Rango de precio: WHERE PRECIO BETWEEN X AND Y")

        # === PATRONES PARA CLIENTES ===
        elif any(k in name_lower for k in ['cliente']):
            if 'estatus' in col_names:
                patterns.append("Clientes activos: WHERE ESTATUS = 'A'")
            if 'nombre' in col_names or 'razon_social' in col_names:
                patterns.append("Buscar: WHERE NOMBRE LIKE '%texto%'")
            if 'rfc' in col_names:
                patterns.append("Por RFC: WHERE RFC = 'XXXX'")

        # === PATRONES PARA INVENTARIO ===
        elif any(k in name_lower for k in ['inventario', 'existencia', 'saldo']):
            if 'existencia' in col_names:
                patterns.append("Stock bajo: WHERE EXISTENCIA < MINIMO")
                patterns.append("Stock total: SUM(EXISTENCIA)")
            if 'articulo_id' in col_names and 'almacen_id' in col_names:
                patterns.append("Por almacén: GROUP BY ALMACEN_ID")

        # === PATRONES GENÉRICOS PARA TABLAS CON FECHA ===
        if 'fecha' in col_names and not patterns:
            patterns.append("Últimos 30 días: WHERE FECHA >= CURRENT_DATE - 30")
            patterns.append("Por mes: WHERE EXTRACT(MONTH FROM FECHA) = X")

        # === PATRONES GENÉRICOS PARA TABLAS CON ESTATUS ===
        if 'estatus' in col_names and not patterns:
            patterns.append("Activos: WHERE ESTATUS = 'A'")

        # === CONTEOS GENÉRICOS ===
        if primary_keys and not patterns:
            pk = primary_keys[0]
            patterns.append(f"Contar registros: COUNT({pk})")

        if patterns:
            return "Consultas típicas: " + " | ".join(patterns[:5])  # Máximo 5 patrones
        return ""

    @staticmethod
    def _generate_search_terms(table_name: str, columns: List[Dict[str, Any]]) -> str:
        """
        Generar términos de búsqueda adicionales y sinónimos para mejorar recuperación.
        Estos términos ayudan a que la búsqueda vectorial capture consultas con vocabulario variado.
        """
        search_terms = set()
        name_lower = table_name.lower()
        col_names = [col['name'].lower() for col in columns]

        # Sinónimos por tipo de tabla
        synonyms_map = {
            'venta': ['vender', 'vendido', 'transacción', 'ingreso', 'ticket', 'factura', 'cobro'],
            'cliente': ['comprador', 'consumidor', 'usuario final', 'socio comercial'],
            'articulo': ['producto', 'mercancía', 'ítem', 'SKU', 'inventario', 'activo', 'activos', 'disponible'],
            'proveedor': ['vendor', 'supplier', 'abastecedor', 'distribuidor'],
            'inventario': ['existencia', 'stock', 'almacén', 'bodega', 'disponible'],
            'compra': ['adquisición', 'orden de compra', 'procurement', 'abastecimiento'],
            'precio': ['costo', 'importe', 'valor', 'monto', 'tarifa'],
            'pago': ['abono', 'cobranza', 'liquidación', 'transacción financiera'],
            'empleado': ['trabajador', 'personal', 'colaborador', 'staff'],
            'pedido': ['orden', 'solicitud', 'requerimiento', 'order'],
            'factura': ['invoice', 'comprobante', 'documento fiscal'],
        }

        # Agregar sinónimos basados en el nombre de la tabla
        for key, synonyms in synonyms_map.items():
            if key in name_lower:
                search_terms.update(synonyms[:8])  # Aumentado para incluir más términos

        # NUEVO: Términos de consulta y agregación para TODAS las tablas
        search_terms.update(['cuántos', 'cuantos', 'cantidad de', 'total de', 'contar', 'listar', 'mostrar', 'registros', 'elementos'])

        # NUEVO: Si tiene columna ESTATUS o similar, agregar términos de estado
        if any('estatus' in col or 'status' in col or 'activo' in col or 'active' in col for col in col_names):
            search_terms.update(['activo', 'activos', 'vigente', 'vigentes', 'disponible', 'disponibles', 'inactivo', 'inactivos'])

        # Sinónimos por columnas presentes
        if any('fecha' in col or 'date' in col for col in col_names):
            search_terms.update(['temporal', 'histórico', 'cronológico'])

        if any('importe' in col or 'precio' in col or 'monto' in col for col in col_names):
            search_terms.update(['financiero', 'monetario', 'económico'])

        if any('cantidad' in col or 'unidades' in col for col in col_names):
            search_terms.update(['volumen', 'conteo', 'suma', 'total'])

        # Términos de análisis comunes
        if 'det' in name_lower or 'detalle' in name_lower:
            search_terms.update(['línea', 'ítem', 'movimiento individual', 'partida'])

        if any(k in name_lower for k in ['encab', 'header', 'docto']):
            search_terms.update(['documento', 'cabecera', 'resumen'])

        # Limitar a los términos más relevantes (aumentado para incluir términos de consulta)
        return ', '.join(list(search_terms)[:25])

    @staticmethod
    def _infer_table_purpose(table_name: str) -> Optional[str]:
        """Inferir el propósito de una tabla por su nombre."""
        name_lower = table_name.lower()
        
        purpose_keywords = {
            # Comercial y ventas
            'ventas': 'ventas y transacciones comerciales',
            'venta': 'ventas y transacciones comerciales',
            'facturas': 'facturación',
            'factura': 'facturación',
            'pedidos': 'gestión de pedidos',
            'pedido': 'gestión de pedidos',
            'cotizaciones': 'cotizaciones y presupuestos',
            'cotizacion': 'cotizaciones y presupuestos',
            'remisiones': 'remisiones y entregas',
            'remision': 'remisiones y entregas',
            
            # Clientes y proveedores
            'clientes': 'información de clientes',
            'cliente': 'información de clientes',
            'proveedores': 'información de proveedores',
            'proveedor': 'información de proveedores',
            'contactos': 'contactos y relaciones',
            'contacto': 'contactos y relaciones',
            
            # Productos e inventario
            'productos': 'catálogo de productos y artículos',
            'producto': 'catálogo de productos y artículos',
            'articulos': 'catálogo de productos y artículos',
            'articulo': 'catálogo de productos y artículos',
            'items': 'catálogo de productos y artículos',
            'inventario': 'control de inventarios y existencias',
            'existencias': 'control de inventarios y existencias',
            'stock': 'control de inventarios y existencias',
            'almacen': 'gestión de almacenes',
            'almacenes': 'gestión de almacenes',
            'bodega': 'gestión de almacenes',
            'bodegas': 'gestión de almacenes',
            'movimientos': 'movimientos de inventario',
            'movimiento': 'movimientos de inventario',
            
            # Personal
            'empleados': 'información de empleados',
            'empleado': 'información de empleados',
            'personal': 'información de empleados',
            'usuarios': 'gestión de usuarios',
            'usuario': 'gestión de usuarios',
            
            # Financiero
            'pagos': 'gestión de pagos',
            'pago': 'gestión de pagos',
            'cobranza': 'cobranza y cuentas por cobrar',
            'cobranzas': 'cobranza y cuentas por cobrar',
            'cuentas': 'cuentas y contabilidad',
            'cuenta': 'cuentas y contabilidad',
            'movtos': 'movimientos financieros',
            'bancos': 'movimientos bancarios',
            'banco': 'movimientos bancarios',
            
            # Catálogos
            'categorias': 'categorización y clasificación',
            'categoria': 'categorización y clasificación',
            'grupos': 'agrupación y clasificación',
            'grupo': 'agrupación y clasificación',
            'tipos': 'tipos y clasificaciones',
            'tipo': 'tipos y clasificaciones',
            'familias': 'familias de productos',
            'familia': 'familias de productos',
            'lineas': 'líneas de productos',
            'linea': 'líneas de productos',
            'marcas': 'marcas de productos',
            'marca': 'marcas de productos',
            
            # Ubicación
            'zonas': 'zonas geográficas',
            'zona': 'zonas geográficas',
            'rutas': 'rutas de distribución',
            'ruta': 'rutas de distribución',
            'sucursales': 'sucursales y ubicaciones',
            'sucursal': 'sucursales y ubicaciones',
            
            # Sistema
            'logs': 'registro de eventos y auditoría',
            'log': 'registro de eventos y auditoría',
            'configuracion': 'configuración del sistema',
            'config': 'configuración del sistema',
            'parametros': 'parámetros del sistema',
            'parametro': 'parámetros del sistema',
            'reportes': 'generación de reportes',
            'reporte': 'generación de reportes',
            'audit': 'auditoría del sistema',
            'auditoria': 'auditoría del sistema',
            'temp': 'datos temporales',
            'temporal': 'datos temporales',
            'backup': 'respaldo de datos',
            'respaldo': 'respaldo de datos',
            
            # Documentos
            'documentos': 'documentos y archivos',
            'documento': 'documentos y archivos',
            'notas': 'notas y comentarios',
            'nota': 'notas y comentarios',
            
            # Procesos
            'compras': 'compras y adquisiciones',
            'compra': 'compras y adquisiciones',
            'produccion': 'producción y manufactura',
            'ordenes': 'órdenes de trabajo',
            'orden': 'órdenes de trabajo',
        }
        
        for keyword, purpose in purpose_keywords.items():
            if keyword in name_lower:
                return purpose
        
        return None
    
    @staticmethod
    def _identify_key_columns(columns: List[Dict[str, Any]]) -> List[str]:
        """Identificar columnas clave de una tabla."""
        key_columns = []
        
        for col in columns[:10]:  # Solo primeras 10 columnas
            col_name = col['name'].lower()
            
            # IDs y claves
            if any(keyword in col_name for keyword in ['id', 'key', 'codigo', 'code']):
                key_columns.append(col['name'])
            
            # Nombres y descripciones
            elif any(keyword in col_name for keyword in ['nombre', 'name', 'descripcion', 'desc']):
                key_columns.append(col['name'])
            
            # Fechas importantes
            elif any(keyword in col_name for keyword in ['fecha', 'date', 'time', 'created', 'updated']):
                key_columns.append(col['name'])
            
            # Montos y cantidades
            elif any(keyword in col_name for keyword in ['monto', 'amount', 'cantidad', 'qty', 'precio', 'price']):
                key_columns.append(col['name'])
        
        return key_columns[:5]  # Máximo 5 columnas clave
    
    @staticmethod
    def _identify_semantic_fields(columns: List[Dict[str, Any]]) -> List[str]:
        """Identificar tipos semánticos de campos para mejorar búsqueda RAG."""
        semantic_types = set()
        
        field_semantics = {
            'identificación': ['id', 'codigo', 'code', 'clave', 'key', 'folio', 'numero'],
            'nombres y descripciones': ['nombre', 'name', 'descripcion', 'desc', 'titulo', 'title'],
            'fechas y tiempos': ['fecha', 'date', 'time', 'hora', 'timestamp', 'created', 'updated', 'modified'],
            'importes y precios': ['precio', 'price', 'monto', 'amount', 'importe', 'costo', 'cost', 'total', 'subtotal'],
            'cantidades': ['cantidad', 'qty', 'quantity', 'stock', 'existencia', 'unidades'],
            'estados': ['status', 'estado', 'activo', 'active', 'vigente', 'eliminado', 'deleted'],
            'personas': ['cliente', 'customer', 'proveedor', 'vendor', 'empleado', 'employee', 'usuario', 'user'],
            'ubicaciones': ['direccion', 'address', 'ciudad', 'city', 'pais', 'country', 'zona', 'region', 'almacen', 'warehouse'],
            'contacto': ['email', 'mail', 'telefono', 'phone', 'celular', 'mobile', 'contacto', 'contact'],
            'financiero': ['pago', 'payment', 'saldo', 'balance', 'credito', 'credit', 'deuda', 'debt'],
            'impuestos': ['iva', 'tax', 'impuesto', 'ieps', 'retencion'],
            'documentos': ['factura', 'invoice', 'pedido', 'order', 'nota', 'recibo', 'receipt', 'documento', 'document'],
        }
        
        for col in columns:
            col_name = col['name'].lower()
            for semantic_category, keywords in field_semantics.items():
                if any(keyword in col_name for keyword in keywords):
                    semantic_types.add(semantic_category)
        
        return sorted(list(semantic_types))
    
    @staticmethod
    def _describe_sample_data(columns: List[Dict[str, Any]], sample_data: List[List[Any]]) -> str:
        """Describir datos de muestra (método antiguo, mantenido por compatibilidad)."""
        # Redirigir al nuevo método enriquecido
        return TableDescriptor._describe_sample_data_enriched(columns, sample_data)

    @staticmethod
    def _analyze_data_patterns(columns: List[Dict[str, Any]], sample_data: List[List[Any]]) -> str:
        """
        Analizar patrones avanzados en datos para detectar características especiales.
        Ejemplos: tablas transaccionales vs maestros, datos históricos vs actuales, etc.
        """
        if not sample_data or not columns:
            return ""

        patterns = []

        # Analizar distribución temporal
        date_cols = [(i, col) for i, col in enumerate(columns) if 'DATE' in col.get('data_type', '') or 'TIMESTAMP' in col.get('data_type', '')]
        if date_cols:
            for col_idx, col in date_cols[:2]:  # Primeras 2 columnas de fecha
                try:
                    date_values = [row[col_idx] for row in sample_data if col_idx < len(row) and row[col_idx]]
                    if date_values:
                        date_strs = [str(d) for d in date_values]
                        first = date_strs[0][:10] if len(date_strs[0]) >= 10 else date_strs[0]
                        last = date_strs[-1][:10] if len(date_strs[-1]) >= 10 else date_strs[-1]

                        # Detectar si son fechas recientes (datos operacionales)
                        if '2024' in last or '2025' in last:
                            patterns.append("datos operacionales actuales")
                        elif first != last:
                            patterns.append(f"datos desde {first[:4]}")
                except:
                    pass

        # Detectar si es tabla transaccional (tiene ID secuencial + fecha)
        has_sequential_id = False
        for i, col in enumerate(columns[:5]):
            if any(k in col['name'].lower() for k in ['_id', 'id', 'folio', 'numero']):
                try:
                    ids = [row[i] for row in sample_data[:10] if i < len(row) and row[i] is not None]
                    if len(ids) >= 3:
                        numeric_ids = [int(v) for v in ids if str(v).isdigit()]
                        if len(numeric_ids) >= 3:
                            # Verificar si son secuenciales
                            diffs = [numeric_ids[i+1] - numeric_ids[i] for i in range(len(numeric_ids)-1)]
                            avg_diff = sum(diffs) / len(diffs) if diffs else 0
                            if 0 < avg_diff < 100:  # Diferencias pequeñas = secuencial
                                has_sequential_id = True
                                patterns.append("registros secuenciales")
                                break
                except:
                    pass

        # Detectar si es catálogo (pocos registros únicos en columnas clave)
        is_catalog = False
        for i, col in enumerate(columns[:3]):
            if 'nombre' in col['name'].lower() or 'descripcion' in col['name'].lower():
                try:
                    values = [row[i] for row in sample_data if i < len(row) and row[i]]
                    unique_count = len(set(str(v) for v in values))
                    if unique_count == len(values) and len(values) < 20:
                        is_catalog = True
                        patterns.append("catálogo maestro")
                        break
                except:
                    pass

        # Detectar campos monetarios significativos
        monetary_cols = [col for col in columns if any(k in col['name'].lower() for k in ['precio', 'importe', 'total', 'costo', 'monto'])]
        if monetary_cols and len(monetary_cols) >= 2:
            patterns.append("gestión financiera")

        # Detectar si tiene campos de auditoría
        audit_fields = [col for col in columns if any(k in col['name'].lower() for k in ['creado', 'modificado', 'usuario', 'created', 'updated'])]
        if audit_fields:
            patterns.append("con auditoría")

        return " | ".join(patterns) if patterns else ""


class VectorStore:
    """Almacén vectorial simple usando JSON + numpy (sin ChromaDB)."""

    def __init__(self):
        self.embeddings_data = {}  # {table_name: {'embedding': [...], 'metadata': {...}}}
        self.storage_path = os.path.join(config.rag.vector_db_path, "embeddings.json")
        self._initialized = False

    def initialize(self):
        """Inicializar almacén vectorial desde archivo JSON."""
        if self._initialized:
            return

        try:
            logger.info("🔧 Inicializando almacén vectorial simple (JSON + numpy)...")

            # Crear directorio si no existe
            os.makedirs(config.rag.vector_db_path, exist_ok=True)

            # Cargar embeddings existentes si hay
            if os.path.exists(self.storage_path):
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    self.embeddings_data = json.load(f)
                logger.info(f"✓ Cargados {len(self.embeddings_data)} embeddings desde archivo")
            else:
                logger.info("✓ Inicializando almacén vectorial vacío")

            self._initialized = True
            logger.info("✅ Almacén vectorial inicializado correctamente")

        except Exception as e:
            logger.error(f"❌ Error inicializando almacén vectorial: {e}")
            # No fallar - continuar con diccionario vacío
            self.embeddings_data = {}
            self._initialized = True

    def add_table_embeddings(self, table_embeddings: Dict[str, Dict[str, Any]]):
        """Agregar embeddings de tablas al almacén."""
        if not self._initialized:
            self.initialize()

        try:
            logger.info(f"💾 Guardando {len(table_embeddings)} embeddings...")

            # Agregar/actualizar embeddings
            for table_name, data in table_embeddings.items():
                self.embeddings_data[table_name] = {
                    'embedding': data['embedding'],
                    'description': data['description'],
                    'row_count': data.get('row_count', 0),
                    'is_active': data.get('is_active', True),
                    'column_count': data.get('column_count', 0),
                    'has_foreign_keys': data.get('has_foreign_keys', False),
                    'created_at': datetime.now().isoformat()
                }

            # Guardar a archivo JSON
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(self.embeddings_data, f, ensure_ascii=False, indent=2)

            logger.info(f"✅ {len(table_embeddings)} embeddings guardados correctamente")

        except Exception as e:
            logger.error(f"❌ Error guardando embeddings: {e}")
            # No fallar - continuar en memoria

    def search_similar_tables(self, query_embedding: List[float],
                            top_k: int = None,
                            filter_active: bool = True) -> List[Dict[str, Any]]:
        """Buscar tablas similares usando cosine similarity."""
        if not self._initialized:
            self.initialize()

        if top_k is None:
            top_k = config.rag.top_k_tables

        try:
            if not self.embeddings_data:
                logger.warning("⚠️ No hay embeddings disponibles para búsqueda")
                return []

            # Convertir query embedding a numpy array
            query_vec = np.array(query_embedding)

            # Calcular similitud coseno con todas las tablas
            similarities = []

            for table_name, data in self.embeddings_data.items():
                # Filtrar por activas si se solicita
                if filter_active and not data.get('is_active', True):
                    continue

                # Calcular cosine similarity
                table_vec = np.array(data['embedding'])

                # Normalizar vectores
                query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
                table_norm = table_vec / (np.linalg.norm(table_vec) + 1e-10)

                # Cosine similarity = dot product de vectores normalizados
                similarity = float(np.dot(query_norm, table_norm))

                similarities.append({
                    'table_name': table_name,
                    'description': data['description'],
                    'similarity': similarity,
                    'metadata': {
                        'row_count': data.get('row_count', 0),
                        'is_active': data.get('is_active', True),
                        'column_count': data.get('column_count', 0),
                        'has_foreign_keys': data.get('has_foreign_keys', False)
                    }
                })

            # Ordenar por similitud descendente
            similarities.sort(key=lambda x: x['similarity'], reverse=True)

            # Filtrar por threshold y limitar a top_k
            similar_tables = [
                table for table in similarities
                if table['similarity'] >= config.rag.similarity_threshold
            ][:top_k]

            logger.info(f"🔍 Encontradas {len(similar_tables)} de {len(similarities)} tablas que superan threshold {config.rag.similarity_threshold}")

            for table in similar_tables[:5]:  # Log top 5
                logger.debug(f"  ✓ {table['table_name']}: {table['similarity']:.3f}")

            return similar_tables

        except Exception as e:
            logger.error(f"❌ Error buscando tablas similares: {e}")
            return []

    def get_collection_stats(self) -> Dict[str, Any]:
        """Obtener estadísticas de la colección."""
        if not self._initialized:
            return {}

        return {
            'total_tables': len(self.embeddings_data),
            'storage_type': 'JSON + numpy',
            'initialized': self._initialized,
            'storage_path': self.storage_path
        }


class SchemaManager:
    """Gestor principal del esquema con capacidades RAG."""
    
    def __init__(self):
        self.embedding_generator = EmbeddingGenerator()
        self.vector_store = VectorStore()
        self.schema_cache = {}
        self.last_schema_update = None
        self.active_tables_cache = None
        self.relationships_graph = None
        self._load_relationships_graph()
        
        # Auto-actualización
        self.auto_update_interval = 12 * 3600  # 12 horas en segundos
        self._auto_update_thread = None
        self._stop_auto_update = threading.Event()
        self.start_auto_update_thread()
    
    def _load_relationships_graph(self):
        """Cargar grafo de relaciones de MicroSIP"""
        try:
            import os
            rel_path = os.path.join(os.path.dirname(__file__), 'microsip_relationships.json')
            if os.path.exists(rel_path):
                with open(rel_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.relationships_graph = data.get('graph', {})
                    logger.info(f"Grafo de relaciones cargado: {len(self.relationships_graph)} tablas con relaciones")
            else:
                self.relationships_graph = {}
                logger.warning("No se encontró microsip_relationships.json, continuando sin expansión de relaciones")
        except Exception as e:
            logger.warning(f"Error cargando grafo de relaciones: {e}")
            self.relationships_graph = {}
    
    def _get_fk_related_tables(self, table_name: str) -> List[str]:
        """
        Obtener tablas relacionadas a través de foreign keys.
        
        Args:
            table_name: Nombre de la tabla
            
        Returns:
            Lista de nombres de tablas relacionadas por FK
        """
        related = []
        
        if not self.schema_cache or 'full_schema' not in self.schema_cache:
            return related
        
        full_schema = self.schema_cache['full_schema']
        
        if table_name not in full_schema:
            return related
        
        table_info = full_schema[table_name]
        
        # Tablas referenciadas (padres)
        for fk in table_info.foreign_keys:
            ref_table = fk.get('referenced_table')
            if ref_table and ref_table not in related:
                related.append(ref_table)
        
        # Tablas que referencian a esta (hijos)
        for other_table_name, other_table_info in full_schema.items():
            if other_table_name == table_name:
                continue
            
            for fk in other_table_info.foreign_keys:
                if fk.get('referenced_table') == table_name and other_table_name not in related:
                    related.append(other_table_name)
        
        return related
    
    def _adjust_scores_by_context(self, tables: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """
        Ajustar scores de tablas basado en sistema multi-factor avanzado.

        Combina:
        1. Similitud semántica (embedding similarity)
        2. Importancia de tabla (row_count, FKs, indices)
        3. Keyword matching (coincidencias exactas en nombre/columnas)

        Args:
            tables: Lista de tablas con scores
            query: Consulta original del usuario

        Returns:
            Lista de tablas con scores ajustados y reordenadas
        """
        if not config.rag.use_relevance_scoring:
            # Si scoring avanzado deshabilitado, retornar tal cual
            return tables

        query_lower = query.lower()
        query_words = [w for w in query_lower.split() if len(w) > 3]  # Palabras significativas

        for table in tables:
            # === FACTOR 1: SIMILITUD SEMÁNTICA (ya viene de ChromaDB) ===
            semantic_score = table.get('similarity_score', 0.0)

            # === FACTOR 2: IMPORTANCIA DE TABLA ===
            importance_score = 0.0

            # 2.1 Volumen de datos (normalizado 0-1)
            row_count = table.get('row_count', 0)
            if row_count > 0:
                # Normalizar logarítmicamente (10 registros = 0.1, 1000 = 0.5, 100k = 0.9, 1M+ = 1.0)
                import math
                importance_score += min(math.log10(row_count + 1) / 6, 1.0) * 0.4
            elif row_count == 0:
                # Penalizar tablas vacías
                importance_score -= 0.3

            # 2.2 Conectividad (foreign keys)
            fk_count = len(table.get('foreign_keys', []))
            if fk_count > 0:
                # Normalizar: 1 FK = 0.2, 3 FKs = 0.6, 5+ FKs = 1.0
                importance_score += min(fk_count / 5.0, 1.0) * 0.3

            # 2.3 Complejidad estructural (número de columnas)
            col_count = len(table.get('columns', []))
            if col_count > 5:
                # Normalizar: 5 cols = 0.1, 15 cols = 0.5, 30+ cols = 1.0
                importance_score += min((col_count - 5) / 25.0, 1.0) * 0.2

            # 2.4 Si es tabla principal (no relacionada), bonificar
            if not table.get('is_related', False):
                importance_score += 0.1

            # === FACTOR 3: KEYWORD MATCHING ===
            keyword_score = 0.0
            table_name = table.get('name', '').lower()
            table_desc = table.get('description', '').lower()

            # 3.1 Coincidencias en nombre de tabla (peso alto)
            for word in query_words:
                if word in table_name:
                    keyword_score += 0.4

            # 3.2 Coincidencias en nombres de columnas (peso medio)
            column_matches = 0
            for col in table.get('columns', []):
                col_name = col.get('name', '').lower()
                for word in query_words:
                    if word in col_name:
                        column_matches += 1
                        break  # Solo contar una vez por columna

            if column_matches > 0:
                # Normalizar: 1 match = 0.2, 3 matches = 0.6, 5+ matches = 1.0
                keyword_score += min(column_matches / 5.0, 1.0) * 0.4

            # 3.3 Coincidencias en descripción (peso bajo)
            desc_matches = sum(1 for word in query_words if word in table_desc)
            if desc_matches > 0:
                keyword_score += min(desc_matches / 10.0, 1.0) * 0.2

            # === COMBINAR SCORES CON PESOS CONFIGURABLES ===
            final_score = (
                semantic_score * config.rag.weight_similarity +
                importance_score * config.rag.weight_table_importance +
                keyword_score * config.rag.weight_keyword_match
            )

            # Guardar scores detallados para debugging
            table['scores_breakdown'] = {
                'original_similarity': semantic_score,
                'importance': importance_score,
                'keyword_match': keyword_score,
                'final': final_score
            }

            table['similarity_score'] = max(0, min(1, final_score))  # Clamp a [0, 1]

        # Reordenar por score final
        tables.sort(key=lambda x: x['similarity_score'], reverse=True)

        # Log detallado de scoring
        logger.info("🎯 Scoring multi-factor aplicado:")
        for i, table in enumerate(tables[:10], 1):  # Top 10
            breakdown = table.get('scores_breakdown', {})
            logger.info(
                f"  {i}. {table['name']}: "
                f"Final={breakdown.get('final', 0):.3f} "
                f"(Sem={breakdown.get('original_similarity', 0):.3f}, "
                f"Imp={breakdown.get('importance', 0):.3f}, "
                f"Kw={breakdown.get('keyword_match', 0):.3f})"
            )

        return tables
    
    def _expand_with_related_tables(self, tables: List[Dict[str, Any]], max_related: int = 5) -> List[Dict[str, Any]]:
        """
        Expandir lista de tablas con tablas relacionadas importantes.
        Incluye expansión dinámica basada en foreign keys reales.
        
        Args:
            tables: Lista de tablas encontradas por RAG
            max_related: Máximo de tablas relacionadas a agregar por tabla principal
        
        Returns:
            Lista expandida de tablas incluyendo las relacionadas
        """
        expanded = []
        added_tables = set()
        
        # Primero agregar las tablas originales
        for table in tables:
            table_name = table['name']
            expanded.append(table)
            added_tables.add(table_name)
        
        # Expandir dinámicamente usando foreign keys reales
        for table in tables[:3]:  # Solo las 3 más relevantes
            table_name = table['name']
            
            # Obtener tablas relacionadas por FK
            fk_related = self._get_fk_related_tables(table_name)
            
            for related_name in fk_related[:max_related]:
                if related_name not in added_tables and related_name in self.schema_cache.get('full_schema', {}):
                    table_info = self.schema_cache['full_schema'][related_name]
                    
                    related_table = {
                        'name': related_name,
                        'similarity_score': table['similarity_score'] * 0.75,
                        'description': f"Relacionada por FK con {table_name}",
                        'row_count': table_info.row_count,
                        'columns': [
                            {'name': col['name'], 'type': col['data_type'], 'nullable': col['nullable']}
                            for col in table_info.columns
                        ],
                        'primary_keys': table_info.primary_keys,
                        'foreign_keys': table_info.foreign_keys,
                        'relationships': db.get_table_relationships(related_name),
                        'is_related': True,
                        'relation_type': 'foreign_key'
                    }
                    
                    expanded.append(related_table)
                    added_tables.add(related_name)
        
        # Luego agregar tablas relacionadas para cada una
        for table in tables[:3]:  # Solo expandir las 3 más relevantes
            table_name = table['name']
            
            if table_name not in self.relationships_graph:
                continue
            
            related_tables = self.relationships_graph[table_name]
            
            # Priorizar tablas relacionadas por importancia semántica
            scored_related = []
            for rel_table in related_tables:
                if rel_table in added_tables:
                    continue
                
                # Calcular score de importancia
                score = 0
                rel_lower = rel_table.lower()
                
                # Tablas de detalle/códigos/claves son muy importantes
                if any(k in rel_lower for k in ['codigo', 'clave', 'detalle', 'det', 'linea']):
                    score += 10
                
                # Catálogos relacionados
                if any(k in rel_lower for k in ['tipo', 'grupo', 'categoria', 'familia']):
                    score += 7
                
                # Existencias y precios muy importantes
                if any(k in rel_lower for k in ['existencia', 'precio', 'costo']):
                    score += 9
                
                # Relaciones con el nombre de la tabla principal
                table_base = table_name.rstrip('S')  # ARTICULOS -> ARTICULO
                if table_base.lower() in rel_lower:
                    score += 8
                
                scored_related.append((rel_table, score))
            
            # Ordenar por score y tomar las mejores
            scored_related.sort(key=lambda x: x[1], reverse=True)
            
            # Agregar las tablas relacionadas más importantes
            for rel_table, score in scored_related[:max_related]:
                if rel_table in self.schema_cache.get('full_schema', {}):
                    table_info = self.schema_cache['full_schema'][rel_table]
                    
                    related_table = {
                        'name': rel_table,
                        'similarity_score': table['similarity_score'] * 0.7,  # Score reducido para relacionadas
                        'description': f"Tabla relacionada con {table_name}",
                        'row_count': table_info.row_count,
                        'columns': [
                            {
                                'name': col['name'],
                                'type': col['data_type'],
                                'nullable': col['nullable']
                            }
                            for col in table_info.columns
                        ],
                        'primary_keys': table_info.primary_keys,
                        'foreign_keys': table_info.foreign_keys,
                        'relationships': db.get_table_relationships(rel_table),
                        'is_related': True,  # Marcar como tabla relacionada
                        'related_to': table_name
                    }
                    
                    expanded.append(related_table)
                    added_tables.add(rel_table)
        
        if len(expanded) > len(tables):
            logger.info(f"Expandidas {len(tables)} tablas a {len(expanded)} (incluyendo {len(expanded) - len(tables)} relacionadas)")
        
        return expanded
        
    @timing_decorator("Schema Loading")
    def load_and_process_schema(self, force_refresh: bool = False, skip_embeddings: bool = False) -> Dict[str, Any]:
        """
        Cargar y procesar esquema completo con TODOS los embeddings.

        Args:
            force_refresh: Forzar recarga desde BD
            skip_embeddings: Si True, solo carga estructura sin embeddings
        """
        try:
            # Verificar si necesitamos actualizar
            if not force_refresh and self._is_schema_cache_valid():
                # Verificar si ya tenemos embeddings completos
                embeddings_complete = self.schema_cache.get('embeddings_pending', True) == False
                if embeddings_complete or skip_embeddings:
                    logger.info("✓ Usando esquema procesado desde caché")
                return self.schema_cache
                # Si faltan embeddings, continuar procesándolos
            
            logger.info("🔄 Cargando esquema completo de la base de datos...")
            
            # Cargar esquema de la base de datos (usa caché si existe)
            full_schema = self.schema_cache.get('full_schema') if not force_refresh else None
            if not full_schema:
                full_schema = db.get_full_schema(force_refresh=True)
            
            if not full_schema:
                raise Exception("No se pudo cargar el esquema de la base de datos")
            
            # Inicializar table_embeddings ANTES del condicional
            table_embeddings = {}

            # Procesar TODAS las tablas para embeddings (no limitar)
            if not skip_embeddings:
                logger.info(f"🧠 Procesando TODAS las tablas para embeddings ({len(full_schema)} tablas)...")
                table_embeddings = self._process_tables_for_embeddings(full_schema, max_tables=None)
            
            # Agregar embeddings al almacén vectorial
            try:
                logger.info("💾 Guardando embeddings en almacén vectorial...")
                self.vector_store.add_table_embeddings(table_embeddings)
                logger.info("✅ Embeddings guardados correctamente")
            except Exception as e:
                logger.warning(f"⚠️ Error guardando embeddings, continúo sin persistencia: {e}")
                # No borrar table_embeddings si falla el guardado
            
            # Identificar tablas activas
            active_tables = self._identify_active_tables(full_schema)
            
            # Actualizar caché (aunque falle el vector store)
            self.schema_cache = {
                'full_schema': full_schema,
                'table_embeddings': table_embeddings,
                'active_tables': active_tables,
                'stats': self._calculate_schema_stats(full_schema, active_tables),
                'is_basic': False,
                'embeddings_pending': skip_embeddings  # False si se procesaron todos
            }
            
            self.last_schema_update = datetime.now()
            self.active_tables_cache = active_tables
            
            logger.info(f"✅ Esquema procesado completamente: {len(full_schema)} tablas totales, "
                       f"{len(active_tables)} activas, {len(table_embeddings)} con embeddings")
            
            return self.schema_cache
            
        except Exception as e:
            # No abortar completamente: devolver caché mínima si existe para que la UI funcione
            logger.error("❌ Error cargando y procesando esquema", e)
            if self.schema_cache:
                return self.schema_cache
            raise

    def load_and_process_schema_basic(self, force_refresh: bool = False, force_minimal: bool = False) -> Dict[str, Any]:
        """
        Cargar esquema básico SOLO estructura (sin embeddings) para inicialización ultra-rápida.
        Los embeddings se procesan después en background.
        """
        try:
            logger.info("⚡ Cargando esquema básico (solo estructura, sin embeddings)...")

            # Cargar esquema de la base de datos
            full_schema = db.get_full_schema(force_refresh=True)

            if not full_schema:
                raise Exception("No se pudo cargar el esquema de la base de datos")

            # NO procesar embeddings aquí - será en background
            table_embeddings = {}

            # Identificar tablas activas
            active_tables = self._identify_active_tables(full_schema)

            # Crear caché básico (sin embeddings)
            self.schema_cache = {
                'full_schema': full_schema,
                'table_embeddings': table_embeddings,
                'active_tables': active_tables,
                'stats': self._calculate_schema_stats(full_schema, active_tables),
                'is_basic': True,  # Marcar como carga básica
                'embeddings_pending': True  # Indicar que faltan embeddings
            }

            self.last_schema_update = datetime.now()
            self.active_tables_cache = active_tables

            stats = self.schema_cache.get('stats', {})
            logger.info(f"✅ Esquema básico cargado: {len(full_schema)} tablas totales, "
                       f"{len(active_tables)} activas (embeddings pendientes)")

            return self.schema_cache

        except Exception as e:
            logger.error("Error cargando esquema básico", e)
            # Intentar devolver algo mínimo si existe
            if self.schema_cache:
                return self.schema_cache
            raise
    
    def _is_schema_cache_valid(self) -> bool:
        """Verificar si el caché del esquema sigue siendo válido."""
        if not self.schema_cache or not self.last_schema_update:
            return False
        
        time_diff = datetime.now() - self.last_schema_update
        return time_diff < timedelta(minutes=config.rag.cache_ttl_minutes)
    
    def _process_tables_for_embeddings(self, schema: Dict[str, TableInfo], max_tables: int = None) -> Dict[str, Dict[str, Any]]:
        """
        Procesar tablas para generar embeddings con priorización inteligente.

        Args:
            schema: Diccionario de tablas
            max_tables: Límite de tablas a procesar (None = todas)
        """
        table_embeddings = {}

        # Limitar el procesamiento a tablas más importantes primero
        tables_to_process = []
        
        for table_name, table_info in schema.items():
            # Priorizar tablas con datos y relaciones
            priority = 0

            # Tablas con relaciones son MUY importantes (catálogos principales)
            priority += len(table_info.foreign_keys) * 15

            # Tablas con muchas columnas suelen ser importantes
            priority += len(table_info.columns) * 2

            # Tablas con datos conocidos (pero no penalizar si row_count = -1)
            if table_info.row_count > 0:
                priority += min(table_info.row_count / 1000, 50)
            elif table_info.row_count == -1:
                # Tabla sin contar aún, asumir prioridad media
                priority += 10

            # Tablas con nombres importantes
            name_upper = table_name.upper()
            if any(kw in name_upper for kw in ['ARTICULO', 'CLIENTE', 'PROVEEDOR', 'VENTA', 'COMPRA', 'FACTURA', 'PEDIDO']):
                priority += 20

            tables_to_process.append((table_name, table_info, priority))

        # Ordenar por prioridad
        tables_to_process.sort(key=lambda x: x[2], reverse=True)

        # Aplicar límite si se especifica
        if max_tables is not None:
            limited_tables = tables_to_process[:max_tables]
        else:
            limited_tables = tables_to_process

        # Procesar tablas con progreso DETALLADO
        total = len(limited_tables)
        processed = 0

        logger.info(f"📊 Iniciando generación de embeddings para {total} tablas...")

        for table_name, table_info, priority in limited_tables:
            try:
                # Log ANTES de procesar cada tabla
                logger.info(f"🔄 [{processed + 1}/{total}] Procesando: {table_name}")

                # Obtener muestra de datos para TODAS las tablas con registros
                sample_data = []
                if table_info.row_count != 0:  # -1 o > 0
                    try:
                        # Intentar obtener muestra (limitada a 10 registros)
                        sample_query = f"SELECT FIRST 10 * FROM {table_name}"
                        result = db.execute_query(sample_query)
                        if result and result.data:
                            sample_data = result.data[:10]
                            logger.debug(f"  ✓ Obtenida muestra de {len(sample_data)} registros")
                    except Exception as e:
                        # No abortar si falla la muestra, continuar sin ella
                        logger.debug(f"  ⚠ No se pudo obtener muestra: {str(e)[:50]}")

                # Generar descripción semántica ENRIQUECIDA
                description = TableDescriptor.describe_table(table_info, sample_data)
                
                # Generar embedding
                embedding = self.embedding_generator.generate_embedding(description)
                
                table_embeddings[table_name] = {
                    'embedding': embedding,
                    'description': description,
                    'row_count': table_info.row_count,
                    'is_active': table_info.is_active,
                    'column_count': len(table_info.columns),
                    'primary_key_count': len(table_info.primary_keys),
                    'foreign_key_count': len(table_info.foreign_keys),
                    'index_count': len(table_info.indexes),
                    'has_foreign_keys': len(table_info.foreign_keys) > 0,
                    'has_unique_indexes': any(idx.get('unique', False) for idx in table_info.indexes),
                    'table_info': table_info
                }
                
                processed += 1

                # Log DESPUÉS de completar cada tabla
                logger.info(f"✓ [{processed}/{total}] {table_name} completada ({(processed/total*100):.1f}%)")
                
            except Exception as e:
                logger.error(f"✗ Error procesando tabla {table_name}: {str(e)}")
                # Continuar con la siguiente tabla
                processed += 1
                continue
        
        logger.info(f"✅ Procesadas {len(table_embeddings)}/{total} tablas para embeddings")
        return table_embeddings
    
    def _identify_active_tables(self, schema: Dict[str, TableInfo]) -> List[str]:
        """Identificar tablas activas usando heurísticas avanzadas."""
        active_tables = []
        
        # Ordenar por relevancia
        tables_by_relevance = []
        
        for table_name, table_info in schema.items():
            relevance_score = 0
            
            # Factor 1: Número de registros
            if table_info.row_count > 0:
                relevance_score += min(table_info.row_count / 1000, 100)
            
            # Factor 2: Relaciones activas
            relevance_score += len(table_info.foreign_keys) * 10
            
            # Factor 3: Nombre no obsoleto
            if table_info.is_active:
                relevance_score += 20
            
            # Factor 4: Complejidad (más columnas = más importante)
            relevance_score += len(table_info.columns) * 2
            
            # Factor 5: Tiene clave primaria
            if table_info.primary_keys:
                relevance_score += 15
            
            tables_by_relevance.append((table_name, relevance_score, table_info))
        
        # Ordenar por relevancia
        tables_by_relevance.sort(key=lambda x: x[1], reverse=True)
        
        # Seleccionar tablas activas
        for table_name, score, table_info in tables_by_relevance:
            if score > 10:  # Threshold mínimo
                active_tables.append(table_name)
        
        return active_tables
    
    def _calculate_schema_stats(self, schema: Dict[str, TableInfo], 
                              active_tables: List[str]) -> Dict[str, Any]:
        """Calcular estadísticas del esquema."""
        total_rows = sum(table.row_count for table in schema.values() if table.row_count > 0)
        
        return {
            'total_tables': len(schema),
            'active_tables': len(active_tables),
            'inactive_tables': len(schema) - len(active_tables),
            'total_rows': total_rows,
            'tables_with_data': len([t for t in schema.values() if t.row_count > 0]),
            'tables_with_foreign_keys': len([t for t in schema.values() if t.foreign_keys]),
            'last_update': datetime.now().isoformat()
        }
    
    @timing_decorator("Table Search")
    def find_relevant_tables(self, query: str, max_tables: int = None, expand_relations: bool = True) -> List[Dict[str, Any]]:
        """
        Encontrar tablas relevantes para una consulta usando RAG.
        
        Args:
            query: Consulta del usuario
            max_tables: Número máximo de tablas principales a buscar
            expand_relations: Si True, expande automáticamente con tablas relacionadas
        
        Returns:
            Lista de tablas relevantes (incluyendo relacionadas si expand_relations=True)
        """
        if max_tables is None:
            max_tables = config.rag.top_k_tables
        
        try:
            # Verificar que el esquema esté cargado
            if not self.schema_cache:
                logger.info("Esquema no cargado, cargando ahora...")
                self.load_and_process_schema()
            
            # Generar embedding de la consulta
            query_embedding = self.embedding_generator.generate_embedding(query)
            
            # Buscar tablas similares
            similar_tables = self.vector_store.search_similar_tables(
                query_embedding, 
                top_k=max_tables * 2,  # Buscar más para filtrar mejor
                filter_active=True
            )
            
            # Enriquecer con información adicional
            relevant_tables = []
            
            for table_result in similar_tables[:max_tables]:
                table_name = table_result['table_name']
                
                # Obtener información completa de la tabla
                if table_name in self.schema_cache['full_schema']:
                    table_info = self.schema_cache['full_schema'][table_name]
                    
                    relevant_table = {
                        'name': table_name,
                        'similarity_score': table_result['similarity'],
                        'description': table_result['description'],
                        'row_count': table_info.row_count,
                        'columns': [
                            {
                                'name': col['name'],
                                'type': col['data_type'],
                                'nullable': col['nullable']
                            }
                            for col in table_info.columns
                        ],
                        'primary_keys': table_info.primary_keys,
                        'foreign_keys': table_info.foreign_keys,
                        'relationships': db.get_table_relationships(table_name),
                        'is_related': False  # Es una tabla principal, no relacionada
                    }
                    
                    relevant_tables.append(relevant_table)
            
            # Logging detallado de las tablas encontradas
            logger.info(f"📊 Encontradas {len(relevant_tables)} tablas principales para: '{query}'")
            if relevant_tables:
                logger.info("🔍 Tablas principales seleccionadas:")
                for i, table in enumerate(relevant_tables, 1):
                    logger.info(f"  {i}. {table['name']} (similitud: {table['similarity_score']:.4f}, {table.get('row_count', 0)} registros)")

            # Expandir con tablas relacionadas si está habilitado
            if expand_relations and relevant_tables:
                relevant_tables = self._expand_with_related_tables(relevant_tables)
                # Mejorar scoring basado en relaciones y datos
                relevant_tables = self._adjust_scores_by_context(relevant_tables, query)

                # === FILTRADO FINAL: Limitar al máximo de tablas para SQL ===
                max_for_sql = config.rag.max_tables_for_sql
                if len(relevant_tables) > max_for_sql:
                    logger.info(f"✂️ Limitando de {len(relevant_tables)} tablas a {max_for_sql} (max_tables_for_sql)")
                    # Mantener solo las top-N por score
                    relevant_tables = relevant_tables[:max_for_sql]

                # Logging final de todas las tablas (principales + relacionadas)
                logger.info(f"📋 Total de tablas tras expansión y filtrado: {len(relevant_tables)}")
                logger.info("🎯 Tablas finales (principales + relacionadas):")
                for i, table in enumerate(relevant_tables[:15], 1):  # Primeras 15
                    is_related = " [RELACIONADA]" if table.get('is_related', False) else " [PRINCIPAL]"
                    logger.info(f"  {i}. {table['name']}{is_related} (score: {table.get('similarity_score', 0):.4f})")

            return relevant_tables
            
        except Exception as e:
            logger.error(f"Error buscando tablas relevantes para '{query}'", e)
            return []
    
    def get_table_context(self, table_names: List[str]) -> str:
        """Generar contexto textual de tablas para enviar a la IA."""
        if not table_names:
            return ""
        
        context_parts = ["Tablas relevantes para esta consulta:\n"]
        
        for table_name in table_names:
            if table_name not in self.schema_cache.get('full_schema', {}):
                continue
            
            table_info = self.schema_cache['full_schema'][table_name]
            
            # Información básica
            context_parts.append(f"- {table_name} ({DataFormatter.format_number(table_info.row_count)} registros):")
            
            # Mostrar TODAS las columnas importantes (máximo 30 para RAG, todas para refinamiento)
            max_cols = min(30, len(table_info.columns))
            main_columns = table_info.columns[:max_cols]

            # Agrupar columnas por línea para mejor legibilidad
            col_names = [col['name'] for col in main_columns]
            context_parts.append(f"  Columnas: {', '.join(col_names)}")

            # Si hay más columnas, indicarlo
            if len(table_info.columns) > max_cols:
                remaining = len(table_info.columns) - max_cols
                context_parts.append(f"  ... y {remaining} columnas más")

            # Información adicional sobre claves e índices
            if table_info.primary_keys:
                context_parts.append(f"  Clave primaria: {', '.join(table_info.primary_keys)}")

            if table_info.indexes:
                indexed_cols = []
                for idx in table_info.indexes[:5]:  # Primeros 5 índices
                    if idx.get('columns'):
                        for col in idx['columns']:
                            if col['name'] not in indexed_cols:
                                indexed_cols.append(col['name'])
                if indexed_cols:
                    context_parts.append(f"  Columnas indexadas: {', '.join(indexed_cols[:10])}")

            if table_info.foreign_keys:
                fk_info = []
                for fk in table_info.foreign_keys[:3]:  # Primeras 3 FKs
                    ref_table = fk.get('referenced_table', '')
                    if ref_table:
                        fk_info.append(f"{', '.join(fk.get('columns', []))} → {ref_table}")
                if fk_info:
                    context_parts.append(f"  Relaciones: {'; '.join(fk_info)}")

            # Añadir semántica de columnas clave
            semantic_cols = []
            for col in main_columns:
                col_name = col['name'].upper()
                if col_name in COLUMN_SEMANTICS:
                    semantic_cols.append(f"    {col_name}: {COLUMN_SEMANTICS[col_name]}")

            if semantic_cols:
                context_parts.append(f"  💡 Información clave de columnas:")
                context_parts.extend(semantic_cols)

            # Añadir notas especiales para tablas críticas
            if 'DOCTOS_PV_DET' in table_name:
                context_parts.append("  ⚠️ IMPORTANTE: Filtrar DESCRIPCION1 para excluir VENTA GLOBAL y artículos de sistema")
            if 'ARTICULOS' in table_name:
                context_parts.append("  ⚠️ IMPORTANTE: Excluir artículos con NOMBRE conteniendo GLOBAL, CORTE, SISTEMA")
            if 'DOCTOS_PV' in table_name:
                context_parts.append("  ⚠️ IMPORTANTE: NO tiene columna SERIE (solo TIPO_DOCTO + FOLIO)")
            if 'DOCTOS_VE' in table_name:
                context_parts.append("  ⚠️ IMPORTANTE: NO tiene columna SERIE (solo TIPO_DOCTO + FOLIO)")
            
            # Claves primarias
            if table_info.primary_keys:
                context_parts.append(f"  Clave primaria: {', '.join(table_info.primary_keys)}")
            
            # Relaciones
            relationships = db.get_table_relationships(table_name)
            if relationships['references']:
                referenced_tables = [ref['table'] for ref in relationships['references']]
                context_parts.append(f"  Referencia a: {', '.join(referenced_tables)}")

            context_parts.append("")  # Línea vacía
        
        return "\n".join(context_parts)
    
    def get_schema_summary(self) -> Dict[str, Any]:
        """Obtener resumen del esquema procesado."""
        if not self.schema_cache:
            return {'error': 'Esquema no cargado'}
        
        stats = self.schema_cache.get('stats', {})
        vector_stats = self.vector_store.get_collection_stats()
        
        return {
            **stats,
            **vector_stats,
            'cache_valid': self._is_schema_cache_valid(),
            'active_tables_sample': self.active_tables_cache[:10] if self.active_tables_cache else [],
            'last_update': self.last_schema_update.isoformat() if self.last_schema_update else None,
            'next_auto_update': (self.last_schema_update + timedelta(seconds=self.auto_update_interval)).isoformat() if self.last_schema_update else None
        }
    
    def start_auto_update_thread(self):
        """Iniciar thread para actualización automática cada 12 horas."""
        if self._auto_update_thread and self._auto_update_thread.is_alive():
            logger.warning("Thread de auto-actualización ya está corriendo")
            return
        
        self._stop_auto_update.clear()
        self._auto_update_thread = threading.Thread(
            target=self._auto_update_worker,
            daemon=True,
            name="SchemaAutoUpdate"
        )
        self._auto_update_thread.start()
        logger.info(f"Thread de auto-actualización iniciado (intervalo: {self.auto_update_interval/3600:.1f} horas)")
    
    def _auto_update_worker(self):
        """Worker thread para actualización automática de estadísticas."""
        while not self._stop_auto_update.is_set():
            try:
                # Esperar el intervalo de actualización
                if self._stop_auto_update.wait(self.auto_update_interval):
                    break  # Se solicitó detener
                
                logger.info("🔄 Iniciando actualización automática de estadísticas...")
                
                # Actualizar solo estadísticas (conteos), no todo el esquema
                stats = db.update_table_stats(force=True)
                
                if stats:
                    logger.info(f"✅ Actualización automática completada: {len(stats)} tablas actualizadas")
                    # Actualizar timestamp
                    self.last_schema_update = datetime.now()
                else:
                    logger.warning("⚠️ Actualización automática no retornó resultados")
                    
            except Exception as e:
                logger.error(f"Error en actualización automática: {e}")
                # Continuar a pesar del error
    
    def stop_auto_update_thread(self):
        """Detener thread de auto-actualización."""
        if self._auto_update_thread and self._auto_update_thread.is_alive():
            logger.info("Deteniendo thread de auto-actualización...")
            self._stop_auto_update.set()
            self._auto_update_thread.join(timeout=5)
            logger.info("Thread de auto-actualización detenido")
    
    def update_statistics_only(self, table_names: List[str] = None) -> Dict[str, int]:
        """
        Actualizar solo las estadísticas de tablas sin recargar el esquema completo.
        
        Args:
            table_names: Lista de tablas a actualizar. Si es None, actualiza todas.
            
        Returns:
            Diccionario con conteos actualizados
        """
        stats = db.update_table_stats(table_names=table_names, force=True)
        
        if stats:
            self.last_schema_update = datetime.now()
            logger.info(f"Estadísticas actualizadas manualmente: {len(stats)} tablas")
        
        return stats


# Instancia global del gestor de esquema
schema_manager = SchemaManager()