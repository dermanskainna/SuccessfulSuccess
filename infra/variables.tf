# -----------------------------------------------------------------------------
# Global / Common Variables
# -----------------------------------------------------------------------------

variable "project_name" {
  description = "Prefix applied to the names of all resources in the stack."
  type        = string
  default     = "successfulsuccess"
}

variable "aws_region" {
  description = "AWS region for all deployed resources."
  type        = string
  default     = "us-east-1"
}

# -----------------------------------------------------------------------------
# Auth (Cognito) Variables
# -----------------------------------------------------------------------------

variable "domain_prefix" {
  description = "Prefix for Cognito UserPoolDomain. If empty, defaults to $${project_name}-$${account_id}."
  type        = string
  default     = ""
}

variable "app_urls" {
  description = "List of allowed callback and logout URLs for Cognito UserPoolClient."
  type        = list(string)
  default = [
    "http://localhost:3000/",
    "http://localhost:3000/auth/callback/"
  ]
}

variable "google_client_id" {
  description = "OAuth client ID of Google Cloud Web application client. Empty string disables Google sign-in."
  type        = string
  default     = ""
}

variable "google_client_secret" {
  description = "OAuth client secret of Google Cloud Web application client. Marked sensitive."
  type        = string
  default     = ""
  sensitive   = true
}

# -----------------------------------------------------------------------------
# Reports Stack Variables
# -----------------------------------------------------------------------------

variable "vpc_id" {
  description = "VPC ID where the backend and Aurora DB reside (used for Lambda builder and S3 gateway endpoint)."
  type        = string
  default     = ""
}

variable "subnet_ids" {
  description = "Private subnet IDs for the report builder Lambda."
  type        = list(string)
  default     = []
}

variable "route_table_ids" {
  description = "Route table IDs for subnets hosting the builder Lambda, used for the S3 Gateway VPCEndpoint."
  type        = list(string)
  default     = []
}

variable "security_group_id" {
  description = "Security Group ID for the report builder Lambda (allowing access to Aurora PostgreSQL)."
  type        = string
  default     = ""
}

variable "reports_image_uri" {
  description = "ECR container image URI (with tag or digest) for report builder and mailer Lambdas."
  type        = string
  default     = ""
}

variable "architecture" {
  description = "Instruction set architecture for Lambda functions (x86_64 or arm64)."
  type        = string
  default     = "x86_64"
  validation {
    condition     = contains(["x86_64", "arm64"], var.architecture)
    error_message = "architecture must be either 'x86_64' or 'arm64'."
  }
}

variable "builder_timeout" {
  description = "Timeout in seconds for report builder Lambda."
  type        = number
  default     = 60
}

variable "database_url" {
  description = "Database connection URL to Aurora PostgreSQL (postgresql+asyncpg://...)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "report_sender_email" {
  description = "Email address for report sender (verified in SES)."
  type        = string
  default     = "reports@example.com"
}

variable "report_recipient_email" {
  description = "Email address for report recipient (verified in SES)."
  type        = string
  default     = "admin@example.com"
}

variable "log_level" {
  description = "Log level for Lambda functions (DEBUG, INFO, WARNING, ERROR)."
  type        = string
  default     = "INFO"
}

# -----------------------------------------------------------------------------
# AI Agenda Parser Variables
# -----------------------------------------------------------------------------

variable "ai_image_uri" {
  description = "ECR container image URI for the AI agenda parser Lambda."
  type        = string
  default     = ""
}

variable "ai_lambda_timeout" {
  description = "Timeout in seconds for agenda parser Lambda."
  type        = number
  default     = 30
}

variable "frontend_origin" {
  description = "Allowed CORS origin for frontend (e.g. CloudFront URL or '*')."
  type        = string
  default     = "*"
}

variable "app_timezone" {
  description = "Application timezone for agenda parsing and report scheduling."
  type        = string
  default     = "Europe/Kyiv"
}
