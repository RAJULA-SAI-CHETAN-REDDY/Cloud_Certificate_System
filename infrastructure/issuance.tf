resource "aws_cloudwatch_log_group" "issuance" {
  name              = "/aws/lambda/ccd-issue-certificate"
  retention_in_days = 30
}

resource "aws_iam_role" "issuance" {
  name = "ccd-issuance-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "issuance" {
  name = "ccd-issuance-runtime"
  role = aws_iam_role.issuance.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Scan"], Resource = aws_dynamodb_table.certificates.arn },
      { Effect = "Allow", Action = ["dynamodb:UpdateItem"], Resource = aws_dynamodb_table.certificates.arn,
      Condition = { "ForAllValues:StringLike" = { "dynamodb:LeadingKeys" = ["NOTIFY#ISSUED#CERT-*", "NOTIFY#REVOKED#CERT-*", "CERT-*"] } } },
      { Effect = "Allow", Action = ["sns:Publish"], Resource = aws_sns_topic.certificate_events.arn },
      { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject"], Resource = "${aws_s3_bucket.certificates.arn}/certificates/*" },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.issuance.arn}:*" }
    ]
  })
}

resource "aws_lambda_function" "issuance" {
  function_name    = "ccd-issue-certificate"
  role             = aws_iam_role.issuance.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "lambda_issue.lambda_handler"
  filename         = "${path.module}/../output/lambda/issuance.zip"
  source_code_hash = filebase64sha256("${path.module}/../output/lambda/issuance.zip")
  memory_size      = 256
  timeout          = 20
  environment {
    variables = {
      CERTIFICATE_TABLE      = aws_dynamodb_table.certificates.name
      CERTIFICATE_BUCKET     = aws_s3_bucket.certificates.bucket
      ADMIN_ISSUER           = "https://cognito-idp.ap-south-1.amazonaws.com/${aws_cognito_user_pool.admin.id}"
      ADMIN_ORGANIZATIONS    = jsonencode(var.admin_organizations)
      ADMIN_CLIENT_ID        = aws_cognito_user_pool_client.admin.id
      VERIFICATION_BASE_URL  = "${local.website_origin}/verify.html"
      ADMIN_WEBSITE_ORIGIN   = local.website_origin
      NOTIFICATION_TOPIC_ARN = aws_sns_topic.certificate_events.arn
    }
  }
  depends_on = [aws_iam_role_policy.issuance, aws_cloudwatch_log_group.issuance]
}

resource "aws_api_gateway_resource" "admin_certificates" {
  rest_api_id = aws_api_gateway_rest_api.verification.id
  parent_id   = aws_api_gateway_resource.admin.id
  path_part   = "certificates"
}

resource "aws_api_gateway_method" "issue" {
  rest_api_id   = aws_api_gateway_rest_api.verification.id
  resource_id   = aws_api_gateway_resource.admin_certificates.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.admin.id
}

resource "aws_api_gateway_integration" "issue" {
  rest_api_id             = aws_api_gateway_rest_api.verification.id
  resource_id             = aws_api_gateway_resource.admin_certificates.id
  http_method             = aws_api_gateway_method.issue.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.issuance.invoke_arn
}

resource "aws_lambda_permission" "issuance_api" {
  statement_id  = "AllowIssuanceApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.issuance.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.verification.execution_arn}/dev/POST/admin/certificates"
}

resource "aws_api_gateway_method" "issue_options" {
  rest_api_id   = aws_api_gateway_rest_api.verification.id
  resource_id   = aws_api_gateway_resource.admin_certificates.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "issue_options" {
  rest_api_id       = aws_api_gateway_rest_api.verification.id
  resource_id       = aws_api_gateway_resource.admin_certificates.id
  http_method       = aws_api_gateway_method.issue_options.http_method
  type              = "MOCK"
  request_templates = { "application/json" = "{\"statusCode\":200}" }
}

resource "aws_api_gateway_method_response" "issue_options" {
  rest_api_id = aws_api_gateway_rest_api.verification.id
  resource_id = aws_api_gateway_resource.admin_certificates.id
  http_method = aws_api_gateway_method.issue_options.http_method
  status_code = "200"
  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin"  = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Headers" = true
  }
}

resource "aws_api_gateway_integration_response" "issue_options" {
  rest_api_id = aws_api_gateway_rest_api.verification.id
  resource_id = aws_api_gateway_resource.admin_certificates.id
  http_method = aws_api_gateway_method.issue_options.http_method
  status_code = aws_api_gateway_method_response.issue_options.status_code
  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,POST,OPTIONS'"
    "method.response.header.Access-Control-Allow-Headers" = "'Authorization,Content-Type,Idempotency-Key'"
  }
  depends_on = [aws_api_gateway_integration.issue_options]
}
