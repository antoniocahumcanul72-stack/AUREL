"""Add sample watches to your own Atlas database. No third-party accounts needed."""
from app import products, client

samples = [
    ('Chronos Heritage', 'AUREL', 'Clásico', 14990, 8, 'Esfera minimalista, caja de acero y correa de piel.'),
    ('Nocturne Automatic', 'AUREL', 'Automático', 28900, 5, 'Movimiento automático y presencia atemporal.'),
    ('Meridian GMT', 'AUREL', 'Deportivo', 21900, 6, 'Doble huso horario para viajeros contemporáneos.'),
    ('Éclat Rose', 'AUREL', 'Elegante', 17490, 4, 'Acabados cálidos y silueta refinada.'),
    ('Obsidian Diver', 'AUREL', 'Deportivo', 32500, 3, 'Inspiración submarina con estética urbana.'),
    ('Monarch Moonphase', 'AUREL', 'Clásico', 42900, 2, 'Inspiración astronómica y sofisticación clásica.'),
]
client.admin.command('ping')
for name, brand, category, price, stock, description in samples:
    products.update_one({'name': name, 'brand': brand}, {'$setOnInsert': {
        'name': name, 'brand': brand, 'category': category, 'price': price,
        'stock': stock, 'description': description, 'image': '', 'active': True
    }}, upsert=True)
print('Catálogo de demostración listo.')
