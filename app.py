"""AUREL Watches: educational luxury watch store, Flask + MongoDB Atlas."""
import io
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps
from urllib.parse import urlparse

import qrcode
from bson import ObjectId
from dotenv import load_dotenv
from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', '')
if not app.secret_key or app.secret_key.startswith('REEMPLAZAR_'):
    raise RuntimeError('Configura SECRET_KEY en .env o Render.')
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=os.getenv('RENDER') == 'true',
                  MAX_CONTENT_LENGTH=2 * 1024 * 1024)
uri = os.getenv('MONGO_URI', '')
if not uri or 'example.mongodb.net' in uri:
    raise RuntimeError('Configura MONGO_URI en .env o Render.')
client = MongoClient(uri, serverSelectionTimeoutMS=12000)
db = client[os.getenv('MONGO_DB', 'aurel_watches')]
products = db.products
users = db.users
orders = db.orders
reservations = db.reservations


def now():
    return datetime.now(timezone.utc)


def oid(value):
    if not ObjectId.is_valid(str(value)):
        abort(404)
    return ObjectId(str(value))


def money(value):
    return f'${Decimal(str(value)):,.2f} MXN'

app.jinja_env.filters['money'] = money


def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(32)
    return session['_csrf']

app.jinja_env.globals['csrf_token'] = csrf_token

@app.before_request
def check_csrf():
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and request.endpoint != 'api_products':
        if not secrets.compare_digest(request.form.get('_csrf', ''), session.get('_csrf', '')):
            abort(400, 'Token de formulario inválido. Recarga la página.')


def current_user():
    uid = session.get('user_id')
    return users.find_one({'_id': oid(uid)}) if uid and ObjectId.is_valid(uid) else None

@app.context_processor
def inject():
    return {'me': current_user(), 'cart_count': sum(int(x) for x in session.get('cart', {}).values())}


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash('Inicia sesión para continuar.', 'warning')
            return redirect(url_for('login', next=request.path))
        return fn(*args, **kwargs)
    return wrapped


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for('login'))
        if not user.get('admin'):
            abort(403)
        return fn(*args, **kwargs)
    return wrapped


def expire_reservations():
    """Release expired holds on access; also ignore them in stock checks."""
    reservations.update_many({'status': 'active', 'expires_at': {'$lte': now()}},
                             {'$set': {'status': 'expired', 'updated_at': now()}})


def product_view(doc):
    doc = dict(doc)
    doc['id'] = str(doc['_id'])
    doc['available'] = max(0, int(doc.get('stock', 0)) - reserved_qty(doc['_id']))
    return doc


def reserved_qty(pid):
    rows = reservations.aggregate([
        {'$match': {'status': 'active', 'expires_at': {'$gt': now()}, 'items.product_id': pid}},
        {'$unwind': '$items'},
        {'$match': {'items.product_id': pid}},
        {'$group': {'_id': None, 'qty': {'$sum': '$items.qty'}}}
    ])
    row = next(rows, None)
    return int(row['qty']) if row else 0


def cart_items():
    result = []
    for pid, qty in session.get('cart', {}).items():
        if ObjectId.is_valid(pid):
            doc = products.find_one({'_id': ObjectId(pid), 'active': True})
            if doc:
                p = product_view(doc)
                result.append({'product': p, 'qty': int(qty), 'subtotal': int(qty) * float(p['price'])})
    return result


def cart_total(items):
    return sum(x['subtotal'] for x in items)

@app.route('/')
def index():
    q = request.args.get('q', '').strip()[:80]
    category = request.args.get('category', '').strip()[:40]
    query = {'active': True}
    if q:
        query['$or'] = [{'name': {'$regex': re.escape(q), '$options': 'i'}},
                        {'brand': {'$regex': re.escape(q), '$options': 'i'}}]
    if category:
        query['category'] = category
    data = [product_view(p) for p in products.find(query).sort('_id', -1).limit(60)]
    categories = sorted(c for c in products.distinct('category', {'active': True}) if c)
    return render_template('index.html', products=data, q=q, category=category, categories=categories)

@app.route('/reloj/<pid>')
def detail(pid):
    doc = products.find_one({'_id': oid(pid), 'active': True})
    if not doc:
        abort(404)
    return render_template('detail.html', p=product_view(doc))

