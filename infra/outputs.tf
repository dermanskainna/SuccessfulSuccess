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

# Lambda functions
output "agenda_parser_lambda_name" {
  description = "Name of the agenda‑parser Lambda function"
  value       = aws_lambda_function.agenda_parser.function_name
}

output "agenda_parser_function_url" {
  description = "Function URL for the agenda‑parser Lambda"
  value       = aws_lambda_function_url.agenda_parser_url.function_url
}
