# -*- coding: utf-8 -*-
"""
Interfaz gráfica principal del sistema de IA para consulta de base de datos.

Este módulo implementa la interfaz de usuario usando PySide6 con un diseño
minimalista centrado en la conversación con el asistente de IA.
"""

import os
import sys
import threading
import traceback
from typing import Dict, List, Optional, Any
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QTextEdit, QLineEdit, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QTabWidget, QProgressBar, QMessageBox, QSplitter, QFrame, QScrollArea,
    QFileDialog, QStatusBar, QMenuBar, QMenu, QToolBar, QGroupBox
)
from PySide6.QtCore import (
    Qt, QThread, QTimer, Signal, QSize, QPropertyAnimation, QEasingCurve
)
from PySide6.QtGui import (
    QFont, QPalette, QColor, QPixmap, QIcon, QAction, QTextCursor, QTextCharFormat
)

from config import config, StatusMessages, Emojis
from database import db
from schema_manager import schema_manager
from ai_assistant import ai_assistant, AIResponse
from report_generator import report_generator, ExportProgress
from utils import logger, DataFormatter


class LoadingWorker(QThread):
    """Worker thread para operaciones de carga en background."""
    
    progress_updated = Signal(str)  # Mensaje de progreso
    schema_loaded = Signal(dict)    # Esquema cargado
    error_occurred = Signal(str)    # Error
    
    def run(self):
        """Ejecutar carga del esquema."""
        try:
            self.progress_updated.emit(StatusMessages.LOADING_SCHEMA)
            
            # Conectar a base de datos
            if not db.is_connected():
                self.progress_updated.emit(StatusMessages.CONNECTING)
                if not db.connect():
                    self.error_occurred.emit("No se pudo conectar a la base de datos")
                    return
            
            # Cargar esquema
            schema_data = schema_manager.load_and_process_schema()
            
            if not schema_data:
                self.error_occurred.emit("No se pudo cargar el esquema")
                return
            
            # Emitir resultado
            stats = schema_data.get('stats', {})
            active_count = stats.get('active_tables', 0)
            
            message = StatusMessages.SCHEMA_READY.format(active_count)
            self.progress_updated.emit(message)
            self.schema_loaded.emit(schema_data)
            
        except Exception as e:
            logger.error("Error en LoadingWorker", e)
            self.error_occurred.emit(f"Error cargando sistema: {str(e)}")


class QueryWorker(QThread):
    """Worker thread para ejecutar consultas AI."""
    
    response_ready = Signal(object)  # AIResponse
    error_occurred = Signal(str)     # Error
    
    def __init__(self, message: str, session_id: str = None):
        super().__init__()
        self.message = message
        self.session_id = session_id
    
    def run(self):
        """Ejecutar consulta de IA."""
        try:
            response = ai_assistant.chat(self.message, self.session_id)
            self.response_ready.emit(response)
            
        except Exception as e:
            logger.error(f"Error procesando consulta: {self.message}", e)
            self.error_occurred.emit(f"Error procesando consulta: {str(e)}")


class ExportProgressDialog(QWidget):
    """Diálogo de progreso de exportación."""
    
    def __init__(self, export_id: str, parent=None):
        super().__init__(parent)
        self.export_id = export_id
        self.setup_ui()
        
        # Timer para actualizar progreso
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_progress)
        self.timer.start(500)  # Actualizar cada 500ms
    
    def setup_ui(self):
        """Configurar interfaz."""
        self.setWindowTitle("Exportando datos...")
        self.setFixedSize(400, 150)
        
        layout = QVBoxLayout(self)
        
        # Etiqueta de estado
        self.status_label = QLabel("Iniciando exportación...")
        layout.addWidget(self.status_label)
        
        # Barra de progreso
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)
        
        # Información detallada
        self.details_label = QLabel("")
        self.details_label.setStyleSheet("color: #666666; font-size: 11px;")
        layout.addWidget(self.details_label)
        
        # Botón cancelar
        button_layout = QHBoxLayout()
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.clicked.connect(self.cancel_export)
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
    
    def update_progress(self):
        """Actualizar progreso de exportación."""
        progress = report_generator.get_export_progress(self.export_id)
        
        if progress:
            self.status_label.setText(progress.status)
            self.progress_bar.setValue(int(progress.progress_percentage))
            
            # Detalles
            details = f"Procesados: {DataFormatter.format_number(progress.processed_rows)}"
            if progress.total_rows > 0:
                details += f" de {DataFormatter.format_number(progress.total_rows)}"
            
            if progress.elapsed_time > 0:
                details += f" | Tiempo: {DataFormatter.format_duration(progress.elapsed_time)}"
            
            self.details_label.setText(details)
            
            # Verificar si terminó
            if progress.status in ['Completado', 'Error', 'Cancelado']:
                self.timer.stop()
                
                if progress.status == 'Completado':
                    self.show_completion_message(progress.file_path)
                elif progress.status == 'Error':
                    self.show_error_message(progress.error)
                
                self.close()
    
    def cancel_export(self):
        """Cancelar exportación."""
        report_generator.cancel_export(self.export_id)
        self.timer.stop()
        self.close()
    
    def show_completion_message(self, file_path: str):
        """Mostrar mensaje de completado."""
        QMessageBox.information(
            self, 
            "Exportación Completada", 
            f"Archivo exportado exitosamente:\n{file_path}"
        )
    
    def show_error_message(self, error: str):
        """Mostrar mensaje de error."""
        QMessageBox.critical(
            self, 
            "Error en Exportación", 
            f"Error durante la exportación:\n{error}"
        )


