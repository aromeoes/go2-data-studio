# Validación de la primera versión

Fecha local: 20 de septiembre de 2026. Pruebas extendidas hasta la madrugada UTC del 21.

Base: DimOS 0.0.14, `c1c3cdc9d2ee54ca72259465688395699d7d99a2`, checkout separado y sin modificaciones de fuente.

## Comprobado

* Compilación de producción React + TypeScript + Vite.
* Ruff sin errores y **12 pruebas automatizadas aprobadas**.
* Creación de un espacio desde la interfaz y persistencia tras reiniciar la aplicación.
* Importación de la grabación existente como copia independiente: 1,94 GB, 462,46 s, 0,2517 GB/min.
* Blueprint de siete módulos de DimOS, con un router Zenoh privado en loopback. Recibe LiDAR, RGB, odometría, TF y calibración desde replay; produce el mapa de ocupación y muestra posición y cámara.
* Exploración de fronteras en replay: el explorador publicó un destino y A* encontró una ruta. Esto valida el pipeline de software; el recorrido reproducido no cambia con las órdenes.
* Transición de exploración a Teleop mientras continuaba la grabación.
* Grabación y cierre de un segmento derivado de replay: **895 nubes LiDAR en 116,45 s**, aproximadamente **0,47 GB**, sin descartes informados por el grabador. El flujo incluye cámara, poses, TF y calibración.
* Reconstrucción completa en CPU con PGO, tanto por CLI como a través de la API de trabajos. La versión exportada contiene **77.110 puntos**. Se generaron PointCloud2 y `inspection.rrd` en una carpeta de versión propia.
* Informe de calidad visible: **3.368 nubes**, **99,8% con pose**, **un hueco mayor a 1 s** en LiDAR. Cobertura total y precisión absoluta se muestran como no medidas.
* HumanCLI local en replay: «andá hasta el fondo» produjo una solicitud de destino y «pará» detuvo el control.
* Un comando Teleop de una época anterior fue rechazado. La liberación de una interfaz antigua no canceló la nueva autoridad; el heartbeat de la autoridad actual siguió vigente.
* Prueba con procesos reales de cierre del runtime cuando desaparece su supervisor, y caducidad de control después de suspender la Mac.
* Pruebas de caducidad de control, parada enclavada, velocidades no finitas, origen HTTP, encabezados de mutación, copia de datos, acceso a archivos, recuperación de catálogo, segmentación al perder el robot y rechazo de estados de control atrasados.
* Inspección visual del tablero en el navegador, incluyendo formulario de espacios, grabación, modos, tabla de archivos y diálogo de calidad.

## Límites de esta validación

No hubo movimiento físico del Go2. Falta la prueba supervisada de conexión WebRTC, postura, Wi-Fi intermitente, apagado y encendido reales, teleoperación, parada y exploración en el nuevo espacio.

El replay de la oficina tiene desfases iniciales entre sensores. No hay que interpretar una espera inicial de odometría como velocidad de arranque típica del robot.

HumanCLI usa un intérprete local de direcciones y distancias. La integración con un agente visual externo quedó desactivada a la espera de autorización específica para enviar imágenes y coordenadas. No hay patrullas ni relocalización automática entre reinicios.

La consola se entrega desconectada y en pausa. Para hacer pruebas sin hardware, seleccionar **Replay** en una grabación importada. Para iniciar una sesión real, usar **Conectar** con el Go2 encendido y supervisado.


## Corrección de controles (2026-09-21)

* 23 pruebas automatizadas: incluye las expresiones reportadas, exclusión entre Teleop y navegación, rechazo de órdenes vencidas, serialización lateral/yaw hacia Sport Move, errores del transporte, cierre del hilo explorador y protección de claves.
* TypeScript y build Vite completados; Ruff sin errores.
* Replay separado del robot físico: frontier explorer a gate a conexión. Se verifican órdenes de navegación habilitadas, transporte sin errores y velocidad lateral y=0,2. No equivale a validar movimiento físico.
* La integración visual se valida con respuestas HTTP simuladas. Falta una API key real para probar una descripción de cámara contra OpenAI.
* Pendiente: confirmar Q/E y navegación con firmware del Go2 real tras cambiar a la API de velocidades. El robot no se mueve como parte de estas pruebas.

* Incidente físico reportado por el usuario: robot cayó y fue apagado. Sin causa establecida. Consola desconectada; pruebas físicas y reconexión suspendidas. Se agregó y probó la confirmación presencial antes de desconexión planificada.

## Transporte MCF y recuperación de Teleop (2026-09-21)

