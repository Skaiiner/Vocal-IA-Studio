# Vocal AI Studio

Estudio vocal de escritorio para practicar canto y modificar la voz. **Todo el procesamiento es local**:
tu audio no sale de tu ordenador salvo que tú lo autorices expresamente.

> **Estado: Fases 1 a 6 completadas y verificadas.** Ya puedes importar canciones, reproducirlas,
> grabar tu voz en varias tomas, exportar el resultado, **analizar tu afinación** (notas, cents,
> estabilidad, rango, vibrato, pausas, BPM y tonalidad) con un **indicador de tu nota en vivo mientras
> cantas**, **corregir la afinación** (autotune con modos predefinidos, o editando nota a nota a mano),
> retocar la voz en **Voice Lab** (formantes, brillo, peso vocal, efectos y presets), recibir
> **feedback de un AI Coach** (puntos fuertes, a mejorar y ejercicios, con reglas locales o IA vía Ollama),
> **separar una canción en voz e instrumental** (Demucs) y **convertir tu voz con un modelo entrenado**
> (arquitectura RVC v2), todo procesado en local. Las fases 7–8 (tiempo real, micrófono virtual,
> OBS/Discord) están diseñadas en la arquitectura pero todavía no implementadas.
> Ver [Hoja de ruta](#hoja-de-ruta).

## Qué hace hoy

| Función | Estado |
|---|---|
| Importar canción o voz (MP3, WAV, FLAC, M4A, OGG, Opus, y más vía FFmpeg) | ✅ |
| **Buscar canción** en tu música o en YouTube, e importarla con un clic | ✅ |
| Reproducir con onda, cursor, zoom y clic para situarte | ✅ |
| Elegir el micrófono y grabar con medidor de nivel y monitorización, todo desde Song | ✅ |
| **Letra**: pegar o importar tu propia letra, y sincronizarla con la canción línea a línea | ✅ |
| Varias tomas (Take 1, 2, 3…), elegir la activa, renombrar y borrar | ✅ |
| Mezcla canción/voz con volúmenes independientes | ✅ |
| **Selector de salida de audio** y botón para reiniciarla si deja de sonar | ✅ |
| **Mezclador de 3 pistas** (canción, voz original separada, tu voz) con silenciar/escuchar independiente, tras separar | ✅ |
| Exportar voz, canción o mezcla en WAV / FLAC / MP3 | ✅ |
| Proyectos con autoguardado (Nuevo, Abrir, Guardar, Guardar como) | ✅ |
| Ajustes de audio, privacidad y detección de hardware | ✅ |
| **Análisis vocal**: afinación, notas, estabilidad, rango, vibrato y pausas | ✅ |
| **Indicador de tu nota en vivo** mientras cantas (Song, Voice, Pitch Editor) | ✅ |
| **BPM y tonalidad** de la canción | ✅ |
| **Autotune**: modos Natural/Balanced/Hard Autotune/Extreme, Amount/Speed/Humanize/Key/Scale/Formantes | ✅ |
| **Sugerir ajustes de autotune con IA** a partir de tu afinación/estabilidad/vibrato y la tonalidad de la canción | ✅ |
| **Editor manual de afinación**: transportar, excluir, dividir y unir notas, arrastrando o con botones | ✅ |
| **Voice Lab**: formantes, brillo, peso vocal, efectos y presets | ✅ |
| **AI Coach**: feedback, puntos fuertes, a mejorar y ejercicios (reglas locales u Ollama) | ✅ |
| **Separar voz/instrumental** de una canción (Demucs) y usar el resultado directamente | ✅ |
| **Conversión de voz** con un modelo RVC entrenado (transposición, protect, index rate...) | ✅ |
| **Voz en vivo**: micrófono procesado en tiempo real (presets, bypass, dry/wet) hacia OBS/Discord | ✅ |
| Tiempo real, micrófono virtual, OBS/Discord | 🚧 Fases 7–8 |

## Instalación

Necesitas **Python 3.10 o superior** ([descargar](https://www.python.org/downloads/), marca
*"Add Python to PATH"* durante la instalación). No hace falta nada más: FFmpeg viene incluido como
paquete de Python.

Abre PowerShell en la carpeta del proyecto y ejecuta:

```powershell
.\scripts\install.ps1
```

Eso crea un entorno aislado en `.venv` e instala todo. Si PowerShell bloquea el script, usa:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

## Ejecutar

Hay un acceso directo **"Vocal AI Studio"** en el escritorio: ábrelo con doble clic como cualquier
otro programa, no hace falta abrir PowerShell para el uso normal.

Para volver a crearlo (por ejemplo tras mover la carpeta del proyecto) o si prefieres la terminal:

```powershell
.\scripts\run.ps1
```

O bien, a mano:

```powershell
.\.venv\Scripts\python.exe -m vocal_ai_studio
```

## Primeros pasos

1. Al abrir, la app crea un proyecto llamado *My Song Project* en `Documentos\VocalAIStudio\Projects`.
2. En **Song**, elige tu micrófono en el desplegable junto a *Nivel de entrada* y habla: el medidor debe
   moverse. Si no se mueve, ese micrófono está silenciado o no es el que usas — prueba otro de la lista.
3. Pulsa **Buscar canción** para encontrar la que quieres practicar — en tu propia música o en YouTube
   (si lo activas) — o usa **Import Song** si ya tienes el archivo.
4. Sitúate donde quieras empezar haciendo clic en la onda y pulsa **Record**. La canción sonará de fondo
   mientras cantas. Pulsa **Stop rec** para guardar la toma.
5. Graba las tomas que quieras y elige la mejor en la lista **Tomas**.
6. Ajusta los volúmenes en **Mezcla** y pulsa **Exportar**.

### Buscar una canción

El botón **Buscar canción** abre dos fuentes:

- **Mi música** — busca por nombre de archivo o de carpeta en las carpetas que configures en
  *Settings ▸ Carpetas ▸ Tu música* (por defecto, tus carpetas Música y Descargas).
- **YouTube** — desactivada por defecto. Actívala en *Settings ▸ Privacidad* si quieres buscar y traer
  canciones desde ahí. Úsala solo con contenido que tengas derecho a utilizar: la app no salta
  protecciones de acceso ni DRM, así que un vídeo privado o restringido simplemente no se podrá descargar.

La búsqueda y la descarga ocurren en segundo plano con una barra de progreso cancelable, así que la
ventana no se queda congelada mientras tanto.

### Letra

Junto a la onda hay un panel **Letra**:

1. Pulsa **Editar letra** y pega el texto (una frase por línea), o **Importar archivo…** para traer
   un `.txt` o `.lrc` que ya tengas tú. Guarda.
2. Si el texto no trae marcas de tiempo, pulsa **Sincronizar**: la canción empieza a sonar y vas
   pulsando **Marcar** (o Enter) justo cuando empieza cada línea, como en un karaoke. **Deshacer**
   corrige la última marca; **Terminar** sale del modo en cualquier momento.
3. Mientras reproduces la canción, la línea que toca se resalta sola.
4. **Quitar sincronización** borra los tiempos y deja la letra entera sin resaltar nada.

La aplicación **no busca letras en Internet por ti**: siempre es contenido que tú pegas o importas,
igual que al importar un audio. Si pegas un `.lrc` con marcas `[mm:ss.xx]`, se sincroniza solo.

### Analizar tu voz (pestaña Voice)

1. Graba una toma o importa una voz (pestaña Song).
2. Ve a **Voice** y pulsa **Analizar**. Si hay canción importada, también calcula su BPM y tonalidad.
3. Verás:
   - **Resumen**: BPM, tonalidad, rango vocal, afinación media (en cents), estabilidad, vibrato y pausas.
   - **Curva de afinación**: tu voz sobre una rejilla de semitonos (como un piano tumbado). Verde = afinado
     (±15 cents), amarillo = desviación ligera, rojo = desviación notable. Clic para situarte; Ctrl+rueda
     para hacer zoom.
   - **Notas**: cuántas se detectaron y la más repetida.

El análisis se guarda con el proyecto (no hace falta repetirlo cada vez que abres la app), y se
recalcula solo si cambias de toma, vuelves a grabar o importas otra canción.

*Nota técnica:* la detección de tono, BPM y tonalidad están implementadas en NumPy puro (algoritmo
YIN), sin depender de Numba/librosa.pyin — en equipos con "Control de aplicaciones inteligente" de
Windows activado, esa dependencia puede bloquearse por política de seguridad, y esta aplicación
funciona igual sin necesidad de tocar esa configuración.

### Tu nota en vivo mientras cantas

En **Song**, **Voice** y **Pitch Editor**, en cuanto el micrófono está abierto (aunque no estés
grabando) aparece tu nota actual: en Song como texto junto al medidor de entrada ("A4 +12¢"), y en
Voice/Pitch Editor como un punto que se mueve sobre la curva de afinación — así puedes ver tu voz
en directo, junto a tu análisis anterior, mientras cantas de nuevo para comparar o practicar.

### Corregir la afinación (pestaña Pitch Editor)

1. Analiza tu voz primero en **Voice** (hace falta su análisis para poder corregir).
2. Ve a **Pitch Editor**. Elige un **modo** (Natural, Balanced, Hard Autotune, Extreme) o ajusta a
   mano **Amount** (cuánto corrige), **Speed/Retune** (qué tan rápido desliza hacia la nota),
   **Humanize** (deja que las notas largas respiren, menos robótico), **Preservar formantes**
   (mantiene tu timbre), **Tonalidad** y **Escala**. Si no sabes por dónde empezar, pulsa
   **"Sugerir con IA"**: analiza tu afinación, estabilidad y vibrato (y la tonalidad de la canción,
   si hay una importada) y rellena esos controles por ti, explicando por qué — tú decides si
   quedarte con la sugerencia, retocarla o ignorarla; no aplica nada hasta que pulses Aplicar.
3. La curva corregida se dibuja en vivo sobre la original, con las notas detectadas como cajas
   que puedes:
   - **Arrastrar verticalmente** para transportar una nota, o usar los botones **+/− semitono**.
   - **Excluir/incluir** una nota concreta de la corrección.
   - **Dividir** por la mitad (en el punto de reproducción) o **unir** con la siguiente.
4. Pulsa **Aplicar**: se renderiza el resultado y se guarda como una **toma nueva** — la original
   nunca se toca, así que puedes comparar o deshacer simplemente seleccionando otra toma.

Con **Amount en 0% la corrección no cambia nada**: nunca es obligatoria. La corrección funciona
mejor en notas sostenidas (el caso normal al cantar una canción); en pasajes muy rápidos con muchos
cambios de nota seguidos, la precisión baja — es una limitación conocida del método (PSOLA, en
NumPy puro, sin detección fina de los pulsos glotales) y una de las primeras cosas a mejorar más
adelante.

### Atajos

| Tecla | Acción |
|---|---|
| Espacio | Reproducir / Pausa |
| Ctrl + N / O / S | Nuevo / Abrir / Guardar proyecto |
| Ctrl + rueda sobre la onda | Zoom |

## Configurar el audio

- **Usa auriculares para grabar.** Si escuchas la canción por altavoces, el micrófono la captará y se
  colará en tu toma.
- **Monitorización** (Settings): te permite oír tu propia voz mientras grabas. Actívala solo con
  auriculares, o se producirá acoplamiento.
- **Compensación de latencia** (Settings): si al reproducir notas que tu voz va retrasada respecto a la
  canción, sube este valor en milisegundos; las tomas siguientes se adelantarán esa cantidad.
  Valores típicos: 20–80 ms.
- La app prefiere **WASAPI**, el sistema de audio moderno de Windows, por tener menos latencia.
- **Salida de audio** (Song): elige por dónde quieres oír la canción y las tomas (altavoces, auriculares,
  un micrófono virtual...). Si pulsas Play y no se oye nada, suele ser que el dispositivo seleccionado
  no es el que tienes conectado ahora mismo — cámbialo aquí, o pulsa **"Reiniciar salida"** para reabrir
  el audio sin cerrar la aplicación.
- **Mezclador de 3 pistas** (panel Mezcla, en Song): "Canción" (el instrumental/la canción de fondo),
  "Voz original" (solo aparece tras separar la canción en la pestaña "Separar voz/instrumental": es la
  voz del cantante original) y "Tu voz" (tu toma activa). Cada una tiene su propio volumen y un botón
  Escuchar/Silenciado para activarla o apagarla a tu gusto — "Voz original" empieza silenciada la primera
  vez que aparece, así nunca se mezcla con la tuya a menos que tú decidas activarla.

## OBS y Discord (voz en vivo)

La pestaña **Live Voice** procesa tu micrófono en tiempo real con la misma cadena de efectos que
Voice Lab (formantes, EQ, de-esser, compresor, reverb, delay), con presets, bypass y mezcla dry/wet:

```
Micrófono → Vocal AI Studio (Live Voice) → dispositivo de audio virtual → OBS / Discord
```

Para que OBS o Discord usen tu voz procesada en vez del micrófono real, hace falta un dispositivo de
audio virtual, porque Windows no permite crear micrófonos virtuales desde una aplicación normal: es un
driver del sistema. Instala **VB-CABLE** o **VoiceMeeter** (búscalos en tu navegador; no se instalan
desde aquí), pulsa "Volver a buscar dispositivos" en Live Voice y selecciónalo como **salida en vivo**.
Luego, en OBS/Discord, elige ese mismo dispositivo virtual como su micrófono de entrada.

## Privacidad

- Todo se procesa localmente. La app no envía tu audio a ningún servidor.
- La opción *Permitir servicios externos* en Settings está **desactivada** por defecto.
- Las claves de API nunca se guardan en el código: se leen de variables de entorno o de un archivo
  `.env` local (ver `.env.example`). Ese archivo no debe compartirse.

## Formatos

- **Importar:** MP3, WAV, FLAC, M4A, AAC, OGG, Opus, WMA, AIFF, y pistas de audio de MP4/WebM/MKV.
- **Exportar:** WAV (24 bits), FLAC (24 bits), MP3 (VBR alta calidad).
- La app no puede abrir archivos protegidos con DRM; importa música que ya poseas.

## Si algo falla

Los errores se explican en pantalla indicando qué pasó, por qué y cómo solucionarlo. El detalle
técnico queda en `logs/app.log` (botón *Abrir carpeta de logs* en Settings).

| Problema | Solución |
|---|---|
| El medidor no se mueve al hablar | Otro micrófono en Settings; revisa Privacidad del micrófono en Windows |
| "No se pudo abrir el micrófono" | Otra aplicación lo está usando (Discord, OBS, un juego): ciérrala |
| La voz suena retrasada | Sube la compensación de latencia en Settings |
| Se oye eco o pitido al grabar | Desactiva la monitorización o usa auriculares |
| No importa un MP3 | Comprueba que suena en otro reproductor; los archivos con DRM no se pueden abrir |

## Desarrollo

```powershell
.\.venv\Scripts\python.exe -m pytest        # 397 tests automáticos
```

Los tests no necesitan tarjeta de sonido: usan un backend de audio falso y Qt en modo *offscreen*.
Lo que no se puede automatizar (micrófono real, altavoces) está en [docs/MANUAL_TESTS.md](docs/MANUAL_TESTS.md).

La arquitectura y las decisiones técnicas están en [ARCHITECTURE.md](ARCHITECTURE.md).

## Hoja de ruta

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Base: importar, reproducir, onda, grabar, exportar, proyectos | ✅ Hecha |
| 2 | Detección de afinación, notas, análisis vocal, BPM y tonalidad | ✅ Hecha |
| 3 | Autotune (Natural/Balanced/Hard/Extreme) y editor manual de pitch | ✅ Hecha |
| 4 | Voice Lab: formantes, brillo, peso vocal, efectos y presets | ✅ Hecha |
| 5 | AI Coach: feedback y ejercicios, con IA local (Ollama) | ✅ Hecha |
| 6 | Separación voz/instrumental (Demucs) y conversión de voz (RVC) | ✅ Hecha |
| 7 | Tiempo real, micrófono virtual, OBS y Discord | ✅ Hecha |
| 8 | Optimización, ejecutable `.exe`, documentación final | Siguiente |

## Licencias

Software libre: PySide6 (LGPL v3), numpy/scipy/soundfile/sounddevice (BSD/MIT),
imageio-ffmpeg (BSD; incluye un binario de FFmpeg bajo LGPL), psutil (BSD), yt-dlp (Unlicense),
torch (BSD), demucs (MIT) y transformers (Apache 2.0). La arquitectura de conversión de voz (RVC v2)
usada en `voice_conversion/` también es MIT.