class ResultsTable(QTableWidget):
    """Tabla optimizada para mostrar resultados."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        """Configurar interfaz de la tabla."""
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.ExtendedSelection)
        
        # Estilos
        self.setStyleSheet("""
            QTableWidget {
                gridline-color: #e0e0e0;
                background-color: white;
                border: 1px solid #cccccc;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QTableWidget::item:selected {
                background-color: #0078d4;
                color: white;
            }
            QHeaderView::section {
                background-color: #f5f5f5;
                padding: 8px;
                border: 1px solid #cccccc;
                font-weight: bold;
            }
        """)
    
    def load_data(self, columns: List[str], data: List[List[Any]], has_more_data: bool = False):
        """Cargar datos en la tabla."""
        self.clear()
        self.setRowCount(len(data))
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels(columns)
        
        # Llenar datos
        for row_idx, row_data in enumerate(data):
            for col_idx, value in enumerate(row_data):
                formatted_value = self.format_cell_value(value)
                item = QTableWidgetItem(str(formatted_value))
                self.setItem(row_idx, col_idx, item)
        
        # Auto-ajustar columnas
        self.resizeColumnsToContents()
        
        # Limitar ancho máximo de columnas
        for col in range(self.columnCount()):
            if self.columnWidth(col) > 200:
                self.setColumnWidth(col, 200)
    
    def format_cell_value(self, value) -> str:
        """Formatear valor de celda."""
        if value is None:
            return ""
        elif isinstance(value, (int, float)):
            return DataFormatter.format_number(value)
        elif isinstance(value, datetime):
            return DataFormatter.format_datetime(value)
        else:
            return DataFormatter.truncate_text(str(value), 100)


class ChatWidget(QWidget):
    """Widget de chat conversacional."""
    
    message_sent = Signal(str)  # Mensaje enviado
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        """Configurar interfaz del chat."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Área de conversación
        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        self.chat_area.setMinimumHeight(300)
        
        # Estilos del chat
        self.chat_area.setStyleSheet("""
            QTextEdit {
                background-color: #f9f9f9;
                border: 1px solid #cccccc;
                border-radius: 8px;
                padding: 10px;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 12px;
                line-height: 1.4;
            }
        """)
        
        layout.addWidget(self.chat_area)
        
        # Área de entrada
        input_layout = QHBoxLayout()
        
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Escribe tu pregunta aquí...")
        self.input_field.returnPressed.connect(self.send_message)
        
        self.send_button = QPushButton("Enviar")
        self.send_button.clicked.connect(self.send_message)
        self.send_button.setDefault(True)
        
        # Estilos de entrada
        self.input_field.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                font-size: 12px;
                border: 2px solid #cccccc;
                border-radius: 5px;
            }
            QLineEdit:focus {
                border-color: #0078d4;
            }
        """)
        
        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 10px 20px;
                font-size: 12px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
        """)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_button)
        
        layout.addLayout(input_layout)
        
        # Mensaje de bienvenida
        self.add_system_message("¡Hola! Soy tu asistente de IA para consultas de base de datos. "
                               "Puedes preguntarme sobre tus datos usando lenguaje natural.")
    
    def send_message(self):
        """Enviar mensaje."""
        message = self.input_field.text().strip()
        if message:
            self.add_user_message(message)
            self.input_field.clear()
            self.message_sent.emit(message)
    
    def add_user_message(self, message: str):
        """Agregar mensaje del usuario."""
        formatted_message = f"""
        <div style="margin: 10px 0; padding: 10px; background-color: #e3f2fd; border-radius: 10px; text-align: right;">
            <strong>Tú:</strong> {message}
        </div>
        """
        self.chat_area.append(formatted_message)
        self.scroll_to_bottom()
    
    def add_ai_message(self, message: str):
        """Agregar mensaje de la IA."""
        formatted_message = f"""
        <div style="margin: 10px 0; padding: 10px; background-color: #f1f8e9; border-radius: 10px;">
            <strong>🤖 Asistente:</strong> {message}
        </div>
        """
        self.chat_area.append(formatted_message)
        self.scroll_to_bottom()
    
    def add_system_message(self, message: str):
        """Agregar mensaje del sistema."""
        formatted_message = f"""
        <div style="margin: 10px 0; padding: 8px; background-color: #fff3e0; border-radius: 8px; font-style: italic;">
            <span style="color: #ff6f00;">ℹ️ Sistema:</span> {message}
        </div>
        """
        self.chat_area.append(formatted_message)
        self.scroll_to_bottom()
    
    def add_suggestions(self, suggestions: List[str]):
        """Agregar sugerencias de seguimiento."""
        if not suggestions:
            return
        
        suggestions_html = "<div style='margin: 10px 0; padding: 10px; background-color: #f3e5f5; border-radius: 8px;'>"
        suggestions_html += "<strong>💡 También puedes preguntar:</strong><ul>"
        
        for suggestion in suggestions:
            suggestions_html += f"<li>{suggestion}</li>"
        
        suggestions_html += "</ul></div>"
        
        self.chat_area.append(suggestions_html)
        self.scroll_to_bottom()
    
    def scroll_to_bottom(self):
        """Hacer scroll al final."""
        scrollbar = self.chat_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


