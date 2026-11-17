from fastapi import APIRouter,Depends
from src.config.database import database
from src.controllers.auth import current,admin,editor
from src.models.ledger import PeriodClose,Correction,LedgerEntry
from src.schemas.requests import CorrectionInput,CloseInput,ReopenInput
from src.services import ledger as service
from src.utils.serialize import row
router=APIRouter()

@router.get('/ledger/periods')
def period_status(db=Depends(database),u=Depends(current)):
 closes={x.period:row(x) for x in db.query(PeriodClose).all()}
 return [{'period':name,'closed':name in closes and closes[name]['status']=='closed',
          'close':closes.get(name)} for name in service._period_names(db)]

@router.post('/ledger/close')
def close(b:CloseInput,db=Depends(database),u=Depends(admin)):
 obj=service.close_period(db,u,b.period);db.commit();return row(obj)

@router.post('/ledger/reopen')
def reopen(b:ReopenInput,db=Depends(database),u=Depends(admin)):
 obj=service.reopen_period(db,u,b.period,b.note);db.commit();return row(obj)

@router.get('/ledger/entries')
def entries(period:str|None=None,db=Depends(database),u=Depends(current)):
 q=db.query(LedgerEntry).order_by(LedgerEntry.id)
 if period: q=q.filter(LedgerEntry.posting_period==period)
 return [row(x) for x in q.all()]

@router.get('/ledger/balances')
def balances(period:str|None=None,db=Depends(database),u=Depends(current)):
 return service.balances(db,period)

@router.post('/ledger/corrections')
def corrections(b:CorrectionInput,db=Depends(database),u=Depends(editor)):
 obj=service.create_correction(db,u,b.base_run_id,b.new_run_id,b.note);db.commit();return row(obj)

@router.get('/ledger/corrections')
def list_corrections(db=Depends(database),u=Depends(current)):
 return [row(x) for x in db.query(Correction).order_by(Correction.id).all()]

@router.get('/ledger/runs/{run_id}/chain')
def chain(run_id:int,db=Depends(database),u=Depends(current)):
 return service.report_chain(db,run_id)

@router.get('/ledger/closes')
def closes(db=Depends(database),u=Depends(current)):
 return [row(x) for x in db.query(PeriodClose).order_by(PeriodClose.id).all()]