@app.route('/registro', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()[:80]
        email = request.form.get('email', '').strip().lower()[:150]
        password = request.form.get('password', '')
        if not name or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email) or len(password) < 8:
            flash('Nombre, correo válido y contraseña de mínimo 8 caracteres.', 'danger')
        elif users.find_one({'email': email}):
            flash('Ese correo ya está registrado.', 'danger')
        else:
            result = users.insert_one({'name': name, 'email': email, 'password_hash': generate_password_hash(password),
                                       'admin': False, 'created_at': now()})
            session.clear()
            session['user_id'] = str(result.inserted_id)
            flash('Cuenta creada correctamente.', 'success')
            return redirect(url_for('index'))
    return render_template('auth.html', register=True)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = users.find_one({'email': email})
        if user and check_password_hash(user['password_hash'], request.form.get('password', '')):
            session.clear()
            session['user_id'] = str(user['_id'])
            flash('Bienvenido a AUREL.', 'success')
            next_path = request.args.get('next', '')
            return redirect(next_path if next_path.startswith('/') and not next_path.startswith('//') else url_for('index'))
        flash('Credenciales incorrectas.', 'danger')
    return render_template('auth.html', register=False)

@app.post('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada.', 'success')
    return redirect(url_for('index'))

@app.post('/carrito/agregar/<pid>')
def add_cart(pid):
    doc = products.find_one({'_id': oid(pid), 'active': True})
    if not doc:
        abort(404)
    qty = request.form.get('qty', '1')
    if not qty.isdigit() or not 1 <= int(qty) <= 10:
        abort(400)
    cart = dict(session.get('cart', {}))
    current = int(cart.get(pid, 0))
    if current + int(qty) > product_view(doc)['available']:
        flash('No hay suficientes unidades disponibles.', 'danger')
    else:
        cart[pid] = current + int(qty)
        session['cart'] = cart
        flash('Reloj añadido al carrito.', 'success')
    return redirect(url_for('cart'))

@app.route('/carrito')
def cart():
    expire_reservations()
    items = cart_items()
    return render_template('cart.html', items=items, total=cart_total(items))

@app.post('/carrito/quitar/<pid>')
def remove_cart(pid):
    cart = dict(session.get('cart', {}))
    cart.pop(pid, None)
    session['cart'] = cart
    return redirect(url_for('cart'))


def lock_product(pid, token):
    """Short-lived per-product lock for inventory-changing operations."""
    until = now() + timedelta(seconds=25)
    return products.find_one_and_update(
        {'_id': pid, '$or': [{'lock_until': {'$exists': False}}, {'lock_until': {'$lte': now()}}]},
        {'$set': {'lock_until': until, 'lock_token': token}}, return_document=ReturnDocument.AFTER)


def release_locks(ids, token):
    products.update_many({'_id': {'$in': ids}, 'lock_token': token}, {'$unset': {'lock_until': '', 'lock_token': ''}})


def acquire_locks(ids):
    token = secrets.token_hex(16)
    locked = []
    for pid in sorted(ids, key=str):
        if not lock_product(pid, token):
            release_locks(locked, token)
            return None, []
        locked.append(pid)
    return token, locked

@app.post('/reservar')
@login_required
def reserve():
    expire_reservations()
    items = cart_items()
    if not items:
        flash('Tu carrito está vacío.', 'warning')
        return redirect(url_for('cart'))
    if reservations.find_one({'user_id': current_user()['_id'], 'status': 'active', 'expires_at': {'$gt': now()}}):
        flash('Ya tienes una reserva activa. Confírmala o cancélala primero.', 'warning')
        return redirect(url_for('my_reservations'))
    ids = [x['product']['_id'] for x in items]
    token, locked = acquire_locks(ids)
    if not token:
        flash('Inventario ocupado. Intenta nuevamente.', 'warning')
        return redirect(url_for('cart'))
    try:
        for x in items:
            latest = products.find_one({'_id': x['product']['_id'], 'active': True})
            if not latest or int(latest['stock']) - reserved_qty(latest['_id']) < x['qty']:
                flash('El inventario cambió. Revisa tu carrito.', 'danger')
                return redirect(url_for('cart'))
        timestamp = now()
        record = {'user_id': current_user()['_id'], 'status': 'active', 'created_at': timestamp,
                  'updated_at': timestamp, 'expires_at': timestamp + timedelta(minutes=5),
                  'public_token': secrets.token_urlsafe(24),
                  'items': [{'product_id': x['product']['_id'], 'name': x['product']['name'],
                             'brand': x['product']['brand'], 'qty': x['qty'],
                             'price': float(x['product']['price'])} for x in items],
                  'total': round(cart_total(items), 2)}
        rid = reservations.insert_one(record).inserted_id
        session['cart'] = {}
        flash('Reserva creada por cinco minutos.', 'success')
        return redirect(url_for('reservation_detail', rid=rid))
    finally:
        release_locks(locked, token)

