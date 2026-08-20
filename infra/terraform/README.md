# Infraestructura — Capa de ingestión (Pub/Sub)

Definición declarativa de la **capa de ingestión** de la arquitectura de cinco
capas: los dos topics de Pub/Sub que desacoplan a los generadores sintéticos del
motor de procesamiento, con sus suscripciones, sus topics de mensajes muertos y
las identidades que pueden publicar y consumir.

Corresponde a la **HU-13** (*"Infraestructura que es declarada, no clickeada"*) y
habilita la **HU-10** (publicación de los generadores) y la **HU-14** (consumidor
que persiste en la capa Raw de BigQuery).

> Cloud Run, Firestore y los datasets de BigQuery completan la HU-13 y se
> agregan en las historias que los introducen. Este directorio se despliega
> solo y no depende de ellos: ver *Qué falta* al final.

---

## 1. Qué crea exactamente

Por cada uno de los dos flujos —`match-events` y `odds-updates`— se crea:

| Recurso | Nombre | Para qué |
|---|---|---|
| Topic | `match-events` / `odds-updates` | Punto de entrega de los generadores |
| Suscripción *pull* | `<topic>-raw` | La consume el cargador de la capa Raw (HU-14) |
| Suscripción *push* | `<topic>-engine` | Entrega al motor en Cloud Run — **solo si ya existe el motor** |
| Topic de dead letter | `<topic>-dead-letter` | Mensajes que fallaron tras N intentos |
| Suscripción de dead letter | `<topic>-dead-letter-sub` | Retiene los muertos para inspección manual |

Más tres identidades de privilegio mínimo:

| Service account | Permiso | Quién la usa |
|---|---|---|
| `gcperros-publisher` | `roles/pubsub.publisher` sobre ambos topics | Generadores sintéticos (HU-10) |
| `gcperros-raw-loader` | `roles/pubsub.subscriber` sobre las suscripciones `-raw` | Cargador de la capa Raw (HU-14) |
| `gcperros-ps-invoker` | `roles/run.invoker` sobre el motor | Pub/Sub, para firmar el token OIDC del push |

La tercera solo se crea cuando el motor está desplegado.

---

## 2. Qué se adaptó de la plantilla del curso, y por qué

El módulo `modules/pubsub/` es **el del profesor, sin una sola modificación**.
Los cambios están todos en la raíz, que es donde la plantilla espera que cada
proyecto exprese sus propias decisiones.

| Plantilla original | Aquí | Justificación |
|---|---|---|
| Un topic (`demo-dev-events`) | Dos topics, vía `for_each` sobre `local.streams` | La arquitectura tiene dos fuentes con dinámica temporal distinta: los eventos de juego llegan cada ~3 s de forma regular; las cuotas llegan en ráfagas reactivas. Separarlas permite escalarlas, retenerlas y auditarlas por separado. Un solo topic con un campo `tipo` mezclaría dos contratos de datos en un mismo canal. |
| Nombres con prefijo `demo-dev-` | Nombres literales del contrato (`match-events`, `odds-updates`) | Los generadores y el motor referencian estos nombres como parte del contrato de datos. El aislamiento entre ambientes se hace **por proyecto de GCP**, no por prefijo. La variable `resource_prefix` conserva el mecanismo del profesor por si se decide lo contrario. |
| Push a Cloud Run obligatorio | Push condicional (`engine_push_endpoint`) | El motor todavía no tiene imagen. En la plantilla, Pub/Sub depende del *output* de Cloud Run, así que no se puede desplegar la ingestión sola. Al pasar la URL por variable, la dependencia se rompe y esta capa se despliega hoy, sin código muerto ni un `hello world` desplegado solo para satisfacer una referencia. |
| Cloud Run + Cloud Storage en la raíz | Fuera de la raíz por ahora | Cloud Storage no aparece en nuestra arquitectura (la persistencia es Firestore + BigQuery). Sus módulos quedan en `modules/`, intactos y listos para las historias que los necesiten. |
| SA de ejecución con llave | Suplantación, sin llaves | La matriz de riesgos del proyecto declara *"prohibición de credenciales en el repositorio"*. Ninguna SA de aquí emite una llave JSON descargable. |
| `.terraform.lock.hcl` ignorado | **Versionado** | Fija el hash exacto del provider para todo el equipo. Es el equivalente en infraestructura de la semilla fija de los generadores; sin él, "reproducible" es una intención y no una garantía. El propio Terraform lo recomienda al ejecutar `init`. |

### Dos decisiones que conviene poder defender

**`enable_message_ordering = false`.** Es una decisión, no un olvido. Activar las
claves de ordenamiento de Pub/Sub serializaría la entrega y ocultaría justamente
el fenómeno que el motor debe resolver por sí mismo: el desorden temporal, que se
corrige con marcas de agua sobre `event_time` (HU-12). El desorden es premisa de
diseño del proyecto —el broker entrega *at-least-once* y sin orden— y suprimirlo
en la capa de ingestión vaciaría de contenido la validación de la HU-12.

