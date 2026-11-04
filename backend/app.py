"""KHENTY management API. WSGI application; run behind Gunicorn and HTTPS."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
MAX_BODY = 65536


class Problem(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def text(value, limit=500, required=False):
    if not isinstance(value, str) or len(value) > limit:
        raise Problem('Texte invalide ou trop long.')
    value = value.strip()
    if required and not value:
        raise Problem('Un champ obligatoire est vide.')
    return value


def integer(value, minimum=0, maximum=1000000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Problem('Nombre entier hors limites.')
    return value


def boolean(value):
    if type(value) is not bool:
        raise Problem('Valeur oui/non invalide.')
    return value


class Management:
    def __init__(self, db_path, password, origin, secure=True):
        if len(password) < 20:
            raise RuntimeError('ADMIN_PASSWORD doit contenir au moins 20 caractères.')
        self.db_path, self.origin, self.secure = str(db_path), origin.rstrip('/'), secure
        self.salt = secrets.token_bytes(32)
        self.password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), self.salt, 300000)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS vendors(id TEXT PRIMARY KEY, name TEXT NOT NULL,
              country TEXT NOT NULL, verified INTEGER NOT NULL, evidence TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY, name TEXT NOT NULL,
              collection TEXT NOT NULL, color TEXT NOT NULL, description TEXT NOT NULL,
              image TEXT NOT NULL, status TEXT NOT NULL, vendor_id TEXT,
              sample_approved INTEGER NOT NULL, logo_approved INTEGER NOT NULL,
              stock_mode TEXT NOT NULL, stock INTEGER NOT NULL DEFAULT 0,
              xaf INTEGER, sar INTEGER, version INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS dossiers(id TEXT PRIMARY KEY, reference TEXT NOT NULL,
              market TEXT NOT NULL, items TEXT NOT NULL, note TEXT NOT NULL,
              status TEXT NOT NULL, created INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, csrf TEXT NOT NULL,
              expires INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY CHECK(id=1),
              count INTEGER NOT NULL, since INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,
              created INTEGER NOT NULL, action TEXT NOT NULL, resource TEXT NOT NULL,
              detail TEXT NOT NULL);
            ''')
            db.execute('PRAGMA journal_mode=WAL')
            # This service uses one Gunicorn worker. Restarting revokes every session.
            db.execute('DELETE FROM sessions')
            if not db.execute('SELECT 1 FROM products LIMIT 1').fetchone():
                for p in json.loads((ROOT / 'seed.json').read_text()):
                    db.execute('''INSERT INTO products(id,name,collection,color,description,image,
                      status,vendor_id,sample_approved,logo_approved,stock_mode,stock,xaf,sar)
                      VALUES(?,?,?,?,?,?, 'concept',NULL,0,0,'unconfirmed',0,NULL,NULL)''',
                      tuple(p[k] for k in ('id','name','collection','color','description','image')))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def audit(db, action, resource, detail):
        db.execute('INSERT INTO audit(created,action,resource,detail) VALUES(?,?,?,?)',
                   (int(time.time()), action, resource, json.dumps(detail, ensure_ascii=False)))

    def authorize(self, db, env, mutate=False):
        cookie = SimpleCookie()
        try:
            cookie.load(env.get('HTTP_COOKIE', ''))
            token = cookie['khenty_session'].value
        except Exception:
            raise Problem('Connexion requise.', 401)
        digest = hashlib.sha256(token.encode()).hexdigest()
        session = db.execute('SELECT * FROM sessions WHERE token=? AND expires>?',
                             (digest, int(time.time()))).fetchone()
        if not session:
            raise Problem('Session expirée. Reconnectez-vous.', 401)
        if mutate and not hmac.compare_digest(env.get('HTTP_X_CSRF_TOKEN', ''), session['csrf']):
            raise Problem('Validation de sécurité manquante.', 403)
        return session, digest

    def body(self, env):
        try:
            size = int(env.get('CONTENT_LENGTH') or '0')
        except ValueError:
            raise Problem('Taille de requête invalide.')
        if not 0 < size <= MAX_BODY:
            raise Problem('Requête vide ou trop volumineuse.', 413)
        if env.get('CONTENT_TYPE', '').split(';')[0] != 'application/json':
            raise Problem('JSON requis.', 415)
        try:
            data = json.loads(env['wsgi.input'].read(size))
        except (ValueError, UnicodeError):
            raise Problem('JSON invalide.')
        if not isinstance(data, dict):
            raise Problem('Objet JSON requis.')
        return data

    def product(self, db, p):
        ident = text(p.get('id'), 32, True)
        if not re.fullmatch(r'[A-Z0-9-]+', ident):
            raise Problem('Référence : lettres majuscules, chiffres et tirets uniquement.')
        name = text(p.get('name'), 100, True)
        collection = text(p.get('collection'), 60, True)
        color = text(p.get('color', ''), 60)
        description = text(p.get('description', ''), 1000)
        image = text(p.get('image', ''), 200)
        if image and not re.fullmatch(r'/assets/[a-z0-9-]+\.jpg', image):
            raise Problem('Utilisez une image du dossier catalogue /assets/.')
        status = p.get('status')
        mode = p.get('stock_mode')
        if status not in ('concept','draft','ready','archived') or mode not in ('unconfirmed','supplier','owned'):
            raise Problem('Statut ou type de stock invalide.')
        vendor_id = text(p.get('vendor_id') or '', 50) or None
        sample, logo = boolean(p.get('sample_approved', False)), boolean(p.get('logo_approved', False))
        prices = []
        for currency in ('xaf','sar'):
            value = p.get(currency)
            prices.append(None if value is None else integer(value, 1))
        old = db.execute('SELECT * FROM products WHERE id=?', (ident,)).fetchone()
        stock = old['stock'] if old else 0
        if old and integer(p.get('version'), 1) != old['version']:
            raise Problem('Ce produit a été modifié ailleurs. Rechargez avant de continuer.', 409)
        vendor = db.execute('SELECT * FROM vendors WHERE id=?', (vendor_id,)).fetchone() if vendor_id else None
        if vendor_id and not vendor:
            raise Problem('Fournisseur introuvable.')
        if old and old['stock_mode'] != mode and stock:
            raise Problem('Ramenez le stock à zéro avant de changer son mode de gestion.')
        if status == 'ready':
            if not (vendor and vendor['verified'] and sample and logo and mode != 'unconfirmed' and any(prices)):
                raise Problem('Avant validation : fournisseur vérifié, échantillon et logo approuvés, prix et disponibilité confirmés.')
        values = (name,collection,color,description,image,status,vendor_id,int(sample),int(logo),mode,*prices)
        if old:
            db.execute('''UPDATE products SET name=?,collection=?,color=?,description=?,image=?,status=?,
              vendor_id=?,sample_approved=?,logo_approved=?,stock_mode=?,xaf=?,sar=?,version=version+1 WHERE id=?''', (*values,ident))
        else:
            db.execute('''INSERT INTO products(name,collection,color,description,image,status,vendor_id,
              sample_approved,logo_approved,stock_mode,xaf,sar,id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (*values,ident))
        self.audit(db, 'product.save', ident, {'status':status})
        return {'ok':True}

    def dispatch(self, env):
        path, method = env.get('PATH_INFO','/'), env.get('REQUEST_METHOD','GET')
        headers = []
        if method == 'POST' and env.get('HTTP_ORIGIN') != self.origin:
            raise Problem('Origine non autorisée.', 403)
        with self.connect() as db:
            if path == '/health' and method == 'GET':
                db.execute('SELECT 1')
                return {'ok':True,'checkout_enabled':False}, headers
            if path == '/api/catalogue' and method == 'GET':
                rows = db.execute("SELECT id,name,collection,color,description,image,status,xaf,sar,stock_mode,stock FROM products WHERE status IN ('concept','ready') ORDER BY id").fetchall()
                return {'products':[dict(r) for r in rows], 'checkout_enabled':False}, headers
            if path == '/api/login' and method == 'POST':
                data = self.body(env)
                now = int(time.time())
                # Global persistent limit prevents spoofed forwarded-IP bypasses.
                db.execute('BEGIN IMMEDIATE')
                attempt = db.execute('SELECT * FROM attempts WHERE id=1').fetchone()
                count = attempt['count'] if attempt and now-attempt['since'] < 900 else 0
                since = attempt['since'] if count else now
                if count >= 10:
                    raise Problem('Trop de tentatives. Réessayez dans quinze minutes.', 429)
                candidate = data.get('password', '')
                if not isinstance(candidate, str) or len(candidate) > 1024:
                    candidate = ''
                valid = hmac.compare_digest(hashlib.pbkdf2_hmac('sha256', candidate.encode(),self.salt,300000),self.password_hash)
                if not valid:
                    db.execute('INSERT OR REPLACE INTO attempts VALUES(1,?,?)',(count+1,since))
                    db.commit()
                    raise Problem('Mot de passe incorrect.', 401)
                db.execute('DELETE FROM attempts')
                db.execute('DELETE FROM sessions WHERE expires<=?',(now,))
                token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
                db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),csrf,now+28800))
                headers.append(('Set-Cookie','khenty_session='+token+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'+('; Secure' if self.secure else '')))
                return {'csrf':csrf},headers
            if path.startswith('/api/admin/') or path == '/api/session' or path == '/api/logout':
                session, digest = self.authorize(db,env,method != 'GET')
                if path == '/api/session' and method == 'GET':
                    return {'csrf':session['csrf']},headers
                if path == '/api/logout' and method == 'POST':
                    db.execute('DELETE FROM sessions WHERE token=?',(digest,))
                    headers.append(('Set-Cookie','khenty_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'+('; Secure' if self.secure else '')))
                    return {'ok':True},headers
                if path == '/api/admin/data' and method == 'GET':
                    result = {table:[dict(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY id')] for table in ('products','vendors','dossiers')}
                    for p in result['products']:
                        p['sample_approved']=bool(p['sample_approved'])
                        p['logo_approved']=bool(p['logo_approved'])
                    for v in result['vendors']:
                        v['verified']=bool(v['verified'])
                    result['audit']=[dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 100')]
                    result['checkout_enabled']=False
                    return result,headers
                if method != 'POST':
                    raise Problem('Méthode non autorisée.',405)
                data = self.body(env)
                db.execute('BEGIN IMMEDIATE')
                if path == '/api/admin/products':
                    return self.product(db,data),headers
                if path == '/api/admin/vendors':
                    ident = text(data.get('id'),50,True)
                    if not re.fullmatch(r'[A-Z0-9-]+',ident):
                        raise Problem('Référence fournisseur invalide.')
                    name = text(data.get('name'),100,True)
                    country = data.get('country')
                    if country not in ('CN','SA','CM'):
                        raise Problem('Pays fournisseur invalide.')
                    verified = boolean(data.get('verified',False))
                    evidence = text(data.get('evidence',''),1000)
                    if verified and not evidence:
                        raise Problem('Documentez le contrôle avant de valider ce fournisseur.')
                    db.execute('INSERT OR REPLACE INTO vendors VALUES(?,?,?,?,?)',(ident,name,country,int(verified),evidence))
                    if not verified:
                        db.execute("UPDATE products SET status='draft',version=version+1 WHERE vendor_id=? AND status='ready'",(ident,))
                    self.audit(db,'vendor.save',ident,{'verified':verified})
                    return {'ok':True},headers
                if path == '/api/admin/inventory':
                    ident = text(data.get('id'),32,True)
                    delta = integer(data.get('delta'),-1000000,1000000)
                    reason = text(data.get('reason'),500,True)
                    row = db.execute('SELECT * FROM products WHERE id=?',(ident,)).fetchone()
                    if not row or row['stock_mode'] != 'owned':
                        raise Problem('Mouvement réservé aux produits en stock KHENTY.')
                    if row['stock']+delta < 0:
                        raise Problem('Le stock ne peut pas devenir négatif.')
                    db.execute('UPDATE products SET stock=stock+?,version=version+1 WHERE id=?',(delta,ident))
                    self.audit(db,'inventory.move',ident,{'delta':delta,'reason':reason})
                    return {'ok':True},headers
                if path == '/api/admin/dossiers':
                    market = data.get('market')
                    if market not in ('CM','SA'):
                        raise Problem('Marché invalide.')
                    status = data.get('status','draft')
                    if status not in ('draft','quote_sent','cancelled'):
                        raise Problem('Paiement et expédition non activés ; utilisez un statut de préparation.')
                    reference = text(data.get('reference'),100,True)
                    note = text(data.get('note',''),1000)
                    items = data.get('items')
                    if not isinstance(items,list) or not 1 <= len(items) <= 30:
                        raise Problem('Sélectionnez entre 1 et 30 lignes.')
                    clean=[]
                    for item in items:
                        if not isinstance(item,dict): raise Problem('Ligne invalide.')
                        product = db.execute('SELECT * FROM products WHERE id=?',(text(item.get('id'),32,True),)).fetchone()
                        if not product: raise Problem('Produit introuvable.')
                        quantity = integer(item.get('quantity'),1,10000)
                        price = product['xaf' if market=='CM' else 'sar']
                        if status == 'quote_sent' and (product['status']!='ready' or price is None or (product['stock_mode']=='owned' and product['stock']<quantity)):
                            raise Problem('Devis envoyable seulement pour un produit validé, tarifé et disponible sur ce marché.')
                        if any(x['id']==product['id'] for x in clean): raise Problem('Regroupez les quantités d’un même produit sur une ligne.')
                        clean.append({'id':product['id'],'quantity':quantity,'unit_price':price})
                    ident = text(data.get('id') or secrets.token_hex(8),50,True)
                    old=db.execute('SELECT created FROM dossiers WHERE id=?',(ident,)).fetchone()
                    db.execute('INSERT OR REPLACE INTO dossiers VALUES(?,?,?,?,?,?,?)',(ident,reference,market,json.dumps(clean),note,status,old['created'] if old else int(time.time())))
                    self.audit(db,'dossier.save',ident,{'status':status})
                    return {'ok':True,'id':ident},headers
                raise Problem('Action inconnue.',404)
        raise Problem('Page introuvable.',404)

    def __call__(self, env, start_response):
        headers=[('X-Content-Type-Options','nosniff'),('X-Frame-Options','DENY'),('Referrer-Policy','no-referrer'),('Cache-Control','no-store'),('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]
        path=env.get('PATH_INFO','/')
        if path == '/api/catalogue':
            headers.append(('Access-Control-Allow-Origin','https://khenty-website.onrender.com'))
        if path in ('/','/admin','/admin.js','/admin.css') and env.get('REQUEST_METHOD')=='GET':
            file={'/':'admin.html','/admin':'admin.html','/admin.js':'admin.js','/admin.css':'admin.css'}[path]
            payload=(ROOT/file).read_bytes()
            mime='text/html' if file.endswith('html') else 'text/javascript' if file.endswith('js') else 'text/css'
            start_response('200 OK',headers+[('Content-Type',mime+'; charset=utf-8')])
            return [payload]
        if re.fullmatch(r'/assets/[a-z0-9-]+\.jpg',path) and env.get('REQUEST_METHOD')=='GET':
            file=ROOT.parent/path.lstrip('/')
            if file.is_file():
                start_response('200 OK',headers+[('Content-Type','image/jpeg')]);return [file.read_bytes()]
        try:
            result, extra = self.dispatch(env)
            status=200
        except Problem as exc:
            result,extra,status={'error':exc.message},[],exc.status
        except Exception:
            # Never return database paths, secrets, or customer records in errors.
            import logging
            logging.exception('Management request failed')
            result,extra,status={'error':'Erreur interne. Réessayez ou contactez l’administrateur.'},[],500
        labels={200:'OK',400:'Bad Request',401:'Unauthorized',403:'Forbidden',404:'Not Found',405:'Method Not Allowed',409:'Conflict',413:'Payload Too Large',415:'Unsupported Media Type',429:'Too Many Requests',500:'Internal Server Error'}
        payload=json.dumps(result,ensure_ascii=False).encode()
        start_response(str(status)+' '+labels[status],headers+extra+[('Content-Type','application/json; charset=utf-8'),('Content-Length',str(len(payload)))])
        return [payload]


def create_app():
    origin=os.environ.get('PUBLIC_ORIGIN','')
    parsed=urlsplit(origin)
    if parsed.scheme!='https' or not parsed.netloc or parsed.path not in ('','/') or parsed.query or parsed.fragment:
        raise RuntimeError('PUBLIC_ORIGIN doit être l’origine HTTPS exacte du service.')
    if not os.environ.get('KHENTY_DB'):
        raise RuntimeError('KHENTY_DB doit viser une base sur stockage persistant.')
    return Management(os.environ['KHENTY_DB'],os.environ.get('ADMIN_PASSWORD',''),origin)
