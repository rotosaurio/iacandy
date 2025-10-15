// ============================================
// Cadnymart Data Assistant - Cliente Optimizado
// ============================================

// Variables globales
let socket = null;
let sessionId = null;
let systemInitialized = false;
let currentTables = [];
let filteredTables = [];
let initTriggered = false;
let searchDebounceTimer = null;
let currentCategory = 'all'; // Nueva variable para filtrado por categoría
let recentQueries = []; // Historial de consultas recientes
let suggestedQueries = []; // Consultas sugeridas basadas en patrones
let lastMessage = ''; // Último mensaje enviado para reintento
let schemaLastUpdate = null; // Timestamp de última actualización de esquema
let autoUpdateInterval = null; // Intervalo para auto-actualización

// ============================================
// Inicialización
// ============================================

document.addEventListener('DOMContentLoaded', function() {
    // Generar ID de sesión único
    sessionId = generateUUID();

    // Cargar tema guardado
    loadTheme();

    // Cargar historial de consultas
    loadQueryHistory();

    // Conectar WebSocket
    connectWebSocket();

    // Verificar estado del sistema y auto-inicializar
    setTimeout(() => {
        checkSystemStatus();
    }, 500);

    // Event listeners
    setupEventListeners();

    // Actualizar consultas sugeridas periódicamente
    setInterval(updateSuggestedQueries, 30000); // Cada 30 segundos

    // NO auto-actualizar estadísticas al inicio
    // Solo programar actualizaciones periódicas sin ejecutar inmediatamente
    // startAutoUpdateSchedule(); // DESHABILITADO: causaba actualizaciones innecesarias al recargar
});

// Generar UUID
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// ============================================
// WebSocket
// ============================================

function connectWebSocket() {
    try {
    socket = io();

    socket.on('connect', function() {
        console.log('WebSocket conectado');
        updateStatus('Conectado', 'success');
    });

    socket.on('disconnect', function() {
        console.log('WebSocket desconectado');
        updateStatus('Desconectado', 'danger');
    });

    socket.on('status_update', function(data) {
        console.log('Estado actualizado:', data);
            showNotification(data.message, data.type || 'info');
    });
    } catch (error) {
        console.error('Error conectando WebSocket:', error);
    }
}

// ============================================
// Event Listeners
// ============================================

function setupEventListeners() {
    const messageInput = document.getElementById('messageInput');
    const inputArea = document.querySelector('.input-area');

    // Textarea auto-resize y eventos
    if (messageInput) {
        messageInput.addEventListener('input', function() {
            updateCharCount();
            autoResize(this);
        });

        messageInput.addEventListener('keydown', function(e) {
            // Ctrl+Enter o Cmd+Enter para enviar
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                sendMessage();
            }
        });
    }

    // Click en el área de entrada enfoca el textarea (evita zonas muertas)
    if (inputArea && messageInput) {
        inputArea.addEventListener('click', (e) => {
            // Evitar que botones reciban foco primero
            if (e.target && e.target.closest('#sendButton')) return;
            messageInput.focus();
        });
    }


}

// Auto-resize del textarea
function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 150) + 'px';
}

// Actualizar contador de caracteres
function updateCharCount() {
    const messageInput = document.getElementById('messageInput');
    const charCount = document.getElementById('charCount');

    if (messageInput && charCount) {
        const count = messageInput.value.length;
        charCount.textContent = `${count} caracteres`;

        if (count > 500) {
            charCount.classList.add('text-warning');
        } else {
            charCount.classList.remove('text-warning');
        }
    }
}

// ============================================
// Tema (Dark Mode)
// ============================================

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);

    // Actualizar icono del botón
    const icon = document.querySelector('#toggleTheme i');
    if (icon) {
        icon.className = newTheme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-stars-fill';
    }

    showNotification(`Tema ${newTheme === 'dark' ? 'oscuro' : 'claro'} activado`, 'success');
}

function loadTheme() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);

    const icon = document.querySelector('#toggleTheme i');
    if (icon) {
        icon.className = savedTheme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-stars-fill';
    }
}


// ============================================
// Limpiar Chat
// ============================================

function clearChat() {
    const messagesDiv = document.getElementById('messages');
    const welcomeMessage = document.getElementById('welcomeMessage');

    if (confirm('¿Estás seguro de que quieres limpiar el historial de chat?')) {
        if (messagesDiv) {
            messagesDiv.innerHTML = '';
            messagesDiv.style.display = 'none';
        }

        if (welcomeMessage) {
            welcomeMessage.style.display = 'block';
        }

        showNotification('Chat limpiado', 'success');
    }
}

// ============================================
// Sistema de Estado
// ============================================

