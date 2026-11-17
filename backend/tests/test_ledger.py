import threading
import pytest
from fastapi import HTTPException
from src.models.ledger import PeriodClose,Correction,LedgerEntry
from src.services import ledger as L
from conftest import ADMIN,ANALYST,make_run

def entries(db,**kw): return db.query(LedgerEntry).filter_by(**kw).all()

# ---------- 1. 已复核报告首次入账，原账保留 ----------
def test_original_posting_on_approve_flow(db):
 r=make_run(db,'2026-10',[('光学研究','仪器维护',1000),('材料研究','试验耗材',2000)],'R1')
 posted=L.post_original(db,r,ADMIN);db.commit()
 assert len(posted)==2
 assert {e.amount_cents for e in entries(db,entry_type='original')}=={1000,2000}
 assert all(e.owned_period==e.posting_period=='2026-10' for e in posted)
 # 幂等：重复入账不产生新行
 again=L.post_original(db,r,ADMIN);db.commit()
 assert db.query(LedgerEntry).filter_by(entry_type='original',run_id=r.id).count()==2
 assert len(again)==2

def test_original_requires_approved(db):
 r=make_run(db,'2026-10',[('光学研究','仪器维护',1000)],'R',approved=False)
 with pytest.raises(HTTPException): L.post_original(db,r,ADMIN)

# ---------- 2. 更正仅追加新旧部门费用差额，保留原账 ----------
def test_correction_appends_delta_only(db):
 base=make_run(db,'2026-10',[('光学研究','仪器维护',1000),('材料研究','试验耗材',2000)],'base')
 L.post_original(db,base,ADMIN);db.commit()
 new=make_run(db,'2026-10',[('光学研究','仪器维护',1300),('材料研究','试验耗材',1700)],'new')
 c=L.create_correction(db,ADMIN,base.id,new.id,'口径更正');db.commit()
 corr=entries(db,entry_type='correction')
 # 原账原样保留
 assert {(e.department,e.amount_cents) for e in entries(db,entry_type='original')}=={('光学研究',1000),('材料研究',2000)}
 # 仅追加差额：+300 / -300，没有红字冲销原行
 assert {(x.department,x.amount_cents) for x in corr}=={('光学研究',300),('材料研究',-300)}
 assert c.delta_total==0 and c.status=='posted' and c.chain_seq==0 and c.prev_correction_id is None
 # 账簿余额 = 原账 + 差额
 bal=L.balances(db,'2026-10')['2026-10']
 assert bal=={'光学研究':1300,'材料研究':1700}

def test_no_delta_rejected(db):
 base=make_run(db,'2026-10',[('光学研究','仪器维护',1000)],'b');L.post_original(db,base,ADMIN);db.commit()
 same=make_run(db,'2026-10',[('光学研究','仪器维护',1000)],'s')
 with pytest.raises(HTTPException): L.create_correction(db,ADMIN,base.id,same.id)

def test_period_mismatch_rejected(db):
 base=make_run(db,'2026-10',[('光学研究','仪器维护',1000)],'b');L.post_original(db,base,ADMIN);db.commit()
 other=make_run(db,'2026-11',[('光学研究','仪器维护',1100)],'o')
 with pytest.raises(HTTPException): L.create_correction(db,ADMIN,base.id,other.id)

# ---------- 3. 封账期差额转下一开放期，保留费用所属期 ----------
def test_closed_period_defers_to_next_open(db):
 base=make_run(db,'2026-10',[('光学研究','仪器维护',1000)],'b');L.post_original(db,base,ADMIN);db.commit()
 L.close_period(db,ADMIN,'2026-10');db.commit()
 new=make_run(db,'2026-10',[('光学研究','仪器维护',1400)],'n')
 c=L.create_correction(db,ADMIN,base.id,new.id);db.commit()
 line=entries(db,entry_type='correction')[0]
 assert line.amount_cents==400
 assert line.owned_period=='2026-10'          # 所属期保留
 assert line.posting_period=='2026-11'        # 转入下一开放期
 assert c.status=='deferred'
 # 封账余额不被后续更正改变
 close=db.query(PeriodClose).filter_by(period='2026-10').one()
 assert close.closing_balance=={'光学研究':1000}

def test_span_multiple_closed_periods_finds_carry_period(db):
 base=make_run(db,'2026-09',[('光学研究','仪器维护',1000)],'b');L.post_original(db,base,ADMIN);db.commit()
 for p in ('2026-09','2026-10','2026-11'): L.close_period(db,ADMIN,p)
 db.commit()
 new=make_run(db,'2026-09',[('光学研究','仪器维护',1250)],'n')
 c=L.create_correction(db,ADMIN,base.id,new.id);db.commit()
 line=entries(db,entry_type='correction')[0]
 assert line.owned_period=='2026-09' and line.posting_period=='2026-12'

