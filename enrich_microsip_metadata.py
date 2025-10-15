"""
Script para enriquecer los metadatos de MicroSIP con información real de la base de datos.

Este script:
1. Lee los archivos existentes microsip_dictionary.json y microsip_relationships.json
2. Analiza la base de datos real para obtener información adicional
3. Enriquece los metadatos con:
   - Descripciones de negocio inferidas
   - Patrones de datos reales
   - Estadísticas de uso
   - Keywords adicionales basados en contenido
   - Relaciones inferidas por análisis de FKs
4. Guarda versiones mejoradas de los archivos
"""

import json
import os
from typing import Dict, List, Any, Set
from collections import defaultdict
from datetime import datetime

from database import db
from schema_manager import TableDescriptor
from utils import logger


class MicroSIPMetadataEnricher:
    """Enriquecedor de metadatos de MicroSIP con análisis real de BD."""

    def __init__(self):
        self.dictionary_path = 'microsip_dictionary.json'
        self.relationships_path = 'microsip_relationships.json'
        self.dictionary = {}
        self.relationships = {}
        self.enriched_data = {}

    def load_existing_metadata(self):
        """Cargar metadatos existentes."""
        logger.info("📖 Cargando metadatos existentes...")

        # Cargar diccionario
        if os.path.exists(self.dictionary_path):
            with open(self.dictionary_path, 'r', encoding='utf-8') as f:
                self.dictionary = json.load(f)
            logger.info(f"✓ Diccionario cargado: {len(self.dictionary.get('tablas', {}))} tablas")
        else:
            logger.warning(f"⚠ No se encontró {self.dictionary_path}")
            self.dictionary = {'metadata': {}, 'categorias': {}, 'tablas': {}, 'keywords_busqueda': {}}

        # Cargar relaciones
        if os.path.exists(self.relationships_path):
            with open(self.relationships_path, 'r', encoding='utf-8') as f:
                self.relationships = json.load(f)
            logger.info(f"✓ Relaciones cargadas: {len(self.relationships.get('graph', {}))} tablas")
        else:
            logger.warning(f"⚠ No se encontró {self.relationships_path}")
            self.relationships = {'relationships': {}, 'graph': {}, 'table_networks': {}}

    def analyze_database(self) -> Dict[str, Any]:
        """Analizar base de datos real para obtener información adicional."""
        logger.info("🔍 Analizando base de datos real...")

        # Obtener esquema completo
        schema = db.get_full_schema(force_refresh=True)

        enriched_tables = {}

        total = len(schema)
        processed = 0

        for table_name, table_info in schema.items():
            processed += 1

            if processed % 50 == 0:
                logger.info(f"  Procesadas {processed}/{total} tablas...")

            try:
                # Análisis básico
                analysis = {
                    'table_name': table_name,
                    'row_count': table_info.row_count,
                    'column_count': len(table_info.columns),
                    'has_primary_key': len(table_info.primary_keys) > 0,
                    'has_foreign_keys': len(table_info.foreign_keys) > 0,
                    'has_indexes': len(table_info.indexes) > 0,
                    'is_active': table_info.is_active,
                }

                # Inferir propósito de negocio
                business_purpose = TableDescriptor._infer_business_purpose(
                    table_name.lower(),
                    table_info.columns
                )
                analysis['business_purpose'] = business_purpose

                # Analizar tipos de columnas semánticas
                semantic_fields = TableDescriptor._identify_semantic_fields(table_info.columns)
                analysis['semantic_fields'] = semantic_fields

                # Generar keywords adicionales
                search_terms = TableDescriptor._generate_search_terms(table_name, table_info.columns)
                analysis['search_terms'] = search_terms.split(', ') if search_terms else []

                # Obtener muestra de datos (solo primeras 100 tablas con datos)
                if processed <= 100 and table_info.row_count != 0:
                    try:
                        sample_query = f"SELECT FIRST 5 * FROM {table_name}"
                        result = db.execute_query(sample_query)
                        if result and result.data:
                            # Analizar patrones en datos
                            patterns = TableDescriptor._analyze_data_patterns(
                                table_info.columns,
                                result.data
                            )
                            analysis['data_patterns'] = patterns
                    except Exception as e:
                        logger.debug(f"  No se pudo analizar muestra de {table_name}: {str(e)[:50]}")

                # Analizar relaciones
                fk_relations = []
                for fk in table_info.foreign_keys:
                    ref_table = fk.get('referenced_table')
                    if ref_table:
                        fk_relations.append({
                            'table': ref_table,
                            'columns': fk.get('columns', []),
                            'referenced_columns': fk.get('referenced_columns', [])
                        })
                analysis['foreign_key_relations'] = fk_relations

                # Categorizar tabla automáticamente
                category = self._auto_categorize_table(table_name, table_info.columns, semantic_fields)
                analysis['auto_category'] = category

                enriched_tables[table_name] = analysis

            except Exception as e:
                logger.error(f"Error analizando {table_name}: {str(e)}")
                continue

        logger.info(f"✅ Análisis completado: {len(enriched_tables)} tablas enriquecidas")
        return enriched_tables

    def _auto_categorize_table(self, table_name: str, columns: List[Dict], semantic_fields: List[str]) -> str:
        """Categorizar tabla automáticamente basándose en nombre y contenido."""
        name_lower = table_name.lower()
        col_names = [col['name'].lower() for col in columns]
        col_names_str = ' '.join(col_names)

        # Prioridad: más específico primero
        if any(k in name_lower for k in ['venta', 'ticket', 'pos', 'factura', 'doctos_pv', 'doctos_ve']):
            return 'VENTAS'

        if any(k in name_lower for k in ['compra', 'orden_compra', 'doctos_in', 'requisicion']):
            return 'COMPRAS'

        if any(k in name_lower for k in ['cliente', 'customer', 'consumidor']):
            return 'CLIENTES'

        if any(k in name_lower for k in ['proveedor', 'vendor', 'supplier']):
            return 'PROVEEDORES'

        if any(k in name_lower for k in ['articulo', 'producto', 'item', 'existencia', 'inventario', 'almacen']):
            return 'INVENTARIO'

        if any(k in name_lower for k in ['empleado', 'personal', 'trabajador', 'usuario']):
            return 'RECURSOS_HUMANOS'

        if any(k in name_lower for k in ['pago', 'cobranza', 'abono', 'saldo', 'cuenta', 'banco']):
            return 'FINANZAS'

        if any(k in name_lower for k in ['pedido', 'cotizacion', 'orden', 'remision']):
            return 'OPERACIONES'

        if any(k in name_lower for k in ['reporte', 'log', 'auditoria', 'bitacora', 'historial']):
            return 'AUDITORIA'

        if any(k in name_lower for k in ['config', 'parametro', 'catalogo', 'tipo', 'categoria', 'grupo']):
            return 'CATALOGOS'

        # Por contenido semántico
        if 'importes y precios' in semantic_fields and 'fechas y tiempos' in semantic_fields:
            return 'TRANSACCIONES'

        if 'nombres y descripciones' in semantic_fields and len(columns) <= 10:
            return 'CATALOGOS'

        return 'OTROS'

    def merge_and_enrich(self, db_analysis: Dict[str, Any]):
        """Combinar metadatos existentes con análisis de BD."""
        logger.info("🔗 Combinando metadatos existentes con análisis de BD...")

        # Enriquecer diccionario
        enriched_dict = self.dictionary.copy()

        # Actualizar metadata
        enriched_dict['metadata'] = {
            'total_tablas': len(db_analysis),
            'sistema': 'MicroSIP',
            'version_analisis': '2.0',
            'fecha_enriquecimiento': datetime.now().isoformat(),
            'enriquecido_con': 'análisis real de base de datos'
        }

        # Actualizar tablas con información enriquecida
        if 'tablas' not in enriched_dict:
            enriched_dict['tablas'] = {}

        for table_name, analysis in db_analysis.items():
            # Mantener info existente si la hay
            existing = enriched_dict['tablas'].get(table_name, {})

            # Combinar información
            enriched_dict['tablas'][table_name] = {
                **existing,  # Mantener datos originales
                'categoria': analysis.get('auto_category', existing.get('categoria', 'OTROS')),
                'row_count': analysis.get('row_count', 0),
                'column_count': analysis.get('column_count', 0),
                'has_primary_key': analysis.get('has_primary_key', False),
                'has_foreign_keys': analysis.get('has_foreign_keys', False),
                'is_active': analysis.get('is_active', True),
                'business_purpose': analysis.get('business_purpose', ''),
                'semantic_fields': analysis.get('semantic_fields', []),
                'data_patterns': analysis.get('data_patterns', ''),
                'columnas': existing.get('columnas', []),
                'tipos_columnas': existing.get('tipos_columnas', {}),
            }

        # Enriquecer keywords de búsqueda
        if 'keywords_busqueda' not in enriched_dict:
            enriched_dict['keywords_busqueda'] = {}

        for table_name, analysis in db_analysis.items():
            existing_keywords = set(enriched_dict['keywords_busqueda'].get(table_name, []))
            new_keywords = set(analysis.get('search_terms', []))

            # Agregar keywords del propósito de negocio
            business_purpose = analysis.get('business_purpose', '')
            if business_purpose:
                words = business_purpose.lower().split()
                # Filtrar palabras significativas (> 4 letras)
                significant_words = [w for w in words if len(w) > 4 and w.isalpha()]
                new_keywords.update(significant_words[:5])

            # Combinar y limitar
            all_keywords = list(existing_keywords.union(new_keywords))[:25]
            enriched_dict['keywords_busqueda'][table_name] = all_keywords

        # Actualizar categorías
        categories = defaultdict(list)
        for table_name, table_data in enriched_dict['tablas'].items():
            category = table_data.get('categoria', 'OTROS')
            categories[category].append(table_name)

        enriched_dict['categorias'] = dict(categories)

        # Enriquecer relaciones
        enriched_rels = self.relationships.copy()

        if 'relationships' not in enriched_rels:
            enriched_rels['relationships'] = {}

        if 'graph' not in enriched_rels:
            enriched_rels['graph'] = {}

        # Agregar relaciones inferidas del análisis
        for table_name, analysis in db_analysis.items():
            fk_relations = analysis.get('foreign_key_relations', [])

            if fk_relations:
                # Actualizar relationships
                if table_name not in enriched_rels['relationships']:
                    enriched_rels['relationships'][table_name] = []

                for rel in fk_relations:
                    ref_table = rel['table']
                    columns = rel['columns']

                    # Agregar si no existe
                    rel_entry = {
                        'column': columns[0] if columns else '',
                        'references': ref_table
                    }

                    if rel_entry not in enriched_rels['relationships'][table_name]:
                        enriched_rels['relationships'][table_name].append(rel_entry)

                # Actualizar graph (lista simple de tablas relacionadas)
                if table_name not in enriched_rels['graph']:
                    enriched_rels['graph'][table_name] = []

                for rel in fk_relations:
                    ref_table = rel['table']
                    if ref_table not in enriched_rels['graph'][table_name]:
                        enriched_rels['graph'][table_name].append(ref_table)

        logger.info(f"✅ Enriquecimiento completado")
        logger.info(f"  - Tablas: {len(enriched_dict['tablas'])}")
        logger.info(f"  - Categorías: {len(enriched_dict['categorias'])}")
        logger.info(f"  - Keywords: {len(enriched_dict['keywords_busqueda'])}")
        logger.info(f"  - Relaciones: {len(enriched_rels['relationships'])}")

        return enriched_dict, enriched_rels

    def save_enriched_metadata(self, enriched_dict: Dict, enriched_rels: Dict):
        """Guardar metadatos enriquecidos."""
        logger.info("💾 Guardando metadatos enriquecidos...")

        # Backup de archivos originales
        if os.path.exists(self.dictionary_path):
            backup_path = self.dictionary_path.replace('.json', '_backup.json')
            os.rename(self.dictionary_path, backup_path)
            logger.info(f"  ✓ Backup creado: {backup_path}")

        if os.path.exists(self.relationships_path):
            backup_path = self.relationships_path.replace('.json', '_backup.json')
            os.rename(self.relationships_path, backup_path)
            logger.info(f"  ✓ Backup creado: {backup_path}")

        # Guardar versiones enriquecidas
        with open(self.dictionary_path, 'w', encoding='utf-8') as f:
            json.dump(enriched_dict, f, indent=2, ensure_ascii=False)
        logger.info(f"  ✓ Guardado: {self.dictionary_path}")

        with open(self.relationships_path, 'w', encoding='utf-8') as f:
            json.dump(enriched_rels, f, indent=2, ensure_ascii=False)
        logger.info(f"  ✓ Guardado: {self.relationships_path}")

        logger.info("✅ Metadatos enriquecidos guardados exitosamente")

    def enrich(self):
        """Proceso completo de enriquecimiento."""
        logger.info("🚀 Iniciando enriquecimiento de metadatos MicroSIP...")

        try:
            # 1. Cargar existentes
            self.load_existing_metadata()

            # 2. Analizar BD
            db_analysis = self.analyze_database()

            # 3. Combinar y enriquecer
            enriched_dict, enriched_rels = self.merge_and_enrich(db_analysis)

            # 4. Guardar
            self.save_enriched_metadata(enriched_dict, enriched_rels)

            # 5. Generar reporte
            self.generate_report(enriched_dict, enriched_rels)

            logger.info("🎉 Enriquecimiento completado exitosamente")

        except Exception as e:
            logger.error(f"❌ Error en enriquecimiento: {str(e)}", e)
            raise

    def generate_report(self, enriched_dict: Dict, enriched_rels: Dict):
        """Generar reporte del enriquecimiento."""
        report = []
        report.append("=" * 80)
        report.append("REPORTE DE ENRIQUECIMIENTO DE METADATOS MICROSIP")
        report.append("=" * 80)
        report.append("")

        # Estadísticas generales
        report.append("📊 ESTADÍSTICAS GENERALES")
        report.append("-" * 80)
        report.append(f"Total de tablas: {len(enriched_dict.get('tablas', {}))}")
        report.append(f"Total de categorías: {len(enriched_dict.get('categorias', {}))}")
        report.append(f"Tablas con keywords: {len(enriched_dict.get('keywords_busqueda', {}))}")
        report.append(f"Tablas con relaciones: {len(enriched_rels.get('relationships', {}))}")
        report.append("")

        # Distribución por categorías
        report.append("📁 DISTRIBUCIÓN POR CATEGORÍAS")
        report.append("-" * 80)
        categories = enriched_dict.get('categorias', {})
        for category, tables in sorted(categories.items(), key=lambda x: len(x[1]), reverse=True):
            report.append(f"  {category}: {len(tables)} tablas")
        report.append("")

        # Top 10 tablas más conectadas
        report.append("🔗 TOP 10 TABLAS MÁS CONECTADAS")
        report.append("-" * 80)
        graph = enriched_rels.get('graph', {})
        sorted_by_connections = sorted(graph.items(), key=lambda x: len(x[1]), reverse=True)[:10]
        for table, related in sorted_by_connections:
            report.append(f"  {table}: {len(related)} conexiones")
        report.append("")

        # Guardar reporte
        report_text = "\n".join(report)
        report_path = 'enriquecimiento_reporte.txt'
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_text)

        logger.info(f"📄 Reporte guardado: {report_path}")
        print(report_text)


def main():
    """Punto de entrada principal."""
    print("=" * 80)
    print("ENRIQUECEDOR DE METADATOS MICROSIP")
    print("=" * 80)
    print()

    enricher = MicroSIPMetadataEnricher()
    enricher.enrich()


if __name__ == '__main__':
    main()
