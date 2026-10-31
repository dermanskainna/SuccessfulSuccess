"""Lambda-обробники для звітної підсистеми.

builder_handler — виконується у VPC, читає БД, пише CSV до S3.
mailer_handler  — виконується поза VPC, читає CSV з S3, надсилає email через SES.

Ці функції розгортаються з одного й того ж образу (той самий Dockerfile.lambda),
але кожна з них зареєстрована в CloudFormation як окрема Lambda-функція
з різним CMD / Handler і різними VpcConfig.
"""

from __future__ import annotations

import json
import logging
import os
from email.message import EmailMessage

import boto3

from app.reports.weekly import build_weekly_report, _previous_iso_week

# Структурований логер — CloudWatch збирає їх як JSON
log = logging.getLogger(__name__)
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


# ---------------------------------------------------------------------------
# Допоміжні функції
# ---------------------------------------------------------------------------


def detect_trigger(event: dict) -> str:
    """Визначає джерело виклику Lambda для логування."""
    if "Records" in event:
        source = event["Records"][0].get("eventSource", "")
        if source == "aws:sqs":
            return "sqs"
        if source == "aws:s3":
            return "s3"
    if event.get("source") == "schedule":
        return "schedule"
    if "action" in event:
        return "direct"
    return "unknown"


def _parse_week(event: dict) -> str:
    """Витягує тиждень з різних форматів запиту.

    Підтримує:
    - Пряме звернення: ``{"week": "2026-W40"}``
    - Виклик з SQS: ``event["Records"][0]["body"]`` (JSON-рядок або dict)
    - Розклад EventBridge: ``{"week": null, "source": "schedule"}``
    """
    week = None

    if "Records" in event and event["Records"]:
        body = event["Records"][0].get("body", "{}")
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except (json.JSONDecodeError, TypeError):
                body = {}
        week = body.get("week")
    else:
        week = event.get("week")

    # null, "" або відсутність → минулий тиждень
    if not week:
        week = _previous_iso_week()

    return week


# ---------------------------------------------------------------------------
# Builder: читає БД, завантажує CSV до S3
# ---------------------------------------------------------------------------


def builder_handler(event: dict, context: object) -> dict:
    """Точка входу для Lambda-будівника звітів (у VPC).

    Тригери: SQS, EventBridge Scheduler, пряме тестове звернення.
    Ключ у S3 завжди ``reports/{week}.csv`` → ідемпотентність.
    """
    trigger = detect_trigger(event)
    week = _parse_week(event)

    log.info("report-builder triggered", extra={"trigger": trigger, "week": week})

    # Генеруємо CSV-байти (звернення до БД через SQLAlchemy/asyncpg)
    csv_bytes = build_weekly_report(week)

    bucket = os.environ["REPORT_BUCKET"]
    key = f"reports/{week}.csv"

    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=csv_bytes,
        ContentType="text/csv; charset=utf-8",
    )

    log.info("report uploaded", extra={"bucket": bucket, "key": key, "bytes": len(csv_bytes)})
    return {"status": "ok", "bucket": bucket, "key": key, "week": week}


# Аліас для універсального виклику app.reports.lambda_handler.handler
handler = builder_handler


# ---------------------------------------------------------------------------
# Mailer: читає CSV з S3, надсилає email через SES v2
# ---------------------------------------------------------------------------


def mailer_handler(event: dict, context: object) -> dict:
    """Точка входу для Lambda-розсилки звітів (поза VPC, є доступ до SES).

    Тригер: S3 ObjectCreated з префіксом ``reports/`` і суфіксом ``.csv``.
    НІКОЛИ не записує нічого у ``reports/`` — щоб уникнути нескінченного циклу.
    """
    # Обробляємо всі S3-записи в батч-події (зазвичай по одному)
    sent: list[str] = []

    for record in event.get("Records", []):
        s3_info = record.get("s3", {})
        bucket = s3_info.get("bucket", {}).get("name", "")
        # URL-декодування ключа (AWS кодує пробіли і спецсимволи)
        import urllib.parse
        key = urllib.parse.unquote_plus(s3_info.get("object", {}).get("key", ""))

        log.info("mailer triggered", extra={"bucket": bucket, "key": key})

        # Зайвий захист: якщо тригер прийшов не з reports/ — ігноруємо
        if not key.startswith("reports/") or not key.endswith(".csv"):
            log.warning("unexpected key, skipping", extra={"key": key})
            continue

        # Зчитуємо CSV з S3
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key=key)
        csv_bytes = obj["Body"].read()

        week = key.removeprefix("reports/").removesuffix(".csv")

        # Будуємо MIME-повідомлення
        recipient = os.environ["REPORT_RECIPIENT"]
        sender = os.environ["REPORT_SENDER"]

        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = f"Тижневий звіт про зустрічі: {week}"
        msg.set_content(
            f"Вітаємо!\n\n"
            f"У додатку до цього листа — тижневий звіт за {week}.\n\n"
            f"З повагою,\nSuccessfulSuccess Reports"
        )
        msg.add_attachment(
            csv_bytes,
            maintype="text",
            subtype="csv",
            filename=f"meetings-{week}.csv",
        )

        # Надсилаємо через SES v2 (функція поза VPC має інтернет-доступ)
        sesv2 = boto3.client("sesv2", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        sesv2.send_email(
            FromEmailAddress=sender,
            Destination={"ToAddresses": [recipient]},
            Content={
                "Raw": {"Data": msg.as_bytes()},
            },
        )

        log.info("email sent", extra={"to": recipient, "week": week})
        sent.append(key)

    return {"status": "ok", "sent": sent}