def test_all_periods_closed_creates_virtual_open_period(db):
 base=make_run(db,'2026-12',[('光学研究','仪器维护',1000)],'b');L.post_original(db,base,ADMIN);db.commit()
 for p in ('2026-09','2026-10','2026-11','2026-12'): L.close_period(db,ADMIN,p)
 db.commit()
 new=make_run(db,'2026-12',[('光学研究','仪器维护',1100)],'n')
 c=L.create_correction(db,ADMIN,base.id,new.id);db.commit()
 assert entries(db,entry_type='correction')[0].posting_period=='2027-01'

# ---------- 4. 更正连续衔接，禁止分支重复冲销 ----------
def test_chain_consecutive_no_branch(db):
 base=make_run(db,'2026-10',[('光学研究','仪器维护',1000)],'b');L.post_original(db,base,ADMIN);db.commit()
 n1=make_run(db,'2026-10',[('光学研究','仪器维护',1100)],'n1')
 c1=L.create_correction(db,ADMIN,base.id,n1.id);db.commit()
 n2=make_run(db,'2026-10',[('光学研究','仪器维护',1250)],'n2')
 c2=L.create_correction(db,ADMIN,base.id,n2.id);db.commit()
 assert c1.chain_seq==0 and c2.chain_seq==1 and c2.prev_correction_id==c1.id
 # 第二笔差额相对 n1 计算（连续衔接），而非相对原账
 assert {(x.department,x.amount_cents) for x in entries(db,correction_id=c2.id)}=={('光学研究',150)}
 tail=db.query(Correction).filter_by(base_run_id=base.id).count()
 assert tail==2
 # 链上序号唯一，分支无法插入重复 seq
 with pytest.raises(Exception):
  dup=Correction(idempotency_key='x',base_run_id=base.id,new_run_id=n2.id,chain_seq=1,
                 owned_period='2026-10',delta=[],delta_total=0)
  db.add(dup);db.commit()
 db.rollback()

# ---------- 5. 整笔调整不拆账：并发封账 ----------
def test_concurrent_close_and_correction_no_split(file_factory):
 """封账与更正并发：每笔更正的全部行必须在同一 posting_period，且无重复入账。"""
 from src.models.run import Run
 outcomes=[]
 s=file_factory();base=make_run(s,'2026-10',[('光学研究','仪器维护',1000),('材料研究','试验耗材',2000)],'b')
 L.post_original(s,base,ADMIN);s.commit();base_id=base.id;s.close()
 # 每个更正工作线程使用不同的新报告，保证各自差额非零；封账重复与无差额属业务拒绝，记录但不破坏一致性。
 def worker(do_close,idx):
  s=file_factory()
  try:
   base=s.query(Run).get(base_id)
   if do_close:
    L.close_period(s,ADMIN,'2026-10');s.commit()
   else:
    v=1700+idx*37
    run=make_run(s,'2026-10',[('光学研究','仪器维护',v),('材料研究','试验耗材',4300-v)],'n-%d'%idx)
    L.create_correction(s,ADMIN,base.id,run.id);s.commit()
  except HTTPException as e:
   outcomes.append(('business',e.status_code,str(e.detail)))
  except Exception as e:
   outcomes.append(('err',repr(e)))
  finally: s.close()
 threads=[threading.Thread(target=worker,args=(i%2==0,i)) for i in range(8)]
 for t in threads:t.start()
 for t in threads:t.join()
 assert not [o for o in outcomes if o[0]=='err'],outcomes  # 仅允许 409/422 业务拒绝，不允许系统错误
 verify=file_factory()
 # 幂等键全局唯一：无重复行
 keys=[r[0] for r in verify.query(LedgerEntry.idempotency_key).all()]
 assert len(keys)==len(set(keys))
 for c in verify.query(Correction).all():
  periods={r.posting_period for r in verify.query(LedgerEntry).filter_by(correction_id=c.id).all()}
  assert len(periods)==1,'出现拆账！'
 posted=verify.query(LedgerEntry).filter_by(posting_period='2026-10').all()
 close=verify.query(PeriodClose).filter_by(period='2026-10').first()
 if close:
  assert close.total_cents==sum(e.amount_cents for e in posted)
  assert close.entry_count==len(posted)
 verify.close()

