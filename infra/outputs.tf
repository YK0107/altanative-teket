output "site_url" {
  value = local.site_url
}

output "site_bucket" {
  value = aws_s3_bucket.site.bucket
}

output "distribution_id" {
  value = aws_cloudfront_distribution.site.id
}

output "table_name" {
  value = aws_dynamodb_table.main.name
}

output "stripe_webhook_url" {
  value = "${local.site_url}/api/stripe/webhook"
}

output "ssm_prefix" {
  description = "ここに秘密情報を手動登録する（README 参照）"
  value       = local.ssm_prefix
}
