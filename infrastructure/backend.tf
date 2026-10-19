terraform {
  backend "s3" {
    bucket              = "ccd-terraform-state-707256068320-ap-south-1"
    key                 = "development/terraform.tfstate"
    region              = "ap-south-1"
    use_lockfile        = true
    allowed_account_ids = ["707256068320"]
  }
}
