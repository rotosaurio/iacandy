# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Firebird AI Assistant** is a conversational AI system for querying Firebird 3.0 databases using natural language. The system combines OpenAI's GPT models with a RAG (Retrieval-Augmented Generation) architecture to automatically generate SQL queries, execute them, and provide intelligent analysis of results.

### Key Technologies
- **Backend**: Python 3.8+, Firebird 3.0 (via firebird-driver)
- **AI**: OpenAI GPT-4o-mini, ChromaDB for vector storage, sentence-transformers for embeddings
- **Web Interface**: Flask + Flask-SocketIO + eventlet
- **Desktop Interface**: PySide6 (Qt for Python)
- **Data Processing**: pandas, openpyxl, xlsxwriter

## Running the Application

### Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Configure database and API key in config.py
# Edit config.py to set:
#   - database.database_path: Path to your Firebird .FDB file
#   - ai.api_key: Your OpenAI API key
```

### Start Desktop GUI
```bash
python main.py
```

### Start Web Interface
```bash
python app.py
# Access at http://localhost:8050
```

### Alternative Web Start Scripts
```bash
# Windows batch
iniciar_web.bat

# Windows PowerShell
.\iniciar_web.ps1
```

## Architecture

### Core Components

**main.py** - Desktop application entry point
- Initializes all system components (database, schema manager, AI assistant)
- Validates configuration and dependencies
- Launches PySide6 GUI via ui_main.py
- Performs system checks (Python version, disk space, write permissions)

**app.py** - Web server entry point
- Flask-based REST API with WebSocket support (Flask-SocketIO)
- Auto-initializes database connection and schema on startup (background thread)
- Manages user sessions with conversation history
- Endpoints: /api/status, /api/chat, /api/export/{format}, /api/schema/tables

**database.py** - Firebird database abstraction
- Connection pool management (configurable pool size in config.py)
- Schema extraction from Firebird system tables (RDB$RELATIONS, RDB$RELATION_FIELDS, etc.)
- Query execution with safety validation (only SELECT allowed)
- Streaming support for large result sets
- **Important**: Schema loading is optimized to avoid counting rows for all tables upfront (too slow). Row counts are set to -1 and determined on-demand. Active tables are identified using heuristics (foreign keys, column count, naming patterns) instead of row counts.

**schema_manager.py** - RAG system for table identification
- Analyzes all tables in the database and generates semantic descriptions
- Uses sentence-transformers (all-MiniLM-L6-v2) to create embeddings
- Stores embeddings in ChromaDB for similarity search
- **Key workflow**: User query → embedding → vector search → top-k relevant tables → generate SQL
- Caches schema for 30 minutes (configurable via config.rag.cache_ttl_minutes)
- Table descriptions include: inferred purpose, column names/types, relationships, sample data patterns

**ai_assistant.py** - OpenAI-powered conversational AI
- SQLGenerator: Generates Firebird SQL from natural language using GPT
- ResultAnalyzer: Analyzes query results and generates insights
- ConversationManager: Maintains conversation context and history
- Auto-retries failed queries with refinement via OpenAI
- Confidence scoring and reasoning for generated SQL

**ui_main.py** - PySide6 desktop interface
- Chat-based UI with split view (conversation + results)
- Background workers (QThread) for loading schema and executing queries
- Real-time status updates and progress indicators
- Export functionality integrated

**report_generator.py** - Data export with streaming
- StreamingExporter: Handles large datasets with batch processing
- Supports Excel (xlsxwriter), CSV, JSON
- Progress tracking for long-running exports
- Excel styling with headers, formatting, and metadata sheets

**utils.py** - Shared utilities
- Logger: UTF-8 aware logging with rotation
- SQLValidator: Security checks (only SELECT, no dangerous patterns)
- DataFormatter: Number, date, duration formatting
- CacheManager: File-based caching with TTL
- DataAnalyzer: Automatic statistical analysis of DataFrames

**config.py** - Centralized configuration
- Dataclass-based config for all modules (database, AI, RAG, UI, export, security, logging)
- Environment variable overrides (FB_HOST, FB_DATABASE, OPENAI_API_KEY, etc.)
- Creates required directories on initialization

## Important Implementation Details

### Firebird SQL Syntax (Critical for AI Queries)
The AI must generate Firebird 3.0-specific SQL:
- Use `FIRST n` instead of `LIMIT n` for row limiting
- Date functions: `CURRENT_DATE`, `CURRENT_TIMESTAMP`
- Date arithmetic: `WHERE fecha >= CURRENT_DATE - 30` (last 30 days)
- String concatenation: `||` operator
- Data types: INTEGER, VARCHAR(n), DECIMAL(p,s), DATE, TIMESTAMP, BLOB
- No support for common MySQL/PostgreSQL syntax

### Schema Loading Performance
- **Do not** count rows for all tables during initial load (too slow for databases with 500+ tables)
- Use `_is_table_active_quick()` which relies on naming patterns and structure
- Only count rows on-demand when specifically needed
- Active table detection heuristics:
  - Foreign keys presence = active
  - Column count > 5 = likely active
  - Exclude prefixes: OLD_, BAK_, TMP_, TEMP_, TEST_, DEL_, BACKUP_, COPY_
  - Exclude suffixes: _OLD, _BAK, _TMP, _TEMP, _TEST, _DEL, _BACKUP, _COPY

### RAG Table Selection
The system uses semantic similarity to find relevant tables:
1. User query is embedded using sentence-transformers
2. ChromaDB performs cosine similarity search across all table descriptions
3. Top-k tables (default: 5, configurable) above similarity_threshold (default: 0.7) are selected
4. Full table metadata (columns, keys, relationships) is provided to GPT for SQL generation

### Security Constraints
- **Only SELECT queries** are allowed (validated by SQLValidator)
- Prohibited patterns: DROP, DELETE, INSERT, UPDATE, ALTER, CREATE, TRUNCATE, EXEC
- No SQL comments (--), no multiple statements (;)
- No stored procedure calls (xp_, sp_)
- Query timeout enforced (default: 60 seconds in config.security)

### UTF-8 Encoding
The codebase heavily emphasizes UTF-8 handling for Windows compatibility:
- All file I/O uses encoding='utf-8' or 'utf-8-sig' (for CSV BOM)
- stdout/stderr are reconfigured with UTF-8 on Windows
- Logger uses UTF-8 for console and file handlers
- Firebird connections use charset='UTF8'

### Conversation Flow
1. User sends natural language query
2. System determines if SQL generation is needed (keywords: dame, muestra, consulta, total, ventas, etc.)
3. RAG system finds relevant tables via embedding similarity
4. GPT generates SQL with Firebird syntax
5. SQL is validated and executed
6. If error occurs, system attempts SQL refinement and retry
7. Results are analyzed by GPT to generate natural language insights
8. Follow-up suggestions are provided based on results and related tables

### Data Export
- Small datasets (<1000 rows): Use report_generator.create_enhanced_excel_report()
- Large datasets: Use streaming via report_generator.start_streaming_export()
- Excel exports include: data sheet, analysis sheet, metadata sheet
- CSV exports use utf-8-sig for Excel compatibility
- Progress tracking via ExportProgress dataclass

## Common Development Tasks

### Adding a New AI Prompt Template
Edit the system prompts in ai_assistant.py:
- `_build_sql_system_prompt()`: Controls SQL generation behavior
- Update REGLAS DE FIREBIRD and INSTRUCCIONES sections
- Test with representative queries

### Modifying Table Selection Logic
Edit schema_manager.py:
- `_identify_active_tables()`: Change relevance scoring algorithm
- `find_relevant_tables()`: Modify similarity search parameters (top_k, threshold)
- `TableDescriptor.describe_table()`: Enhance semantic descriptions

### Changing Database Schema Caching
Edit config.py:
- `RAGConfig.cache_ttl_minutes`: Cache duration
- Edit schema_manager.py `_is_schema_cache_valid()` for custom invalidation logic

### Adding New Export Formats
Edit report_generator.py:
- Add new method to StreamingExporter class
- Update `ReportGenerator.start_streaming_export()` to handle format
- Add format to SUPPORTED_FORMATS in config.py

### Debugging SQL Generation Issues
1. Check logs in `logs/firebird_ai_assistant.log` for detailed SQL and errors
2. Enable detailed SQL logging: Set config.logging.detailed_sql_logging = True
3. Review generated SQL in ui_main.py SQL tab or check response.sql_generated
4. Test table selection: Call schema_manager.find_relevant_tables("your query")
5. Verify Firebird syntax is correct (FIRST not LIMIT, etc.)

## Configuration Reference

Key config.py settings:
- `database.database_path`: Path to Firebird .FDB file
- `database.connection_pool_size`: Number of concurrent connections (default: 5)
- `ai.api_key`: OpenAI API key (or set OPENAI_API_KEY env var)
- `ai.model`: OpenAI model (default: "gpt-4o-mini")
- `ai.temperature`: Controls randomness (default: 0.1 for deterministic SQL)
- `rag.top_k_tables`: Max tables to consider for each query (default: 5)
- `rag.similarity_threshold`: Minimum cosine similarity (default: 0.7)
- `ui.preview_row_limit`: Max rows to show in UI preview (default: 1000)
- `security.query_timeout_seconds`: Max query execution time (default: 60)
- `export.batch_size`: Rows per batch for streaming exports (default: 5000)

## Testing Workflow

The system has no formal test suite. To test changes:
1. Start with desktop GUI: `python main.py` - watch for initialization errors
2. Test web interface: `python app.py` - verify auto-initialization completes
3. Test natural language queries through UI
4. Check logs for errors: `logs/firebird_ai_assistant.log`
5. Test export functionality with small and large result sets
6. Verify SQL generation with various query types (aggregations, joins, date filters)

## Troubleshooting

**"Schema no cargado" / Schema not loaded**
- Check database path in config.py is correct and file exists
- Verify Firebird connection credentials (username/password)
- Review logs for schema loading errors
- Try force refresh: schema_manager.load_and_process_schema(force_refresh=True)

**"ChromaDB no disponible"**
- ChromaDB is optional; system will degrade gracefully
- Check if data/chroma_db directory has correct permissions
- Reinstall chromadb: `pip install chromadb==0.4.22`

**Slow schema loading**
- Normal for large databases (500+ tables)
- System loads in background for web interface
- Avoid counting rows for all tables (use quick heuristics)
- Check config.rag.cache_ttl_minutes to extend cache duration

**SQL generation errors**
- Verify OpenAI API key is valid and has credits
- Check if query is too vague (system will ask for clarification)
- Review generated SQL for Firebird syntax errors (FIRST vs LIMIT)
- Check if relevant tables were identified (low similarity scores)

**UTF-8 encoding errors on Windows**
- Ensure Python is run with UTF-8 environment: set PYTHONIOENCODING=utf-8
- Check that all file operations use encoding='utf-8'
- Verify stdout/stderr reconfiguration in main.py runs correctly