def test_correction_landing_before_close_gets_published(db):
 base=make_run(db,'2026-10',[('光学研究','仪器维护',1000)],'b');L.post_original(db,base,ADMIN);db.commit()
 n=make_run(db,'2026-10',[('光学研究','仪器维护',1300)],'n')
 c=L.create_correction(db,ADMIN,base.id,n.id);db.commit()
 assert c.status=='posted'
 close=L.close_period(db,ADMIN,'2026-10');db.commit()
 # 封账把更正一并发布，余额含差额
 assert close.closing_balance=={'光学研究':1300}
 assert db.query(Correction).filter_by(id=c.id).one().status=='posted'
 assert all(e.posted for e in entries(db,posting_period='2026-10'))

# ---------- 6. 崩溃恢复：重试不重复入账 ----------
def test_crash_retry_correction_idempotent(db):
 base=make_run(db,'2026-10',[('光学研究','仪器维护',1000)],'b');L.post_original(db,base,ADMIN);db.commit()
 n=make_run(db,'2026-10',[('光学研究','仪器维护',1400)],'n')
 L.CRASH_POINTS.add('correction.before_commit')
 with pytest.raises(RuntimeError): L.create_correction(db,ADMIN,base.id,n.id)
 db.rollback()
 # 崩溃后无残留
 assert db.query(Correction).count()==0
 assert db.query(LedgerEntry).filter_by(entry_type='correction').count()==0
 # 重试成功且仅一份
 c=L.create_correction(db,ADMIN,base.id,n.id);db.commit()
 assert db.query(Correction).count()==1
 assert db.query(LedgerEntry).filter_by(entry_type='correction').count()==1
 # 再重试（同 base/new 组合）返回同一笔，不新增
 again=L.create_correction(db,ADMIN,base.id,n.id);db.commit()
 assert again.id==c.id
 assert db.query(LedgerEntry).filter_by(entry_type='correction').count()==1

def test_crash_retry_close_balance_published_atomically(db):
 base=make_run(db,'2026-10',[('光学研究','仪器维护',1000)],'b');L.post_original(db,base,ADMIN);db.commit()
 L.CRASH_POINTS.add('close.before_commit')
 with pytest.raises(RuntimeError): L.close_period(db,ADMIN,'2026-10')
 db.rollback()
 assert db.query(PeriodClose).filter_by(period='2026-10').count()==0
 assert not any(e.posted for e in entries(db))
 close=L.close_period(db,ADMIN,'2026-10');db.commit()
 assert close.status=='closed' and close.total_cents==1000
 assert all(e.posted for e in entries(db,posting_period='2026-10'))

def test_crash_retry_original_idempotent(db):
 r=make_run(db,'2026-10',[('光学研究','仪器维护',1000)],'r')
 L.CRASH_POINTS.add('original.before_commit')
 with pytest.raises(RuntimeError): L.post_original(db,r,ADMIN)
 db.rollback()
 assert db.query(LedgerEntry).count()==0
 L.post_original(db,r,ADMIN);db.commit()
 L.post_original(db,r,ADMIN);db.commit()
 assert db.query(LedgerEntry).count()==1

# ---------- 7. 报告链可追溯 ----------
def test_report_chain_traceability(db):
 base=make_run(db,'2026-10',[('光学研究','仪器维护',1000),('材料研究','试验耗材',2000)],'b')
 L.post_original(db,base,ADMIN);db.commit()
 L.close_period(db,ADMIN,'2026-10');db.commit()
 n=make_run(db,'2026-10',[('光学研究','仪器维护',1200),('材料研究','试验耗材',1800)],'n')
 c=L.create_correction(db,ADMIN,base.id,n.id);db.commit()
 view=L.report_chain(db,base.id)
 assert len(view['original_lines'])==2
 assert view['corrections'][0]['new_run_id']==n.id
 assert view['corrections'][0]['posting_period']=='2026-11'
 assert view['corrections'][0]['owned_period']=='2026-10'
 assert view['corrections'][0]['prev_correction_id'] is None

def test_reopen_allows_correction_in_owned_period(db):
 base=make_run(db,'2026-10',[('光学研究','仪器维护',1000)],'b');L.post_original(db,base,ADMIN);db.commit()
 L.close_period(db,ADMIN,'2026-10');db.commit()
 L.reopen_period(db,ADMIN,'2026-10','差错重开');db.commit()
 n=make_run(db,'2026-10',[('光学研究','仪器维护',1100)],'n')
 c=L.create_correction(db,ADMIN,base.id,n.id);db.commit()
 assert entries(db,entry_type='correction')[0].posting_period=='2026-10'
