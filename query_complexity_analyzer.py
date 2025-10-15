"""
Analizador de complejidad de consultas y selector inteligente de modelos.

Este módulo determina la complejidad de una consulta y selecciona el modelo
de IA más apropiado para optimizar costos y rendimiento.
"""

import re
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass
from enum import Enum

from config import config
from utils import logger


class QueryComplexity(Enum):
    """Niveles de complejidad de consulta."""
    SIMPLE = "simple"           # 1-2 tablas, operaciones básicas
    MODERATE = "moderate"       # 3-4 tablas, agregaciones simples
    COMPLEX = "complex"         # 5-7 tablas, múltiples JOINs
    VERY_COMPLEX = "very_complex"  # 8+ tablas, subconsultas, CTEs


@dataclass
class ComplexityAnalysis:
    """Resultado del análisis de complejidad."""
    level: QueryComplexity
    score: int  # 0-100
    factors: Dict[str, int]
    recommended_model: str
    explanation: str
    estimated_tables: int


class QueryComplexityAnalyzer:
    """Analizador de complejidad de consultas."""
    
    # Palabras clave que indican complejidad
    COMPLEXITY_INDICATORS = {
        # Operaciones complejas
        'high': ['subconsulta', 'subquery', 'cte', 'with', 'window', 'partition', 'over',
                'row_number', 'rank', 'dense_rank', 'lag', 'lead', 'union', 'intersect',
                'except', 'recursive', 'pivot', 'unpivot'],
        
        # Operaciones moderadas
        'medium': ['join', 'inner', 'left', 'right', 'full', 'cross', 'group by', 
                  'having', 'distinct', 'case when', 'coalesce', 'cast'],
        
        # Agregaciones
        'aggregation': ['sum', 'count', 'avg', 'max', 'min', 'total', 'promedio',
                       'suma', 'conteo', 'cantidad', 'maximo', 'máximo', 'minimo', 'mínimo'],
        
        # Múltiples tablas
        'multi_table': ['y', 'con', 'de', 'desde', 'relacionado', 'combinado', 'cruzado',
                       'junto', 'vinculado', 'asociado', 'entre'],
        
        # Análisis temporal
        'temporal': ['mes', 'año', 'trimestre', 'periodo', 'fecha', 'tiempo', 'día',
                    'semana', 'histórico', 'tendencia', 'crecimiento', 'evolución'],
        
        # Análisis financiero/complejo
        'financial': ['margen', 'utilidad', 'ganancia', 'rentabilidad', 'ratio',
                     'porcentaje', 'proporción', 'comparativo', 'diferencia', 'variación']
    }
    
    # Tablas que típicamente requieren JOINs complejos
    COMPLEX_TABLES = [
        'DOCTOS_PV_DET', 'DOCTOS_CC_DET', 'MOVIMIENTOS_ALMACEN', 'EXISTENCIAS',
        'PRECIOS_ARTICULOS', 'CLAVES_ARTICULOS', 'MOVIMIENTOS_CAJA'
    ]
    
    def __init__(self):
        self.complexity_weights = {
            'high': 25,
            'medium': 10,
            'aggregation': 8,
            'multi_table': 5,
            'temporal': 7,
            'financial': 12
        }
    
    def analyze_query_complexity(self, user_query: str, relevant_tables: List[Dict[str, Any]] = None) -> ComplexityAnalysis:
        """Analizar la complejidad de una consulta de usuario."""
        query_lower = user_query.lower()
        factors = {}
        score = 0
        
        # 1. Análisis de palabras clave
        for category, keywords in self.COMPLEXITY_INDICATORS.items():
            matches = sum(1 for keyword in keywords if keyword in query_lower)
            if matches > 0:
                factors[f'keywords_{category}'] = matches
                weight = self.complexity_weights.get(category, 5)
                score += matches * weight
        
        # 2. Análisis de tablas relevantes
        num_tables = len(relevant_tables) if relevant_tables else 1
        factors['num_tables'] = num_tables
        
        if num_tables >= 8:
            score += 40
        elif num_tables >= 5:
            score += 30
        elif num_tables >= 3:
            score += 15
        elif num_tables >= 2:
            score += 5
        
        # 3. Tablas complejas identificadas
        if relevant_tables:
            complex_tables_count = sum(
                1 for table in relevant_tables 
                if table.get('name', '').upper() in self.COMPLEX_TABLES
            )
            factors['complex_tables'] = complex_tables_count
            score += complex_tables_count * 8
        
        # 4. Longitud y detalle de la consulta
        query_length = len(user_query.split())
        if query_length > 20:
            score += 15
            factors['query_length'] = 'long'
        elif query_length > 10:
            score += 8
            factors['query_length'] = 'medium'
        else:
            factors['query_length'] = 'short'
        
        # 5. Palabras que indican análisis múltiple
        multi_analysis_keywords = ['y también', 'además', 'igualmente', 'comparar con',
                                  'diferencia entre', 'relación entre', 'versus']
        multi_count = sum(1 for keyword in multi_analysis_keywords if keyword in query_lower)
        if multi_count > 0:
            factors['multi_analysis'] = multi_count
            score += multi_count * 10
        
        # Limitar score a 100
        score = min(score, 100)
        
        # Determinar nivel de complejidad
        if score >= 70:
            level = QueryComplexity.VERY_COMPLEX
        elif score >= 45:
            level = QueryComplexity.COMPLEX
        elif score >= 20:
            level = QueryComplexity.MODERATE
        else:
            level = QueryComplexity.SIMPLE
        
        # Seleccionar modelo recomendado
        recommended_model = self._select_model(level, num_tables)
        
        # Generar explicación
        explanation = self._generate_explanation(level, factors, num_tables)
        
        return ComplexityAnalysis(
            level=level,
            score=score,
            factors=factors,
            recommended_model=recommended_model,
            explanation=explanation,
            estimated_tables=num_tables
        )
    
    def _select_model(self, complexity: QueryComplexity, num_tables: int) -> str:
        """Seleccionar el modelo más apropiado basado en complejidad."""
        if not config.ai.enable_smart_model_selection:
            # Si no está habilitada la selección inteligente, usar modelo principal
            return config.ai.model
        
        # Estrategia de selección
        if complexity in [QueryComplexity.VERY_COMPLEX, QueryComplexity.COMPLEX]:
            # Queries complejas siempre usan el mejor modelo
            return config.ai.model_complex
        
        elif complexity == QueryComplexity.MODERATE:
            # Queries moderadas: depende del número de tablas
            if num_tables >= config.ai.complexity_threshold:
                return config.ai.model_complex
            else:
                return config.ai.model_simple
        
        else:  # SIMPLE
            # Queries simples usan modelo económico
            return config.ai.model_simple
    
    def _generate_explanation(self, level: QueryComplexity, factors: Dict[str, int], num_tables: int) -> str:
        """Generar explicación de la complejidad."""
        explanations = {
            QueryComplexity.SIMPLE: f"Consulta simple ({num_tables} tabla(s)). Operaciones básicas de SELECT.",
            QueryComplexity.MODERATE: f"Consulta moderada ({num_tables} tabla(s)). Incluye JOINs o agregaciones.",
            QueryComplexity.COMPLEX: f"Consulta compleja ({num_tables} tabla(s)). Múltiples JOINs y cálculos avanzados.",
            QueryComplexity.VERY_COMPLEX: f"Consulta muy compleja ({num_tables} tabla(s)). Requiere análisis profundo con subconsultas o CTEs."
        }
        
        base_explanation = explanations.get(level, "Nivel de complejidad indeterminado")
        
        # Agregar factores destacados
        factor_notes = []
        if factors.get('keywords_high', 0) > 0:
            factor_notes.append("operaciones avanzadas")
        if factors.get('keywords_financial', 0) > 0:
            factor_notes.append("análisis financiero")
        if factors.get('keywords_temporal', 0) > 0:
            factor_notes.append("análisis temporal")
        if factors.get('complex_tables', 0) > 0:
            factor_notes.append("tablas de alto volumen")
        
        if factor_notes:
            base_explanation += f" Detectado: {', '.join(factor_notes)}."
        
        return base_explanation


