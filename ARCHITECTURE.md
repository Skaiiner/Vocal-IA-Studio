# Arquitectura

Objetivo del diseño: **poder sustituir cualquier modelo de IA o algoritmo sin reescribir la aplicación**.
Por eso los módulos se comunican mediante interfaces declaradas en `core/interfaces.py`, nunca entre
implementaciones concretas.

## Stack y por qué

| Decisión | Motivo |
|---|---|
| **Python 3.12** | Es donde viven las librerías de audio e IA (librosa, torch, Demucs, RVC). |
| **PySide6 (Qt)** | Un solo proceso para UI y audio, lo que importa para la latencia en tiempo real (Fase 7). Widgets propios con QPainter para onda y pitch. Licencia LGPL. Empaquetable con PyInstaller y portable a macOS/Linux. |
| **sounddevice (PortAudio)** | Acceso de bajo nivel con callbacks propios; permite seek, pausa y monitorización. WASAPI en Windows. |
| **soundfile + FFmpeg** | soundfile para WAV/FLAC/OGG; FFmpeg para todo lo demás. El binario viene en el paquete `imageio-ffmpeg`, así que no hay que instalar nada a mano. |
| **numpy / scipy** | DSP y detección de tono/BPM/tonalidad (algoritmo YIN propio, ver más abajo). torch se añadirá en las fases que lo necesiten. |

Alternativas descartadas: Electron y Tauri añadían una segunda cadena de herramientas y comunicación
entre procesos sin aportar nada a una aplicación de audio de un solo usuario.

## Mapa de módulos

```
src/vocal_ai_studio/
├── core/                  Sin dependencias de otros módulos
│   ├── interfaces.py      Contratos (Protocols) entre capas
│   ├── config.py          Settings en JSON + .env (nunca claves en el código)
│   ├── errors.py          AppError: qué falló / por qué / cómo solucionarlo
│   ├── logging_setup.py   logs/app.log rotativo
│   └── hardware.py        CPU/RAM/GPU; nunca falla si no hay GPU
├── audio/                 Formato interno: float32 (frames, channels)
│   ├── io.py              load_audio / save_audio / resample / conform_channels
│   ├── convert.py         Decodificar y codificar con FFmpeg
│   ├── ffmpeg_locator.py  FFmpeg del PATH o el incluido en el paquete
│   ├── mix.py             Mezcla offline con offsets y ganancias
│   ├── waveform.py        PeakCache: picos multirresolución para dibujar con zoom
│   └── backends.py        SoundDeviceBackend (implementa AudioBackend)
├── playback/player.py     Reproductor multipista con callback propio
├── recording/recorder.py  Grabador: armar, grabar, pausar, continuar, nivel, monitor
├── storage/
│   ├── project.py         Carpeta de proyecto + autoguardado
│   └── exporter.py        Renderizar voz / canción / mezcla
├── song_import/
│   ├── importer.py        Archivo local → proyecto, normalizado
│   └── sources.py         SongSource: contrato de búsqueda/descarga (SearchResult, LocalLibrarySource)
├── youtube/source.py      YouTubeSource (implementa SongSource) vía yt-dlp; desactivado por defecto
├── lyrics/model.py        Lyrics/LyricLine: texto propio del usuario, parseo LRC, sincronización manual
├── pitch/
│   ├── yin.py             Algoritmo YIN en NumPy puro: F0 frame a frame (ver nota más abajo)
│   ├── notes.py           Hz <-> MIDI <-> nombre de nota (C4, A#3...), cents, median_smooth (compartido)
│   ├── detector.py        YinPitchDetector: implementa PitchDetector (intercambiable en el futuro)
│   ├── scales.py          Escalas musicales (Mayor, Menor, Pentatónicas...) y cuantización a la más cercana
│   ├── correction.py      CorrectionSettings/NoteOverride/build_target_curve: la curva objetivo del autotune
│   └── shifter.py         psola_resynthesize: PSOLA en NumPy puro, renderiza la corrección a audio
├── voice_analysis/
│   ├── notes.py           Agrupa el rastro de F0 en NoteSegment (notas con duración, cents, nombre)
│   ├── metrics.py         VocalAnalysis: afinación media, estabilidad, rango, pausas, vibrato
│   └── song.py             SongAnalysis: BPM (autocorrelación de onsets) y tonalidad (cromagrama + Krumhansl-Kessler)
├── session.py             Une proyecto + reproductor + grabador + análisis + corrección (la UI solo habla con esto)
├── ui/                    PySide6: main_window, song_view, voice_view, pitch_view, pitch_editor_widget,
│                           pitch_editor_view, settings_view, waveform_widget, background (QThread
│                           reutilizable), theme
└── voice_conversion/ effects/ ai/ realtime/ obs/ discord/
                           Reservados para las fases 4–7 (hoy solo documentación)
```

