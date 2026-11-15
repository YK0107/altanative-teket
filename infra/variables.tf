variable "project" {
  description = "リソース名の接頭辞。SSM のパスにも使う（/<project>/...）"
  type        = string
  default     = "teket-alt"
}

variable "region" {
  type    = string
  default = "ap-northeast-1"
}

variable "event_id" {
  description = "公演ID（DynamoDB 上のキー）。次回公演で切り替える"
  type        = string
  default     = "evt_2027"
}

variable "domain_name" {
  description = "サイトのドメイン（例: tickets.example.jp）。空なら CloudFront の既定ドメインで動かす"
  type        = string
  default     = ""
}

variable "route53_zone_name" {
  description = "domain_name を置く Route 53 ホストゾーン名。空なら domain_name と同じ"
  type        = string
  default     = ""
}

variable "mail_from" {
  description = "送信元アドレス。空なら tickets@<domain_name>。ドメインなしの場合は必須（SES でメールアドレス認証する）"
  type        = string
  default     = ""
}

variable "alarm_email" {
  description = "エラー通知先（空なら通知しない）"
  type        = string
  default     = ""
}

variable "lambda_zip" {
  description = "backend/build_lambda.sh が作る zip のパス"
  type        = string
  default     = "../backend/dist/lambda.zip"
}

variable "api_throttle" {
  description = "API Gateway のスロットリング（簡易 DoS 対策）"
  type = object({
    rate  = number
    burst = number
  })
  default = { rate = 200, burst = 400 }
}
