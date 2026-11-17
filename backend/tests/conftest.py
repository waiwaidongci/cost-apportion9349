import os,sys,time
from pathlib import Path

# 在导入 src 之前准备最小环境：SQLite 内存库 + 本地 JWT 密钥，不依赖 Docker/Redis。
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('APP_DIR',str(ROOT))
os.environ.setdefault('DATABASE_URL','sqlite:///:memory:')
os.environ.setdefault('JWT_SECRET','test-secret-cross-period-ledger')
os.environ.setdefault('REDIS_URL','redis://localhost:6399/0')

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import src.config.database as database
from src.models import identity,source,run,ledger
from src.models.identity import User
from src.models.source import Source,Policy,Period
from src.models.run import Run
from src.utils.security import password_hash

@pytest.fixture()
def db_factory(monkeypatch):
 """每用例一个共享连接的内存 SQLite，BEGIN IMMEDIATE 可在同连接下工作。"""
 engine=create_engine('sqlite://',connect_args={'check_same_thread':False},
                      poolclass=StaticPool,isolation_level=None)
 Session=sessionmaker(bind=engine,expire_on_commit=False)
 monkeypatch.setattr(database,'engine',engine)
 monkeypatch.setattr(database,'Session',Session)
 identity.Base.metadata.create_all(engine)
 source.Base.metadata.create_all(engine)
 run.Base.metadata.create_all(engine)
 ledger.Base.metadata.create_all(engine)
 with Session() as setup:
  setup.add(User(email='admin@demo.local',role='admin',password=password_hash('x')))
  setup.add(User(email='analyst@demo.local',role='analyst',password=password_hash('x')))
  for p in ('2026-09','2026-10','2026-11','2026-12'):
   setup.add(Period(name=p,description='测试期间'))
  setup.commit()
 yield Session
 engine.dispose()

@pytest.fixture()
def db(db_factory):
 s=db_factory()
 try: yield s
 finally: s.close()

@pytest.fixture()
def file_factory(tmp_path,monkeypatch):
 """文件型 SQLite + 每线程独立连接，BEGIN IMMEDIATE 形成真实写锁竞争。"""
 import src.config.database as database
 url='sqlite:///'+str(tmp_path/'concurrency.db')
 engine=create_engine(url,connect_args={'check_same_thread':False,'timeout':30},isolation_level=None)
 Session=sessionmaker(bind=engine,expire_on_commit=False)
 monkeypatch.setattr(database,'engine',engine)
 monkeypatch.setattr(database,'Session',Session)
 identity.Base.metadata.create_all(engine);source.Base.metadata.create_all(engine)
 run.Base.metadata.create_all(engine);ledger.Base.metadata.create_all(engine)
 with Session() as setup:
  setup.add(User(email='admin@demo.local',role='admin',password=password_hash('x')))
  setup.add(User(email='analyst@demo.local',role='analyst',password=password_hash('x')))
  for p in ('2026-09','2026-10','2026-11','2026-12'): setup.add(Period(name=p,description='测试期间'))
  setup.commit()
 yield Session
 engine.dispose()

class U:
 def __init__(self,email): self.email=email;self.role='admin' if email.startswith('admin') else 'analyst'
ADMIN=U('admin@demo.local');ANALYST=U('analyst@demo.local')

def make_run(db,period,rows,name,approved=True,policy_version='v1'):
 """rows: [(部门,费用类别,分摊金额分)]；构造已完成报告（含 result.rows 透视）。"""
 pivot={}
 for d,c,v in rows: pivot[(d,c)]=pivot.get((d,c),0)+v
 result={'rows':[{'期间':period,'部门':d,'费用类别':c,'分摊金额分':v} for (d,c),v in sorted(pivot.items())],
         'summary':{},'trace':[],'method':'test','warnings':[]}
 r=Run(name=name,status='completed',snapshot={'period':period,'sources':[],'policy':{'version':policy_version}},
       checksum=name,result=result,created=time.time(),approved=approved,review='ok' if approved else '')
 db.add(r);db.commit();return r