**Dead letter además del repositorio de eventos inválidos (HU-16).** No se
solapan: la HU-16 aísla lo que **incumple el contrato de datos** (esquema, campos
obligatorios) y lo rechaza en la frontera, antes de gastar cómputo. El dead
letter recoge lo que es **contractualmente válido pero el motor no logró
procesar** tras varios intentos. Causas distintas, repositorios distintos.

---

## 3. Requisitos previos

- **Terraform ≥ 1.5** — <https://developer.hashicorp.com/terraform/install>
- **Google Cloud CLI** — <https://cloud.google.com/sdk/docs/install>
- Un proyecto de GCP con **facturación vinculada** y rol `roles/owner`
  (o, como mínimo: `serviceusage.serviceUsageAdmin`, `pubsub.admin`,
  `iam.serviceAccountAdmin`, `resourcemanager.projectIamAdmin`).

```bash
gcloud auth login                                   # sesión personal
gcloud auth application-default login               # credenciales que consume Terraform
gcloud config set project TU_PROJECT_ID
gcloud auth application-default set-quota-project TU_PROJECT_ID
```

> Configura además un **presupuesto con alertas** en Facturación → Presupuestos.
> La matriz de riesgos del proyecto compromete alertas al 25 %, 50 % y 75 % del
> crédito educativo.

---

## 4. Desplegar

```bash
cd infra/terraform

cp terraform.tfvars.example terraform.tfvars   # y edita project_id
terraform init
terraform validate
terraform plan -out=tfplan                     # revisar SIEMPRE antes de aplicar
terraform apply tfplan
```

Con `engine_push_endpoint` sin definir, el plan crea **12 recursos**: 2 topics,
2 topics de dead letter, 4 suscripciones, 2 service accounts y las
autorizaciones IAM correspondientes. No hay nada que facture mientras no se
publiquen mensajes.

Salidas:

```bash
terraform output topic_names
terraform output subscriptions
terraform output publisher_service_account
```

---

## 5. Verificar que la capa funciona

```bash
# Publicar un evento de prueba
gcloud pubsub topics publish match-events \
  --message='{"event_id":"test-1","event_type":"pass","match_id":"m-001"}'

# Consumirlo desde la suscripción pull
gcloud pubsub subscriptions pull match-events-raw --auto-ack --limit=5

# Lo mismo para el flujo de cuotas
gcloud pubsub topics publish odds-updates --message='{"market":"1x2","home":2.10}'
gcloud pubsub subscriptions pull odds-updates-raw --auto-ack --limit=5
```

### Publicar sin llaves JSON

Los generadores corren fuera de GCP. En lugar de descargar una llave de la
service account —que tarde o temprano termina en el repositorio— se usa
suplantación:

```bash
# Concede, una sola vez, el derecho a suplantar a quien va a ejecutar
gcloud iam service-accounts add-iam-policy-binding \
  $(terraform output -raw publisher_service_account) \
  --member="user:TU_CORREO@eafit.edu.co" \
  --role="roles/iam.serviceAccountTokenCreator"

# A partir de ahí, el código local publica con la identidad de la SA
gcloud auth application-default login \
  --impersonate-service-account=$(terraform output -raw publisher_service_account)
```

---

## 6. Estado remoto (recomendado para trabajo en equipo)

Por defecto el estado queda en la máquina de quien aplica, lo que impide que
otro integrante planifique sobre la misma realidad.

```bash
gcloud storage buckets create gs://TU_PROJECT_ID-tfstate --location=us-central1
gcloud storage buckets update gs://TU_PROJECT_ID-tfstate --versioning
```

Luego descomenta el bloque `backend "gcs"` en `versions.tf`, ajusta el nombre y
ejecuta `terraform init -migrate-state`.

> El estado contiene la topología completa en texto plano. Está en `.gitignore`
> y no debe subirse nunca.

---

## 7. Destruir

```bash
terraform destroy
```

Las APIs habilitadas no se deshabilitan (`disable_on_destroy = false`), para no
romper otros recursos del mismo proyecto.

---

## 8. Costos

Pub/Sub tiene un nivel gratuito mensual de **10 GiB** de volumen de mensajes.
Un partido completo emite entre 1.200 y 1.500 eventos de unos pocos cientos de
bytes: del orden de **1 MB por partido**. El consumo real de esta capa durante
todo el semestre se mantiene holgadamente dentro del nivel gratuito.

Lo que sí factura es la **retención**: `topic_message_retention_duration` está
en 24 h, suficiente para reproducir un partido con `seek` sin volver a
publicarlo, y despreciable en almacenamiento.

---

## 9. Qué falta para cerrar la HU-13

| Pendiente | Historia | Qué hay que agregar |
|---|---|---|
| Servicio de Cloud Run del motor | HU-11 / HU-12 | Imagen en Artifact Registry, invocar `modules/cloud_run` y poner `engine_push_endpoint` en `terraform.tfvars` |
| Datasets de BigQuery (Raw) | HU-14 | `bigquery.tf` + `bigquery.googleapis.com` en `apis.tf` |
| Base de datos de Firestore | HU-15 | `firestore.tf` + `firestore.googleapis.com` en `apis.tf` |

Los módulos `modules/cloud_run/` y `modules/cloud_storage/` están presentes y sin
modificar, listos para invocarse cuando corresponda.