class MainWindow(QMainWindow):
    """Ventana principal del sistema."""
    
    def __init__(self):
        super().__init__()
        self.session_id = None
        self.current_query_result = None
        self.loading_worker = None
        self.query_worker = None
        self.schema_loaded = False
        
        self.setup_ui()
        self.setup_menu_bar()
        self.setup_status_bar()
        
        # Iniciar carga del sistema
        self.start_system_loading()
    
    def setup_ui(self):
        """Configurar interfaz principal."""
        self.setWindowTitle(config.ui.window_title)
        self.setGeometry(100, 100, config.ui.window_width, config.ui.window_height)
        
        # Widget central
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Layout principal
        main_layout = QHBoxLayout(central_widget)
        
        # Splitter principal
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        
        # Panel izquierdo - Chat
        left_panel = self.create_chat_panel()
        splitter.addWidget(left_panel)
        
        # Panel derecho - Resultados
        right_panel = self.create_results_panel()
        splitter.addWidget(right_panel)
        
        # Proporciones del splitter
        splitter.setSizes([400, 800])
        
        # Estilos generales
        self.setStyleSheet("""
            QMainWindow {
                background-color: #fafafa;
            }
            QWidget {
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cccccc;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
            }
        """)
    
    def create_chat_panel(self) -> QWidget:
        """Crear panel de chat."""
        panel = QGroupBox("💬 Conversación")
        layout = QVBoxLayout(panel)
        
        # Widget de chat
        self.chat_widget = ChatWidget()
        self.chat_widget.message_sent.connect(self.process_user_message)
        
        layout.addWidget(self.chat_widget)
        
        return panel
    
    def create_results_panel(self) -> QWidget:
        """Crear panel de resultados."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Tabs para resultados
        self.results_tabs = QTabWidget()
        layout.addWidget(self.results_tabs)
        
        # Tab de datos
        self.create_data_tab()
        
        # Tab de SQL
        self.create_sql_tab()
        
        return panel
    
    def create_data_tab(self):
        """Crear tab de datos."""
        data_widget = QWidget()
        layout = QVBoxLayout(data_widget)
        
        # Header con información
        header_layout = QHBoxLayout()
        
        self.results_info_label = QLabel("Sin datos")
        self.results_info_label.setStyleSheet("font-weight: bold; color: #666666;")
        header_layout.addWidget(self.results_info_label)
        
        header_layout.addStretch()
        
        # Botón exportar
        self.export_button = QPushButton(f"{Emojis.EXPORT} Exportar a Excel")
        self.export_button.clicked.connect(self.export_current_results)
        self.export_button.setEnabled(False)
        header_layout.addWidget(self.export_button)
        
        layout.addLayout(header_layout)
        
        # Tabla de resultados
        self.results_table = ResultsTable()
        layout.addWidget(self.results_table)
        
        self.results_tabs.addTab(data_widget, f"{Emojis.ANALYSIS} Datos")
    
    def create_sql_tab(self):
        """Crear tab de SQL."""
        sql_widget = QWidget()
        layout = QVBoxLayout(sql_widget)
        
        # Área de SQL
        self.sql_display = QTextEdit()
        self.sql_display.setReadOnly(True)
        self.sql_display.setMaximumHeight(200)
        self.sql_display.setPlaceholderText("El SQL generado aparecerá aquí...")
        
        self.sql_display.setStyleSheet("""
            QTextEdit {
                background-color: #f8f8f8;
                border: 1px solid #cccccc;
                border-radius: 5px;
                padding: 10px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
            }
        """)
        
        layout.addWidget(QLabel("Consulta SQL generada:"))
        layout.addWidget(self.sql_display)
        
        layout.addStretch()
        
        self.results_tabs.addTab(sql_widget, f"{Emojis.DATABASE} SQL")
    
    def setup_menu_bar(self):
        """Configurar barra de menú."""
        menubar = self.menuBar()
        
        # Menú Archivo
        file_menu = menubar.addMenu("Archivo")
        
        export_action = QAction("Exportar resultados...", self)
        export_action.triggered.connect(self.export_current_results)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Salir", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Menú Herramientas
        tools_menu = menubar.addMenu("Herramientas")
        
        refresh_schema_action = QAction("Actualizar esquema", self)
        refresh_schema_action.triggered.connect(self.refresh_schema)
        tools_menu.addAction(refresh_schema_action)
        
        # Menú Ayuda
        help_menu = menubar.addMenu("Ayuda")
        
        about_action = QAction("Acerca de...", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def setup_status_bar(self):
        """Configurar barra de estado."""
        self.status_bar = self.statusBar()
        
        # Etiqueta de conexión
        self.connection_label = QLabel(f"{Emojis.DISCONNECTED} Desconectado")
        self.status_bar.addWidget(self.connection_label)
        
        # Etiqueta de esquema
        self.schema_label = QLabel("Esquema: No cargado")
        self.status_bar.addPermanentWidget(self.schema_label)
    
    def start_system_loading(self):
        """Iniciar carga del sistema."""
        self.loading_worker = LoadingWorker()
        self.loading_worker.progress_updated.connect(self.update_loading_progress)
        self.loading_worker.schema_loaded.connect(self.on_schema_loaded)
        self.loading_worker.error_occurred.connect(self.on_loading_error)
        self.loading_worker.start()
        
        # Deshabilitar interfaz durante carga
        self.chat_widget.setEnabled(False)
        
        # Mostrar progreso inicial
        self.chat_widget.add_system_message("Iniciando sistema...")
    
    def update_loading_progress(self, message: str):
        """Actualizar progreso de carga."""
        self.chat_widget.add_system_message(message)
        self.status_bar.showMessage(message)
    
    def on_schema_loaded(self, schema_data: dict):
        """Manejar esquema cargado."""
        self.schema_loaded = True
        stats = schema_data.get('stats', {})
        
        # Actualizar UI
        self.connection_label.setText(f"{Emojis.CONNECTED} Conectado")
        self.connection_label.setStyleSheet("color: green;")
        
        active_tables = stats.get('active_tables', 0)
        total_tables = stats.get('total_tables', 0)
        self.schema_label.setText(f"Esquema: {active_tables}/{total_tables} tablas activas")
        
        # Habilitar interfaz
        self.chat_widget.setEnabled(True)
        
        # Iniciar sesión de chat
        self.session_id = ai_assistant.start_session()
        
        # Mensaje final
        final_message = f"Sistema listo. {active_tables} tablas activas identificadas."
        self.status_bar.showMessage(final_message)
    
    def on_loading_error(self, error_message: str):
        """Manejar error de carga."""
        self.chat_widget.add_system_message(f"❌ Error: {error_message}")
        self.status_bar.showMessage(f"Error: {error_message}")
        
        # Mostrar dialog de error
        QMessageBox.critical(self, "Error del Sistema", 
                           f"No se pudo inicializar el sistema:\n\n{error_message}\n\n"
                           "Verifica la configuración de la base de datos.")
    
    def process_user_message(self, message: str):
        """Procesar mensaje del usuario."""
        if not self.schema_loaded:
            self.chat_widget.add_system_message("Sistema aún cargando. Espera un momento...")
            return
        
        # Deshabilitar entrada durante procesamiento
        self.chat_widget.setEnabled(False)
        self.status_bar.showMessage(f"{Emojis.SEARCH} Procesando consulta...")
        
        # Iniciar worker
        self.query_worker = QueryWorker(message, self.session_id)
        self.query_worker.response_ready.connect(self.on_ai_response)
        self.query_worker.error_occurred.connect(self.on_query_error)
        self.query_worker.start()
    
    def on_ai_response(self, response: AIResponse):
        """Manejar respuesta de IA."""
        # Agregar respuesta al chat
        self.chat_widget.add_ai_message(response.message)
        
        # Agregar sugerencias si las hay
        if response.suggested_actions:
            self.chat_widget.add_suggestions(response.suggested_actions)
        
        # Si hay SQL generado, mostrarlo
        if response.sql_generated:
            self.sql_display.setText(response.sql_generated)
            
            # Si la query ya fue ejecutada, mostrar resultados
            if not response.needs_execution and hasattr(self.query_worker, 'query_result'):
                # Esto requeriría modificar el worker para incluir resultados
                pass
        
        # Habilitar interfaz
        self.chat_widget.setEnabled(True)
        self.status_bar.showMessage("Listo")
    
    def on_query_error(self, error_message: str):
        """Manejar error de consulta."""
        self.chat_widget.add_system_message(f"❌ Error: {error_message}")
        
        # Habilitar interfaz
        self.chat_widget.setEnabled(True)
        self.status_bar.showMessage("Error en consulta")
    
    def export_current_results(self):
        """Exportar resultados actuales."""
        if not self.current_query_result:
            QMessageBox.information(self, "Sin datos", "No hay resultados para exportar.")
            return
        
        # Diálogo de selección de archivo
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar reporte",
            f"reporte_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            "Archivos Excel (*.xlsx);;Archivos CSV (*.csv)"
        )
        
        if file_path:
            try:
                # Determinar formato
                export_format = 'xlsx' if file_path.endswith('.xlsx') else 'csv'
                
                # Exportar
                report_generator.export_query_result(
                    self.current_query_result, 
                    export_format, 
                    file_path
                )
                
                QMessageBox.information(
                    self, 
                    "Exportación completa", 
                    f"Archivo guardado exitosamente:\n{file_path}"
                )
                
            except Exception as e:
                QMessageBox.critical(
                    self, 
                    "Error de exportación", 
                    f"No se pudo exportar el archivo:\n{str(e)}"
                )
    
    def refresh_schema(self):
        """Actualizar esquema."""
        if self.loading_worker and self.loading_worker.isRunning():
            QMessageBox.information(self, "Sistema ocupado", "El sistema ya está cargando.")
            return
        
        self.schema_loaded = False
        self.start_system_loading()
    
    def show_about(self):
        """Mostrar información sobre la aplicación."""
        QMessageBox.about(
            self,
            "Acerca de Firebird AI Assistant",
            f"""
            <h3>Firebird AI Assistant v1.0</h3>
            <p>Sistema inteligente para consulta de bases de datos Firebird usando IA conversacional.</p>
            
            <p><b>Características:</b></p>
            <ul>
            <li>Consultas en lenguaje natural</li>
            <li>Generación automática de SQL</li>
            <li>Análisis inteligente de resultados</li>
            <li>Exportación a Excel y CSV</li>
            <li>Sistema RAG para identificación de tablas</li>
            </ul>
            
            <p><b>Configuración actual:</b></p>
            <ul>
            <li>Base de datos: {config.database.database_path}</li>
            <li>Tablas activas: {self.schema_label.text().split(':')[1] if ':' in self.schema_label.text() else 'No disponible'}</li>
            </ul>
            """
        )
    
    def closeEvent(self, event):
        """Manejar cierre de la aplicación."""
        # Detener workers si están corriendo
        if self.loading_worker and self.loading_worker.isRunning():
            self.loading_worker.quit()
            self.loading_worker.wait()
        
        if self.query_worker and self.query_worker.isRunning():
            self.query_worker.quit()
            self.query_worker.wait()
        
        # Cerrar conexiones
        try:
            db.close()
        except:
            pass
        
        event.accept()


def main():
    """Función principal de la UI."""
    # Crear aplicación
    app = QApplication(sys.argv)
    
    # Configurar aplicación
    app.setApplicationName("Firebird AI Assistant")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("AI Database Solutions")
    
    # Configurar estilo
    app.setStyle("Fusion")
    
    # Crear y mostrar ventana principal
    window = MainWindow()
    window.show()
    
    # Ejecutar aplicación
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())