### Regla de dependencias

```
ui → session → {playback, recording, storage, song_import} → audio → core
```

Nada apunta hacia arriba. `core` no importa a nadie. Los módulos de fases futuras dependerán de
`core/interfaces.py`, no unos de otros.

## Interfaces clave

`core/interfaces.py` declara los contratos. Los de la Fase 1 ya están implementados; el resto son los
puntos de extensión de las fases siguientes:

| Interfaz | Para qué | Fase |
|---|---|---|
| `AudioBackend` | Abrir entrada/salida de audio. Implementado por `SoundDeviceBackend`; en los tests, por un backend falso. | 1 ✅ |
| `SongSource` | Buscar y traer canciones. Implementado por `LocalLibrarySource` (carpetas propias) y `YouTubeSource` (yt-dlp, opcional). Añadir otra fuente (otro servicio) no toca el resto de la app. | 1 ✅ |
| `PitchDetector` | Implementado por `YinPitchDetector` (CPU, NumPy puro). En el futuro, CREPE/torchcrepe (GPU) con la misma firma. | 2 ✅ |
| `EffectProcessor` | EQ, compresor, reverb… encadenables | 4 |
| — | `pitch.shifter.psola_resynthesize` no sigue ninguna interfaz propia todavía (solo hay un método); se extraerá a un `PitchShifter` Protocol si llega un segundo algoritmo (p. ej. WORLD). | 3 ✅ |
| `AIProvider` | IA local (Ollama), API gratuita o de pago, intercambiables | 5 |
| `SourceSeparator` | Demucs u otro, con progreso y cancelación | 6 |
| `VoiceConversionModel` | RVC, So-VITS-SVC, DDSP: declara licencia y si exige GPU | 6 |

Antes de integrar un modelo hay que comprobar licencia, requisitos, rendimiento y si necesita GPU;
la interfaz `VoiceConversionModel` obliga a declarar `license` y `requires_gpu` precisamente por eso.

## Decisiones que conviene conocer

**El audio se procesa en hilos de PortAudio.** Los callbacks de `Player` y `Recorder` se ejecutan en un
hilo de tiempo real: no pueden asignar memoria grande, bloquearse ni tocar Qt. Por eso `Player` sustituye
el diccionario de pistas de forma atómica en lugar de modificarlo, y la UI consulta el estado con un
`QTimer` a 20 Hz en vez de recibir señales desde el audio.

**Negociación de canales en el grabador, no en el backend.** El grabador prefiere mono y acepta estéreo
si el dispositivo no admite mono (mezcla a mono en el callback). Es política de aplicación, así que vive
en `Recorder`; el backend solo abre lo que se le pide y traduce los fallos a `AppError`.

**Formato interno único:** float32, `(frames, channels)`, a la frecuencia del proyecto (44,1 kHz). Todo
lo que entra se normaliza al importar, así ningún módulo posterior tiene que lidiar con conversiones.

