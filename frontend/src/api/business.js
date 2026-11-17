import {request} from './client.js';
const LOAD=[['sources','/sources'],['periods','/periods'],['policies','/policies'],['runs','/runs'],
 ['schedules','/schedules'],['deliveries','/deliveries'],['audits','/audits'],
 ['periodCloses','/ledger/periods'],['ledgerEntries','/ledger/entries'],
 ['corrections','/ledger/corrections'],['closes','/ledger/closes']];
export const loadAll=async()=>Object.fromEntries(await Promise.all(LOAD.map(async ([k,path])=>[k,await request(path)])));
export const saveSource=(data,id)=>request('/sources'+(id?'/'+id:''),id?'PUT':'POST',{data});
export const savePolicy=data=>request('/policies','POST',{data});
export const submitRun=data=>request('/runs','POST',data);
export const approveRun=(id,note)=>request('/runs/'+id+'/approve','POST',{note});
export const closePeriod=period=>request('/ledger/close','POST',{period});
export const reopenPeriod=(period,note)=>request('/ledger/reopen','POST',{period,note});
export const createCorrection=data=>request('/ledger/corrections','POST',data);
export const reportChain=runId=>request('/ledger/runs/'+runId+'/chain');
