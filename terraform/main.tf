# main.tf

# Configure the AWS Provider
provider "aws" {
  region = var.aws_region
}

# --- Data Sources ---
# Get the current AWS account ID
data "aws_caller_identity" "current" {}

# Get the current AWS region
data "aws_region" "current" {}

# --- IAM Role for Lambda Function ---
resource "aws_iam_role" "lambda_execution_role" {
  name = "${var.lambda_function_name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          Service = "lambda.amazonaws.com"
        },
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project = "PRReviewBot"
  }
}

# Attach AWS Managed Policy for Basic Lambda Execution (CloudWatch Logs)
resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Inline Policy for Bedrock Access
resource "aws_iam_role_policy" "bedrock_access" {
  name = "BedrockAccessPolicy"
  role = aws_iam_role.lambda_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "bedrock:InvokeModel",
          "bedrock:ListFoundationModels"
        ],
        Resource = "*"
      }
    ]
  })
}

# Inline Policy for Secrets Manager Access
resource "aws_iam_role_policy" "secrets_manager_access" {
  name = "SecretsManagerAccessPolicy"
  role = aws_iam_role.lambda_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "secretsmanager:GetSecretValue"
        ],
        # Narrows down resource to secrets matching the pattern
        Resource = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:${var.secrets_manager_secret_name}-*"
      }
    ]
  })
}

# Inline Policy for S3 Knowledge Base Access
resource "aws_iam_role_policy" "s3_knowledge_base_access" {
  name = "S3KnowledgeBaseAccessPolicy"
  role = aws_iam_role.lambda_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ],
        Resource = [
          "arn:aws:s3:::${var.example_project_s3_bucket}",
          "arn:aws:s3:::${var.example_project_s3_bucket}/*"
        ]
      }
    ]
  })
}


# --- Secrets Manager Secret ---
resource "aws_secretsmanager_secret" "github_app_secrets" {
  name        = var.secrets_manager_secret_name
  description = "Stores GitHub App credentials for the PR Review Bot."

  tags = {
    Project = "PRReviewBot"
  }
}

resource "aws_secretsmanager_secret_version" "github_app_secret_version" {
  secret_id = aws_secretsmanager_secret.github_app_secrets.id

  # The secret content as a JSON string
  secret_string = jsonencode({
    GITHUB_APP_ID       = var.github_app_id,
    GITHUB_PRIVATE_KEY  = var.github_private_key,
    GITHUB_WEBHOOK_SECRET = var.github_webhook_secret,
    BEDROCK_MODEL_ID    = var.bedrock_model_id # Optional: if you want to manage model ID as a secret
  })
}

# --- Lambda Function ---
resource "aws_lambda_function" "pr_review_bot_lambda" {
  function_name = var.lambda_function_name
  handler       = "lambda_function.lambda_handler"
  runtime       = var.lambda_runtime
  role          = aws_iam_role.lambda_execution_role.arn
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory
  description   = "GitHub PR Review Bot powered by AWS Bedrock and Secrets Manager (S3 KB enabled)."

  # The content of the Lambda function.
  # This assumes you have a 'pr_review_bot.zip' file in the same directory as your Terraform config.
  # You need to create this zip file manually or via a separate script (e.g., deploy_lambda.sh).
  filename = "pr_review_bot.zip"
  source_code_hash = filebase64sha256("pr_review_bot.zip")

  environment {
    variables = {
      LOG_LEVEL                 = var.log_level
      TRIGGER_TEAM_SLUG         = var.trigger_team_slug
      AWS_REGION                = data.aws_region.current.name
      SECRETS_MANAGER_SECRET_NAME = var.secrets_manager_secret_name
      EXAMPLE_PROJECT_S3_BUCKET = var.example_project_s3_bucket # New env var
      EXAMPLE_PROJECT_S3_PREFIX = var.example_project_s3_prefix # New env var
      # BEDROCK_MODEL_ID is primarily sourced from Secrets Manager, but can be set here as fallback
      # BEDROCK_MODEL_ID          = var.bedrock_model_id
    }
  }

  tags = {
    Project = "PRReviewBot"
  }
}

