"""跨期更正账簿核心服务。

账簿纪律：
1. 已复核报告首次入账（original），原账永久保留，更正只追加差额（correction），不做红字冲销。
2. 更正差额 = 新报告部门费用 − 基准（首入或上一笔更正后）部门费用；prev 指针串成单链，禁止分支。
3. 所属期已封账时，差额转下一开放期入账，但 owned_period 永远保留费用所属期。
4. 同期间封账与更正并发：整笔调整要么进封账前账期，要么整体转下期，不拆账。
5. 跨多个已封账期：沿期间字典顺序找到第一个开放期承接。
6. 全部写入以幂等键 + 事务保护，崩溃重试不重复入账；封账余额与账簿发布同事务生效。
"""
import time
from fastapi import HTTPException
from sqlalchemy import text
from src.models.run import Run
from src.models.ledger import PeriodClose,Correction,LedgerEntry
from src.services.audit import log

ORIGINAL='original';CORRECTION='correction'
POSTED='posted';DEFERRED='deferred';SUPERSEDED='superseded'

# 故障注入点：测试把名称放入该集合，服务执行到对应点时抛出，模拟进程崩溃（事务回滚）。
CRASH_POINTS=set()
def _crash(name):
 if name in CRASH_POINTS:
  CRASH_POINTS.discard(name)
  raise RuntimeError('injected crash @ '+name)

def _transaction_lock(db):
 """串行化封账与更正事务：PostgreSQL 用事务级咨询锁，SQLite 用保留表锁。
 同一把锁保证“整笔调整要么进封账前账期、要么转下期”的判定与落库原子。
 SQLite 若已存在 DEFERRED 读事务，则升级为保留写锁（无待写变更，升级安全）。"""
 dialect=db.bind.dialect.name
 if dialect=='postgresql':
  db.execute(text('SELECT pg_advisory_xact_lock(912741)'))
 else:
  raw=db.connection().connection
  if raw.in_transaction:
   # 已有 DEFERRED 读事务（调用方先做过查询）：升级为保留写锁；无待写变更，升级安全。
   db.execute(text('COMMIT'))
   db.execute(text('BEGIN IMMEDIATE'))
  else:
   # 自动提交模式：直接以保留写锁开始，真正串行化。
   db.execute(text('BEGIN IMMEDIATE'))

def _period_names(db):
 """按字典序稳定排列的全部期间（来源期间 ∪ 已有封账期 ∪ 分录期）。"""
 from src.models.source import Source
 names={x.data['period'] for x in db.query(Source).all()}
 names|={x.period for x in db.query(PeriodClose).all()}
 names|={x.owned_period for x in db.query(LedgerEntry).all()}
 names|={x.posting_period for x in db.query(LedgerEntry).all()}
 return sorted(names)

def is_closed(db,period):
 return db.query(PeriodClose).filter_by(period=period,status='closed').first() is not None

def _closed_periods(db):
 return {x.period for x in db.query(PeriodClose).filter_by(status='closed').all()}

def next_open_period(db,owned_period):
 """承接期：所属期未封账则用自身；否则沿期间顺序找第一个开放期；
 全部封账（或中间无开放期）时按所属期逐月推进到开放期，可跨越多个已封账期。"""
 if not is_closed(db,owned_period): return owned_period
 known=_period_names(db)
 for name in known:
  if name>owned_period and not is_closed(db,name): return name
 candidate=_bump_period(owned_period)
 while is_closed(db,candidate): candidate=_bump_period(candidate)
 return candidate

def _bump_period(period):
 parts=period.split('-')
 if len(parts)==2 and parts[1].isdigit():
  y,m=int(parts[0]),int(parts[1]);m+=1
  if m==13: y+=1;m=1
  return f'{y:04d}-{m:02d}'
 return period+'-next'

def _pivot(run):
 """报告结果透视 -> {(部门,费用类别): 金额分}。"""
 out={}
 for r in (run.result or {}).get('rows',[]):
  out[(r['部门'],r['费用类别'])]=out.get((r['部门'],r['费用类别']),0)+r['分摊金额分']
 return out

def _delta_lines(base_pivot,new_pivot):
 keys=sorted(set(base_pivot)|set(new_pivot))
 lines=[{'department':d,'category':c,'delta_cents':new_pivot.get((d,c),0)-base_pivot.get((d,c),0)}
        for d,c in keys]
 return [x for x in lines if x['delta_cents']!=0]

