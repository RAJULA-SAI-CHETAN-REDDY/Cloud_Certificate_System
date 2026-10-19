locals {
  website_origin = "https://d6uwrv2kb0dl8.cloudfront.net"
}

resource "aws_s3_bucket" "frontend" {
  bucket = "ccd-frontend-${data.aws_caller_identity.current.account_id}-ap-south-1"
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "ccd-frontend-access"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_cache_policy" "frontend" {
  name        = "ccd-frontend-cache"
  min_ttl     = 0
  default_ttl = 60
  max_ttl     = 300

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "verify.html"
  comment             = "CCD public verification website"
  price_class         = "PriceClass_100"
  wait_for_deployment = true

  tags = {
    Name = "ccd-frontend"
  }

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "ccd-frontend-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  default_cache_behavior {
    target_origin_id       = "ccd-frontend-s3"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    viewer_protocol_policy = "redirect-to-https"
    compress               = true
    cache_policy_id        = aws_cloudfront_cache_policy.frontend.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  depends_on = [aws_s3_object.frontend_files, aws_s3_object.frontend_config]
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
      Condition = {
        StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn }
      }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.frontend]
}

# Publish only these public assets. No PDFs, metadata, or backend code are uploaded.
resource "aws_s3_object" "frontend_files" {
  for_each = {
    "index.html"            = "text/html; charset=utf-8"
    "verify.html"           = "text/html; charset=utf-8"
    "admin.html"            = "text/html; charset=utf-8"
    "css/verify.css"        = "text/css; charset=utf-8"
    "css/navigation.css"    = "text/css; charset=utf-8"
    "css/admin.css"         = "text/css; charset=utf-8"
    "js/verify.js"          = "text/javascript; charset=utf-8"
    "js/scan.js"            = "text/javascript; charset=utf-8"
    "js/pdf.worker.min.mjs" = "text/javascript; charset=utf-8"
    "js/admin-config.js"   = "text/javascript; charset=utf-8"
    "js/admin.js"          = "text/javascript; charset=utf-8"
  }
  bucket        = aws_s3_bucket.frontend.id
  key           = each.key
  source        = "${path.module}/../frontend/${each.key}"
  source_hash   = filemd5("${path.module}/../frontend/${each.key}")
  content_type  = each.value
  cache_control = "public, max-age=60"
  depends_on    = [aws_s3_bucket_server_side_encryption_configuration.frontend]
}

resource "aws_s3_object" "frontend_config" {
  bucket        = aws_s3_bucket.frontend.id
  key           = "js/config.js"
  content_type  = "text/javascript; charset=utf-8"
  cache_control = "public, max-age=60"
  content = "window.CERTIFICATE_CONFIG = Object.freeze(${jsonencode({
    verificationApiUrl = "${aws_api_gateway_stage.verification.invoke_url}/verify"
  })});"
  depends_on = [aws_s3_bucket_server_side_encryption_configuration.frontend]
}

output "website_url" {
  value = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "frontend_bucket" {
  value = aws_s3_bucket.frontend.bucket
}
