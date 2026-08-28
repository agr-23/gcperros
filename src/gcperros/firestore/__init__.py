"""Estado vivo por partido en Firestore (HU-15).

Publica el estado que ya mantiene ``gcperros.engine`` en un único documento
por partido, denormalizado, para que un dashboard lo consuma con un listener
en tiempo real (``onSnapshot``) en vez de sondear (*polling*). Es la mitad que
le corresponde a este repositorio: el dashboard mismo vive fuera de GCP (ver
el diagrama de arquitectura en el README) y su contrato de consumo es
justamente el documento que este paquete escribe.

Por qué un documento por partido, y no uno por evento, está en
``docs/decisiones-de-diseno.md``, sección 11: en corto, un documento por
evento obligaría al dashboard a leer todo el historial del partido para saber
el estado actual, y cada una de esas lecturas cuenta contra la cuota gratis
diaria de Firestore. Un único documento que se sobrescribe reduce esa lectura
a una sola, más lo que el listener empuje mientras siga conectado.

Estructura, en el mismo orden que ``gcperros.loading`` (la contraparte hacia
BigQuery, HU-14), que resuelve un problema simétrico —persistir el estado de
un componente interno en un servicio externo—:

- ``document.py``  — la forma exacta del documento (``LiveMatchDocument``) y
  cómo se deriva del estado del motor.
- ``store.py``      — protocolo de persistencia (``DocumentStore``) y su
  doble en memoria, para pruebas.
- ``client.py``     — adaptador real hacia Firestore.
- ``publisher.py``  — cuándo se publica: en cada evento que de verdad cambió
  el estado, ni antes ni con un reloj aparte. Ver la sección 11 para por qué
  se descartó publicar con un temporizador.
"""

from __future__ import annotations
