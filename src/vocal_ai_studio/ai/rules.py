from __future__ import annotations

from vocal_ai_studio.ai.feedback import CoachFeedback, Exercise
from vocal_ai_studio.voice_analysis.metrics import VocalAnalysis
from vocal_ai_studio.voice_analysis.song import SongAnalysis


def _fmt_time(seconds: float) -> str:
    m, s = divmod(max(0.0, seconds), 60)
    return f"{int(m)}:{int(s):02d}"


def build_feedback(vocal: VocalAnalysis, song: SongAnalysis | None = None) -> CoachFeedback:
    strengths: list[str] = []
    issues: list[str] = []
    exercises: list[Exercise] = []

    dev = vocal.avg_cents_deviation
    if dev < 10:
        strengths.append(f"Tu afinación media es muy precisa (desviación de {dev:.0f} cents).")
    elif dev < 25:
        issues.append(f"Tu afinación media se desvía {dev:.0f} cents de la nota correcta.")
        exercises.append(Exercise(
            "Entonación con referencia",
            "Canta escalas lentas (Do-Re-Mi...) con un piano o afinador de referencia, "
            "sosteniendo cada nota 3-4 segundos antes de pasar a la siguiente.",
        ))
    else:
        issues.append(f"Tu afinación media se desvía bastante ({dev:.0f} cents) de la nota correcta.")
        exercises.append(Exercise(
            "Entrenamiento de oído + voz",
            "Practica con un drone (nota sostenida de fondo) en tu tonalidad y canta intervalos simples "
            "(unísono, tercera, quinta) hasta que suenen estables contra el drone.",
        ))

    stability = vocal.stability_cents
    if stability < 15:
        strengths.append("Mantienes el tono estable dentro de cada nota, sin temblor.")
    elif stability > 30:
        issues.append(f"El tono tiembla dentro de las notas sostenidas (variación de {stability:.0f} cents).")
        exercises.append(Exercise(
            "Notas largas sin vibrato",
            "Sostén una vocal (ej. 'ah') en una nota cómoda durante 8-10 segundos intentando mantener "
            "una línea de tono perfectamente recta, apoyada en la respiración.",
        ))

    worst = sorted(vocal.notes, key=lambda n: n.max_abs_cents, reverse=True)[:3]
    for note in worst:
        if note.max_abs_cents < 25:
            continue
        direction = "por encima" if note.avg_cents > 0 else "por debajo"
        issues.append(
            f"La nota en {_fmt_time(note.start)} ({note.name}) está {abs(note.avg_cents):.0f} cents {direction}."
        )

    if vocal.vocal_range:
        low, high = vocal.vocal_range
        strengths.append(f"Tu rango en esta toma va de {low} a {high}.")

    if vocal.vibrato_rate_hz is not None:
        rate, extent = vocal.vibrato_rate_hz, vocal.vibrato_extent_cents or 0.0
        if extent > 150:
            issues.append(f"Tu vibrato es muy amplio ({extent:.0f} cents) y puede sonar desafinado.")
            exercises.append(Exercise(
                "Vibrato controlado",
                "Sostén una nota recta (sin vibrato) la mitad del tiempo y deja que el vibrato aparezca "
                "de forma suave solo en la segunda mitad, controlando la amplitud con el apoyo del diafragma.",
            ))
        elif 4.5 <= rate <= 7.0:
            strengths.append(f"Tu vibrato ({rate:.1f} Hz) suena natural y controlado.")
    elif any(n.duration > 1.0 for n in vocal.notes):
        exercises.append(Exercise(
            "Introducir vibrato",
            "En notas largas, practica una ligera ondulación del tono (medio tono arriba/abajo) a un ritmo "
            "regular de unas 5-6 veces por segundo, primero despacio y luego más rápido.",
        ))

    long_pauses = [p for p in vocal.pauses if p[1] - p[0] > 1.0]
    if len(long_pauses) >= 3 and vocal.duration > 0:
        issues.append(f"Hay {len(long_pauses)} pausas largas; vigila la gestión de la respiración entre frases.")

    if not issues:
        summary = "Buen trabajo: no se detectaron problemas importantes de afinación o estabilidad."
    else:
        summary = f"Se detectaron {len(issues)} punto(s) a mejorar, principalmente de afinación y estabilidad."
    if song is not None and song.bpm:
        summary += f" Canción a {song.bpm_label} en {song.key_label}."

    if not exercises:
        exercises.append(Exercise(
            "Mantenimiento",
            "Sigue practicando escalas y arpegios diarios para conservar esta precisión.",
        ))

    return CoachFeedback(summary=summary, strengths=strengths, issues=issues, exercises=exercises)
