from database import db

db.connect()
schema = db.get_full_schema()

# schema es un dict de TableInfo objects
table = schema.get('DOCTOS_PV_DET')
if table:
    cols = [c.name for c in table.columns[:30]]
    print('Primeras 30 columnas de DOCTOS_PV_DET:')
    for i, col in enumerate(cols, 1):
        print(f'{i}. {col}')

    # Buscar si existe DESCRIPCION1 o similar
    print('\nBuscando columnas con "DESC"...')
    desc_cols = [c.name for c in table.columns if 'DESC' in c.name.upper()]
    if desc_cols:
        print(f'Encontradas: {", ".join(desc_cols)}')
    else:
        print('No se encontraron columnas con "DESC"')
else:
    print('Tabla DOCTOS_PV_DET no encontrada')
