create table if not exists public.backtest_runs (
    run_id text primary key,
    strategy text not null,
    as_of_date date not null,
    max_targets integer not null default 0,
    snapshot_rows integer not null default 0,
    dragon_count integer not null default 0,
    hidden_count integer not null default 0,
    combined_count integer not null default 0,
    diagnostics jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists public.backtest_snapshot_rows (
    run_id text not null references public.backtest_runs(run_id) on delete cascade,
    as_of_date date not null,
    stock_id text not null,
    branch_label text not null default '',
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    primary key (run_id, stock_id)
);

create index if not exists backtest_runs_strategy_created_at_idx
    on public.backtest_runs(strategy, created_at desc);

create index if not exists backtest_snapshot_rows_as_of_date_idx
    on public.backtest_snapshot_rows(as_of_date);

create index if not exists backtest_snapshot_rows_stock_id_idx
    on public.backtest_snapshot_rows(stock_id);
