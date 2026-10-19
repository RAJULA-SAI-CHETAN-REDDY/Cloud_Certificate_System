variable "notification_email_enabled" {
  description = "Enable the administrator's development email subscription."
  type        = bool
  default     = false
}

variable "notification_email" {
  description = "Administrator inbox; supply locally, never commit the address."
  type        = string
  sensitive   = true
  default     = ""
  validation {
    condition     = var.notification_email == "" || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.notification_email))
    error_message = "Provide a valid administrator email address."
  }
}

resource "aws_sns_topic" "certificate_events" {
  name = "ccd-certificate-events"
}

resource "aws_sns_topic_subscription" "administrator_email" {
  count     = var.notification_email_enabled ? 1 : 0
  topic_arn = aws_sns_topic.certificate_events.arn
  protocol  = "email"
  endpoint  = var.notification_email

  lifecycle {
    precondition {
      condition     = var.notification_email != ""
      error_message = "Set TF_VAR_notification_email before enabling the email subscription."
    }
  }
}
