// API实体字段约定：来源{id,natural_key,data}、口径{id,version,data}、报告{id,status,snapshot,checksum,result,approved}、计划{next_at,enabled}。
// 账簿：PeriodClose{period,status,closing_balance,total_cents,entry_count,closed_by,closed_at}、Correction{base_run_id,new_run_id,prev_correction_id,chain_seq,owned_period,status,delta,delta_total}、LedgerEntry{entry_type,run_id,correction_id,owned_period,posting_period,department,category,amount_cents,posted}。
export const ENTITY_KEYS=['sources','policies','runs','schedules','deliveries','ledgerEntries','corrections','closes'];
