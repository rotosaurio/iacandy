# -*- coding: utf-8 -*-
"""
Módulo de gestión de historial de conversaciones.
Almacenamiento local en JSON para persistencia de chats.
"""

import json
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
from utils import logger


class ChatHistory:
    """Gestor de historial de conversaciones con persistencia local."""

    def __init__(self, storage_path: str = "data/chat_history.json"):
        """
        Inicializar gestor de historial.

        Args:
            storage_path: Ruta del archivo JSON para almacenar historial
        """
        self.storage_path = storage_path
        self._ensure_storage_exists()
        self.conversations = self._load_conversations()

    def _ensure_storage_exists(self):
        """Crear directorio y archivo si no existen."""
        storage_dir = os.path.dirname(self.storage_path)
        if storage_dir and not os.path.exists(storage_dir):
            os.makedirs(storage_dir, exist_ok=True)

        if not os.path.exists(self.storage_path):
            self._save_conversations({})

    def _load_conversations(self) -> Dict[str, Dict]:
        """
        Cargar conversaciones desde archivo JSON.

        Returns:
            Diccionario de conversaciones {session_id: conversation_data}
        """
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error cargando historial: {e}")
            return {}

    def _save_conversations(self, conversations: Dict = None):
        """
        Guardar conversaciones en archivo JSON.

        Args:
            conversations: Diccionario de conversaciones a guardar
        """
        try:
            data = conversations if conversations is not None else self.conversations
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error guardando historial: {e}")

    def create_conversation(self, session_id: str = None, title: str = "Nueva conversación") -> str:
        """
        Crear nueva conversación.

        Args:
            session_id: ID de sesión (se genera uno nuevo si no se proporciona)
            title: Título de la conversación

        Returns:
            ID de la conversación creada
        """
        if not session_id:
            session_id = str(uuid.uuid4())

        conversation = {
            'id': session_id,
            'title': title,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'messages': []
        }

        self.conversations[session_id] = conversation
        self._save_conversations()

        logger.info(f"Conversación creada: {session_id}")
        return session_id

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        sql_query: str = None,
        data: Any = None
    ):
        """
        Agregar mensaje a una conversación.

        Args:
            session_id: ID de la conversación
            role: Rol del mensaje ('user' o 'assistant')
            content: Contenido del mensaje
            sql_query: Query SQL generado (opcional)
            data: Datos de respuesta (opcional)
        """
        if session_id not in self.conversations:
            self.create_conversation(session_id)

        conversation = self.conversations[session_id]

        message = {
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat()
        }

        if sql_query:
            message['sql_query'] = sql_query

        if data:
            message['has_data'] = True
            # No guardamos los datos completos por tamaño, solo indicador

        conversation['messages'].append(message)
        conversation['updated_at'] = datetime.now().isoformat()

        # Auto-generar título basado en primer mensaje del usuario
        if len(conversation['messages']) == 1 and role == 'user':
            conversation['title'] = self._generate_title(content)

        self._save_conversations()

    def _generate_title(self, first_message: str, max_length: int = 50) -> str:
        """
        Generar título automático basado en el primer mensaje.

        Args:
            first_message: Primer mensaje del usuario
            max_length: Longitud máxima del título

        Returns:
            Título generado
        """
        # Limpiar y truncar
        title = first_message.strip()
        if len(title) > max_length:
            title = title[:max_length].rsplit(' ', 1)[0] + '...'

        return title

    def get_conversation(self, session_id: str) -> Optional[Dict]:
        """
        Obtener una conversación por ID.

        Args:
            session_id: ID de la conversación

        Returns:
            Datos de la conversación o None si no existe
        """
        return self.conversations.get(session_id)

    def get_all_conversations(self, sort_by: str = 'updated_at') -> List[Dict]:
        """
        Obtener todas las conversaciones ordenadas.

        Args:
            sort_by: Campo para ordenar ('created_at' o 'updated_at')

        Returns:
            Lista de conversaciones ordenadas por fecha (más reciente primero)
        """
        conversations_list = list(self.conversations.values())

        # Ordenar por fecha (más reciente primero)
        conversations_list.sort(
            key=lambda x: x.get(sort_by, ''),
            reverse=True
        )

        return conversations_list

    def get_conversations_grouped_by_date(self) -> Dict[str, List[Dict]]:
        """
        Obtener conversaciones agrupadas por fecha.

        Returns:
            Diccionario con conversaciones agrupadas:
            {
                'Hoy': [...],
                'Ayer': [...],
                'Esta semana': [...],
                'Este mes': [...],
                'Anteriores': [...]
            }
        """
        from datetime import date, timedelta

        today = date.today()
        yesterday = today - timedelta(days=1)
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)

        groups = {
            'Hoy': [],
            'Ayer': [],
            'Esta semana': [],
            'Este mes': [],
            'Anteriores': []
        }

        for conv in self.get_all_conversations():
            # Parsear fecha de actualización
            updated_str = conv.get('updated_at', '')
            try:
                updated_date = datetime.fromisoformat(updated_str).date()
            except:
                groups['Anteriores'].append(conv)
                continue

            # Clasificar por grupo
            if updated_date == today:
                groups['Hoy'].append(conv)
            elif updated_date == yesterday:
                groups['Ayer'].append(conv)
            elif updated_date >= week_ago:
                groups['Esta semana'].append(conv)
            elif updated_date >= month_ago:
                groups['Este mes'].append(conv)
            else:
                groups['Anteriores'].append(conv)

        # Eliminar grupos vacíos
        return {k: v for k, v in groups.items() if v}

    def update_conversation_title(self, session_id: str, new_title: str):
        """
        Actualizar título de una conversación.

        Args:
            session_id: ID de la conversación
            new_title: Nuevo título
        """
        if session_id in self.conversations:
            self.conversations[session_id]['title'] = new_title
            self.conversations[session_id]['updated_at'] = datetime.now().isoformat()
            self._save_conversations()
            logger.info(f"Título actualizado para conversación {session_id}")

    def delete_conversation(self, session_id: str) -> bool:
        """
        Eliminar una conversación.

        Args:
            session_id: ID de la conversación

        Returns:
            True si se eliminó, False si no existía
        """
        if session_id in self.conversations:
            del self.conversations[session_id]
            self._save_conversations()
            logger.info(f"Conversación eliminada: {session_id}")
            return True
        return False

    def clear_all_conversations(self):
        """Eliminar todas las conversaciones."""
        self.conversations = {}
        self._save_conversations()
        logger.info("Todas las conversaciones eliminadas")

    def get_conversation_summary(self, session_id: str) -> Dict:
        """
        Obtener resumen de una conversación para lista.

        Args:
            session_id: ID de la conversación

        Returns:
            Diccionario con datos resumidos
        """
        conv = self.conversations.get(session_id)
        if not conv:
            return None

        return {
            'id': conv['id'],
            'title': conv['title'],
            'created_at': conv['created_at'],
            'updated_at': conv['updated_at'],
            'message_count': len(conv['messages']),
            'preview': conv['messages'][0]['content'][:100] if conv['messages'] else ''
        }

    def search_conversations(self, query: str) -> List[Dict]:
        """
        Buscar conversaciones por texto.

        Args:
            query: Texto de búsqueda

        Returns:
            Lista de conversaciones que coinciden con la búsqueda
        """
        query_lower = query.lower()
        results = []

        for conv in self.conversations.values():
            # Buscar en título
            if query_lower in conv['title'].lower():
                results.append(conv)
                continue

            # Buscar en mensajes
            for msg in conv['messages']:
                if query_lower in msg['content'].lower():
                    results.append(conv)
                    break

        return results


# Instancia global
chat_history = ChatHistory()
