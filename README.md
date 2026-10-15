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

## Variables de entorno

Copia `.env.example` a `.env` para trabajar en local. **Nunca subas `.env`.**

| Variable | Dónde | Para qué |
|---|---|---|
| `DATABASE_URL` | API, GitHub Actions | Cadena del *pooler* de Supabase (puerto 6543, modo transacción) |
| `SUPABASE_URL`, `SUPABASE_KEY` | API (reservadas) | Identificación del proyecto; el backend accede por `DATABASE_URL` |
| `HF_TOKEN` | **solo** servicio edge (y `generate_test_frames.py` en local) | Token con permiso «Inference Providers» |
| `HF_PROVIDER`, `DETECTOR_MODEL`, `DETECTOR_THRESHOLD` | edge | `hf-inference`, `facebook/detr-resnet-50`, `0.7` |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | API | Redactor (por defecto `claude-opus-5-5`). Sin clave se usa la plantilla. |
| `CORS_ORIGINS` | API | p. ej. `https://<proyecto>.web.app,http://localhost:5173` |
| `EDGE_URL` / `API_URL` | API / edge | URL pública del otro servicio |
| `SENSOR_API_KEY` | API, edge, `send_frames.py` | Secreto compartido para `POST /sensor/aggregates` |
| `VITE_API_URL` | web (variable de GitHub `vars.VITE_API_URL`) | URL de la API |

## Despliegue (todo en la nube)

1. **Supabase**: crea un proyecto. En *Project Settings → Database* copia la cadena del *Transaction pooler* → `DATABASE_URL`.
2. **GitHub**: sube el repo y añade en *Settings → Secrets and variables → Actions*:
   - Secretos: `DATABASE_URL`, `FIREBASE_SERVICE_ACCOUNT`, `FIREBASE_PROJECT_ID`.
   - Variable: `VITE_API_URL` (la URL de la API, paso 4).
3. **Ingesta y datos de la demo**: en *Actions* ejecuta **ingest-madrid** (*Run workflow*; aplica las migraciones y carga los datos reales, ~1 min) y después **seed-synthetic-shops**. En el log del sembrado verás el `shop_id` del comercio de Fuencarral. A partir de ahí, el cron refresca los datos a diario (y los aforos, cada lunes).
4. **Render**: *New → Blueprint* sobre el repo (lee `render.yaml`) y rellena las variables marcadas `sync: false` en los dos servicios: `hora-valle-api` y `hora-valle-edge`. Comprueba `GET /health` en ambos.
5. **Firebase Hosting**: crea el proyecto en Firebase, pon su id en `.firebaserc` y genera una cuenta de servicio (`firebase init hosting:github` lo hace por ti, o desde *Google Cloud → IAM*). Cada *push* a `main` que toque `web/` despliega con **deploy-web**.
6. Añade la URL de Firebase a `CORS_ORIGINS` de la API.

## Imágenes de prueba (sintéticas)

Las imágenes **nunca** se envían a Claude ni a ningún LLM: solo al detector de personas.

```bash
python scripts/generate_test_frames.py
```

Genera 30 imágenes (6 categorías × 5) con FLUX.1-schnell y `data/test_frames/ground_truth.json`.
Necesita `HF_TOKEN`. Ejecútalo **una sola vez**, porque consume créditos. FLUX.1-schnell no está en
`hf-inference`; se usa el proveedor `auto` (hoy, `fal-ai` o `wavespeed`).

```bash
python scripts/review_ground_truth.py
```

Abre una página local que muestra cada imagen con sus etiquetas y permite corregirlas o excluirlas. Después, versiona `data/test_frames/` en el repo.

Plan B, con fotogramas reales de MOT20 (CC BY-NC-SA 3.0, uso académico; no se versionan):

```bash
python scripts/fetch_mot_frames.py
```

## Guion de demo (criterio de aceptación)

1. Abre la app (Firebase). En **Inicio** («Tu calle, hoy») elige un día de las últimas 4 semanas: verás las barras por segmento, la curva real de la estación `PERM_PEA02_PM01` (Fuencarral 22) y las franjas con pérdida en rojo. Con el comercio de la calle lateral de Gran Vía aparece la tarjeta **Efecto Sombra**.
2. **Aprendizajes**: 20 campañas pasadas entre los dos comercios. En Fuencarral, el **2x1 fracasa con grupos impares** («en un grupo de 3 alguien se queda fuera») y el **«20 % si entráis todos»** funciona.
3. Simula la cámara en directo con 10 imágenes sobre la franja de las 18:00 de hoy:

   ```bash
   python scripts/send_frames.py --edge https://hora-valle-edge.onrender.com --shop <ID_FUENCARRAL> --limit 10 --interval 5 --start "$(date +%F)T18:00"
   ```

   El script muestra los agregados enviados y la precisión frente al ground truth.
4. En **Alertas** («Una oferta para todos») aparece la notificación de las 18:00, redactada por Claude a partir solo del JSON agregado (o con la plantilla si no hay clave). Muestra el porqué (p. ej., grupos impares) y la oferta recomendada. Pulsa **Lanzar oferta**; en Aprendizajes podrás cerrarla y medir su resultado.
5. **Sensor demo**: sube una de las imágenes para ver cajas y grupos (personas difuminadas) y la línea de la puerta.
6. API documentada en `https://hora-valle-api.onrender.com/docs`.

Comprobaciones: `GET /sensor/eval?shop_id=<id>` (precisión del sensor), `GET /shops/<id>/notifications` y `GET /madrid/provenance` (última carga de cada dataset).

## Desarrollo local

```bash
python -m venv .venv
```

```bash
.venv/Scripts/pip install -r requirements-dev.txt
```

```bash
.venv/Scripts/python -m pytest -q
```

```bash
.venv/Scripts/python -m ingest.run --dry-run
```

`--dry-run` descarga y transforma los datos reales sin escribir en la BD.

```bash
uvicorn api.main:app --reload --port 8000
```

```bash
uvicorn edge.service:app --reload --port 8001
```

```bash
cd web && npm install && npm run dev
```

Para la web hace falta Node 20 o superior.
