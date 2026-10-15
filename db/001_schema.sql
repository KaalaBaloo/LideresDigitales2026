-- Hora Valle + Efecto Sombra — esquema inicial (Supabase / Postgres 15)
-- Convenciones:
--   * Tablas madrid_*: datos REALES de datos.madrid.es con procedencia
--     (source_dataset, source_resource, loaded_at).
--   * Tablas del comercio: columna synthetic NOT NULL (true = dato sintético de demo).
--   * Nunca se almacenan imágenes ni datos personales: solo agregados.

create table if not exists ingest_runs (
  id            bigserial primary key,
  connector     text not null,
  source_dataset text not null,
  source_resource text,
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  rows_loaded   integer,
  status        text not null default 'running',
  detail        jsonb
);

-- ---------------------------------------------------------------- Aforos peatonales
create table if not exists madrid_stations (
  station_id      text primary key,           -- p. ej. PERM_PEA02_PM01
  address         text,
  district        text,
  notes           text,
  lat             double precision,
  lon             double precision,
  source_dataset  text not null,
  source_resource text not null,
  loaded_at       timestamptz not null default now()
);

create table if not exists madrid_ped_counts (
  station_id      text not null references madrid_stations(station_id) on delete cascade,
  ts              timestamp not null,          -- hora local de Madrid
  pedestrians     integer not null,
  source_dataset  text not null,
  source_resource text not null,
  loaded_at       timestamptz not null default now(),
  primary key (station_id, ts)
);

-- Curva patrón: estación × día de la semana (0=lunes) × hora
create table if not exists madrid_ped_patterns (
  station_id      text not null references madrid_stations(station_id) on delete cascade,
  dow             smallint not null check (dow between 0 and 6),
  hour            smallint not null check (hour between 0 and 23),
  mean            double precision not null,
  p30             double precision not null,
  p70             double precision not null,
  n_obs           integer not null,
  period_from     date not null,
  period_to       date not null,
  source_dataset  text not null,
  source_resource text not null,
  loaded_at       timestamptz not null default now(),
  primary key (station_id, dow, hour)
);

-- ---------------------------------------------------------------- Censo de locales
create table if not exists madrid_shops (
  id_local        text not null,
  id_epigrafe     text not null default '',
  rotulo          text,
  street          text,
  street_number   text,
  district        text,
  barrio          text,
  seccion         text,
  division        text,
  epigrafe        text,
  utm_x           double precision,
  utm_y           double precision,
  lat             double precision,
  lon             double precision,
  source_dataset  text not null,
  source_resource text not null,
  loaded_at       timestamptz not null default now(),
  primary key (id_local, id_epigrafe)
);
create index if not exists madrid_shops_latlon on madrid_shops (lat, lon);

create table if not exists madrid_terraces (
  id_terraza      text primary key,
  id_local        text,
  rotulo          text,
  location        text,
  lat             double precision,
  lon             double precision,
  tables_count    integer,
  chairs_count    integer,
  hours           jsonb,
  source_dataset  text not null,
  source_resource text not null,
  loaded_at       timestamptz not null default now()
);
create index if not exists madrid_terraces_latlon on madrid_terraces (lat, lon);

-- ---------------------------------------------------------------- Agenda
create table if not exists madrid_events (
  event_id        text primary key,
  title           text,
  starts_at       timestamp,
  ends_at         timestamp,
  hour            text,
  venue           text,
  district        text,
  free            boolean,
  event_type      text,
  lat             double precision,
  lon             double precision,
  source_dataset  text not null,
  source_resource text not null,
  loaded_at       timestamptz not null default now()
);
create index if not exists madrid_events_start on madrid_events (starts_at);

-- ---------------------------------------------------------------- Meteorología
create table if not exists madrid_weather_stations (
  station_code    text primary key,            -- CODIGO_CORTO (p. ej. 4)
  name            text,
  lat             double precision,
  lon             double precision,
  magnitudes      text[],
  source_dataset  text not null,
  source_resource text not null,
  loaded_at       timestamptz not null default now()
);

create table if not exists madrid_weather_hourly (
  station_code    text not null,
  ts              timestamp not null,
  magnitude       smallint not null,           -- 83=T(ºC) 89=precip(l/m2) 86=HR
  value           double precision not null,
  source_dataset  text not null,
  source_resource text not null,
  loaded_at       timestamptz not null default now(),
  primary key (station_code, ts, magnitude)
);

