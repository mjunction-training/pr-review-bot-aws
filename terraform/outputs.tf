# outputs.tf

output "webhook_url" {
  description = "URL for the GitHub Webhook endpoint"
  value       = "${aws_apigateway_deployment.pr_review_bot_deployment.invoke_url}/prod/webhook"
}

output "health_check_url" {
  description = "URL for the Health Check endpoint"
  value       = "${aws_apigateway_deployment.pr_review_bot_deployment.invoke_url}/prod/health"
}

output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = aws_lambda_function.pr_review_bot_lambda.function_name
}

output "lambda_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda_execution_role.arn
}

output "secrets_manager_secret_arn" {
  description = "ARN of the Secrets Manager secret"
  value       = aws_secretsmanager_secret.github_app_secrets.arn
}
