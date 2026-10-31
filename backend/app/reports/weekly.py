"""Генератор тижневого CSV-звіту про зустрічі.

Функція ``build_weekly_report`` читає базу даних і повертає байти CSV-файлу.
Звіт ідемпотентний: двічі запущений для одного й того самого тижня дає
однаковий результат і перезаписує один і той самий ключ в S3.
"""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import date, timedelta

from sqlalchemy import func, select, text

from app.db import SessionFactory
from app.models.meeting import Meeting, Participant


def _previous_iso_week() -> str:
    """Повертає рядок ISO-тижня для минулого тижня, напр. '2026-W40'."""
    today = date.today()
    # isocalendar повертає (рік, тиждень, день_тижня); відступаємо на 7 днів
    prev = today - timedelta(days=7)
    iso = prev.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _week_bounds(week: str) -> tuple[str, str]:
    """Повертає (понеділок, неділя) ISO-тижня у форматі 'YYYY-MM-DD'.

    Наприклад, для '2026-W40':
      Monday = 2026-09-28, Sunday = 2026-10-04
    """
    # Python 3.8+: date.fromisocalendar(year, week, day)
    year, w = week.split("-W")
    monday = date.fromisocalendar(int(year), int(w), 1)
    sunday = monday + timedelta(days=6)
    return str(monday), str(sunday)


async def _fetch_week_data(week_start: str, week_end: str) -> list[Meeting]:
    """Завантажує зустрічі за вказаний інтервал дат з БД."""
    async with SessionFactory() as session:
        result = await session.execute(
            select(Meeting)
            .where(
                func.date(Meeting.starts_at) >= week_start,
                func.date(Meeting.starts_at) <= week_end,
            )
            .order_by(
                # Для топ-5 найдовших — сортуємо за тривалістю спадно
                (Meeting.ends_at - Meeting.starts_at).desc()
            )
        )
        return list(result.scalars().all())


async def _fetch_week_summary(week_start: str, week_end: str) -> tuple[int, float]:
    """Повертає (кількість_зустрічей, сума_годин) за інтервал дат."""
    async with SessionFactory() as session:
        row = await session.execute(
            select(
                func.count(Meeting.id).label("cnt"),
                func.coalesce(
                    func.sum(
                        func.extract("epoch", Meeting.ends_at - Meeting.starts_at) / 3600
                    ),
                    0,
                ).label("hours"),
            ).where(
                func.date(Meeting.starts_at) >= week_start,
                func.date(Meeting.starts_at) <= week_end,
            )
        )
        r = row.one()
        return int(r.cnt), float(r.hours)


def build_weekly_report(week: str | None = None) -> bytes:
    """Генерує CSV-звіт для вказаного ISO-тижня й повертає байти.

    Args:
        week: рядок ISO-тижня, напр. ``'2026-W40'``. Якщо ``None`` або не
              передано — використовується минулий тиждень.

    Returns:
        Байти UTF-8 CSV з BOM (для коректного відкриття в Excel).
    """
    if not week:
        week = _previous_iso_week()

    week_start, week_end = _week_bounds(week)

    # Минулий тиждень — для відображення динаміки
    prev_year, prev_w = week.split("-W")
    prev_week_date = date.fromisocalendar(int(prev_year), int(prev_w), 1) - timedelta(days=7)
    prev_iso = prev_week_date.isocalendar()
    prev_week = f"{prev_iso[0]}-W{prev_iso[1]:02d}"
    prev_start, prev_end = _week_bounds(prev_week)

    # Запускаємо всі запити паралельно в одному event loop
    async def _gather() -> tuple[list[Meeting], tuple[int, float], tuple[int, float]]:
        meetings, curr_summary, prev_summary = await asyncio.gather(
            _fetch_week_data(week_start, week_end),
            _fetch_week_summary(week_start, week_end),
            _fetch_week_summary(prev_start, prev_end),
        )
        return meetings, curr_summary, prev_summary

    meetings, (curr_count, curr_hours), (prev_count, prev_hours) = asyncio.run(_gather())

    # --- Побудова CSV ---
    output = io.StringIO()
    writer = csv.writer(output)

    # Секція 1: Загальна статистика
    writer.writerow(["section", "metric", "value"])
    writer.writerow(["summary", "week", week])
    writer.writerow(["summary", "week_start", week_start])
    writer.writerow(["summary", "week_end", week_end])
    writer.writerow(["summary", "total_meetings", curr_count])
    writer.writerow(["summary", "total_hours", f"{curr_hours:.2f}"])
    writer.writerow(["summary", "prev_week", prev_week])
    writer.writerow(["summary", "prev_total_meetings", prev_count])
    writer.writerow(["summary", "prev_total_hours", f"{prev_hours:.2f}"])
    writer.writerow(
        [
            "summary",
            "change_meetings",
            f"{curr_count - prev_count:+d}",
        ]
    )
    writer.writerow(
        [
            "summary",
            "change_hours",
            f"{curr_hours - prev_hours:+.2f}",
        ]
    )

    # Секція 2: Топ-5 найдовших зустрічей
    writer.writerow([])
    writer.writerow(["section", "rank", "title", "starts_at", "duration_min", "participants"])
    for rank, meeting in enumerate(meetings[:5], start=1):
        duration_sec = (meeting.ends_at - meeting.starts_at).total_seconds()
        duration_min = int(duration_sec // 60)
        writer.writerow(
            [
                "top5",
                rank,
                meeting.name,
                meeting.starts_at.isoformat(),
                duration_min,
                len(meeting.participants),
            ]
        )

    # BOM (\ufeff) для сумісності з Excel
    return ("\ufeff" + output.getvalue()).encode("utf-8")