@app.route('/mis-reservas')
@login_required
def my_reservations():
    expire_reservations()
    data = list(reservations.find({'user_id': current_user()['_id']}).sort('created_at', -1).limit(50))
    return render_template('reservations.html', reservations=data)


def owned_reservation(rid):
    r = reservations.find_one({'_id': oid(rid)})
    user = current_user()
    if not r or not user or (r['user_id'] != user['_id'] and not user.get('admin')):
        abort(404)
    return r

@app.route('/reserva/<rid>')
@login_required
def reservation_detail(rid):
    expire_reservations()
    r = owned_reservation(rid)
    remaining = max(0, int((r['expires_at'].replace(tzinfo=timezone.utc) - now()).total_seconds())) if r['status'] == 'active' else 0
    return render_template('reservation_detail.html', r=r, remaining=remaining)

@app.post('/reserva/<rid>/cancelar')
@login_required
def cancel_reservation(rid):
    r = owned_reservation(rid)
    reservations.update_one({'_id': r['_id'], 'status': 'active'},
                            {'$set': {'status': 'cancelled', 'updated_at': now()}})
    flash('Reserva cancelada. Existencias liberadas.', 'success')
    return redirect(url_for('reservation_detail', rid=rid))

@app.post('/reserva/<rid>/confirmar')
@login_required
def confirm_reservation(rid):
    expire_reservations()
    r = owned_reservation(rid)
    if r['status'] != 'active' or r['expires_at'].replace(tzinfo=timezone.utc) <= now():
        flash('La reserva ya no está activa.', 'danger')
        return redirect(url_for('reservation_detail', rid=rid))
    ids = [x['product_id'] for x in r['items']]
    token, locked = acquire_locks(ids)
    if not token:
        flash('Inventario ocupado. Intenta nuevamente.', 'warning')
        return redirect(url_for('reservation_detail', rid=rid))
    try:
        r = reservations.find_one({'_id': r['_id'], 'status': 'active', 'expires_at': {'$gt': now()}})
        if not r:
            flash('La reserva expiró.', 'danger')
            return redirect(url_for('reservation_detail', rid=rid))
        # Reserve stock by atomically decrementing each product while locks are held.
        changed = []
        for x in r['items']:
            result = products.update_one({'_id': x['product_id'], 'stock': {'$gte': x['qty']}},
                                         {'$inc': {'stock': -x['qty']}})
            if not result.modified_count:
                for pid, qty in changed:
                    products.update_one({'_id': pid}, {'$inc': {'stock': qty}})
                flash('No hay existencias suficientes.', 'danger')
                return redirect(url_for('reservation_detail', rid=rid))
            changed.append((x['product_id'], x['qty']))
        try:
            order = {'user_id': r['user_id'], 'reservation_id': r['_id'], 'items': r['items'],
                     'total': r['total'], 'created_at': now(), 'status': 'simulated',
                     'public_token': r['public_token']}
            order_id = orders.insert_one(order).inserted_id
            reservations.update_one({'_id': r['_id'], 'status': 'active'},
                                    {'$set': {'status': 'confirmed', 'order_id': order_id, 'updated_at': now()}})
        except Exception:
            for pid, qty in changed:
                products.update_one({'_id': pid}, {'$inc': {'stock': qty}})
            raise
        flash('Compra simulada confirmada. No se realizó ningún cobro.', 'success')
        return redirect(url_for('my_orders'))
    finally:
        release_locks(locked, token)

