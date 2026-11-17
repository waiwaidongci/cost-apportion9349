from sqlalchemy import Column,Integer,String,JSON,Text,Float,Boolean,UniqueConstraint,Index
from src.config.database import Base

class PeriodClose(Base):
 """账期封账记录：closed_at 与封账余额随账簿发布一起生效（同事务提交）。"""
 __tablename__='period_closes'
 id=Column(Integer,primary_key=True)
 period=Column(String(120),unique=True,nullable=False)
 status=Column(String(20),default='closed')            # closed / reopened
 closing_balance=Column(JSON,nullable=False)           # {部门: 余额分} 封账时点快照
 total_cents=Column(Integer,default=0)
 entry_count=Column(Integer,default=0)
 closed_by=Column(String(120))
 closed_at=Column(Float)
 reopen_note=Column(Text,default='')

class Correction(Base):
 """跨期更正：以已复核报告首次入账为基准，仅追加新旧部门费用差额，保留原账（不冲销）。
 prev_correction_id 串成单链，禁止分支重复冲销。"""
 __tablename__='corrections'
 id=Column(Integer,primary_key=True)
 idempotency_key=Column(String(160),unique=True,nullable=False)
 base_run_id=Column(Integer,nullable=False)            # 首次入账的已复核报告
 new_run_id=Column(Integer,nullable=False)             # 更正所依据的新报告
 prev_correction_id=Column(Integer,nullable=True)      # 同一 base 报告链上的上一笔更正
 chain_seq=Column(Integer,default=0)                   # 链上序号，0 表示首笔更正
 owned_period=Column(String(120),nullable=False)       # 费用所属期（永远保留）
 status=Column(String(20),default='posted')            # posted / deferred / superseded
 delta=Column(JSON,nullable=False)                     # [{department,category,delta_cents}]
 delta_total=Column(Integer,default=0)
 created_by=Column(String(120))
 created_at=Column(Float)
 note=Column(Text,default='')
 __table_args__=(UniqueConstraint('base_run_id','chain_seq',name='uq_correction_chain_seq'),
                 Index('ix_correction_prev','prev_correction_id'))

class LedgerEntry(Base):
 """账簿分录：original=已复核报告首次入账（保留原账）；correction=更正差额追加（仅差额）。
 整笔调整同进同出，不拆账：一笔更正的所有行同 posting_period、同状态。"""
 __tablename__='ledger_entries'
 id=Column(Integer,primary_key=True)
 entry_type=Column(String(20),nullable=False)          # original / correction
 run_id=Column(Integer,nullable=False)
 correction_id=Column(Integer,nullable=True)
 owned_period=Column(String(120),nullable=False)       # 费用所属期
 posting_period=Column(String(120),nullable=False)     # 实际入账期（封账则承接开放期）
 department=Column(String(120),nullable=False)
 category=Column(String(120),nullable=False)
 amount_cents=Column(Integer,nullable=False)           # original 为正；correction 为带符号差额
 posted=Column(Boolean,default=False)                  # 随封账/发布事务一起置真
 idempotency_key=Column(String(160),unique=True,nullable=False)
 created_at=Column(Float)
 __table_args__=(Index('ix_ledger_posting','posting_period','posted'),
                 Index('ix_ledger_owned','owned_period'),
                 Index('ix_ledger_corr','correction_id'))