async function checkSystemStatus() {
    try {
        const response = await axios.get('/api/status');
        const data = response.data;

        console.log('Estado del sistema:', data);

        if (data.initialized) {
            systemInitialized = true;
            onSystemInitialized(data);
        } else {
            console.log('Sistema no inicializado, intentando inicializar...');
            updateStatus('Conectando...', 'warning');

            const initBtn = document.getElementById('initButton');
            if (initBtn) initBtn.style.display = 'inline-block';

            if (!initTriggered) {
                initTriggered = true;
                initializeSystem();
            } else {
                setTimeout(() => {
                    checkSystemStatus();
                }, 2000);
            }
        }
    } catch (error) {
        console.error('Error verificando estado del sistema:', error);
        updateStatus('Error de conexión', 'danger');

        // Mostrar botón de inicialización en caso de error
        const initBtn = document.getElementById('initButton');
        if (initBtn) {
            initBtn.style.display = 'inline-block';
            initBtn.classList.remove('hidden');
        }
    }
}

async function initializeSystem() {
    try {
        showNotification('🍬 Inicializando Cadnymart AI...', 'info');

        const initBtn = document.getElementById('initButton');
        if (initBtn) {
            initBtn.disabled = true;
            initBtn.innerHTML = '<i class="bi bi-gear animate-spin"></i> Inicializando...';
        }

        const response = await axios.post('/api/initialize', {}, {
            timeout: 30000, // 30 segundos timeout para inicialización
            onDownloadProgress: (progressEvent) => {
                console.log('Progreso de inicialización:', progressEvent);
            }
        });

        const data = response.data;

        if (data.status === 'initialized' || data.status === 'already_initialized') {
            systemInitialized = true;
            onSystemInitialized(data);

            const timeMsg = data.initialization_time ? ` en ${data.initialization_time.toFixed(1)}s` : '';
            showNotification(`✅ ¡Sistema listo${timeMsg}! Ya puedes hacer consultas`, 'success');

            // Ocultar botón después de inicialización exitosa
            if (initBtn) {
                initBtn.style.display = 'none';
            }

            // Si es esquema básico, mostrar que embeddings se están procesando
            if (data.is_basic_schema) {
                showNotification('🔄 Procesando embeddings avanzados en segundo plano...', 'info');
            }
        }
    } catch (error) {
        console.error('Error inicializando sistema:', error);

        let errorMessage = '❌ Error al inicializar el sistema.';
        if (error.code === 'ECONNABORTED') {
            errorMessage = '⏱️ La inicialización tardó demasiado tiempo. Puede que el esquema sea muy grande.';
        } else if (error.response && error.response.data && error.response.data.error) {
            errorMessage += ' ' + error.response.data.error;
        } else if (error.message) {
            errorMessage += ' Detalles: ' + error.message;
        }

        showNotification(errorMessage, 'danger');

        const initBtn = document.getElementById('initButton');
        if (initBtn) {
            initBtn.disabled = false;
            initBtn.innerHTML = '<i class="bi bi-plug"></i>';
        }
    }
}

function onSystemInitialized(data) {
    console.log('Sistema inicializado:', data);

    // Habilitar controles
    const messageInput = document.getElementById('messageInput');
    const sendButton = document.getElementById('sendButton');
    const clearChatBtn = document.getElementById('clearChat');

    if (messageInput) {
        messageInput.disabled = false;
        messageInput.placeholder = 'Escribe tu consulta... (Ctrl+Enter para enviar)';
        messageInput.focus();
    }
    if (sendButton) sendButton.disabled = false;
    if (clearChatBtn) clearChatBtn.disabled = false;

    // Ocultar botón de inicializar
    const initBtn = document.getElementById('initButton');
    if (initBtn) initBtn.style.display = 'none';

    // Actualizar estado con información de tablas
    const tableCount = data.schema?.stats?.active_tables || 'múltiples';
    updateStatus(`Sistema Listo (${tableCount} tablas)`, 'success');

    // Actualizar badge del navbar
    const statusBadge = document.getElementById('statusBadge');
    if (statusBadge) {
        statusBadge.innerHTML = `<i class="bi bi-check-circle-fill"></i> <span class="d-none d-sm-inline">Sistema Listo (${tableCount} tablas)</span>`;
        statusBadge.className = 'badge bg-success text-white';
    }


    // Actualizar estadísticas
    if (data.schema && data.schema.stats) {
        updateSchemaStats(data.schema.stats);
    }

    showNotification('✅ Sistema listo para recibir consultas', 'success');
}

// ============================================
// ============================================
// Gestión de Historial y Personalización
// ============================================

