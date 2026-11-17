import {heading} from '../components/common/header.js';import {table} from '../components/common/table.js';import {esc,time,fmt} from '../utils/format.js';
const statusTag=v=>`<span class="tag tag-${esc(v)}">${({posted:'已入账',deferred:'转下期',closed:'已封账',reopened:'已重开'}[v]||esc(v))}</span>`;
export function ledger(c,d){
 const approved=d.runs.filter(r=>r.approved);
 const periodRows=d.periodCloses.map(p=>({期间:p.period,状态:p.closed?'已封账':'开放',分录数:p.close?.entry_count??0,封账合计分:p.close?.total_cents??0,封账人:p.close?.closed_by||'',封账时间:p.close?.closed_at?time(p.close.closed_at):'',封账余额:p.close?.closing_balance||{}}));
 const entryRows=d.ledgerEntries.map(e=>({编号:e.id,类型:e.entry_type==='original'?'原账首入':'更正差额',报告:e.run_id,更正:e.correction_id??'—',所属期:e.owned_period,入账期:e.posting_period,部门:e.department,费用类别:e.category,金额分:e.amount_cents,发布:e.posted?'是':'否'}));
 const corrRows=d.corrections.map(x=>({编号:x.id,链序:x.chain_seq,上一笔:x.prev_correction_id??'—',基准报告:x.base_run_id,新报告:x.new_run_id,所属期:x.owned_period,状态:statusTag(x.status),差额合计分:x.delta_total,差额明细:x.delta.map(z=>`${z.department}/${z.category}:${z.delta_cents}`).join('；'),操作人:x.created_by,说明:x.note||''}));
 return heading('CROSS-PERIOD LEDGER / 05','跨期更正账簿','已复核报告首次入账保留原账；更正仅追加新旧部门费用差额。封账期差额整体转下一开放期，所属期永久保留。')
 +`<form id="close-form" class="inline-form"><label>开放账期<select name="period">${d.periodCloses.filter(p=>!p.closed).map(p=>`<option>${esc(p.period)}</option>`).join('')||'<option value="">无开放账期</option>'}</select></label><button>封账并发布余额</button></form>`
 +`<form id="reopen-form" class="inline-form"><label>已封账期<select name="period">${d.closes.filter(x=>x.status==='closed').map(x=>`<option>${esc(x.period)}</option>`).join('')||'<option value="">无</option>'}</select></label><label>重开说明<input name="note" placeholder="至少2字" minlength="2" required></label><button>重开账期</button></form>`
 +`<h2>账期与封账依据</h2>${table(periodRows)}`
 +`<form id="correction-form" class="inline-form"><label>基准报告（首入账）<select name="base_run_id">${approved.map(r=>`<option value="${r.id}">#${r.id} ${esc(r.name)}（${esc(r.snapshot.period)}）</option>`).join('')}</select></label><label>更正新报告<select name="new_run_id">${approved.map(r=>`<option value="${r.id}">#${r.id} ${esc(r.name)}（${esc(r.snapshot.period)}）</option>`).join('')}</select></label><label>更正说明<input name="note" placeholder="可选，不超过2000字"></label><button>追加差额更正</button></form>`
 +`<h2>更正链（单链衔接，禁止分支冲销）</h2>${table(corrRows)}`
 +`<form id="chain-form" class="inline-form"><label>追溯报告链<select name="run_id">${approved.map(r=>`<option value="${r.id}">#${r.id} ${esc(r.name)}</option>`).join('')}</select></label><button>查看报告链</button></form><div id="chain-view"></div>`
 +`<h2>账簿分录（原账保留 + 差额追加，不拆账）</h2>${table(entryRows)}`;
}
export function chainView(chain){
 if(!chain)return '<p class="empty">选择报告查看首入账与逐笔更正链。</p>';
 const orig=chain.original_lines.map(x=>({部门:x.department,费用类别:x.category,首入金额分:x.amount_cents,入账期:x.posting_period,已发布:x.posted?'是':'否'}));
 const corr=chain.corrections.map(x=>({链序:x.seq,上一笔:x.prev_correction_id??'—',新报告:x.new_run_id,所属期:x.owned_period,承接入账期:x.posting_period,状态:statusTag(x.status),差额:x.delta.map(z=>`${z.department}/${z.category}:${z.delta_cents}`).join('；'),差额合计:x.delta_total,操作人:x.created_by,说明:x.note||''}));
 return `<h3>报告 #${chain.base_run_id} 追溯链 · 费用所属期 ${esc(chain.owned_period)}</h3><h4>首次入账（原账保留）</h4>${table(orig)}<h4>跨期更正（仅差额追加）</h4>${table(corr)}`;
}