**Los proyectos son carpetas, no archivos binarios.** Si algo se rompe, el audio sigue ahí y se puede
abrir con cualquier reproductor. `project.json` tolera campos desconocidos para que una versión antigua
pueda abrir proyectos de una versión nueva.

**Los errores siempre explican la solución.** `AppError` tiene tres partes (qué, por qué, cómo arreglarlo)
y `explain_exception()` traduce las excepciones técnicas habituales (archivo no encontrado, permiso
denegado, PortAudio) a lenguaje comprensible.

## Análisis vocal: por qué YIN en NumPy puro, y no librosa.pyin

Decisión tomada durante la Fase 2, tras un fallo real en este equipo: `librosa.pyin`/`.yin`/`.beat`
dependen de Numba (compilación JIT), y en Windows con **Control de aplicaciones inteligente** activado,
el sistema bloquea la DLL compilada de Numba al cargarla (`Code Integrity` la rechaza por no cumplir
el nivel de firma exigido). No es razonable pedirle al usuario que desactive una protección de
seguridad de su propio sistema para poder usar la aplicación, así que `pitch/yin.py` implementa el
algoritmo YIN (de Cheveigné y Kawahara, 2002) **en NumPy/SciPy puro**: autocorrelación por FFT,
vectorizado por bloques de frames (sin bucles Python por muestra), procesado en *chunks* para acotar
memoria e informar de progreso. `voice_analysis/song.py` hace lo mismo para BPM (autocorrelación de
una envolvente de energía) y tonalidad (cromagrama propio correlacionado con los perfiles numéricos
de Krumhansl-Kessler, un dato de investigación académica estándar en MIR, no una obra protegida).

Consecuencia práctica: ningún futuro proveedor de IA/DSP de esta aplicación debería depender de Numba
sin red de seguridad, porque el fallo observado aquí puede repetirse en cualquier equipo con la misma
política. Si hiciera falta Numba en una fase posterior (p. ej. algún acelerador de CPU), hay que
mantener esta implementación en NumPy como *fallback* automático, igual que ya se hace con CPU/GPU
en `core/hardware.py`.

## Autotune: por qué se cuantiza con mediana, no frame a frame

Primer intento (Fase 3): cuantizar cada frame de F0 a la nota de la escala más cercana,
independientemente. Funcionaba perfecto en los tests con tonos sintéticos (frecuencia constante),
pero con voz real apenas mejoraba la afinación media. Diagnóstico: el vibrato natural y el ruido
de seguimiento de la detección de tono hacen que frames consecutivos de la MISMA nota perceptual
caigan unas veces en un semitono y otras en el de al lado — la cuantización nunca se asentaba,
por rápida que fuera la velocidad de retonación.

Un segundo intento, anclar la cuantización al tono medio de cada *nota detectada*
(`voice_analysis.notes.segment_notes`), tampoco bastó: ese segmentador exige el mismo semitono
redondeado en frames contiguos para contar como una nota, así que con voz real (vibrato, glissandos)
solo cubría ~13% de los frames con voz en una grabación de prueba; el resto caía al mismo problema
de antes.

La solución que funciona: `pitch.notes.median_smooth()`, una mediana deslizante corta (ventana de
9 frames, ~100ms) aplicada en el dominio MIDI/logarítmico, **solo dentro de cada tramo de voz
continuo** (nunca cruza un silencio), usada exclusivamente para decidir a qué semitono cuantizar
cada frame — el *speed*/retonación sigue operando sobre el F0 real para el deslizamiento entre
notas. El mismo suavizado se aplica también al F0 de origen que usa `pitch.shifter` para generar
sus marcas de análisis PSOLA, por la misma razón. Verificado con una grabación de voz real: la
desviación media del semitono objetivo bajó de 17.95 a 7.35 cents (mediana: de 14.9 a 0.04).

