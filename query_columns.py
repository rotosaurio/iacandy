from database import db

db.connect()
with db.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT FIRST 30 rf.RDB$FIELD_NAME
        FROM RDB$RELATION_FIELDS rf
        WHERE rf.RDB$RELATION_NAME = 'DOCTOS_PV_DET'
        ORDER BY rf.RDB$FIELD_POSITION
    """)
    cols = [row[0].strip() for row in cursor.fetchall()]
    cursor.close()

    print('Primeras 30 columnas de DOCTOS_PV_DET:')
    for i, col in enumerate(cols, 1):
        print(f'{i}. {col}')

    # Buscar DESC
    print('\nBuscando columnas con "DESC"...')
    cursor2 = conn.cursor()
    cursor2.execute("""
        SELECT rf.RDB$FIELD_NAME
        FROM RDB$RELATION_FIELDS rf
        WHERE rf.RDB$RELATION_NAME = 'DOCTOS_PV_DET'
        AND rf.RDB$FIELD_NAME CONTAINING 'DESC'
        ORDER BY rf.RDB$FIELD_POSITION
    """)
    desc_cols = [row[0].strip() for row in cursor2.fetchall()]
    cursor2.close()

    if desc_cols:
        print(f'Encontradas: {", ".join(desc_cols)}')
    else:
        print('No hay columnas con "DESC"')
