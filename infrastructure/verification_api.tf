resource "aws_api_gateway_rest_api" "verification" {
  name = "ccd-verification-api"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_resource" "verify" {
  rest_api_id = aws_api_gateway_rest_api.verification.id
  parent_id   = aws_api_gateway_rest_api.verification.root_resource_id
  path_part   = "verify"
}

resource "aws_api_gateway_resource" "certificate_id" {
  rest_api_id = aws_api_gateway_rest_api.verification.id
  parent_id   = aws_api_gateway_resource.verify.id
  path_part   = "{id}"
}

resource "aws_api_gateway_method" "verify" {
  rest_api_id   = aws_api_gateway_rest_api.verification.id
  resource_id   = aws_api_gateway_resource.certificate_id.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "verify" {
  rest_api_id             = aws_api_gateway_rest_api.verification.id
  resource_id             = aws_api_gateway_resource.certificate_id.id
  http_method             = aws_api_gateway_method.verify.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.verification.invoke_arn
}

resource "aws_lambda_permission" "verification_api" {
  statement_id  = "AllowVerificationApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.verification.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.verification.execution_arn}/dev/GET/verify/*"
}

resource "aws_api_gateway_deployment" "verification" {
  rest_api_id = aws_api_gateway_rest_api.verification.id

  triggers = {
    redeployment = sha1(jsonencode({
      path                = aws_api_gateway_resource.certificate_id.path
      method              = aws_api_gateway_method.verify.http_method
      authorization       = aws_api_gateway_method.verify.authorization
      type                = aws_api_gateway_integration.verify.type
      uri                 = aws_api_gateway_integration.verify.uri
      admin_path          = aws_api_gateway_resource.admin_session.path
      admin_authorization = aws_api_gateway_method.admin_session.authorization
      admin_authorizer    = aws_api_gateway_authorizer.admin.id
      admin_client        = aws_api_gateway_authorizer.admin.identity_validation_expression
      admin_uri           = aws_api_gateway_integration.admin_session.uri
      admin_cors          = aws_api_gateway_integration_response.admin_options.response_parameters
      management_routes   = [aws_api_gateway_method.list_certificates.http_method, aws_api_gateway_method.revoke.http_method, aws_api_gateway_resource.revoke.path]
      management_uri      = aws_api_gateway_integration.revoke.uri
      management_cors     = aws_api_gateway_integration_response.revoke_options.response_parameters
      issuance_path       = aws_api_gateway_resource.admin_certificates.path
      issuance_authorizer = aws_api_gateway_method.issue.authorizer_id
      issuance_uri        = aws_api_gateway_integration.issue.uri
      issuance_cors       = aws_api_gateway_integration_response.issue_options.response_parameters
    }))
  }

  depends_on = [
    aws_api_gateway_integration.list_certificates, aws_lambda_permission.list_certificates_api,
    aws_api_gateway_integration.revoke, aws_lambda_permission.revoke_api,
    aws_api_gateway_integration_response.revoke_options,
    aws_api_gateway_integration.verify, aws_lambda_permission.verification_api,
    aws_api_gateway_integration.admin_session, aws_lambda_permission.admin_api,
    aws_api_gateway_integration_response.admin_options,
    aws_api_gateway_gateway_response.admin_unauthorized,
    aws_api_gateway_integration.issue, aws_lambda_permission.issuance_api,
    aws_api_gateway_integration_response.issue_options,
  ]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "verification" {
  deployment_id         = aws_api_gateway_deployment.verification.id
  rest_api_id           = aws_api_gateway_rest_api.verification.id
  stage_name            = "dev"
  cache_cluster_enabled = false
  xray_tracing_enabled  = false
}

resource "aws_api_gateway_method_settings" "verification" {
  rest_api_id = aws_api_gateway_rest_api.verification.id
  stage_name  = aws_api_gateway_stage.verification.stage_name
  method_path = "*/*"

  settings {
    throttling_burst_limit = 5
    throttling_rate_limit  = 2
    caching_enabled        = false
    metrics_enabled        = false
    logging_level          = "OFF"
    data_trace_enabled     = false
  }
}

output "verification_api_url" {
  value = "${aws_api_gateway_stage.verification.invoke_url}/verify"
}

# Browser-readable errors even when API Gateway rejects a request before Lambda.
resource "aws_api_gateway_gateway_response" "cors_errors" {
  for_each      = toset(["DEFAULT_4XX", "DEFAULT_5XX"])
  rest_api_id   = aws_api_gateway_rest_api.verification.id
  response_type = each.value
  response_templates = {
    "application/json" = "{\"message\":$context.error.messageString}"
  }

  response_parameters = {
    "gatewayresponse.header.Access-Control-Allow-Origin" = "'*'"
    "gatewayresponse.header.Cache-Control"               = "'no-store'"
  }
}
