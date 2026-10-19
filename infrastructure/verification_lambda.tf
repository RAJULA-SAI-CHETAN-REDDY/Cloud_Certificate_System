resource "aws_cloudwatch_log_group" "verification" {
  name              = "/aws/lambda/ccd-verify-certificate"
  retention_in_days = 30
}

resource "aws_iam_role" "verification" {
  name = "ccd-verification-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "verification" {
  name = "ccd-verification-runtime"
  role = aws_iam_role.verification.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem"]
        Resource = aws_dynamodb_table.certificates.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.verification.arn}:*"
      }
    ]
  })
}

resource "aws_lambda_function" "verification" {
  function_name    = "ccd-verify-certificate"
  role             = aws_iam_role.verification.arn
  runtime          = "python3.12"
  handler          = "lambda_verify.lambda_handler"
  filename         = "${path.module}/../output/lambda/verification.zip"
  source_code_hash = filebase64sha256("${path.module}/../output/lambda/verification.zip")
  memory_size      = 128
  timeout          = 5

  environment {
    variables = {
      CERTIFICATE_TABLE   = aws_dynamodb_table.certificates.name
      ADMIN_ISSUER        = "https://cognito-idp.ap-south-1.amazonaws.com/${aws_cognito_user_pool.admin.id}"
      ADMIN_ORGANIZATIONS = jsonencode(var.admin_organizations)
      ADMIN_CLIENT_ID     = aws_cognito_user_pool_client.admin.id
      ADMIN_WEBSITE_ORIGIN = local.website_origin
    }
  }

  depends_on = [aws_iam_role_policy.verification, aws_cloudwatch_log_group.verification]
}

output "verification_function" {
  value = aws_lambda_function.verification.function_name
}
