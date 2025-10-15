"""
Gestor de procedimientos almacenados para MicroSIP.

Este módulo identifica y utiliza procedimientos almacenados existentes
en la base de datos para optimizar consultas complejas.
"""

import json
import os
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

from config import config
from database import db
from utils import logger


@dataclass
class StoredProcedure:
    """Información de un procedimiento almacenado."""
    name: str
    description: str
    parameters: List[Dict[str, str]]
    return_type: str
    use_cases: List[str]
    example_call: str
    complexity_score: int  # Qué tan complejo es el cálculo que realiza


class StoredProceduresManager:
    """Gestor de procedimientos almacenados."""
    
    def __init__(self):
        self.procedures: Dict[str, StoredProcedure] = {}
        self.procedures_cache_file = config.rag.procedures_cache_path
        self._load_procedures()
    
    def _load_procedures(self) -> None:
        """Cargar procedimientos almacenados desde la base de datos."""
        try:
            # Intentar cargar desde caché
            if os.path.exists(self.procedures_cache_file):
                with open(self.procedures_cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    cache_time = datetime.fromisoformat(cached_data.get('timestamp', '2000-01-01'))
                    
                    # Si el caché tiene menos de 7 días, usarlo
                    if (datetime.now() - cache_time).days < 7:
                        self._load_from_cache(cached_data['procedures'])
                        logger.info(f"Procedimientos almacenados cargados desde caché: {len(self.procedures)}")
                        return
            
            # Si no hay caché válido, escanear la base de datos
            self._scan_database_procedures()
            self._save_to_cache()
            
        except Exception as e:
            logger.warning(f"No se pudieron cargar procedimientos almacenados: {e}")
            # Cargar procedimientos predefinidos de MicroSIP
            self._load_microsip_default_procedures()
    
    def _scan_database_procedures(self) -> None:
        """Escanear la base de datos para encontrar procedimientos almacenados."""
        try:
            # Query para obtener procedimientos en Firebird
            query = """
                SELECT 
                    RDB$PROCEDURE_NAME,
                    RDB$DESCRIPTION
                FROM RDB$PROCEDURES
                WHERE RDB$SYSTEM_FLAG = 0
                ORDER BY RDB$PROCEDURE_NAME
            """
            
            result = db.execute_query(query)
            
            if result.data:
                for row in result.data:
                    proc_name = row[0].strip() if row[0] else ""
                    proc_desc = row[1].strip() if row[1] and len(row) > 1 else ""
                    
                    if proc_name:
                        # Obtener parámetros del procedimiento
                        params = self._get_procedure_parameters(proc_name)
                        
                        # Crear objeto de procedimiento
                        procedure = StoredProcedure(
                            name=proc_name,
                            description=proc_desc or f"Procedimiento {proc_name}",
                            parameters=params,
                            return_type="TABLE",
                            use_cases=self._infer_use_cases(proc_name, proc_desc),
                            example_call=self._generate_example_call(proc_name, params),
                            complexity_score=self._calculate_complexity_score(proc_name, params)
                        )
                        
                        self.procedures[proc_name] = procedure
                
                logger.info(f"Escaneados {len(self.procedures)} procedimientos almacenados")
        
        except Exception as e:
            logger.error(f"Error escaneando procedimientos: {e}")
    
    def _get_procedure_parameters(self, procedure_name: str) -> List[Dict[str, str]]:
        """Obtener parámetros de un procedimiento."""
        try:
            query = f"""
                SELECT 
                    RDB$PARAMETER_NAME,
                    RDB$PARAMETER_TYPE,
                    RDB$FIELD_NAME
                FROM RDB$PROCEDURE_PARAMETERS
                WHERE RDB$PROCEDURE_NAME = '{procedure_name}'
                ORDER BY RDB$PARAMETER_NUMBER
            """
            
            result = db.execute_query(query)
            params = []
            
            if result.data:
                for row in result.data:
                    params.append({
                        'name': row[0].strip() if row[0] else "",
                        'type': 'INPUT' if row[1] == 0 else 'OUTPUT',
                        'field': row[2].strip() if row[2] else ""
                    })
            
            return params
        
        except Exception as e:
            logger.warning(f"No se pudieron obtener parámetros de {procedure_name}: {e}")
            return []
    
    def _infer_use_cases(self, proc_name: str, description: str) -> List[str]:
        """Inferir casos de uso basado en el nombre y descripción."""
        use_cases = []
        name_lower = proc_name.lower()
        desc_lower = description.lower() if description else ""
        
        # Mapeo de palabras clave a casos de uso
        keywords_map = {
            'venta': 'Análisis de ventas',
            'cliente': 'Gestión de clientes',
            'inventario': 'Control de inventario',
            'existencia': 'Consulta de existencias',
            'costo': 'Cálculo de costos',
            'precio': 'Gestión de precios',
            'reporte': 'Generación de reportes',
            'estadistica': 'Análisis estadístico',
            'movimiento': 'Movimientos de almacén',
            'factura': 'Facturación',
            'compra': 'Compras',
            'proveedor': 'Proveedores'
        }
        
        for keyword, use_case in keywords_map.items():
            if keyword in name_lower or keyword in desc_lower:
                use_cases.append(use_case)
        
        return use_cases if use_cases else ['Operación general']
    
    def _generate_example_call(self, proc_name: str, params: List[Dict[str, str]]) -> str:
        """Generar ejemplo de llamada al procedimiento."""
        input_params = [p for p in params if p['type'] == 'INPUT']
        
        if input_params:
            param_list = ', '.join([f":{p['name']}" for p in input_params])
            return f"SELECT * FROM {proc_name}({param_list})"
        else:
            return f"SELECT * FROM {proc_name}"
    
    def _calculate_complexity_score(self, proc_name: str, params: List[Dict[str, str]]) -> int:
        """Calcular score de complejidad del procedimiento."""
        score = 5  # Base score
        
        # Más parámetros = más complejo
        score += len(params) * 2
        
        # Nombres que sugieren complejidad
        complex_keywords = ['calculo', 'analisis', 'estadistica', 'reporte', 'consolidado']
        for keyword in complex_keywords:
            if keyword in proc_name.lower():
                score += 10
                break
        
        return min(score, 50)
    
    def _load_microsip_default_procedures(self) -> None:
        """Cargar procedimientos conocidos de MicroSIP."""
        # Procedimientos comunes en MicroSIP
        default_procedures = [
            {
                'name': 'SP_EXISTENCIAS_ARTICULO',
                'description': 'Obtener existencias actuales de artículos por almacén',
                'parameters': [
                    {'name': 'ARTICULO_ID', 'type': 'INPUT', 'field': 'INTEGER'},
                    {'name': 'ALMACEN_ID', 'type': 'INPUT', 'field': 'INTEGER'}
                ],
                'use_cases': ['Control de inventario', 'Consulta de existencias'],
                'complexity_score': 15
            },
            {
                'name': 'SP_VENTAS_PERIODO',
                'description': 'Análisis de ventas por período',
                'parameters': [
                    {'name': 'FECHA_INI', 'type': 'INPUT', 'field': 'DATE'},
                    {'name': 'FECHA_FIN', 'type': 'INPUT', 'field': 'DATE'}
                ],
                'use_cases': ['Análisis de ventas', 'Generación de reportes'],
                'complexity_score': 25
            },
            {
                'name': 'SP_COSTO_PROMEDIO',
                'description': 'Cálculo de costo promedio de artículos',
                'parameters': [
                    {'name': 'ARTICULO_ID', 'type': 'INPUT', 'field': 'INTEGER'}
                ],
                'use_cases': ['Cálculo de costos', 'Análisis financiero'],
                'complexity_score': 20
            }
        ]
        
        for proc_data in default_procedures:
            procedure = StoredProcedure(
                name=proc_data['name'],
                description=proc_data['description'],
                parameters=proc_data['parameters'],
                return_type='TABLE',
                use_cases=proc_data['use_cases'],
                example_call=self._generate_example_call(proc_data['name'], proc_data['parameters']),
                complexity_score=proc_data['complexity_score']
            )
            self.procedures[proc_data['name']] = procedure
        
        logger.info(f"Cargados {len(default_procedures)} procedimientos por defecto de MicroSIP")
    
    def _load_from_cache(self, cached_procedures: List[Dict]) -> None:
        """Cargar procedimientos desde caché."""
        for proc_data in cached_procedures:
            procedure = StoredProcedure(
                name=proc_data['name'],
                description=proc_data['description'],
                parameters=proc_data['parameters'],
                return_type=proc_data.get('return_type', 'TABLE'),
                use_cases=proc_data.get('use_cases', []),
                example_call=proc_data.get('example_call', ''),
                complexity_score=proc_data.get('complexity_score', 10)
            )
            self.procedures[proc_data['name']] = procedure
    
    def _save_to_cache(self) -> None:
        """Guardar procedimientos en caché."""
        try:
            os.makedirs(os.path.dirname(self.procedures_cache_file), exist_ok=True)
            
            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'procedures': [
                    {
                        'name': proc.name,
                        'description': proc.description,
                        'parameters': proc.parameters,
                        'return_type': proc.return_type,
                        'use_cases': proc.use_cases,
                        'example_call': proc.example_call,
                        'complexity_score': proc.complexity_score
                    }
                    for proc in self.procedures.values()
                ]
            }
            
            with open(self.procedures_cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Procedimientos almacenados guardados en caché")
        
        except Exception as e:
            logger.warning(f"No se pudo guardar caché de procedimientos: {e}")
    
    def find_relevant_procedures(self, user_query: str, top_k: int = 3) -> List[StoredProcedure]:
        """Encontrar procedimientos relevantes para una consulta."""
        if not config.rag.enable_stored_procedures or not self.procedures:
            return []
        
        query_lower = user_query.lower()
        scored_procedures = []
        
        for proc in self.procedures.values():
            score = 0
            
            # Puntuar por nombre
            if any(word in proc.name.lower() for word in query_lower.split()):
                score += 20
            
            # Puntuar por descripción
            if proc.description and any(word in proc.description.lower() for word in query_lower.split()):
                score += 15
            
            # Puntuar por casos de uso
            for use_case in proc.use_cases:
                if any(word in use_case.lower() for word in query_lower.split()):
                    score += 10
            
            # Bonus por complejidad (procedimientos complejos son más útiles)
            score += proc.complexity_score * 0.3
            
            if score > 0:
                scored_procedures.append((score, proc))
        
        # Ordenar por score y tomar top_k
        scored_procedures.sort(reverse=True, key=lambda x: x[0])
        return [proc for score, proc in scored_procedures[:top_k]]
    
    def get_procedures_context(self, relevant_procedures: List[StoredProcedure]) -> str:
        """Generar contexto de procedimientos para el prompt."""
        if not relevant_procedures:
            return ""
        
        context_parts = ["\n📦 PROCEDIMIENTOS ALMACENADOS DISPONIBLES:"]
        
        for proc in relevant_procedures:
            context_parts.append(f"\n**{proc.name}**")
            context_parts.append(f"  Descripción: {proc.description}")
            
            if proc.parameters:
                params_str = ", ".join([f"{p['name']} ({p['type']})" for p in proc.parameters])
                context_parts.append(f"  Parámetros: {params_str}")
            
            context_parts.append(f"  Uso: {', '.join(proc.use_cases)}")
            context_parts.append(f"  Ejemplo: {proc.example_call}")
            context_parts.append("")
        
        return "\n".join(context_parts)
    
    def get_all_procedures(self) -> List[StoredProcedure]:
        """Obtener todos los procedimientos almacenados."""
        return list(self.procedures.values())
    
    def get_procedure_by_name(self, name: str) -> Optional[StoredProcedure]:
        """Obtener un procedimiento por nombre."""
        return self.procedures.get(name.upper())


# Instancia global del gestor de procedimientos
procedures_manager = StoredProceduresManager()

