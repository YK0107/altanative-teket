# 独自ドメイン（domain_name が空なら何も作らない）

data "aws_route53_zone" "main" {
  count = local.has_domain ? 1 : 0
  name  = local.zone_name
}

resource "aws_acm_certificate" "site" {
  count             = local.has_domain ? 1 : 0
  provider          = aws.us_east_1
  domain_name       = var.domain_name
  validation_method = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "cert_validation" {
  for_each = local.has_domain ? {
    for o in aws_acm_certificate.site[0].domain_validation_options : o.domain_name => o
  } : {}
  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = each.value.resource_record_name
  type    = each.value.resource_record_type
  records = [each.value.resource_record_value]
  ttl     = 300
}

resource "aws_acm_certificate_validation" "site" {
  count                   = local.has_domain ? 1 : 0
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.site[0].arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

resource "aws_route53_record" "site" {
  for_each = local.has_domain ? toset(["A", "AAAA"]) : toset([])
  zone_id  = data.aws_route53_zone.main[0].zone_id
  name     = var.domain_name
  type     = each.key
  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}

# ---------- SES ----------
# サンドボックス解除の申請はコンソールから手動で行う

resource "aws_sesv2_email_identity" "main" {
  # ドメインがあればドメイン認証（DKIM）、なければ送信元アドレスを認証する
  email_identity = local.has_domain ? var.domain_name : local.mail_from
}

resource "aws_route53_record" "dkim" {
  count   = local.has_domain ? 3 : 0
  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = "${aws_sesv2_email_identity.main.dkim_signing_attributes[0].tokens[count.index]}._domainkey.${var.domain_name}"
  type    = "CNAME"
  ttl     = 600
  records = ["${aws_sesv2_email_identity.main.dkim_signing_attributes[0].tokens[count.index]}.dkim.amazonses.com"]
}

# SPF を揃えるための MAIL FROM サブドメイン
resource "aws_sesv2_email_identity_mail_from_attributes" "main" {
  count                  = local.has_domain ? 1 : 0
  email_identity         = aws_sesv2_email_identity.main.email_identity
  mail_from_domain       = "bounce.${var.domain_name}"
  behavior_on_mx_failure = "USE_DEFAULT_VALUE"
}

resource "aws_route53_record" "mail_from_mx" {
  count   = local.has_domain ? 1 : 0
  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = "bounce.${var.domain_name}"
  type    = "MX"
  ttl     = 600
  records = ["10 feedback-smtp.${var.region}.amazonses.com"]
}

resource "aws_route53_record" "mail_from_spf" {
  count   = local.has_domain ? 1 : 0
  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = "bounce.${var.domain_name}"
  type    = "TXT"
  ttl     = 600
  records = ["v=spf1 include:amazonses.com ~all"]
}

resource "aws_route53_record" "dmarc" {
  count   = local.has_domain ? 1 : 0
  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = "_dmarc.${var.domain_name}"
  type    = "TXT"
  ttl     = 600
  records = ["v=DMARC1; p=none;"]
}