def _effective_pivot(run):
 """首入基准 = 已复核报告自身透视。"""
 return _pivot(run)

def _chain_tail(db,base_run_id):
 return db.query(Correction).filter_by(base_run_id=base_run_id).order_by(Correction.chain_seq.desc()).first()

def post_original(db,run,actor):
 """已复核报告首次入账；幂等：重试不重复。"""
 key=f'original:run:{run.id}'
 if db.query(LedgerEntry).filter_by(run_id=run.id,entry_type=ORIGINAL).first():
  return db.query(LedgerEntry).filter_by(run_id=run.id,entry_type=ORIGINAL).all()
 if not run.approved or run.status!='completed':
  raise HTTPException(409,'仅已复核报告可首次入账')
 owned=run.snapshot.get('period','全部')
 pivot=_effective_pivot(run)
 if not pivot: raise HTTPException(409,'报告无透视结果，无法入账')
 now=time.time();entries=[]
 for (dept,cat),amount in sorted(pivot.items()):
  e=LedgerEntry(entry_type=ORIGINAL,run_id=run.id,correction_id=None,
                owned_period=owned,posting_period=owned,department=dept,category=cat,
                amount_cents=amount,posted=False,idempotency_key=f'{key}:{dept}:{cat}',created_at=now)
  db.add(e);entries.append(e)
 _crash('original.before_commit')
 log(db,getattr(actor,'email',actor),'ledger.original',f'run={run.id} period={owned} lines={len(entries)}')
 return entries

def _correction_key(base_run_id,new_run_id,seq):
 return f'correction:base={base_run_id}:new={new_run_id}:seq={seq}'

def create_correction(db,user,base_run_id,new_run_id,note=''):
 """以新报告对基准报告做跨期更正；整笔同事务，封账则整体转下期，不拆账。"""
 _transaction_lock(db)
 base=db.get(Run,base_run_id);new=db.get(Run,new_run_id)
 if not base or not new: raise HTTPException(404,'基准或新报告不存在')
 for r,label in ((base,'基准报告'),(new,'新报告')):
  if not r.approved or r.status!='completed': raise HTTPException(409,label+'须为已复核报告')
 if base.id==new.id: raise HTTPException(422,'新报告不能与基准报告相同')
 owned=base.snapshot.get('period','全部')
 if new.snapshot.get('period','全部')!=owned: raise HTTPException(422,'两份报告费用所属期不一致，不能跨期更正')
 # 崩溃恢复/网络重试：同 base+new 组合已存在则原样返回，不重复入账。
 prior=db.query(Correction).filter_by(base_run_id=base_run_id,new_run_id=new_run_id).order_by(Correction.id.desc()).first()
 if prior: return prior
 # 全流程禁止 autoflush：并发下待写对象不能被链查询/封账查询提前刷库，只在取 id 时显式 flush。
 with db.no_autoflush:
  tail=_chain_tail(db,base_run_id)
  seq=(tail.chain_seq+1) if tail else 0
  key=_correction_key(base_run_id,new_run_id,seq)
  existing=db.query(Correction).filter_by(idempotency_key=key).first()
  if existing: return existing                      # 崩溃恢复重试：直接返回既有更正
  # 基准透视：首笔用原报告；其后沿链使用上一笔更正所依据的新报告（连续衔接）。
  ref_run=db.get(Run,tail.new_run_id) if tail else base
  base_pivot=_pivot(ref_run);new_pivot=_pivot(new)
  lines=_delta_lines(base_pivot,new_pivot)
  if not lines: raise HTTPException(422,'新旧报告部门费用无差额，无需更正')
  delta_total=sum(x['delta_cents'] for x in lines)
  # 封账判定在落库前完成：一旦决定转下期，整笔所有行进同一个 posting_period。
  target=next_open_period(db,owned)
  deferred=target!=owned
  corr=Correction(idempotency_key=key,base_run_id=base_run_id,new_run_id=new_run_id,
                  prev_correction_id=tail.id if tail else None,chain_seq=seq,owned_period=owned,
                  status=DEFERRED if deferred else POSTED,delta=lines,delta_total=delta_total,
                  created_by=user.email,created_at=time.time(),note=note)
  db.add(corr);db.flush()                            # 取 corr.id，唯一约束冲突在此显式暴露
  now=time.time()
  for i,line in enumerate(lines):
   db.add(LedgerEntry(entry_type=CORRECTION,run_id=new_run_id,correction_id=corr.id,
                      owned_period=owned,posting_period=target,department=line['department'],
                      category=line['category'],amount_cents=line['delta_cents'],posted=False,
                      idempotency_key=f'{key}:line={i}',created_at=now))
 _crash('correction.before_commit')
 log(db,user.email,'ledger.correction',f'base={base_run_id} new={new_run_id} seq={seq} target={target} lines={len(lines)} deferred={deferred}')
 return corr

