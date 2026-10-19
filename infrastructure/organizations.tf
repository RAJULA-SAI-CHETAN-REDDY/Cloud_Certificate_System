# Cognito subjects are assigned by the account owner, not by a browser form.
# Multiple subjects may point at the same organization.
variable "admin_organizations" {
  type        = map(string)
  description = "Cognito administrator subject to organization ID (org-1, org-2, ...). Missing subjects have read-only access."
  default     = {}
  sensitive   = true
  validation {
    condition     = alltrue([for organization in values(var.admin_organizations) : can(regex("^org-[1-9][0-9]{0,3}$", organization))])
    error_message = "Organization IDs must be org-1 through org-9999."
  }
}
