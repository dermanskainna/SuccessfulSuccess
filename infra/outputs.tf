# =============================================================================
# Terraform Outputs (used by frontend, Makefile, etc.)
# =============================================================================

# Cognito
output "cognito_user_pool_id" {
  description = "ID of the Cognito User Pool"
  value       = aws_cognito_user_pool.user_pool.id
}

output "cognito_user_pool_client_id" {
  description = "ID of the Cognito User Pool App Client"
  value       = aws_cognito_user_pool_client.user_pool_client.id
}

output "cognito_user_pool_domain" {
  description = "Domain name for the Cognito User Pool"
  value       = aws_cognito_user_pool_domain.user_pool_domain.domain
}

# Reports bucket
output "reports_bucket_name" {
  description = "Name of the S3 bucket that stores generated reports"
  value       = aws_s3_bucket.reports.bucket
}

# SQS queues
output "report_requests_queue_url" {
  description = "URL of the report requests SQS queue"
  value       = aws_sqs_queue.report_requests.id
}

output "report_requests_dlq_url" {
  description = "URL of the dead‑letter queue for report requests"
  value       = aws_sqs_queue.report_requests_dlq.id
}

# Lambda functions
output "agenda_parser_lambda_name" {
  description = "Name of the agenda‑parser Lambda function"
  value       = aws_lambda_function.agenda_parser.function_name
}

output "agenda_parser_function_url" {
  description = "Function URL for the agenda‑parser Lambda"
  value       = aws_lambda_function_url.agenda_parser_url.function_url
}

# Optional: expose the reports builder and mailer function names (useful for CI/CD)
output "report_builder_lambda_name" {
  description = "Name of the report builder Lambda"
  value       = aws_lambda_function.builder.function_name
}

output "report_mailer_lambda_name" {
  description = "Name of the report mailer Lambda"
  value       = aws_lambda_function.mailer.function_name
}