-- ---------------------------------------------------------------- Aparcamientos
-- Inventario de plazas (denominador para el % de ocupación del servicio en tiempo real,
-- que se consulta en vivo por SOAP y se empareja por cercanía de coordenadas).
create table if not exists madrid_parking_capacity (
  code            text primary key,
  name            text,
  parking_type    text,
  spaces_rotation integer,
  spaces_total    integer,
  lat             double precision,
  lon             double precision,
  source_dataset  text not null,
  source_resource text not null,
  loaded_at       timestamptz not null default now()
);

-- ================================================================ Comercio (sintético)
create table if not exists shops (
  id               serial primary key,
  census_id_local  text,                        -- local REAL del Censo
  name             text not null,
  street           text,
  lat              double precision not null,
  lon              double precision not null,
  station_id       text references madrid_stations(station_id),  -- estación más cercana
  main_station_id  text references madrid_stations(station_id),  -- calle principal (Efecto Sombra)
  role             text not null default 'main' check (role in ('main','lateral')),
  capacity         integer,                     -- aforo
  conversion_ref   jsonb not null default '{}', -- segmento -> tasa de entrada de referencia
  avg_ticket       jsonb not null default '{}', -- segmento -> € por grupo
  audience         jsonb not null default '{}', -- mezcla de público observada
  vetoed_offers    text[] not null default '{}',
  -- Perfil (pantalla "Tu comercio"): tipo, horario, franja preferida, público objetivo,
  -- descuento máximo, productos elegibles, canal y duración máxima de campaña.
  profile          jsonb not null default '{}',
  door_line        jsonb not null default '{"p1":[0.0,0.62],"p2":[1.0,0.62],"inside":"below"}',
  synthetic        boolean not null
);

create table if not exists sensor_aggregates (
  shop_id           integer not null references shops(id) on delete cascade,
  day               date not null,
  hour              smallint not null check (hour between 0 and 23),
  segment           text not null,
  groups_passing    integer not null default 0,
  groups_entering   integer not null default 0,
  people_passing    integer not null default 0,
  people_entering   integer not null default 0,
  odd_groups        integer not null default 0,  -- grupos de tamaño impar (pasan + entran)
  frames            integer not null default 0,
  synthetic         boolean not null,
  updated_at        timestamptz not null default now(),
  primary key (shop_id, day, hour, segment, synthetic)
);

create table if not exists sensor_eval (
  id              bigserial primary key,
  shop_id         integer references shops(id) on delete cascade,
  created_at      timestamptz not null default now(),
  frame_name      text,
  count_true      integer,
  count_pred      integer,
  segment_match   double precision,             -- fracción de grupos con segmento correcto
  synthetic       boolean not null default true
);

create table if not exists campaigns (
  id            serial primary key,
  shop_id       integer not null references shops(id) on delete cascade,
  offer_type    text not null,
  starts_at     timestamp not null,
  ends_at       timestamp not null,
  context       jsonb not null default '{}',     -- franja, día, segmento dominante, paridad, evento, clima, competencia
  status        text not null default 'active' check (status in ('active','closed')),
  synthetic     boolean not null,
  created_at    timestamptz not null default now()
);

create table if not exists tickets (
  id            bigserial primary key,
  shop_id       integer not null references shops(id) on delete cascade,
  ts            timestamp not null,
  amount        numeric(10,2) not null,
  group_size    smallint,
  segment       text,
  campaign_id   integer references campaigns(id) on delete set null,
  redeemed      boolean not null default false,  -- canje de la promo
  synthetic     boolean not null
);
create index if not exists tickets_shop_ts on tickets (shop_id, ts);

create table if not exists campaign_results (
  campaign_id   integer primary key references campaigns(id) on delete cascade,
  entries       integer,
  revenue       numeric(12,2),
  avg_ticket    numeric(10,2),
  baseline      jsonb,
  uplift        double precision,
  success       boolean,
  diagnosis     jsonb,
  synthetic     boolean not null,
  computed_at   timestamptz not null default now()
);

create table if not exists bandit_arms (
  shop_id       integer not null references shops(id) on delete cascade,
  franja        text not null,
  segment       text not null,
  offer_type    text not null,
  alpha         double precision not null default 1,
  beta          double precision not null default 1,
  primary key (shop_id, franja, segment, offer_type)
);

create table if not exists notifications (
  id            bigserial primary key,
  shop_id       integer not null references shops(id) on delete cascade,
  created_at    timestamptz not null default now(),
  day           date not null,
  hour          smallint not null,
  payload       jsonb not null,                 -- diagnóstico + recomendación (lo único que ve el LLM)
  text          text not null,
  text_source   text not null check (text_source in ('claude','template')),
  status        text not null default 'new',
  synthetic     boolean not null,
  unique (shop_id, day, hour)
);