**Limitación conocida:** incluso con este suavizado, el renderizado final (PSOLA sin detección de
instantes de cierre glotal) pierde algo de precisión en pasajes con cambios de nota muy rápidos
(p. ej. una escala cantada en 3 segundos); en notas sostenidas — el caso normal al cantar una
canción — la precisión es mucho mejor, como demuestran los tests con tonos sintéticos y vibrato.
Mejorar esto más (epochs reales en vez de periodo instantáneo) es candidato para una fase futura.

## Tu nota en vivo mientras cantas

`Recorder` mantiene un buffer circular de las últimas ~4096 muestras captadas (`recent_samples()`),
reasignado como objeto nuevo en cada callback (nunca mutado in-place) para que una lectura
concurrente desde el hilo de la UI sea siempre segura. `Recorder.live_pitch()` reutiliza
`yin_pitch_track()` sobre ese buffer con `frame_length == hop_length == len(buffer)` (un único
frame): cero código DSP nuevo, solo una llamada distinta a algo ya probado. Las pestañas Song,
Voice y Pitch Editor consultan esto en su `QTimer` de refresco (~20 Hz) y lo muestran: como texto
en Song, y como un punto que se mueve sobre la curva de afinación en `PitchView`/`PitchEditorWidget`
(método `set_live_pitch`), superpuesto al análisis ya existente — así puedes cantar de nuevo y
comparar en directo contra tu análisis anterior, en la misma gráfica.

## Análisis vocal: caché en el proyecto

`analyze_vocal()`/`analyze_song()` (en `session.py`) guardan el resultado en `project/analysis/`:
un `.json` con las métricas (notas, pausas, vibrato, BPM, tonalidad...) y un `.npz` con los arrays
grandes del rastro de F0 (tiempos, frecuencia, confianza). La clave de caché es `vocal_take{id}` /
`vocal_imported` para la voz (así cada toma mantiene su propio análisis) y `song_tempo_key` para la
canción. `Project.set_song()`/`set_vocal()`/`delete_take()` invalidan la caché correspondiente
automáticamente para que nunca se muestre un análisis de un audio que ya no es el actual.

## Preparado para el futuro

La estructura admite sin rediseño: MIDI, detección de acordes, letras sincronizadas, metrónomo,
ejercicios vocales, scoring, comparación entre tomas, mezcla automática y plugins VST3.
El `PeakCache` y el reproductor multipista ya soportan varias pistas con offsets, que es lo que
necesitarán el comping de tomas y la separación voz/instrumental.

## Búsqueda de canciones

`SearchDialog` ejecuta la búsqueda y la descarga en un `QThread` aparte (ver `ui/search_dialog.py`),
con progreso y cancelación, para que la ventana no se congele. Un detalle de robustez: YouTube a veces
entrega un flujo de audio parcial como si estuviera completo; `YouTubeSource.fetch()` compara el tamaño
descargado contra el tamaño esperado, reintenta una vez y, si sigue incompleto, lo informa en vez de
dejar una canción cortada sin avisar.

## Letra

`lyrics/model.py` no tiene ninguna dependencia de red ni de otros módulos: el texto siempre lo aporta
el usuario (pegado o desde un `.txt`/`.lrc` propio). Igual que con YouTube, por diseño la aplicación
**no busca ni descarga letras de Internet** — evita reproducir contenido con derechos de autor sin
permiso, igual que con el audio. `parse_text()` detecta marcas `[mm:ss.xx]` (formato LRC) y, si las
encuentra, sincroniza sola; si no, `ui/lyrics_panel.py` ofrece un modo de sincronización manual tipo
karaoke (reproducir y pulsar "Marcar" al empezar cada línea), guardando los tiempos en
`project/lyrics.json`.

## Tests

282 tests automáticos sin necesidad de hardware: el audio usa un backend falso que bombea bloques bajo
control del test, y Qt corre en modo *offscreen*. Lo que no se puede automatizar está documentado como
prueba manual en `docs/MANUAL_TESTS.md`.
