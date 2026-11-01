# =============================================================================
# Auth: Cognito User Pool, Domain, Identity Provider, and App Client
# (Migrated from infra/auth.yml)
# =============================================================================

locals {
  has_google     = var.google_client_id != ""
  cognito_domain = var.domain_prefix != "" ? var.domain_prefix : "${var.project_name}-${data.aws_caller_identity.current.account_id}"
  supported_idps = local.has_google ? ["COGNITO", "Google"] : ["COGNITO"]
}

resource "aws_cognito_user_pool" "user_pool" {
  name                     = "${var.project_name}-users"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  user_pool_tier           = "ESSENTIALS"

  username_configuration {
    case_sensitive = false
  }

  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  password_policy {
    minimum_length                   = 8
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
  }

  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  tags = {
    PROJECT_NAME = "demo"
  }
}

resource "aws_cognito_user_pool_domain" "user_pool_domain" {
  domain       = local.cognito_domain
  user_pool_id = aws_cognito_user_pool.user_pool.id
}

resource "aws_cognito_identity_provider" "google" {
  count         = local.has_google ? 1 : 0
  user_pool_id  = aws_cognito_user_pool.user_pool.id
  provider_name = "Google"
  provider_type = "Google"

  provider_details = {
    client_id        = var.google_client_id
    client_secret    = var.google_client_secret
    authorize_scopes = "openid email profile"
  }

  attribute_mapping = {
    email          = "email"
    email_verified = "email_verified"
    name           = "name"
  }
}

resource "aws_cognito_user_pool_client" "user_pool_client" {
  name         = "${var.project_name}-web"
  user_pool_id = aws_cognito_user_pool.user_pool.id

  generate_secret                      = false
  explicit_auth_flows                  = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = local.supported_idps
  callback_urls                        = var.app_urls
  logout_urls                          = var.app_urls

  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  depends_on = [
    aws_cognito_user_pool_domain.user_pool_domain,
    aws_cognito_identity_provider.google
  ]
}

resource "aws_cognito_managed_login_branding" "branding" {
  user_pool_id                = aws_cognito_user_pool.user_pool.id
  client_id                   = aws_cognito_user_pool_client.user_pool_client.id
  use_cognito_provided_values = true

  depends_on = [
    aws_cognito_user_pool_domain.user_pool_domain,
    aws_cognito_user_pool_client.user_pool_client
  ]
}
