import io
import json
from pathlib import Path
import tempfile
import unittest
from app import Management


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Management(Path(self.temp.name)/'db.sqlite3','a-real-test-password-very-long','https://gestion.test')
        self.cookie, self.csrf = '', ''

    def tearDown(self):
        self.temp.cleanup()

    def call(self,path,body=None,origin='https://gestion.test',csrf=True):
        raw=json.dumps(body).encode() if body is not None else b''
        env={'PATH_INFO':path,'REQUEST_METHOD':'POST' if body is not None else 'GET',
             'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),
             'wsgi.input':io.BytesIO(raw),'HTTP_COOKIE':self.cookie,'HTTP_ORIGIN':origin,
             'HTTP_X_CSRF_TOKEN':self.csrf if csrf else ''}
        response={}
        def start(status,headers):response.update(status=int(status.split()[0]),headers=dict(headers))
        result=json.loads(b''.join(self.app(env,start)))
        return response,result

    def login(self):
        r,j=self.call('/api/login',{'password':'a-real-test-password-very-long'})
        self.assertEqual(r['status'],200)
        self.cookie=r['headers']['Set-Cookie'].split(';')[0];self.csrf=j['csrf']
        self.assertIn('HttpOnly',r['headers']['Set-Cookie']);self.assertIn('Secure',r['headers']['Set-Cookie'])

    def first(self):return self.call('/api/admin/data')[1]['products'][0]

    def test_private_data_and_csrf(self):
        self.assertEqual(self.call('/api/admin/data')[0]['status'],401)
        self.login()
        self.assertEqual(self.call('/api/logout',{},csrf=False)[0]['status'],403)
        self.assertEqual(self.call('/api/logout',{},origin='https://evil.test')[0]['status'],403)
        self.assertEqual(self.call('/api/logout',{})[0]['status'],200)
        self.assertEqual(self.call('/api/admin/data')[0]['status'],401)

    def test_concepts_do_not_become_sellable_by_price(self):
        self.login();p=self.first();p.update(status='ready',xaf=15000,sar=10000)
        self.assertEqual(self.call('/api/admin/products',p)[0]['status'],400)
        r,j=self.call('/api/catalogue');self.assertFalse(j['checkout_enabled'])
        self.assertEqual(len(j['products']),8)
        self.assertNotIn('vendor_id',j['products'][0])

    def test_supplier_validation_and_demotion(self):
        self.login()
        vendor={'id':'SUP-1','name':'Test fournisseur','country':'CN','verified':True,'evidence':''}
        self.assertEqual(self.call('/api/admin/vendors',vendor)[0]['status'],400)
        vendor['evidence']='Contrôle test, sans fournisseur réel'
        self.assertEqual(self.call('/api/admin/vendors',vendor)[0]['status'],200)
        p=self.first();p.update(vendor_id='SUP-1',sample_approved=True,logo_approved=True,stock_mode='supplier',status='ready',xaf=15000)
        self.assertEqual(self.call('/api/admin/products',p)[0]['status'],200)
        vendor['verified']=False
        self.call('/api/admin/vendors',vendor)
        self.assertEqual(self.first()['status'],'draft')

    def test_inventory_atomic_and_versions(self):
        self.login();p=self.first();p['stock_mode']='owned'
        self.assertEqual(self.call('/api/admin/products',p)[0]['status'],200)
        self.assertEqual(self.call('/api/admin/products',p)[0]['status'],409)
        self.assertEqual(self.call('/api/admin/inventory',{'id':p['id'],'delta':-1,'reason':'test'})[0]['status'],400)
        self.assertEqual(self.call('/api/admin/inventory',{'id':p['id'],'delta':5,'reason':'test réception'})[0]['status'],200)
        self.assertEqual(self.first()['stock'],5)
        self.assertEqual(self.call('/api/admin/inventory',{'id':p['id'],'delta':-6,'reason':'test sortie'})[0]['status'],400)
        self.assertEqual(self.first()['stock'],5)

    def test_dossiers_never_claim_payment(self):
        self.login();p=self.first()
        d={'reference':'TEST-1','market':'CM','items':[{'id':p['id'],'quantity':1}],'status':'paid'}
        self.assertEqual(self.call('/api/admin/dossiers',d)[0]['status'],400)
        d['status']='quote_sent'
        self.assertEqual(self.call('/api/admin/dossiers',d)[0]['status'],400)
        d['status']='draft'
        self.assertEqual(self.call('/api/admin/dossiers',d)[0]['status'],200)
        self.assertEqual(len(self.call('/api/admin/data')[1]['dossiers']),1)

    def test_rate_limit_and_restart(self):
        for _ in range(10):self.assertEqual(self.call('/api/login',{'password':'wrong'})[0]['status'],401)
        self.assertEqual(self.call('/api/login',{'password':'a-real-test-password-very-long'})[0]['status'],429)

    def test_persistence_and_revocation(self):
        self.login();p=self.first();p['name']='Nom persistant';self.call('/api/admin/products',p)
        self.app=Management(Path(self.temp.name)/'db.sqlite3','a-real-test-password-very-long','https://gestion.test')
        self.assertEqual(self.call('/api/admin/data')[0]['status'],401)
        self.login();self.assertEqual(self.first()['name'],'Nom persistant')

    def test_unsafe_inputs_and_private_files(self):
        self.login();p=self.first();p['image']='https://evil.test/tracking.jpg'
        self.assertEqual(self.call('/api/admin/products',p)[0]['status'],400)
        self.assertEqual(self.call('/seed.json')[0]['status'],404)
        self.assertEqual(self.call('/app.py')[0]['status'],404)
        self.assertEqual(self.call('/../db.sqlite3')[0]['status'],404)


if __name__=='__main__':unittest.main()