def close_period(db,user,period):
 """封账：发布该期全部未发布分录并冻结余额，同事务生效。
 与更正并发时，已落库进本期的整笔随本次封账发布；未落库的更正随后只能转下期。"""
 _transaction_lock(db)
 existing=db.query(PeriodClose).filter_by(period=period).first()
 if existing and existing.status=='closed': raise HTTPException(409,f'期间 {period} 已封账')
 entries=db.query(LedgerEntry).filter_by(posting_period=period).order_by(LedgerEntry.id).all()
 balance={};total=0
 for e in entries:
  e.posted=True
  balance[e.department]=balance.get(e.department,0)+e.amount_cents;total+=e.amount_cents
 if existing:
  existing.status='closed';existing.closing_balance=balance;existing.total_cents=total
  existing.entry_count=len(entries);existing.closed_by=user.email;existing.closed_at=time.time()
  close=existing
 else:
  close=PeriodClose(period=period,status='closed',closing_balance=balance,total_cents=total,
                    entry_count=len(entries),closed_by=user.email,closed_at=time.time())
  db.add(close)
 # 整笔更正若全部落在本期并随本次发布，标记 posted；转下期的保持 deferred。
 for c in db.query(Correction).filter_by(owned_period=period).all():
  rows=db.query(LedgerEntry).filter_by(correction_id=c.id).all()
  if rows and all(r.posting_period==period and r.posted for r in rows): c.status=POSTED
 _crash('close.before_commit')
 log(db,user.email,'period.close',f'period={period} entries={len(entries)} total={total}')
 return close

def reopen_period(db,user,period,note):
 close=db.query(PeriodClose).filter_by(period=period,status='closed').first()
 if not close: raise HTTPException(404,'该期间未封账')
 close.status='reopened';close.reopen_note=note
 log(db,user.email,'period.reopen',f'period={period} note={note}')
 return close

def balances(db,period=None):
 """账簿余额视图：按入账期汇总各部门已发布/全部金额。"""
 q=db.query(LedgerEntry)
 if period: q=q.filter_by(posting_period=period)
 out={}
 for e in q.order_by(LedgerEntry.id).all():
  node=out.setdefault(e.posting_period,{})
  node[e.department]=node.get(e.department,0)+e.amount_cents
 return out

def report_chain(db,base_run_id):
 """报告链可追溯：首入 + 逐笔更正（基准/新报告、差额、承接期、状态）。"""
 base=db.get(Run,base_run_id)
 if not base: raise HTTPException(404,'报告不存在')
 originals=db.query(LedgerEntry).filter_by(run_id=base_run_id,entry_type=ORIGINAL).all()
 corrs=db.query(Correction).filter_by(base_run_id=base_run_id).order_by(Correction.chain_seq).all()
 chain=[]
 for c in corrs:
  rows=db.query(LedgerEntry).filter_by(correction_id=c.id).all()
  chain.append({'correction_id':c.id,'seq':c.chain_seq,'base_run_id':c.base_run_id,'new_run_id':c.new_run_id,
                'prev_correction_id':c.prev_correction_id,'owned_period':c.owned_period,
                'posting_period':rows[0].posting_period if rows else None,'status':c.status,
                'delta':c.delta,'delta_total':c.delta_total,'created_by':c.created_by,'note':c.note})
 return {'base_run_id':base_run_id,'owned_period':base.snapshot.get('period'),
         'original_lines':[{'department':e.department,'category':e.category,'amount_cents':e.amount_cents,
                            'posting_period':e.posting_period,'posted':e.posted} for e in originals],
         'corrections':chain}
