# pupper-talk

Demo unificado para Mini Pupper 2 con 7 modos de interaccion por voz, cambio de modo por hotword, y dos backends de control (directo en Pi o via HTTP bridge).

**Slides de la charla:** [GDE Summit 2026 — pupper-talk](https://docs.google.com/presentation/d/1scd2uwQbCOYL3UUnDrJSRUVo4u01OACLcjSv0aeEBcc/present)

## Modos

### live (default)
Conversacion libre. Habla de lo que quieras — ciencia, filosofia, el clima, consejos. Tiene Google Search para preguntas factuales. Baila cuando esta emocionado, asiente cuando esta de acuerdo.

**Ejemplos:**
- "Como esta el clima en Guatemala?"
- "Explicame la teoria de la relatividad"
- "Que piensas de la inteligencia artificial?"

### rocky
Rocky, el alien Eridiano de Project Hail Mary. Habla sin articulos, repite palabras tres veces ("Amaze amaze amaze!"), termina con "pregunta"/"afirmacion". Produce sonidos musicales Eridianos cuando se emociona. Tiene Google Search ("I use human device, afirmacion!").

**Ejemplos:**
- "Rocky, de donde vienes?"
- "Que es el Astrophage?"
- "Cuanto es la poblacion de Guatemala?" (usa Google Search)
- Escucha los sonidos cuando dice cosas como *acorde alegre*

### bumblebee
Bumblebee no puede hablar — comunica SOLO con fragmentos de canciones. Las letras son sus palabras. Mantiene conversacion ida y vuelta: responde, pregunta, opina, bromea. 158 clips en EN y ES. Cara mecanica Autobot con ojos dorados y boca animada. Google Search para preguntas factuales (busca y responde con clips).

**Ejemplos:**
- "Hola, como estas?" → responde con clips de saludo + estado
- "Estoy triste" → pregunta que paso (clip ASK), luego consuela
- "Cuentame un chiste" → combina clips absurdos
- "Que opinas del reggaeton?" → opina con clips

### vision
Juego "Veo Veo" (I Spy). Usa la camara para ver el entorno, escoge un objeto, y da pistas de color y primera letra. Adivina — si fallas te da mas pistas, si aciertas celebra y escoge otro. En mock muestra preview de webcam.

**Ejemplos:**
- Inicia automaticamente al entrar al modo
- "Es una taza?" → "No, pero es algo que usas en la cocina..."
- "Dame otra pista" → da pista adicional
- "No se, dime" → revela y escoge nuevo objeto

### quiz
Trivia. Genera preguntas con 4 opciones (a,b,c,d) usando Gemini con JSON estructurado. Lleva puntaje. Baila cuando aciertas. Comparte un dato curioso despues de cada respuesta.

**Ejemplos:**
- Inicia automaticamente al entrar al modo
- "La b" → verifica, dice si es correcta, da fun fact
- "Otra pregunta" → genera nueva de tema diferente
- Temas: ciencia, geografia, historia, cultura pop, Guatemala, tecnologia

### code
Resuelve problemas de matematicas y logica ejecutando Python en sandbox de Gemini. Habla el resultado en 1-2 oraciones.

**Ejemplos:**
- "Cuanto es 347 por 892?"
- "Cual es la raiz cuadrada de 1764?"
- "Si tengo 5 manzanas y le doy 2 a cada uno de 3 amigos, cuantas me quedan?"
- "Cuantos numeros primos hay entre 1 y 1000?"

### sentiment
Pixel — perro robot emocional. Detecta el sentimiento en tu voz (tono + contenido) y cambia su expresion facial en tiempo real. Ojos animados que cambian de COLOR segun el mood: verde (happy), azul hielo (sad), rojo (angry), teal (surprised), cyan (neutral), ambar (curious). Tambien mueve el cuerpo (poses y danzas por mood). Google Search para preguntas factuales.

**Ejemplos:**
- "Estoy muy contento hoy!" → ojos verdes, pose excited, wiggle dance
- "Me siento mal..." → ojos azul hielo, pose sad
- "Eso me enoja mucho" → ojos rojos, pose firme
- "Que?! En serio?!" → ojos teal grandes, pose greet + dance
- "Cuanto cuesta un vuelo a Madrid?" → usa Google Search

## Arquitectura

```
                 +-----------------+
                 |  Gemini Live API |
                 | (gemini-3.1-flash|
                 |  -live-preview)  |
                 +--------+--------+
                          |
               WebSocket (audio + tools)
                          |
          +---------------+----------------+
          |                                |
   +------+------+                  +------+------+
   | on_device/  |                  | using_bridge|
   | __main__.py |                  | __main__.py |
   +------+------+                  +------+------+
          |                                |
   +------+------+                  +------+------+
   | GifDisplay  |                  | BridgeClient|
   | + EyeRender |                  | (HTTP POST) |
   +------+------+                  +------+------+
          |                                |
   +------+------+                  +------+------+
   | RobotMotion |                  | pupper-bridge|
   | (servos)    |                  | (FastAPI Pi) |
   +-------------+                  +--------------+

core/                    Compartido entre on_device y using_bridge
  audio.py               AudioManager (sounddevice, mic+speaker, echo suppression)
  stream.py              Streaming bidireccional Gemini (mic -> API -> audio/tools)
  audio_router.py        Dual-stream a Vosk + Gemini, pause/resume
  hotword.py             VoskHotwordDetector (bilingual EN+ES, background)
  camera.py              CameraManager (OpenCV, preview en mock)
  modes/
    base.py              Mode ABC + inject_switch_tool
    live.py              Conversacion libre + dance/nod + Google Search
    rocky.py             Rocky character + Eridian sounds + Google Search
    bumblebee.py         Song clips + catalog + crossfade + Google Search
    vision.py            I Spy + camera frames cada 5s
    quiz.py              Trivia + JSON schema + generateContent
    code.py              Math solver + code_execution sandbox
    sentiment.py         Pixel emocional + set_expression + Google Search

on_device/               Pi directo (MangDang HardwareInterface)
  __main__.py            Entry point + orchestrator + mode switching
  gif_display.py         GIF renderer + eye renderer (Bumblebee amarillo / Sentiment colores)
  robot_motion.py        Servo control: 5 poses, 2 dances, mood reactions

using_bridge/            Laptop + HTTP bridge
  __main__.py            Entry point + orchestrator
  bridge_client.py       httpx POST a pupper-bridge :9090
```

### Patron Mode ABC

Todos los modos heredan de `Mode` (`core/modes/base.py`) e implementan:

| Metodo / Atributo | Proposito |
|-------------------|-----------|
| `get_live_config(lang)` | Devuelve `LiveConnectConfig` (prompt, voz, tools, activity detection) |
| `handle_tool_call(fc, client, audio, robot)` | Ejecuta function calls (baile, busqueda, set_expression, etc.) |
| `get_greeting(lang)` (opcional) | Texto inicial que Gemini dice al entrar al modo |
| `on_enter(audio, robot, display)` (opcional) | Side effects al entrar (ej. sonido de radio en Bumblebee) |
| `on_output_transcription(text)` (opcional) | Intercepta transcripciones para trigger de efectos (Rocky `*happy*` -> WAV) |
| `extra_tasks(session, audio, camera)` (opcional) | Corutinas en paralelo al loop principal (Vision envia frames cada 5s) |
| `suppress_voice` (opcional) | Si `True`, ignora audio de Gemini (Bumblebee usa solo clips) |

`inject_switch_tool()` agrega el tool `switch_mode` preservando tools existentes (Google Search, function declarations). Fix importante: no reemplaza tools, los combina.

### Streaming loop (`core/stream.py`)

Un solo handler unificado gestiona todos los modos:

1. **Mic -> Gemini:** `send_audio()` envia PCM 16kHz con echo suppression (silencio durante playback, pass-through si RMS > threshold para permitir barge-in)
2. **Gemini -> altavoz:** `handle_responses()` reproduce audio (skip si `suppress_voice=True`), procesa transcripciones, ejecuta tool calls
3. **Tool mic suppression:** durante ejecucion de function calls, el mic se silencia (`audio.start_suppression()`) para evitar que ruido ambiental interrumpa al bot mientras procesa
4. **Switch mode:** si se llama `switch_mode`, el handler pone `switching=True` y drena respuestas pendientes sin reproducirlas (evita voz superpuesta)

### Capas de supresion de audio

Dos mecanismos independientes previenen echo y self-interrupts:

| Capa | Flag | Nivel | Uso |
|------|------|-------|-----|
| Clip-level | `audio.suppressing` | Absoluto (silencio total) | Durante reproduccion de WAVs/clips, tool execution. Nesteable via `_suppress_depth` counter |
| Chunk-level | `audio.speaking` | RMS gate | Mientras Gemini habla, silencia mic a menos que RMS > 1500 (permite interrumpir) |

### Threading model

```
macOS (mock):  Pygame MAIN thread    |  asyncio BACKGROUND thread
Pi:            asyncio MAIN thread   |  Pygame BACKGROUND thread (SDL_VIDEODRIVER=dummy)
```

Obligatorio: SDL requiere main thread en macOS; asyncio necesita main thread en Pi para signal handling.

### Resampleo de audio (Pi)

Hardware I2S del Pi corre a 48kHz. Gemini espera 16kHz in / 24kHz out. `AudioManager` hace resampleo lineal in-line (interpolacion simple, suficiente para voz).

### Stack tecnologico

- Python 3.10 (requerido por el BSP de MangDang)
- `uv` como package manager
- Gemini Live API (`gemini-3.1-flash-live-preview`) para voz
- Gemini API (`gemini-3.1-flash-lite-preview`) para quiz JSON y code execution
- `sounddevice` (PortAudio), `opencv-python`, `vosk` (solo Linux), `pydub`, `pyyaml`, `httpx`, `pygame` + `Pillow`

## Skills

Este repo incluye dos skills de referencia en `skills/` que cualquier agente (Claude Code, Cursor, etc.) puede cargar como contexto al trabajar en este tipo de proyecto:

| Skill | Cuando usarla |
|-------|---------------|
| [`skills/mini-pupper-2/SKILL.md`](skills/mini-pupper-2/SKILL.md) | Codigo para Mini Pupper 2 — servos, LCD, I2S, MangDang HardwareInterface, deployment en Pi, mock mode |
| [`skills/gemini-live-api/SKILL.md`](skills/gemini-live-api/SKILL.md) | Apps de voz/vision en tiempo real con Gemini Live API — session setup, streaming, tool calling, activity detection, transcription |

Cada skill es un documento conciso con:
- Overview y specs clave
- Patrones canonicos (codigo listo para copiar)
- Tablas de comparacion y decisiones
- Errores comunes y sus fixes

## Creacion de skills

Los skills anteriores se generaron con prompts estructurados, documentados en [`skill-creation-prompts.md`](skill-creation-prompts.md). Esos prompts se usan con agentes (Claude Code, Cursor, ChatGPT) que tienen acceso a web search para investigar docs oficiales y repos publicos antes de consolidar el skill.

La idea: en vez de hacer copy-paste de documentacion, el agente investiga fuentes oficiales (ai.google.dev, minipupperdocs, mangdangroboticsclub/mini_pupper) y produce un skill conciso y practico. Cada prompt define:

- Las fuentes que debe consultar (URLs especificas + web search queries)
- Los topicos que el skill DEBE cubrir (numerados)
- Constraints y formato (tablas, code blocks, brevedad)

Reproducir los skills:

```bash
# En Claude Code o Cursor con un agente que tenga web search
# Copiar el prompt correspondiente de skill-creation-prompts.md
# Pegar y ejecutar — el agente investiga y genera skills/<nombre>/SKILL.md
```

### Movimiento por modo

| Modo | Acciones | Cuando |
|------|----------|--------|
| **live** | dance, nod | Celebrar, asentir |
| **rocky** | dance, nod | "Amaze!" = dance, "Is good" = nod |
| **bumblebee** | dance, nod, shake | Segun el clip que reproduce |
| **vision** | look_around | Cuando busca nuevos objetos |
| **quiz** | dance | Cuando aciertas una pregunta |
| **code** | nod | Al presentar la solucion |
| **sentiment** | react_to_mood (5 poses + 2 dances) | Cada cambio de sentimiento |

### Display por modo

| Modo | Display |
|------|---------|
| **live** | GIF animado |
| **rocky** | GIF animado |
| **bumblebee** | Ojos mecanicos Autobot (amarillo fijo, forma cambia por mood, boca animada) |
| **vision** | GIF animado + preview camara (mock) |
| **quiz** | GIF animado |
| **code** | GIF animado |
| **sentiment** | Ojos animados (COLOR cambia por mood: verde/azul/rojo/teal/cyan/ambar) |

## on_device vs using_bridge

| | on_device | using_bridge |
|---|-----------|-------------|
| **Donde corre** | En el Pi directamente | Laptop (audio+Gemini) + Pi (servos via HTTP) |
| **Servos** | MangDang HardwareInterface directo | HTTP POST a pupper-bridge (FastAPI) |
| **LCD/Display** | ST7789 SPI (GIF o EyeRenderer) | Sin display (el proceso corre en laptop, el LCD esta en el Pi) |
| **Audio** | Pi I2S (48kHz resample) | Laptop audio nativo (24kHz) |
| **Mock mode** | `--mock` simula todo en laptop (Pygame + servos mock) | No aplica (siempre corre en laptop) |
| **Cambio de modo** | Vosk hotwords (Pi) o Gemini fallback | Gemini fallback (di "go rocky") |
| **Camara (vision)** | Pi camera o USB | Webcam laptop |

### Limitaciones

**on_device:**
- Requiere Pi con Ubuntu 22.04 + ROS2 Humble + MangDang BSP
- Python 3.10 (BSP requirement)
- Audio I2S a 48kHz requiere resample

**using_bridge:**
- Sin display (el LCD esta fisicamente en el Pi, no se controla desde la laptop)
- Bridge debe estar corriendo en Pi (`pupper-bridge` FastAPI en :9090)
- Requiere que el Pi este corriendo `pupper-bridge` (FastAPI en :9090)

## Cambio de modo por voz

Di **"go {modo}"** para cambiar. Funciona en todos los entornos:

- **En Pi (con Vosk):** Vosk detecta el hotword localmente, sin pasar por Gemini
- **En laptop / sin Vosk:** Gemini escucha "go rocky" y llama `switch_mode` como tool call

| Comando | Accion |
|---------|--------|
| "go live" | Conversacion libre |
| "go rocky" | Rocky (Project Hail Mary) |
| "go bumblebee" | Bumblebee (canciones) |
| "go vision" | Veo Veo (I Spy) |
| "go quiz" | Trivia |
| "go code" | Resolver matematicas |
| "go sentiment" / "go pixel" | Pixel (emocional) |
| "pausa" / "pause" | Silenciar mic (solo Vosk) |
| "activo" / "active" | Reanudar mic (solo Vosk) |

## Uso

Sin `--mode`, inicia en **live** (conversacion libre).

```bash
# Laptop (mock) — simula display + robot en ventana Pygame
uv run python -m on_device --lang es --mock
uv run python -m on_device --mode sentiment --lang es --mock
uv run python -m on_device --mode bumblebee --lang es --mock

# Pi (directo) — LCD real + servos
uv run python -m on_device --mode rocky --lang es
uv run python -m on_device --mode vision --lang es

# Laptop + bridge HTTP — voz en laptop, movimiento en Pi
uv run python -m using_bridge --mode quiz --lang en --bridge-url http://192.168.86.20:9090

# Para probar sin Pi, usar on_device --mock
```

## Setup

```bash
# Laptop
brew install portaudio ffmpeg
uv sync

# Pi
sudo apt install -y libportaudio2 python3.10-venv ffmpeg
uv venv --python 3.10 --system-site-packages
uv sync
```

```bash
cp .env.example .env
# Agregar GEMINI_API_KEY
```

## Modelos Vosk (opcional, Pi)

```bash
mkdir -p vosk-models && cd vosk-models
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
wget https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip
unzip '*.zip'
```

## Issues conocidos

| Issue | Severidad | Descripcion |
|-------|-----------|-------------|
| Session leak (bridge) | Media | `using_bridge` usa `__aenter__` manual en vez de `async with`. Puede leakear WebSocket connections tras muchos mode switches. Refactor futuro. |
| Thread leak (mic) | Baja | `queue.Queue.get()` sin timeout en el executor thread. Tras muchos switches puede agotar el thread pool. Workaround: reiniciar la app. |
| Audio device index (Pi) | Media | Device index hardcoded a `1` para I2S. Si el Pi enumera devices diferente tras reboot, audio falla silenciosamente. Verificar con `sd.query_devices()`. |
| Race condition (motion) | Baja | `react_to_mood` no pone `_busy=True` antes de delegar a `_run_dance`. Dos calls concurrentes podrian pelear por los servos. En practica los tool calls son serializados. |
| Crossfade parcial (bumblebee) | Baja | `play_sequence` solo crossfadea los primeros 2 clips. Del 3ro en adelante usa static+clip individual. |

## Variables de entorno

- `GEMINI_API_KEY` — requerido
- `BRIDGE_URL` — URL de pupper-bridge (default: `http://localhost:9090`)
