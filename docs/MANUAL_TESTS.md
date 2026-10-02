# Pruebas manuales

Los 102 tests automáticos (`.\.venv\Scripts\python.exe -m pytest`) cubren la lógica con un backend de
audio falso. Lo que necesita hardware real o juicio humano se comprueba aquí.

Marca cada prueba tras ejecutarla. Si algo falla, mira `logs/app.log`.

## Resultado de la última verificación (Fase 1, 2026-10-02)

Verificado automáticamente contra el hardware real de este equipo (RTX 5060 Ti, Ryzen 5 5600X,
11 dispositivos de entrada / 20 de salida):

| Comprobación | Resultado |
|---|---|
| Importar MP3 generado (5,00 s, estéreo, 44,1 kHz) | ✅ |
| Reproducción real por PortAudio (posición avanzó a 1,47 s) | ✅ |
| Grabación real del micrófono (2 tomas, duraciones correctas) | ✅ |
| Nivel captado: C922 pico 0,63 · HyperX QuadCast S pico 0,19 · G733 **silencio total** | ✅ (el G733 está mudo) |
| Exportar 3 contenidos × 3 formatos (9 archivos) y volver a cargarlos | ✅ |
| Reabrir proyecto desde disco con tomas y toma activa | ✅ |

> ⚠️ El micrófono del **G733 Gaming Headset** (el predeterminado del sistema) devuelve silencio absoluto.
> Si vas a grabar, selecciona el **HyperX QuadCast S** en Settings, o revisa si el G733 está silenciado
> por hardware.

---

## P1 · Reproducción por altavoces
1. Abre la app, importa una canción con **Import Song**.
2. Pulsa **Play**.

✅ Se oye la canción, el cursor amarillo avanza sobre la onda y el reloj cuenta.
✅ **Pause** detiene el sonido dejando el cursor donde estaba; **Play** continúa desde ahí.
✅ **Stop** devuelve el cursor al principio.
✅ Un clic en cualquier punto de la onda salta a ese punto, también mientras suena.

## P2 · Selección de micrófono
1. Ve a **Settings** → **Micrófono (entrada)**.
2. Pulsa **Probar micrófono** y habla.

✅ El medidor se mueve al hablar y se queda quieto al callar.
✅ Al cambiar de micrófono en la lista, el medidor sigue respondiendo (al correcto).
✅ Con un micrófono desconectado a mitad de prueba, aparece un mensaje que explica qué hacer, sin
   cerrarse la aplicación.

## P3 · Grabación cantando sobre la canción
**Usa auriculares.** Con altavoces, el micrófono captará la canción y se colará en la toma.

1. Importa una canción, haz clic en la onda donde empieza la estrofa.
2. Pulsa **Record** y canta. Pulsa **Stop rec**.

✅ Mientras grabas se ve `● REC` con el tiempo, y una línea roja avanza sobre la onda.
✅ La canción suena de fondo mientras grabas.
✅ Al parar aparece *Take 1* en la lista y su onda verde se dibuja **en la posición donde empezaste**,
   no al principio.
✅ Al pulsar Play, tu voz y la canción suenan juntas y sincronizadas.

## P4 · Sincronización (latencia)
1. Graba una toma cantando o dando palmadas a tiempo con la canción.
2. Reprodúcela.

✅ Si tu voz suena retrasada: en Settings sube **Compensación de latencia** (prueba 40 ms), graba otra
   toma y compara. La nueva toma debe sonar más adelantada.
✅ Con el valor correcto, las palmadas coinciden con el ritmo de la canción.

## P5 · Varias tomas
1. Graba tres tomas seguidas.

✅ Aparecen *Take 1*, *Take 2* y *Take 3*; la última queda marcada con `●`.
✅ Al hacer clic en otra toma, se marca ella y al reproducir se oye esa.
✅ Doble clic permite renombrarla y el nombre se conserva al reabrir el proyecto.
✅ **Eliminar** la borra de la lista y del disco (comprueba la carpeta `takes/` del proyecto).

## P6 · Monitorización
1. Con **auriculares puestos**, activa en Settings *"Escuchar mi voz mientras grabo"*.
2. Graba y habla.

✅ Te oyes a ti mismo por los auriculares.
✅ Al desactivarlo, dejas de oírte pero la grabación sigue capturando.
⚠️ Si lo activas con altavoces se produce acoplamiento (pitido). Es esperable: usa auriculares.

## P7 · Exportación
1. Con una canción y una toma, elige en **Exportar** cada combinación y guarda.

✅ *Solo voz* → se oye únicamente tu voz, en su posición temporal.
✅ *Solo canción* → solo el instrumental.
✅ *Mezcla completa* → ambas, con los volúmenes que fijaste en **Mezcla**.
✅ Los tres formatos (WAV, FLAC, MP3) se abren correctamente en otro reproductor.
✅ Si subes los dos volúmenes al máximo, la mezcla no satura ni distorsiona.

## P8 · Proyectos
1. **Proyecto ▸ Nuevo proyecto**, ponle un nombre, importa audio y graba una toma.
2. Cierra la aplicación y vuelve a abrirla.

✅ Al reabrir, el proyecto aparece tal cual lo dejaste (canción, tomas, volúmenes, toma activa).
✅ En `Documentos\VocalAIStudio\Projects\<nombre>` están `project.json`, `song.wav` y la carpeta `takes/`.
✅ **Guardar como** crea una copia completa e independiente: borrar una toma en la copia no afecta al original.
✅ Al crear un proyecto con un nombre que ya existe, se crea *"<nombre> 2"* sin sobrescribir nada.

## P9 · Errores comprensibles
1. Intenta importar un archivo que no sea audio (por ejemplo un `.txt` renombrado a `.mp3`).

✅ Aparece un mensaje que dice qué falló, por qué y qué hacer — no un volcado técnico.
✅ La aplicación sigue funcionando después del error.
✅ El detalle técnico queda registrado en `logs/app.log`.

## P10 · Rendimiento
1. Importa una canción larga (5 minutos o más).

✅ La onda se dibuja en menos de un par de segundos y el zoom responde con fluidez.
✅ La reproducción no se entrecorta ni chasquea.
✅ Grabar 5 minutos seguidos no agota la memoria ni ralentiza la aplicación.