Se detectó una incompatibilidad en el formato de Move de la versión fijada: usaba
`req` sin `policy.noreply`. El ejemplo del driver para MCF usa `msg`, API 1008,
`policy: {priority: 0, noreply: true}` y `binary: []`. La consola adapta solamente
el publicador de velocidades de su instancia WebRTC; conserva el watchdog de
DimOS y no modifica el checkout del framework ni el controlador de marcha.
Referencia: [ejemplo MCF del driver](https://github.com/legion1581/unitree_webrtc_connect/blob/9bad111871a564218e74cc9e86df50b2d4d24191/examples/go2/data_channel/sportmode_mcf/sportmode_mcf.py).

* 28 pruebas automatizadas aprobadas. La regresión de transporte verifica el JSON
  realmente serializado por el driver, los ejes laterales, el envío automático de
  velocidad cero, el error de canal cerrado y la exclusión de replay/joystick.
* Ruff y compilación de producción TypeScript/Vite sin errores.
* Consola web aislada en puerto 8893, sin robot: activar teclado, vencer su permiso
  y reactivarlo obtiene una nueva época y reanuda el envío. Desactivar lo libera.
* La clave de OpenAI ya se configuró en almacenamiento privado de la aplicación.
  Una consulta con una imagen real respondió correctamente y el usuario confirmó
  que HumanCLI funciona. No se guardan claves en el repositorio.
* El robot estaba conectado y en pausa durante la preparación. No se emitieron
  órdenes de movimiento ni de cambio de locomoción. La validación física de
  Teleop y navegación sigue pendiente; el envío de mensajes no demuestra marcha.
* Para cargar el adaptador hace falta recrear el runtime después de confirmar
  visualmente que el Go2 está acostado y apoyado. No reiniciar en pie.

Prueba integrada adicional con grabación: 58 órdenes de navegación recibidas y
reenviadas, 60 envíos del transporte y cero errores. Teleop conservó y=0,2.
El replay confirma el circuito de software, sin validar movimiento físico.


## Panel Teleop y preparación de marcha (2026-09-21)

* El panel de controles permanece visible en pausa y después de una postura.
  Se incorporaron seis botones mantenidos Q/W/E y A/S/D con etiquetas de dirección.
  Las pulsaciones y liberaciones envían la velocidad inmediatamente, además de
  renovarla periódicamente. Respuestas de permisos antiguos no desarman uno nuevo.
* Levantarse completa StandUp 1004, espera de 3 segundos y BalanceStand 1002,
  como la secuencia de arranque de la versión fijada de DimOS. Solo ocurre como
  respuesta a una solicitud explícita de postura, nunca al conectar.
* Cada respuesta de postura requiere status.code=0. Se libera el bloqueo durante
  la espera para permitir Parar; si cambia la época o se enclava la parada, se
  cancela BalanceStand. No se reanuda automáticamente Teleop ni exploración.
* 34 pruebas automatizadas aprobadas, Ruff sin errores y compilación TS/Vite.
* Navegador conectado a un mock sin hardware: Levantarse mantiene el panel;
  W/S, A/D y Q/E producen los seis vectores esperados y luego cero al soltar.
  Los botones laterales también enviaron Q/E y finalizaron en cero.
* Pendiente de carga en el runtime físico y comprobación presencial de marcha.
  La conexión no fue reiniciada durante esta preparación.


## Estado de navegación y batería (2026-09-21)

* Estado en español derivado de los mensajes reales del planificador fijado:
  giro inicial/final, seguimiento, obstáculo, recálculo, ausencia de ruta y llegada.
  Historial acotado, sin importar mensajes de sesiones anteriores. Los avisos de
  obstáculos muestran lo informado por el planificador, no una validación física.
* Aviso separado basado en odometría: una orden sostenida de giro o avance sin
  progreso medible durante 4 s. Requiere posición y comando recientes y se borra
  al pausar, vencer los datos, cambiar la orden o cambiar la época de control.
* Batería desde lowstate.bms_state.soc con fecha de recepción; 0% válido, datos
  ausentes o inválidos no se inventan. La interfaz distingue replay y muestras
  desactualizadas después de 10 s. No estima minutos restantes.
* 40 pruebas aprobadas, Ruff y build TypeScript/Vite correctos. Navegador con mock
  verificó mensajes, historial y porcentaje de ejemplo. Replay aislado verificó
  eventos del planificador, estado de giro inicial y batería desconocida.
* Durante la instalación el Go2 no respondía y la consola estaba reconectando.
  No se reinició ni se controló una sesión física. La lectura de batería real
  queda pendiente de que el robot vuelva a conectarse.


## DimOS Cloud uploads and English UI (2026-09-21)

* Verified the official production API health and authentication endpoints, and
  implemented the current Bearer-key device flow and multipart contract.
* Tests cover committed WAL snapshots, resumed parts, SHA-256 deduplication,
  failure before verification, pause/restart recovery, remote deletion, private
  credentials, signed PUT checksums, local request protection, and English intents.
* Browser preview used simulated remote storage, without a physical robot or
  external dataset transfer. Confirmed 0% preparing state, upload completion,
  persistent Backed up after reload, and English labels/layout.
* Production cloud upload still requires the user's cloud sign-in. No user
  recordings were uploaded during development.
* Deployment required idle/offline-or-reconnecting state, no recording, and no
  Go2 runtime process. The dashboard restart sends no physical robot commands.
* Final checks: 50 pytest tests passed; Ruff and TypeScript/Vite build passed.
  The installed dashboard was reloaded and verified in the browser, with both
  physical recording segments present and cloud uploads awaiting sign-in.


## Signed upload header fix (2026-09-21)

* Reproduced S3 HTTP 403 AccessDenied on the first real upload part. Content-MD5
  was added to a URL signed for host only; S3 rejected that unsigned header.
* Removed the extra header. The same 16 MiB part then succeeded with HTTP 200.
* Added streaming SHA-256 verification of the downloaded cloud object before
  Backed up, and sanitized S3 error codes with no retry for permanent 4xx errors.
* 53 tests passed, including unsigned-header regression, actual-byte checksum
  verification, corrupted-download rejection, and resume after failed verification.
* Deployment checked offline/idle state, no recording and no robot runtime.
* Live retry completed segment fa70469d38ec4922: 852,914,176 bytes uploaded,
  full signed-GET SHA-256 verification passed, status complete at 100%.
  Reconciliation with DimOS Cloud confirmed the persisted backup.
