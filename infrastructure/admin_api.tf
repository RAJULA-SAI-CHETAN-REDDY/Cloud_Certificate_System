resource "aws_api_gateway_authorizer" "admin" {
  name                           = "ccd-admin-cognito"
  rest_api_id                    = aws_api_gateway_rest_api.verification.id
  type                           = "COGNITO_USER_POOLS"
  provider_arns                  = [aws_cognito_user_pool.admin.arn]
  identity_source                = "method.request.header.Authorization"
  identity_validation_expression = "^${aws_cognito_user_pool_client.admin.id}$"
}

resource "aws_api_gateway_resource" "admin" {
  rest_api_id = aws_api_gateway_rest_api.verification.id
  parent_id   = aws_api_gateway_rest_api.verification.root_resource_id
  path_part   = "admin"
}

resource "aws_api_gateway_resource" "admin_session" {
  rest_api_id = aws_api_gateway_rest_api.verification.id
  parent_id   = aws_api_gateway_resource.admin.id
  path_part   = "session"
}

resource "aws_api_gateway_method" "admin_session" {
  rest_api_id   = aws_api_gateway_rest_api.verification.id
  resource_id   = aws_api_gateway_resource.admin_session.id
  http_method   = "GET"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.admin.id
}

resource "aws_api_gateway_integration" "admin_session" {
  rest_api_id             = aws_api_gateway_rest_api.verification.id
  resource_id             = aws_api_gateway_resource.admin_session.id
  http_method             = aws_api_gateway_method.admin_session.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.verification.invoke_arn
}

resource "aws_lambda_permission" "admin_api" {
  statement_id  = "AllowAdminSessionApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.verification.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.verification.execution_arn}/dev/GET/admin/session"
}

resource "aws_api_gateway_method" "admin_options" {
  rest_api_id   = aws_api_gateway_rest_api.verification.id
  resource_id   = aws_api_gateway_resource.admin_session.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "admin_options" {
  rest_api_id       = aws_api_gateway_rest_api.verification.id
  resource_id       = aws_api_gateway_resource.admin_session.id
  http_method       = aws_api_gateway_method.admin_options.http_method
  type              = "MOCK"
  request_templates = { "application/json" = "{\"statusCode\": 200}" }
}

resource "aws_api_gateway_method_response" "admin_options" {
  rest_api_id = aws_api_gateway_rest_api.verification.id
  resource_id = aws_api_gateway_resource.admin_session.id
  http_method = aws_api_gateway_method.admin_options.http_method
  status_code = "200"
  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin"  = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Headers" = true
  }
}

resource "aws_api_gateway_integration_response" "admin_options" {
  rest_api_id = aws_api_gateway_rest_api.verification.id
  resource_id = aws_api_gateway_resource.admin_session.id
  http_method = aws_api_gateway_method.admin_options.http_method
  status_code = aws_api_gateway_method_response.admin_options.status_code
  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,OPTIONS'"
    "method.response.header.Access-Control-Allow-Headers" = "'Authorization'"
  }
  depends_on = [aws_api_gateway_integration.admin_options]
}

# Cognito rejects missing/invalid tokens before Lambda; keep those errors local.
resource "aws_api_gateway_gateway_response" "admin_unauthorized" {
  rest_api_id   = aws_api_gateway_rest_api.verification.id
  response_type = "UNAUTHORIZED"
  status_code   = "401"
  response_parameters = {
    "gatewayresponse.header.Access-Control-Allow-Origin" = "'*'"
    "gatewayresponse.header.Cache-Control"               = "'no-store'"
  }
  response_templates = { "application/json" = "{\"error\":\"Sign in to continue.\"}" }
}
