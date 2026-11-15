data "aws_caller_identity" "current" {}

locals {
  has_domain = var.domain_name != ""
  zone_name  = var.route53_zone_name != "" ? var.route53_zone_name : var.domain_name
  site_host  = local.has_domain ? var.domain_name : aws_cloudfront_distribution.site.domain_name
  site_url   = "https://${local.site_host}"
  mail_from  = var.mail_from != "" ? var.mail_from : "tickets@${var.domain_name}"
  ssm_prefix = "/${var.project}"
  account_id = data.aws_caller_identity.current.account_id
}

check "mail_from_configured" {
  assert {
    condition     = local.has_domain || var.mail_from != ""
    error_message = "domain_name が空の場合は mail_from を指定してください。"
  }
}
