# Atravia - Hora Valle + Efecto Sombra
Atravia ayuda a los comercios locales de Madrid a convertir en clientes a la gente que ya pasa por su puerta. Detecta cuántas personas pasan, en qué tipo de grupo y a qué hora, calcula la oportunidad perdida y propone la oferta que mejor encaja con ese público, aprendiendo de cada campaña.

Plataforma *smart city* para que los comercios locales de Madrid atraigan clientes con
promociones adaptadas al flujo peatonal, la hora y el **tipo de grupos** que pasan por su
puerta. Reto #31 · Cátedras Telefónica.

- **Datos de ciudad reales** de [datos.madrid.es](https://datos.madrid.es): se descubren en tiempo de ejecución vía CKAN.
- **Datos sintéticos** solo para el comercio (tickets, campañas) y las imágenes de cámara; siempre llevan `synthetic=true`.
- Arquitectura, flujos, lógica de IA, datasets, privacidad y riesgos: [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

```
/api      FastAPI (routers madrid, sensor, shops, campaigns, ai)        → Render: hora-valle-api
/edge     pipeline del dispositivo (detector, grupos, puerta)           → Render: hora-valle-edge
/ai       oportunidad, memoria, reglas (rules.yaml), bandit (offers.yaml), redactor
/ingest   conectores CKAN de datos.madrid.es                            → GitHub Actions (cron)
/db       migraciones SQL + db/migrate.py                               → Supabase
/web      PWA React + Vite                                              → Firebase Hosting
/scripts  generate_test_frames, review_ground_truth, send_frames, fetch_mot_frames, seed_synthetic_shop
/tests    pytest (agrupador, detector de oportunidad, reglas, bandit, redactor)
```
