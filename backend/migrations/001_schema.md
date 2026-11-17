# 初始结构

SQLAlchemy启动创建以下业务表：costperiods, costentrys, allocationrules, allocationruns, delivery_schedules, deliveries、users、audits。Source专属JSON字段由对应validation严格校验；Policy为不可覆盖的版本记录；Run保存source/policy冻结快照；Period仅用于已有期间选择器，不计入核心复杂度。已有数据库升级需先备份，后续字段演进应以独立迁移执行。

# 002 跨期更正账簿

新增三张表，由 SQLAlchemy `create_all` 在启动时自动建立（仅增不改旧表，旧库安全）：

- `period_closes`：账期封账记录，唯一键 `period`；`closing_balance` 为封账时点部门余额快照，与分录发布在同一事务提交。
- `corrections`：跨期更正单链。`idempotency_key` 全局唯一（崩溃重试不重复），`(base_run_id, chain_seq)` 唯一禁止分支；`prev_correction_id` 串联同一基准报告的逐笔更正；`owned_period` 永久保留费用所属期。
- `ledger_entries`：账簿分录。`entry_type=original` 为已复核报告首次入账（原账永久保留），`correction` 为仅含差额的追加分录（带符号，无红字冲销）；`owned_period` 与 `posting_period` 分离，封账期差额整体转入下一开放期；`idempotency_key` 唯一。

并发纪律：PostgreSQL 使用事务级咨询锁 `pg_advisory_xact_lock(912741)` 串行化封账与更正；SQLite 使用 `BEGIN IMMEDIATE` 保留写锁。整笔更正的所有行同入一个入账期，不拆账。