# --- API Gateway ---
resource "aws_apigateway_rest_api" "pr_review_bot_api" {
  name        = "${var.lambda_function_name}-api"
  description = "API Gateway for GitHub PR Review Bot Lambda."

  tags = {
    Project = "PRReviewBot"
  }
}

# Root resource (/)
resource "aws_apigateway_resource" "root_resource" {
  rest_api_id = aws_apigateway_rest_api.pr_review_bot_api.id
  parent_id   = aws_apigateway_rest_api.pr_review_bot_api.root_resource_id
  path_part   = "/"
}

# Webhook resource (/webhook)
resource "aws_apigateway_resource" "webhook_resource" {
  rest_api_id = aws_apigateway_rest_api.pr_review_bot_api.id
  parent_id   = aws_apigateway_rest_api.pr_review_bot_api.root_resource_id
  path_part   = "webhook"
}

# Webhook POST method
resource "aws_apigateway_method" "webhook_post_method" {
  rest_api_id   = aws_apigateway_rest_api.pr_review_bot_api.id
  resource_id   = aws_apigateway_resource.webhook_resource.id
  http_method   = "POST"
  authorization = "NONE"
}

# Webhook Lambda integration
resource "aws_apigateway_integration" "webhook_lambda_integration" {
  rest_api_id             = aws_apigateway_rest_api.pr_review_bot_api.id
  resource_id             = aws_apigateway_resource.webhook_resource.id
  http_method             = aws_apigateway_method.webhook_post_method.http_method
  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = aws_lambda_function.pr_review_bot_lambda.invoke_arn
}

# Health resource (/health)
resource "aws_apigateway_resource" "health_resource" {
  rest_api_id = aws_apigateway_rest_api.pr_review_bot_api.id
  parent_id   = aws_apigateway_rest_api.pr_review_bot_api.root_resource_id
  path_part   = "health"
}

# Health GET method
resource "aws_apigateway_method" "health_get_method" {
  rest_api_id   = aws_apigateway_rest_api.pr_review_bot_api.id
  resource_id   = aws_apigateway_resource.health_resource.id
  http_method   = "GET"
  authorization = "NONE"
}

# Health Lambda integration
resource "aws_apigateway_integration" "health_lambda_integration" {
  rest_api_id             = aws_apigateway_rest_api.pr_review_bot_api.id
  resource_id             = aws_apigateway_resource.health_resource.id
  http_method             = aws_apigateway_method.health_get_method.http_method
  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = aws_lambda_function.pr_review_bot_lambda.invoke_arn
}


# API Gateway Deployment
resource "aws_apigateway_deployment" "pr_review_bot_deployment" {
  rest_api_id = aws_apigateway_rest_api.pr_review_bot_api.id

  # Redeploy when methods or integrations change
  triggers = {
    redeployment = sha1(jsonencode([
      aws_apigateway_integration.webhook_lambda_integration.id,
      aws_apigateway_integration.health_lambda_integration.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

# API Gateway Stage
resource "aws_apigateway_stage" "prod_stage" {
  deployment_id = aws_apigateway_deployment.pr_review_bot_deployment.id
  rest_api_id   = aws_apigateway_rest_api.pr_review_bot_api.id
  stage_name    = "prod"

  variables = {
    lambda_function_name = aws_lambda_function.pr_review_bot_lambda.function_name
  }
}

# --- Lambda Permissions for API Gateway ---
resource "aws_lambda_permission" "apigateway_webhook_permission" {
  statement_id  = "AllowAPIGatewayInvokeWebhook"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pr_review_bot_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  # The /*/* allows invocation from any HTTP method on any resource path
  source_arn    = "${aws_apigateway_rest_api.pr_review_bot_api.execution_arn}/*/*"
}

