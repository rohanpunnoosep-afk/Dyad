-- Brojans middle man schema (Postgres / Neon). Idempotent: safe to re-run.
-- Shapes follow json_formats.md. Prices are dollars.

-- The SKU/dollar schema replaced the old cents/tags one. Refuse to run on top of the old tables
-- instead of failing halfway; drop them by hand if that data is disposable.
do $$
begin
    if exists (select 1 from information_schema.columns
               where table_schema = current_schema() and table_name = 'items' and column_name = 'price_cents') then
        raise exception 'old Brojans schema found: drop tables events, analyses, item_heat, judgments, bundles, negotiations, items and re-run';
    end if;
end $$;

create table if not exists items (
    sku          text primary key,
    name         text not null,
    category     text not null,
    color        text not null,
    material     text not null,
    size         text not null,
    price        numeric(10, 2) not null check (price >= 0),
    stock        integer not null default 0 check (stock >= 0),
    image        text not null
);

create table if not exists negotiations (
    id           uuid primary key,
    buyer_input  text not null,
    brief        jsonb,
    status       text not null default 'pending',   -- pending | running | done | failed
    step         text not null default 'BRIEF',     -- see models.schemas.Step
    lease_owner  text,
    lease_until  timestamptz,
    error        text,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

create table if not exists bundles (
    id              uuid primary key,
    negotiation_id  uuid not null references negotiations(id) on delete cascade,
    round           integer not null,                -- 1 = the 5 bundles, 2 = final bundle
    name            text not null,
    skus            text[] not null,
    price           numeric(10, 2) not null,
    pitch           text not null,
    created_at      timestamptz not null default now()
);
create index if not exists bundles_negotiation_round on bundles (negotiation_id, round);

create table if not exists judgments (
    bundle_id       uuid primary key references bundles(id) on delete cascade,
    negotiation_id  uuid not null references negotiations(id) on delete cascade,
    round           integer not null,
    probability     real not null check (probability between 0 and 1),
    reason          text not null
);
alter table judgments add column if not exists price_score real;
alter table judgments add column if not exists fit_score real;
alter table judgments add column if not exists style_score real;
alter table judgments add column if not exists decision text;      -- accept | reject, final offer only

create table if not exists item_heat (
    negotiation_id  uuid not null references negotiations(id) on delete cascade,
    round           integer not null,
    sku             text not null,
    score           real not null,
    label           text not null,                   -- hot | neutral | cold
    bundle_count    integer not null,
    primary key (negotiation_id, round, sku)
);

create table if not exists analyses (
    negotiation_id  uuid not null references negotiations(id) on delete cascade,
    round           integer not null,
    payload         jsonb not null,                  -- models.schemas.RoundAnalysis
    primary key (negotiation_id, round)
);

create table if not exists events (
    id              bigserial primary key,
    negotiation_id  uuid not null references negotiations(id) on delete cascade,
    type            text not null,
    payload         jsonb not null,
    ts              timestamptz not null default now()
);
create index if not exists events_negotiation_id on events (negotiation_id, id);
