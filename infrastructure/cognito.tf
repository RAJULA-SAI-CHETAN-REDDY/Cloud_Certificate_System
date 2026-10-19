resource "aws_cognito_user_pool" "admin" {
  name                     = "ccd-admin"
  user_pool_tier           = "LITE"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  deletion_protection      = "ACTIVE"

  username_configuration {
    case_sensitive = false
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 3
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_cognito_user_pool_client" "admin" {
  name                                 = "ccd-admin-browser"
  user_pool_id                         = aws_cognito_user_pool.admin.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["http://localhost:8000/admin.html", "${local.website_origin}/admin.html"]
  logout_urls                          = ["http://localhost:8000/verify.html", "${local.website_origin}/verify.html"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH"]
  access_token_validity                = 15
  id_token_validity                    = 15
  refresh_token_validity               = 1

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

resource "aws_cognito_user_group" "admins" {
  name         = "admins"
  user_pool_id = aws_cognito_user_pool.admin.id
  description  = "Certificate administrators"
}

resource "aws_cognito_user_pool_domain" "admin" {
  domain                = "ccd-admin-${data.aws_caller_identity.current.account_id}"
  user_pool_id          = aws_cognito_user_pool.admin.id
  managed_login_version = 1
}

output "admin_user_pool_id" {
  value = aws_cognito_user_pool.admin.id
}

output "admin_client_id" {
  value = aws_cognito_user_pool_client.admin.id
}