function loadQueryHistory() {
    try {
        const saved = localStorage.getItem('cadnymart_query_history');
        if (saved) {
            recentQueries = JSON.parse(saved);
        }
    } catch (error) {
        console.error('Error cargando historial de consultas:', error);
        recentQueries = [];
    }
}

function saveQueryHistory() {
    try {
        localStorage.setItem('cadnymart_query_history', JSON.stringify(recentQueries));
    } catch (error) {
        console.error('Error guardando historial de consultas:', error);
    }
}

function addQueryToHistory(query) {
    if (!query || query.trim().length === 0) return;

    // Remover si ya existe
    recentQueries = recentQueries.filter(q => q.text !== query);

    // Agregar al inicio
    recentQueries.unshift({
        text: query,
        timestamp: Date.now(),
        category: currentCategory
    });

    // Mantener solo las últimas 10 consultas
    if (recentQueries.length > 10) {
        recentQueries = recentQueries.slice(0, 10);
    }

    saveQueryHistory();
    updateSuggestedQueries();
}

function updateSuggestedQueries() {
    // Generar sugerencias basadas en patrones de uso
    const suggestions = [];

    // Sugerencias basadas en consultas recientes
    if (recentQueries.length > 0) {
        const lastQuery = recentQueries[0];

        // Sugerencias relacionadas con ventas
        if (lastQuery.text.toLowerCase().includes('venta') ||
            lastQuery.text.toLowerCase().includes('sale')) {
            suggestions.push({
                text: "¿Cuáles son nuestros productos más vendidos esta semana?",
                icon: "bi-star-fill",
                reason: "Relacionado con tu consulta anterior sobre ventas"
            });
        }

        // Sugerencias relacionadas con inventario
        if (lastQuery.text.toLowerCase().includes('inventar') ||
            lastQuery.text.toLowerCase().includes('stock')) {
            suggestions.push({
                text: "Muestra productos con stock crítico (menos de 10 unidades)",
                icon: "bi-exclamation-triangle",
                reason: "Para mantener el control de inventario"
            });
        }

        // Sugerencias relacionadas con clientes
        if (lastQuery.text.toLowerCase().includes('cliente') ||
            lastQuery.text.toLowerCase().includes('customer')) {
            suggestions.push({
                text: "Lista los 5 clientes con más compras este mes",
                icon: "bi-trophy",
                reason: "Análisis de clientes importantes"
            });
        }
    }

    // Sugerencias contextuales basadas en la hora del día
    const hour = new Date().getHours();
    if (hour >= 6 && hour < 12) {
        suggestions.push({
            text: "Resumen de ventas de la mañana",
            icon: "bi-sunrise",
            reason: "Información matutina"
        });
    } else if (hour >= 18 && hour < 22) {
        suggestions.push({
            text: "Cierre de caja del día",
            icon: "bi-moon-stars",
            reason: "Preparación para el cierre"
        });
    }

    suggestedQueries = suggestions.slice(0, 3); // Máximo 3 sugerencias

    // Actualizar la interfaz si estamos en la pantalla de bienvenida
    updateSuggestionsDisplay();
}

function getSuggestedQueriesHTML() {
    if (suggestedQueries.length === 0) return '';

    let html = '<div class="suggested-queries mt-3"><h6><i class="bi bi-lightbulb"></i> Sugerencias para ti:</h6>';
    suggestedQueries.forEach(suggestion => {
        html += `
            <div class="suggestion-card" onclick="useSuggestion('${suggestion.text.replace(/'/g, "\\'")}')">
                <i class="bi ${suggestion.icon}"></i>
                <div class="suggestion-content">
                    <div class="suggestion-text">${suggestion.text}</div>
                    <small class="suggestion-reason text-muted">${suggestion.reason}</small>
                </div>
            </div>
        `;
    });
    html += '</div>';
    return html;
}

function useSuggestion(query) {
    const input = document.getElementById('messageInput');
    if (input) {
        input.value = query;
        input.focus();
        updateCharCount();
        autoResize(input);
    }
}

function updateSuggestionsDisplay() {
    const container = document.getElementById('suggestionsContainer');
    const welcomeMessage = document.getElementById('welcomeMessage');

    if (!container || !welcomeMessage || welcomeMessage.style.display === 'none') {
        return; // No mostrar sugerencias si ya no estamos en la pantalla de bienvenida
    }

    container.innerHTML = getSuggestedQueriesHTML();
}

function retryLastMessage() {
    if (lastMessage && systemInitialized) {
        console.log('Reintentando último mensaje:', lastMessage);
        // Crear un evento sintético para enviar el mensaje
        const input = document.getElementById('messageInput');
        if (input) {
            input.value = lastMessage;
            updateCharCount();
            autoResize(input);
            sendMessage();
        }
    } else {
        showNotification('⚠️ No hay ningún mensaje para reintentar o el sistema no está listo', 'warning');
    }
}

