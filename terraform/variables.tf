# variables.tf

variable "aws_region" {
  description = "The AWS region to deploy resources in."
  type        = string
  default     = "us-east-1"
}

# --- Lambda Configuration ---
variable "lambda_function_name" {
  description = "Name for the Lambda function."
  type        = string
  default     = "pr-review-bot-lambda"
}

variable "lambda_runtime" {
  description = "Python runtime for the Lambda function."
  type        = string
  default     = "python3.9"
}

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds (max 900)."
  type        = number
  default     = 600
}

variable "lambda_memory" {
  description = "Lambda function memory in MB."
  type        = number
  default     = 512
}

variable "log_level" {
  description = "Logging level for the Lambda function (DEBUG, INFO, WARNING, ERROR)."
  type        = string
  default     = "INFO"
}

# --- GitHub App & Bot Configuration ---
variable "github_app_id" {
  description = "Your GitHub App ID."
  type        = string
  sensitive   = true # Mark as sensitive to prevent logging
}

variable "github_private_key" {
  description = "Your GitHub App Private Key (full content including BEGIN/END lines)."
  type        = string
  sensitive   = true # Mark as sensitive
}

variable "github_webhook_secret" {
  description = "Your GitHub App Webhook Secret."
  type        = string
  sensitive   = true # Mark as sensitive
}

variable "trigger_team_slug" {
  description = "The slug of the GitHub team that triggers reviews."
  type        = string
  default     = "ai-review-bots"
}

# --- Bedrock Configuration ---
variable "bedrock_model_id" {
  description = "The AWS Bedrock model ID to use for reviews. This can also be stored in Secrets Manager."
  type        = string
  default     = "anthropic.claude-3-sonnet-20240229-v1:0"
}

# --- Secrets Manager Configuration ---
variable "secrets_manager_secret_name" {
  description = "Name for the Secrets Manager secret storing GitHub credentials and optionally Bedrock IDs."
  type        = string
  default     = "github/pr-review-bot-secrets"
}

# --- Bedrock Knowledge Base Configuration ---
variable "bedrock_knowledge_base_id" {
  description = "The ID of the AWS Bedrock Knowledge Base to use for RAG. Can be empty if stored in Secrets Manager."
  type        = string
  default     = ""
}

