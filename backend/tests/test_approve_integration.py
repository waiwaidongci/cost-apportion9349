import pytest
from fastapi import HTTPException
from src.models.ledger import LedgerEntry,PeriodClose
from src.services.report import approve
from src.services import ledger as L
from conftest import ADMIN,make_run

def test_approve_posts_original_in_same_commit(db):
 r=make_run(db,'2026-10',[('光学研究','仪器维护',1000),('材料研究','试验耗材',2000)],'r',approved=False)
 out=approve(db,ADMIN,r.id,'已核对口径与数值')
 assert out.approved is True
 rows=db.query(LedgerEntry).filter_by(run_id=r.id,entry_type='original').all()
 assert len(rows)==2 and all(x.posting_period=='2026-10' for x in rows)
 # 重复复核被拒，原账不翻倍
 with pytest.raises(HTTPException): approve(db,ADMIN,r.id,'再次复核')
 assert db.query(LedgerEntry).filter_by(run_id=r.id,entry_type='original').count()==2

def test_correction_after_close_chain_and_balance_consistency(db):
 # 端到端：首入→封账→更正转下期→再封承接期，验证两段余额各自守恒
 base=make_run(db,'2026-10',[('光学研究','仪器维护',1000),('材料研究','试验耗材',2000)],'b',approved=False)
 approve(db,ADMIN,base.id,'复核通过首入')
 close1=L.close_period(db,ADMIN,'2026-10');db.commit()
 assert close1.closing_balance=={'光学研究':1000,'材料研究':2000}
 n=make_run(db,'2026-10',[('光学研究','仪器维护',1400),('材料研究','试验耗材',1500)],'n')
 c=L.create_correction(db,ADMIN,base.id,n.id,'跨期更正');db.commit()
 assert c.status=='deferred'
 deferred=db.query(LedgerEntry).filter_by(entry_type='correction').all()
 assert {x.posting_period for x in deferred}=={'2026-11'} and len(deferred)==2
 close2=L.close_period(db,ADMIN,'2026-11');db.commit()
 # 承接期只含差额：+400 / -500，合计 -100
 assert close2.closing_balance=={'光学研究':400,'材料研究':-500} and close2.total_cents==-100
 # 原账封账余额不受影响
 assert db.query(PeriodClose).filter_by(period='2026-10').one().total_cents==3000