// Función para probar el scroll (útil para debugging)
function testScroll() {
    const chatContainer = document.getElementById('chatContainer');
    if (chatContainer) {
        console.log('Chat container scrollHeight:', chatContainer.scrollHeight);
        console.log('Chat container clientHeight:', chatContainer.clientHeight);
        console.log('Can scroll:', chatContainer.scrollHeight > chatContainer.clientHeight);
    }
}

function showHelp() {
    const helpModal = new bootstrap.Modal(document.getElementById('helpModal'));
    helpModal.show();
}

async function showTableDetails(tableName) {
    try {
        const response = await axios.get(`/api/schema/table/${tableName}`);
        const table = response.data;

        document.getElementById('tableModalTitle').innerHTML =
            `<i class="bi bi-table"></i> ${escapeHtml(table.name)}`;

        let columnsHtml = '';
        (table.columns || []).forEach(col => {
            columnsHtml += `
                <tr>
                    <td><strong>${escapeHtml(col.name)}</strong></td>
                    <td><span class="badge bg-secondary">${escapeHtml(col.type)}</span></td>
                    <td>${col.nullable ? '<span class="text-success">Sí</span>' : '<span class="text-danger">No</span>'}</td>
                    <td>${col.default_value ? escapeHtml(col.default_value) : '<span class="text-muted">-</span>'}</td>
                </tr>
            `;
        });

        document.getElementById('tableModalBody').innerHTML = `
            <div class="mb-4 p-3 bg-light rounded">
                <div class="row">
                    <div class="col-md-6">
                        <strong><i class="bi bi-info-circle"></i> Tipo:</strong> ${escapeHtml(table.type)}
                    </div>
                    <div class="col-md-6">
                        <strong><i class="bi bi-hash"></i> Registros:</strong> ${formatNumber(table.row_count)}
                    </div>
                </div>
            </div>

            <h6 class="mb-3">
                <i class="bi bi-list-columns-reverse"></i> 
                Columnas (${table.columns.length})
            </h6>
            <div class="table-responsive">
                <table class="table table-sm table-hover">
                    <thead class="table-primary">
                        <tr>
                            <th>Nombre</th>
                            <th>Tipo</th>
                            <th>Nullable</th>
                            <th>Por defecto</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${columnsHtml}
                    </tbody>
                </table>
            </div>

            ${table.primary_keys && table.primary_keys.length > 0 ? `
                <h6 class="mt-4 mb-2">
                    <i class="bi bi-key-fill text-warning"></i> Llaves Primarias
                </h6>
                <div class="alert alert-warning">
                    <code>${table.primary_keys.join(', ')}</code>
                </div>
            ` : ''}

            ${table.foreign_keys && table.foreign_keys.length > 0 ? `
                <h6 class="mt-4 mb-2">
                    <i class="bi bi-arrow-left-right text-primary"></i> Llaves Foráneas (${table.foreign_keys.length})
                </h6>
                <div class="table-responsive">
                    <table class="table table-sm table-hover">
                        <thead class="table-light">
                            <tr>
                                <th>Campo Local</th>
                                <th>Tabla Referenciada</th>
                                <th>Campo Referenciado</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${table.foreign_keys.map(fk => `
                                <tr>
                                    <td><code class="text-primary">${escapeHtml(fk.column)}</code></td>
                                    <td>
                                        <i class="bi bi-table text-muted"></i>
                                        <strong>${escapeHtml(fk.referenced_table)}</strong>
                                    </td>
                                    <td><code class="text-success">${escapeHtml(fk.referenced_column)}</code></td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            ` : ''}

            ${table.indexes && table.indexes.length > 0 ? `
                <h6 class="mt-4 mb-2">
                    <i class="bi bi-lightning-fill text-info"></i> Índices (${table.indexes.length})
                </h6>
                <div class="d-flex flex-wrap gap-2">
                    ${table.indexes.slice(0, 10).map(idx => `
                        <span class="badge ${idx.unique_flag ? 'bg-success' : 'bg-info'}" title="${idx.unique_flag ? 'Índice único' : 'Índice normal'}">
                            <i class="bi bi-${idx.unique_flag ? 'star-fill' : 'list'}"></i>
                            ${escapeHtml(idx.name)}
                        </span>
                    `).join('')}
                    ${table.indexes.length > 10 ? `
                        <span class="badge bg-secondary">
                            +${table.indexes.length - 10} más...
                        </span>
                    ` : ''}
                </div>
            ` : ''}
        `;

        new bootstrap.Modal(document.getElementById('tableModal')).show();

    } catch (error) {
        console.error('Error cargando detalles de tabla:', error);
        showNotification('Error al cargar detalles de la tabla', 'danger');
    }
}

// ============================================
// Ejemplos de Consultas
// ============================================

function useExample(element) {
    const query = element.getAttribute('data-query');
    const messageInput = document.getElementById('messageInput');

    if (messageInput && query) {
        messageInput.value = query;
        updateCharCount();
        autoResize(messageInput);
        messageInput.focus();

        // Si el sistema está listo, enviar automáticamente
        if (systemInitialized) {
            setTimeout(() => {
                sendMessage();
            }, 300);
        }
    }
}

// ============================================
// Chat
// ============================================

async function sendMessage() {
    console.log('🎯 [sendMessage] Función llamada');

    const input = document.getElementById('messageInput');
    const sendButton = document.getElementById('sendButton');
    const message = input.value.trim();

    console.log('📝 [sendMessage] Mensaje:', message ? `"${message}" (${message.length} chars)` : 'VACÍO');

    if (!message) {
        console.warn('⚠️ [sendMessage] Mensaje vacío, abortando');
        input.focus();
        return;
    }

    // Guardar mensaje para posible reintento
    lastMessage = message;

    // Agregar consulta al historial
    addQueryToHistory(message);

    console.log('🔍 [sendMessage] Estado del sistema:', {
        systemInitialized,
        online: navigator.onLine,
        sessionId
    });

    if (!systemInitialized) {
        console.warn('⚠️ [sendMessage] Sistema no inicializado');
        showNotification('🍬 El sistema se está inicializando... Espera un momento antes de enviar consultas.', 'info');
        return;
    }

    // Verificación adicional: asegurarse de que el backend esté respondiendo
    if (!navigator.onLine) {
        console.warn('⚠️ [sendMessage] Sin conexión a internet');
        showNotification('🌐 Sin conexión a internet. Verifica tu conexión.', 'warning');
        return;
    }

    // Ocultar mensaje de bienvenida
    const welcomeMessage = document.getElementById('welcomeMessage');
    const messagesDiv = document.getElementById('messages');
    if (welcomeMessage && welcomeMessage.style.display !== 'none') {
        console.log('👋 [sendMessage] Ocultando mensaje de bienvenida');
        welcomeMessage.style.display = 'none';
        messagesDiv.style.display = 'block';
    }

    // Deshabilitar controles
    console.log('🔒 [sendMessage] Deshabilitando controles');
    input.disabled = true;
    if (sendButton) {
        sendButton.disabled = true;
        sendButton.innerHTML = '<div class="flex items-center gap-2"><div class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div> <span class="d-none d-sm-inline">Enviando...</span></div>';
    }

    // Agregar mensaje del usuario
    console.log('💬 [sendMessage] Agregando mensaje a la UI');
    addMessage('user', message);

    // Limpiar input
    input.value = '';
    updateCharCount();
    autoResize(input);

    // Mostrar indicador de escritura
    const typingId = addTypingIndicator();

    try {
        console.log(`🚀 [sendMessage] Enviando consulta al backend (${message.length} chars, sin timeout):`, message);

        const response = await axios.post('/api/chat', {
            message: message,
            session_id: sessionId
        }, {
            // SIN timeout - esperar lo que sea necesario
            timeout: 0,
            onDownloadProgress: (progressEvent) => {
                // Actualizar indicador de progreso si es posible
                console.log('Progreso de descarga:', progressEvent);
            }
        });

        const data = response.data;
        console.log('✅ [sendMessage] Respuesta recibida del backend:', {
            message: data.message?.substring(0, 100) + '...',
            has_data: data.has_data,
            sql_query: data.sql_query ? 'Sí' : 'No',
            timestamp: data.timestamp
        });

        // Remover indicador de escritura
        removeTypingIndicator(typingId);

        // Agregar respuesta del asistente
        addAssistantMessage(data);

    } catch (error) {
        console.error('❌ [sendMessage] Error enviando mensaje:', error);
        console.error('❌ [sendMessage] Detalles del error:', {
            message: error.message,
            code: error.code,
            status: error.response?.status,
            data: error.response?.data
        });
        removeTypingIndicator(typingId);

        let errorMessage = '❌ Error al procesar la consulta.';
        let canRetry = true;

        if (error.response) {
            // Error del servidor
            if (error.response.status === 503) {
                errorMessage = '🔧 El sistema no está completamente inicializado. Espera un momento o recarga la página.';
                canRetry = false;
            } else if (error.response.status === 500) {
                errorMessage = '💥 Error interno del servidor. Esto puede deberse a una consulta muy compleja.';
            } else if (error.response.data && error.response.data.error) {
                errorMessage += '\n\n' + error.response.data.error;
            }
        } else if (error.code === 'ECONNABORTED') {
            errorMessage = '⏱️ La consulta tardó demasiado tiempo. Intenta con una consulta más específica o divide tu pregunta en partes más pequeñas.';
        } else if (error.code === 'NETWORK_ERROR' || error.message.includes('Network')) {
            errorMessage = '🌐 Error de conexión. Verifica tu conexión a internet e intenta nuevamente.';
            canRetry = true;
        } else if (error.message) {
            errorMessage += '\n\nDetalles técnicos: ' + error.message;
        }

        // Agregar botón de reintentar si es posible
        if (canRetry) {
            errorMessage += '\n\n💡 <button class="btn-retry" onclick="retryLastMessage()">Intentar nuevamente</button>';
        }

        addMessage('assistant', errorMessage);
    } finally {
        // Habilitar controles
        console.log('🔓 [sendMessage] Habilitando controles');
        input.disabled = false;
        if (sendButton) {
            sendButton.disabled = false;
            sendButton.innerHTML = '<i class="bi bi-send-fill text-lg"></i>';
        }
        input.focus();
        console.log('✅ [sendMessage] Función completada');
    }
}

function addMessage(type, content) {
    const messagesDiv = document.getElementById('messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;

    const time = new Date().toLocaleTimeString('es-ES', {
        hour: '2-digit',
        minute: '2-digit'
    });

    messageDiv.innerHTML = `
        <div class="message-content">
            ${escapeHtml(content).replace(/\n/g, '<br>')}
        </div>
        <div class="message-time">${time}</div>
    `;

    messagesDiv.appendChild(messageDiv);
    scrollToBottom();
}

function addAssistantMessage(data) {
    const messagesDiv = document.getElementById('messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant';

    const time = new Date().toLocaleTimeString('es-ES', {
        hour: '2-digit',
        minute: '2-digit'
    });

    let contentHtml = `<div class="message-content">${escapeHtml(data.message || '').replace(/\n/g, '<br>')}</div>`;

    // Agregar SQL si existe
    if (data.sql_query) {
        contentHtml += `
            <div class="sql-query">
                <pre><code class="language-sql">${escapeHtml(data.sql_query)}</code></pre>
            </div>
        `;
    }

    // Agregar tabla de datos si existe
    if (data.has_data && data.data) {
        contentHtml += renderDataTable(data.data);

        // Agregar botones de exportación
        contentHtml += `
            <div class="export-buttons">
                <button class="btn" onclick="exportData('excel')">
                    <i class="bi bi-file-earmark-excel"></i> Excel
                </button>
                <button class="btn" onclick="exportData('csv')">
                    <i class="bi bi-file-earmark-text"></i> CSV
                </button>
                <button class="btn" onclick="exportData('json')">
                    <i class="bi bi-filetype-json"></i> JSON
                </button>
            </div>
        `;
    }

    messageDiv.innerHTML = contentHtml + `<div class="message-time">${time}</div>`;

    messagesDiv.appendChild(messageDiv);
    scrollToBottom();

    // Resaltar sintaxis SQL
    if (data.sql_query && typeof Prism !== 'undefined') {
        Prism.highlightAll();
    }
}

function renderDataTable(data) {
    if (!data.columns || data.columns.length === 0) {
        return '<p class="text-muted mt-2">No hay datos para mostrar</p>';
    }

    let html = `
        <div class="data-table">
            <table class="table table-sm">
                <thead>
                    <tr>
    `;

    // Headers
    data.columns.forEach(col => {
        html += `<th>${escapeHtml(col)}</th>`;
    });

    html += `
                    </tr>
                </thead>
                <tbody>
    `;

    // Rows
    (data.rows || []).forEach(row => {
        html += '<tr>';
        row.forEach(cell => {
            if (cell === null || cell === undefined) {
                html += '<td><span class="text-muted">null</span></td>';
            } else {
                html += `<td>${escapeHtml(String(cell))}</td>`;
            }
        });
        html += '</tr>';
    });

    html += `
                </tbody>
            </table>
        </div>
    `;

    if (data.truncated) {
        html += `
            <div class="alert alert-info mt-2">
                <small>
                    <i class="bi bi-info-circle"></i>
                    Mostrando ${data.preview_rows} de ${formatNumber(data.total_rows)} registros.
                    Usa los botones de exportación para obtener todos los datos.
                </small>
            </div>
        `;
    }

    return html;
}

function addTypingIndicator() {
    const messagesDiv = document.getElementById('messages');
    const typingDiv = document.createElement('div');
    const typingId = 'typing-' + Date.now();
    typingDiv.id = typingId;
    typingDiv.className = 'message assistant';
    typingDiv.innerHTML = `
        <div class="message-content bg-gradient-to-r from-candy-blue/10 to-candy-purple/10 border-2 border-candy-blue/30">
            <div class="flex items-center gap-3">
                <div class="flex space-x-1">
                    <div class="w-2 h-2 bg-candy-pink rounded-full animate-bounce"></div>
                    <div class="w-2 h-2 bg-candy-purple rounded-full animate-bounce" style="animation-delay: 0.1s;"></div>
                    <div class="w-2 h-2 bg-candy-orange rounded-full animate-bounce" style="animation-delay: 0.2s;"></div>
                </div>
                <span class="text-candy-purple font-medium">🍬 Procesando consulta con IA avanzada...</span>
            </div>
            <div class="mt-2 text-xs text-candy-purple/70">
                Esto puede tomar unos momentos dependiendo de la complejidad de tu consulta
            </div>
        </div>
    `;
    messagesDiv.appendChild(typingDiv);
    scrollToBottom();
    return typingId;
}

function removeTypingIndicator(typingId) {
    const typingDiv = document.getElementById(typingId);
    if (typingDiv) {
        typingDiv.remove();
    }
}

// ============================================
// Exportación
// ============================================

async function exportData(format) {
    try {
        showNotification('⬇️ Preparando exportación...', 'info');

        const response = await axios.post(`/api/export/${format}`, {
            session_id: sessionId
        }, {
            responseType: 'blob',
            timeout: 60000
        });

        // Crear link de descarga
        const url = window.URL.createObjectURL(new Blob([response.data]));
        const link = document.createElement('a');
        link.href = url;

        // Nombre del archivo
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-').split('T')[0];
        let extension = format;
        if (format === 'excel') extension = 'xlsx';

        link.download = `firebird_export_${timestamp}.${extension}`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        
        // Limpiar URL
        setTimeout(() => window.URL.revokeObjectURL(url), 100);

        showNotification('✅ Datos exportados correctamente', 'success');

    } catch (error) {
        console.error('Error exportando datos:', error);
        showNotification('❌ Error al exportar los datos', 'danger');
    }
}

// ============================================
// Modal de Información
// ============================================

async function showInfo() {
    try {
        const response = await axios.get('/api/status');
        const data = response.data;

        let infoHtml = `
            <h6 class="mb-3"><i class="bi bi-server"></i> Estado del Sistema</h6>
            <table class="table table-sm">
                <tr>
                    <td><strong>Base de datos:</strong></td>
                    <td>${data.database.connected ? '<span class="badge bg-success">✅ Conectada</span>' : '<span class="badge bg-danger">❌ Desconectada</span>'}</td>
                </tr>
                <tr>
                    <td><strong>Ruta BD:</strong></td>
                    <td><small><code>${escapeHtml(data.database.path)}</code></small></td>
                </tr>
                <tr>
                    <td><strong>Modelo IA:</strong></td>
                    <td><span class="badge bg-primary">${escapeHtml(data.ai.model)}</span></td>
                </tr>
                <tr>
                    <td><strong>Proveedor IA:</strong></td>
                    <td>${escapeHtml(data.ai.provider)}</td>
                </tr>
            </table>
        `;

        if (data.schema && data.schema.stats) {
            infoHtml += `
                <h6 class="mt-4 mb-3"><i class="bi bi-diagram-3"></i> Estadísticas del Esquema</h6>
                <table class="table table-sm">
                    <tr>
                        <td><strong>Tablas activas:</strong></td>
                        <td><span class="badge bg-info">${data.schema.stats.active_tables || 0}</span></td>
                    </tr>
                    <tr>
                        <td><strong>Total tablas:</strong></td>
                        <td><span class="badge bg-secondary">${data.schema.stats.total_tables || 0}</span></td>
                    </tr>
                </table>
            `;
        }

        document.getElementById('infoModalBody').innerHTML = infoHtml;
        new bootstrap.Modal(document.getElementById('infoModal')).show();

    } catch (error) {
        console.error('Error obteniendo información:', error);
        showNotification('Error al obtener información del sistema', 'danger');
    }
}

// ============================================
// UI Helpers
// ============================================

function updateStatus(text, type) {
    const badge = document.getElementById('statusBadge');
    if (badge) {
        badge.className = `badge bg-${type} status-badge`;
        badge.innerHTML = `<i class="bi bi-circle-fill"></i> <span class="d-none d-sm-inline">${text}</span>`;
    }
}

function updateSchemaStats(stats) {
    if (!stats) return;

    updateSchemaInfo(stats.active_tables || 0);
}

function showNotification(message, type = 'info') {
    // Mapear tipos a iconos candy
    const icons = {
        'success': '🍬',
        'info': '💡',
        'warning': '⚠️',
        'danger': '❌',
        'error': '🚫'
    };

    const icon = icons[type] || icons.info;

    const alert = document.createElement('div');
    alert.className = `alert alert-${type} alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3 shadow-lg`;
    alert.style.zIndex = '9999';
    alert.style.minWidth = '320px';
    alert.style.maxWidth = '550px';
    alert.style.borderRadius = '12px';
    alert.style.border = '2px solid';
    alert.innerHTML = `
        <div class="d-flex align-items-center">
            <span class="me-2 fs-5">${icon}</span>
            <div class="flex-grow-1">${message}</div>
            <button type="button" class="btn-close ms-2" data-bs-dismiss="alert"></button>
        </div>
    `;

    document.body.appendChild(alert);

    // Auto-remover después de 6 segundos
    setTimeout(() => {
        alert.classList.remove('show');
        setTimeout(() => alert.remove(), 300);
    }, 6000);
}

function scrollToBottom() {
    const chatContainer = document.getElementById('chatContainer');
    if (chatContainer) {
        // Forzar scroll inmediato
        setTimeout(() => {
    chatContainer.scrollTop = chatContainer.scrollHeight;
        }, 100);
        
        // También smooth scroll
        chatContainer.scrollTo({
            top: chatContainer.scrollHeight,
            behavior: 'smooth'
        });
    }
}

// ============================================
// Utilidades
// ============================================

function escapeHtml(text) {
    if (!text) return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return String(text).replace(/[&<>"']/g, m => map[m]);
}

function formatNumber(num) {
    if (num === undefined || num === null) return '0';
    return new Intl.NumberFormat('es-ES').format(num);
}

// ============================================
// Auto-actualización de Estadísticas
// ============================================

function startAutoUpdateSchedule() {
    // Limpiar intervalo anterior si existe
    if (autoUpdateInterval) {
        clearInterval(autoUpdateInterval);
    }
    
    // Programar actualización cada 12 horas (43200000 ms)
    autoUpdateInterval = setInterval(async () => {
        try {
            console.log('🔄 Ejecutando auto-actualización programada de estadísticas...');
            await updateSchemaStats();
        } catch (error) {
            console.error('Error en auto-actualización:', error);
        }
    }, 12 * 60 * 60 * 1000); // 12 horas
    
    console.log('✅ Auto-actualización programada cada 12 horas');
}

async function updateSchemaStats(showNotif = false) {
    try {
        const response = await axios.post('/api/schema/stats/update', {});
        
        if (response.data.updated) {
            schemaLastUpdate = response.data.last_update;
            
            // Actualizar indicador visual
            updateSchemaUpdateStatus();
            
            if (showNotif) {
                showNotification(
                    `📊 Estadísticas actualizadas: ${response.data.total_updated} tablas`,
                    'success'
                );
            }
            
            console.log(`✅ Estadísticas actualizadas: ${response.data.total_updated} tablas`);
            return true;
        }
        
        return false;
    } catch (error) {
        console.error('Error actualizando estadísticas:', error);
        if (showNotif) {
            showNotification('❌ Error actualizando estadísticas', 'danger');
        }
        return false;
    }
}

function updateSchemaUpdateStatus() {
    const statusEl = document.getElementById('schemaUpdateStatus');
    if (statusEl && schemaLastUpdate) {
        const timeAgo = formatTimeAgo(schemaLastUpdate);
        statusEl.innerHTML = `
            <small class="text-muted">
                <i class="bi bi-clock-history"></i> 
                Actualizado ${timeAgo}
            </small>
        `;
    }
}

function formatTimeAgo(isoString) {
    if (!isoString) return 'nunca';
    
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    
    if (diffMins < 1) return 'justo ahora';
    if (diffMins < 60) return `hace ${diffMins} min`;
    if (diffHours < 24) return `hace ${diffHours}h`;
    if (diffDays < 7) return `hace ${diffDays}d`;
    
    return date.toLocaleDateString('es-ES', { 
        year: 'numeric', 
        month: 'short', 
        day: 'numeric' 
    });
}

// Función manual para forzar actualización
async function manualUpdateStats() {
    const updating = await updateSchemaStats(true);
    if (updating) {
        // Reiniciar el timer de auto-actualización
        startAutoUpdateSchedule();
    }
}

// ============================================
// Service Worker (Para PWA - Futuro)
// ============================================

if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        // Descomentar cuando tengamos service worker
        // navigator.serviceWorker.register('/sw.js');
    });
}
