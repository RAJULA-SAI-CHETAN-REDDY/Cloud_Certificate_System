# Management uses the existing protected issuance Lambda and existing table/topic.
resource "aws_api_gateway_resource" "admin_certificate" {
  rest_api_id = aws_api_gateway_rest_api.verification.id
  parent_id   = aws_api_gateway_resource.admin_certificates.id
  path_part   = "{id}"
}
resource "aws_api_gateway_resource" "revoke" {
  rest_api_id = aws_api_gateway_rest_api.verification.id
  parent_id   = aws_api_gateway_resource.admin_certificate.id
  path_part   = "revoke"
}

resource "aws_api_gateway_method" "list_certificates" {
  rest_api_id   = aws_api_gateway_rest_api.verification.id
  resource_id   = aws_api_gateway_resource.admin_certificates.id
  http_method   = "GET"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.admin.id
}
resource "aws_api_gateway_integration" "list_certificates" {
  rest_api_id             = aws_api_gateway_rest_api.verification.id
  resource_id             = aws_api_gateway_resource.admin_certificates.id
  http_method             = aws_api_gateway_method.list_certificates.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.issuance.invoke_arn
}
resource "aws_lambda_permission" "list_certificates_api" {
  statement_id  = "Allowlist_certificatesApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.issuance.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.verification.execution_arn}/dev/GET/admin/certificates"
}

resource "aws_api_gateway_method" "revoke" {
  rest_api_id   = aws_api_gateway_rest_api.verification.id
  resource_id   = aws_api_gateway_resource.revoke.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.admin.id
}
resource "aws_api_gateway_integration" "revoke" {
  rest_api_id             = aws_api_gateway_rest_api.verification.id
  resource_id             = aws_api_gateway_resource.revoke.id
  http_method             = aws_api_gateway_method.revoke.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.issuance.invoke_arn
}
resource "aws_lambda_permission" "revoke_api" {
  statement_id  = "AllowrevokeApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.issuance.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.verification.execution_arn}/dev/POST/admin/certificates/*/revoke"
}
resource "aws_api_gateway_method" "revoke_options" {
  rest_api_id   = aws_api_gateway_rest_api.verification.id
  resource_id   = aws_api_gateway_resource.revoke.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "revoke_options" {
  rest_api_id       = aws_api_gateway_rest_api.verification.id
  resource_id       = aws_api_gateway_resource.revoke.id
  http_method       = aws_api_gateway_method.revoke_options.http_method
  type              = "MOCK"
  request_templates = { "application/json" = "{\"statusCode\":200}" }
}

resource "aws_api_gateway_method_response" "revoke_options" {
  rest_api_id = aws_api_gateway_rest_api.verification.id
  resource_id = aws_api_gateway_resource.revoke.id
  http_method = aws_api_gateway_method.revoke_options.http_method
  status_code = "200"
  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin"  = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Headers" = true
  }
}

resource "aws_api_gateway_integration_response" "revoke_options" {
  rest_api_id = aws_api_gateway_rest_api.verification.id
  resource_id = aws_api_gateway_resource.revoke.id
  http_method = aws_api_gateway_method.revoke_options.http_method
  status_code = aws_api_gateway_method_response.revoke_options.status_code
  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'"
    "method.response.header.Access-Control-Allow-Headers" = "'Authorization,Content-Type'"
  }
  depends_on = [aws_api_gateway_integration.revoke_options]
}
