import pytest
from fastapi.testclient import TestClient
import src.config.database as database
from src.main import app
from src.models.run import Run
from src.models.identity import User
from src.models.ledger import Correction,LedgerEntry,PeriodClose
from src.services import ledger as L
from src.utils.security import password_hash
from conftest import ADMIN,make_run

@pytest.fixture()
def client(db_factory):
 def override():
  s=db_factory()
  try: yield s
  finally: s.close()
 app.dependency_overrides[database.database]=override
 with TestClient(app) as c: yield c
 app.dependency_overrides.clear()

def auth(client,email='admin@demo.local'):
 r=client.post('/auth/login',json={'email':email,'password':'x'})
 assert r.status_code==200,r.text
 return {'Authorization':'Bearer '+r.json()['token']}

def test_full_ledger_flow_over_http(client,db_factory):
 h=auth(client)
 s=db_factory()
 base=make_run(s,'2026-10',[('光学研究','仪器维护',1000),('材料研究','试验耗材',2000)],'base')
 new=make_run(s,'2026-10',[('光学研究','仪器维护',1300),('材料研究','试验耗材',1700)],'new')
 L.post_original(s,base,ADMIN);s.commit();s.close()
 r=client.get('/ledger/periods',headers=h);assert r.status_code==200
 r=client.post('/ledger/close',headers=h,json={'period':'2026-10'})
 assert r.status_code==200 and r.json()['status']=='closed'
 r=client.post('/ledger/corrections',headers=h,json={'base_run_id':base.id,'new_run_id':new.id,'note':'口径修订'})
 assert r.status_code==200,r.text
 body=r.json();assert body['status']=='deferred' and body['owned_period']=='2026-10'
 r=client.get('/ledger/entries',headers=h)
 corr=[e for e in r.json() if e['entry_type']=='correction']
 assert len(corr)==2 and all(e['posting_period']=='2026-11' and e['owned_period']=='2026-10' for e in corr)
 r=client.get(f'/ledger/runs/{base.id}/chain',headers=h)
 chain=r.json();assert len(chain['original_lines'])==2 and chain['corrections'][0]['new_run_id']==new.id
 r=client.get('/ledger/closes',headers=h)
 closes=r.json();assert closes[0]['closing_balance']=={'光学研究':1000,'材料研究':2000}
 before=len(client.get('/ledger/entries',headers=h).json())
 client.post('/ledger/corrections',headers=h,json={'base_run_id':base.id,'new_run_id':new.id})
 assert len(client.get('/ledger/entries',headers=h).json())==before

def test_viewer_cannot_write(client,db_factory):
 s=db_factory()
 s.add(User(email='v@demo.local',role='viewer',password=password_hash('x')));s.commit();s.close()
 h=auth(client,'v@demo.local')
 assert client.post('/ledger/close',headers=h,json={'period':'2026-10'}).status_code==403
