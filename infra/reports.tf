# =============================================================================
# Reports: Weekly Meeting Reports Pipeline
# (Migrated from infra/reports.yml)
# =============================================================================

locals {
  reports_bucket_name = "${var.project_name}-reports-${data.aws_caller_identity.current.account_id}"
  distinct_recipient  = var.report_sender_email != var.report_recipient_email
}

# -----------------------------------------------------------------------------
# S3 Bucket & Policies
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "reports" {
  bucket = local.reports_bucket_name
}

resource "aws_s3_bucket_public_access_block" "reports" {
  bucket = aws_s3_bucket.reports.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    id     = "ExpireReportsAfter90Days"
    status = "Enabled"

    filter {
      prefix = "reports/"
    }

    expiration {
      days = 90
    }
  }
}

resource "aws_s3_bucket_notification" "reports_notification" {
  bucket = aws_s3_bucket.reports.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.mailer.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "reports/"
    filter_suffix       = ".csv"
  }

  depends_on = [
    aws_lambda_permission.s3_invoke_mailer
  ]
}

# -----------------------------------------------------------------------------
# VPC Endpoint: Gateway for S3
# -----------------------------------------------------------------------------

resource "aws_vpc_endpoint" "s3_gateway" {
  count             = var.vpc_id != "" ? 1 : 0
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.route_table_ids

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = "*"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${local.reports_bucket_name}",
          "arn:aws:s3:::${local.reports_bucket_name}/*",
          "arn:aws:s3:::prod-us-east-1-starport-layer-bucket/*",
          "arn:aws:s3:::prod-us-east-1-starport-layer-bucket"
        ]
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# SQS: Report Requests Queue & DLQ
# -----------------------------------------------------------------------------

resource "aws_sqs_queue" "report_requests_dlq" {
  name                      = "${var.project_name}-report-requests-dlq"
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "report_requests" {
  name                       = "${var.project_name}-report-requests"
  visibility_timeout_seconds = 360

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.report_requests_dlq.arn
    maxReceiveCount     = 3
  })
}

# -----------------------------------------------------------------------------
# IAM: Roles and Policies
# -----------------------------------------------------------------------------

# Builder Role (in VPC)
resource "aws_iam_role" "builder" {
  name = "${var.project_name}-report-builder"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "builder_vpc" {
  role       = aws_iam_role.builder.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy_attachment" "builder_sqs" {
  role       = aws_iam_role.builder.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole"
}

resource "aws_iam_role_policy" "builder_s3" {
  name = "S3PutReports"
  role = aws_iam_role.builder.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject"
        ]
        Resource = "arn:aws:s3:::${local.reports_bucket_name}/reports/*"
      }
    ]
  })
}

# Mailer Role (outside VPC)
resource "aws_iam_role" "mailer" {
  name = "${var.project_name}-report-mailer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "mailer_basic" {
  role       = aws_iam_role.mailer.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "mailer_s3" {
  name = "S3ReadReports"
  role = aws_iam_role.mailer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "arn:aws:s3:::${local.reports_bucket_name}/reports/*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "mailer_ses" {
  name = "SESSendEmail"
  role = aws_iam_role.mailer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail",
          "sesv2:SendEmail",
          "sesv2:SendRawEmail"
        ]
        Resource = "*"
      }
    ]
  })
}

# Scheduler Role
resource "aws_iam_role" "scheduler" {
  name = "${var.project_name}-report-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "scheduler.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "scheduler_sqs" {
  name = "SendToReportQueue"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.report_requests.arn
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# CloudWatch Log Groups
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "builder" {
  name              = "/aws/lambda/${var.project_name}-report-builder"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "mailer" {
  name              = "/aws/lambda/${var.project_name}-report-mailer"
  retention_in_days = 14
}

# -----------------------------------------------------------------------------
# Lambda Functions
# -----------------------------------------------------------------------------

resource "aws_lambda_function" "builder" {
  function_name = "${var.project_name}-report-builder"
  description   = "Generates CSV reports and uploads them to S3 (in VPC)"
  package_type  = "Image"
  image_uri     = var.reports_image_uri
  architectures = [var.architecture]
  role          = aws_iam_role.builder.arn
  memory_size   = 256
  timeout       = var.builder_timeout

  image_config {
    command = ["app.reports.lambda_handler.builder_handler"]
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.builder.name
  }

  dynamic "vpc_config" {
    for_each = length(var.subnet_ids) > 0 ? [1] : []
    content {
      subnet_ids         = var.subnet_ids
      security_group_ids = var.security_group_id != "" ? [var.security_group_id] : []
    }
  }

  environment {
    variables = {
      REPORT_BUCKET = local.reports_bucket_name
      LOG_LEVEL     = var.log_level
      DATABASE_URL  = var.database_url
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.builder
  ]
}

resource "aws_lambda_function" "mailer" {
  function_name = "${var.project_name}-report-mailer"
  description   = "Sends CSV reports via email using SES v2 (outside VPC)"
  package_type  = "Image"
  image_uri     = var.reports_image_uri
  architectures = [var.architecture]
  role          = aws_iam_role.mailer.arn
  memory_size   = 128
  timeout       = 30

  image_config {
    command = ["app.reports.lambda_handler.mailer_handler"]
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.mailer.name
  }

  # Intentionally without VPC config to access SES public endpoint
  environment {
    variables = {
      REPORT_BUCKET    = local.reports_bucket_name
      REPORT_SENDER    = var.report_sender_email
      REPORT_RECIPIENT = var.report_recipient_email
      LOG_LEVEL        = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.mailer
  ]
}

# S3 invocation permission for Mailer Lambda
resource "aws_lambda_permission" "s3_invoke_mailer" {
  statement_id   = "AllowExecutionFromS3Bucket"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.mailer.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = "arn:aws:s3:::${local.reports_bucket_name}"
  source_account = data.aws_caller_identity.current.account_id
}

# SQS -> Builder Lambda Event Source Mapping
resource "aws_lambda_event_source_mapping" "builder_sqs" {
  event_source_arn        = aws_sqs_queue.report_requests.arn
  function_name           = aws_lambda_function.builder.arn
  batch_size              = 1
  enabled                 = true
  function_response_types = ["ReportBatchItemFailures"]
}

# -----------------------------------------------------------------------------
# EventBridge Scheduler: Weekly on Monday at 07:00 Kyiv
# -----------------------------------------------------------------------------

resource "aws_scheduler_schedule" "weekly_report" {
  name                         = "${var.project_name}-weekly-report"
  description                  = "Runs weekly report every Monday at 07:00 Kyiv time"
  schedule_expression          = "cron(0 7 ? * MON *)"
  schedule_expression_timezone = var.app_timezone
  state                        = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sqs_queue.report_requests.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ week = null, source = "schedule" })
  }
}

# -----------------------------------------------------------------------------
# SES Email Identities
# -----------------------------------------------------------------------------

resource "aws_ses_email_identity" "sender" {
  email = var.report_sender_email
}

resource "aws_ses_email_identity" "recipient" {
  count = local.distinct_recipient ? 1 : 0
  email = var.report_recipient_email
}