class ModelSelector:
    """Selector inteligente de modelos de IA."""
    
    def __init__(self):
        self.analyzer = QueryComplexityAnalyzer()
        self.usage_stats = {
            'gpt-5': 0,
            'gpt-4o': 0,
            'fallback': 0
        }
    
    def select_model_for_query(self, user_query: str, relevant_tables: List[Dict[str, Any]] = None) -> Tuple[str, ComplexityAnalysis]:
        """Seleccionar el modelo óptimo para una consulta."""
        # Analizar complejidad
        analysis = self.analyzer.analyze_query_complexity(user_query, relevant_tables)
        
        # Obtener modelo recomendado
        model = analysis.recommended_model
        
        # Registrar uso
        if 'gpt-5' in model.lower():
            self.usage_stats['gpt-5'] += 1
        elif 'gpt-4' in model.lower():
            self.usage_stats['gpt-4o'] += 1
        else:
            self.usage_stats['fallback'] += 1
        
        # Log de selección
        logger.info(
            f"Modelo seleccionado: {model} | "
            f"Complejidad: {analysis.level.value} (score: {analysis.score}) | "
            f"Tablas: {analysis.estimated_tables} | "
            f"Razón: {analysis.explanation}"
        )
        
        return model, analysis
    
    def get_usage_statistics(self) -> Dict[str, Any]:
        """Obtener estadísticas de uso de modelos."""
        total = sum(self.usage_stats.values())
        if total == 0:
            return {"total_queries": 0}
        
        return {
            "total_queries": total,
            "gpt-5_usage": self.usage_stats['gpt-5'],
            "gpt-4o_usage": self.usage_stats['gpt-4o'],
            "fallback_usage": self.usage_stats['fallback'],
            "gpt-5_percentage": round(self.usage_stats['gpt-5'] / total * 100, 1),
            "gpt-4o_percentage": round(self.usage_stats['gpt-4o'] / total * 100, 1)
        }
    
    def should_use_advanced_model(self, analysis: ComplexityAnalysis) -> bool:
        """Determinar si se debe usar el modelo avanzado."""
        return analysis.level in [QueryComplexity.COMPLEX, QueryComplexity.VERY_COMPLEX]


# Instancia global del selector de modelos
model_selector = ModelSelector()

