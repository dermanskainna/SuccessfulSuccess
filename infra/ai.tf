# =============================================================================
# AI: Agenda Parser Lambda (migrated from infra/ai.yml)
# =============================================================================

# -----------------------------------------------------------------------------
# IAM Role for the Agenda Parser Lambda
# -----------------------------------------------------------------------------
resource "aws_iam_role" "agenda_parser" {
  name = "${var.project_name}-agenda-parser"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    ProjectName = var.project_name
    ManagedBy   = "terraform"
  }
}

# Basic execution role (CloudWatch Logs)
resource "aws_iam_role_policy_attachment" "agenda_parser_basic" {
  role       = aws_iam_role.agenda_parser.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Permission to invoke Bedrock (CreateInference) for the selected model
resource "aws_iam_role_policy" "agenda_parser_bedrock" {
  name = "BedrockCreateInference"
  role = aws_iam_role.agenda_parser.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock-mantle:CreateInference"]
      Resource = "*"
    }]
  })
}

# -----------------------------------------------------------------------------
# Lambda Function (container image)
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "agenda_parser" {
  function_name = "${var.project_name}-agenda-parser"
  description   = "Parses meeting agenda using Anthropic Claude via Bedrock"
  package_type  = "Image"
  image_uri     = var.ai_image_uri
  architectures = [var.architecture]
  role          = aws_iam_role.agenda_parser.arn
  memory_size   = 512
  timeout       = var.ai_lambda_timeout

  # Image command matches the handler defined in the Docker image
  image_config {
    command = ["app.ai.agenda_lambda.handler"]
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.agenda_parser.name
  }

  environment {
    variables = {
      PARSER_MODEL = "anthropic.claude-sonnet-4-6"
      APP_TZ      = var.app_timezone
      LOG_LEVEL   = var.log_level
    }
  }

  tags = {
    ProjectName = var.project_name
    ManagedBy   = "terraform"
  }
}

# CloudWatch Log Group for the Lambda
resource "aws_cloudwatch_log_group" "agenda_parser" {
  name              = "/aws/lambda/${var.project_name}-agenda-parser"
  retention_in_days = 14
}

# -----------------------------------------------------------------------------
# Function URL (public access, CORS handled by infra/ai.yml)
# -----------------------------------------------------------------------------
resource "aws_lambda_function_url" "agenda_parser_url" {
  function_name = aws_lambda_function.agenda_parser.function_name
  authorization_type = "NONE"
  cors {
    allow_credentials = false
    allow_headers     = ["*"]
    allow_methods     = ["POST"]
    allow_origins     = [var.frontend_origin]
    expose_headers    = []
    max_age           = 0
  }
}
