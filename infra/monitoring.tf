resource "aws_sns_topic" "alarm" {
  name = "${var.project}-alarm"
}

resource "aws_sns_topic_subscription" "alarm_email" {
  count     = var.alarm_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alarm.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# アプリが出した ERROR ログ（決済後の解放競合 PAID_AFTER_RELEASE、メール送信失敗など）
resource "aws_cloudwatch_log_metric_filter" "app_error" {
  name           = "${var.project}-app-error"
  log_group_name = aws_cloudwatch_log_group.api.name
  pattern        = "\"[ERROR]\""
  metric_transformation {
    name          = "AppErrors"
    namespace     = var.project
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "app_error" {
  alarm_name          = "${var.project}-app-error"
  namespace           = var.project
  metric_name         = "AppErrors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarm.arn]
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.project}-lambda-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.api.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarm.arn]
}