@app.route('/mis-compras')
@login_required
def my_orders():
    data = list(orders.find({'user_id': current_user()['_id']}).sort('created_at', -1).limit(50))
    return render_template('orders.html', orders=data)

@app.route('/reserva/<rid>/qr.png')
@login_required
def reservation_qr(rid):
    r = owned_reservation(rid)
    # A QR contains a public verification URL, not private customer data.
    base = os.getenv('PUBLIC_BASE_URL', '').rstrip('/') or request.url_root.rstrip('/')
    url = base + url_for('verify_reservation', token=r['public_token'])
    qr = qrcode.QRCode(box_size=8, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='#161a1c', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png', download_name=f'reserva-{rid}.png', as_attachment=False)

@app.route('/verificar/<token>')
def verify_reservation(token):
    if len(token) > 100:
        abort(404)
    r = reservations.find_one({'public_token': token})
    if not r:
        abort(404)
    status = r['status']
    if status == 'active' and r['expires_at'].replace(tzinfo=timezone.utc) <= now():
        status = 'expired'
    # Public view intentionally omits personal data, email, and account identifiers.
    return render_template('verify.html', r=r, status=status)

@app.route('/api/productos', methods=['GET'])
def api_products():
    result = []
    for doc in products.find({'active': True}).limit(100):
        p = product_view(doc)
        result.append({'id': p['id'], 'nombre': p['name'], 'marca': p['brand'],
                       'categoria': p.get('category', ''), 'precio': p['price'],
                       'disponibles': p['available'], 'imagen': p.get('image', '')})
    return jsonify({'productos': result, 'total': len(result)})

@app.route('/admin')
@admin_required
def admin():
    data = list(products.find().sort('_id', -1))
    return render_template('admin.html', products=[product_view(x) for x in data],
                           orders=orders.count_documents({}), reservations=reservations.count_documents({}))


def parse_product_form():
    name = request.form.get('name', '').strip()[:100]
    brand = request.form.get('brand', '').strip()[:70]
    category = request.form.get('category', '').strip()[:50]
    description = request.form.get('description', '').strip()[:1200]
    image = request.form.get('image', '').strip()[:500]
    if image and (urlparse(image).scheme != 'https' or not urlparse(image).netloc):
        raise ValueError('La imagen debe ser una URL HTTPS válida.')
    price = float(request.form.get('price', '0'))
    stock = int(request.form.get('stock', '0'))
    if not name or not brand or not category or not 0 < price <= 10000000 or not 0 <= stock <= 100000:
        raise ValueError('Completa los datos con precio y existencias válidos.')
    return {'name': name, 'brand': brand, 'category': category, 'description': description,
            'image': image, 'price': round(price, 2), 'stock': stock, 'active': True}

@app.route('/admin/reloj/nuevo', methods=['GET', 'POST'])
@admin_required
def new_product():
    if request.method == 'POST':
        try:
            data = parse_product_form()
            products.insert_one(data)
            flash('Reloj creado.', 'success')
            return redirect(url_for('admin'))
        except (ValueError, TypeError):
            flash('Revisa los campos del formulario.', 'danger')
    return render_template('product_form.html', p=None)

@app.route('/admin/reloj/<pid>/editar', methods=['GET', 'POST'])
@admin_required
def edit_product(pid):
    doc = products.find_one({'_id': oid(pid)})
    if not doc:
        abort(404)
    if request.method == 'POST':
        try:
            data = parse_product_form()
            products.update_one({'_id': doc['_id']}, {'$set': data})
            flash('Reloj actualizado.', 'success')
            return redirect(url_for('admin'))
        except (ValueError, TypeError):
            flash('Revisa los campos del formulario.', 'danger')
    return render_template('product_form.html', p=doc)

@app.post('/admin/reloj/<pid>/eliminar')
@admin_required
def delete_product(pid):
    products.update_one({'_id': oid(pid)}, {'$set': {'active': False}})
    flash('Reloj ocultado del catálogo.', 'success')
    return redirect(url_for('admin'))

@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(500)
def error(e):
    code = getattr(e, 'code', 500)
    return render_template('error.html', code=code), code

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG') == '1')
