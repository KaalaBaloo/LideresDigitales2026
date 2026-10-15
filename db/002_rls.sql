-- La app web nunca habla con Supabase directamente: todo pasa por la API (rol postgres).
-- Activamos RLS sin políticas para que la API REST pública de Supabase (rol anon) no exponga nada.
do $$
declare t text;
begin
  foreach t in array array[
    'ingest_runs','madrid_stations','madrid_ped_counts','madrid_ped_patterns','madrid_shops',
    'madrid_terraces','madrid_events','madrid_weather_stations','madrid_weather_hourly',
    'madrid_parking_capacity','shops','sensor_aggregates','sensor_eval','campaigns','tickets',
    'campaign_results','bandit_arms','notifications']
  loop
    execute format('alter table %I enable row level security', t);
  end loop;
end $$;
