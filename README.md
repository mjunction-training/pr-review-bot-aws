# **GitHub PR Review Bot with AWS Lambda and Bedrock**

This project implements a GitHub Pull Request (PR) review bot that leverages AWS Lambda to handle webhooks and AWS Bedrock (specifically the Claude Sonnet model) to generate automated code reviews.

## **Features**

* **Automated PR Reviews**: Automatically reviews pull requests when they are opened, reopened, synchronized, or a review is requested for a specific team.  
* **Bedrock Integration**: Utilizes AWS Bedrock's Claude Sonnet model for comprehensive code analysis and review generation.  
* **Detailed & Structured Output**: Provides a comprehensive review including:  
  * Overall PR summary.  
  * Line-specific comments (for precise feedback).  
  * General PR comments (for broader architectural or process feedback).  
  * Categorized security vulnerabilities (SEVERE, MODERATE, LOW).  
* **Secure Secret Management**: Retrieves sensitive credentials (GitHub App private key, webhook secret) from AWS Secrets Manager, enhancing security.  
* **S3 Knowledge Base**: Can leverage example projects stored in an S3 bucket as a knowledge base to provide more informed and context-aware reviews.  
* **Configurable**: Easy to configure GitHub App details, webhook secrets, the target team for reviews, and S3 knowledge base settings via environment variables and Secrets Manager.  
* **Serverless Deployment**: Deploys as an AWS Lambda function, triggered by AWS API Gateway, offering scalability and cost-effectiveness.  
* **Multiple Deployment Options**: Supports deployment via shell scripts, AWS CloudFormation, and Terraform.

## **Architecture**

1. **GitHub Webhook**: When a relevant PR event occurs (opened, reopened, synchronize, review requested), GitHub sends a webhook payload to an AWS API Gateway endpoint.  
2. **API Gateway**: Receives the webhook, validates the signature, and acts as a proxy to trigger the AWS Lambda function.  
3. **AWS Lambda**:  
   * The lambda\_function.py serves as the entry point.  
   * It initializes SecretUtils to securely retrieve credentials from AWS Secrets Manager.  
   * It initializes S3Utils to read example projects from an S3 bucket, forming a knowledge base.  
   * It then initializes GitHubUtils (using secrets from SecretUtils) to interact with the GitHub API (fetching diffs, posting comments) and MCPClient (which now directly interfaces with AWS Bedrock).  
   * It processes the GitHub webhook payload.  
   * If the PR is relevant and a review is requested for the configured team, it fetches the PR diff.  
   * **Multi-Step LLM Interaction**: The MCPClient performs a series of calls to AWS Bedrock:  
     1. **Initial Analysis**: An initial prompt asks the LLM to identify potential areas for line comments, general comments, and security issues based on the diff and comprehensive guidelines. This prompt *includes the S3 knowledge base* for enhanced context.  
     2. **Detailed Line Comments**: A separate prompt is sent to generate detailed, actionable comments for identified specific lines of code.  
     3. **Detailed General Comments**: Another prompt generates broader comments relevant to the entire PR.  
     4. **Detailed Security Issues**: A dedicated prompt focuses on identified security vulnerabilities, assigning a severity (SEVERE, MODERATE, LOW).  
     5. **Summary Generation**: Finally, all generated comments and issues are combined, and a summary prompt creates a concise overview.  
   * Finally, it uses GitHubUtils to post the review summary, comments, and security issues back to the GitHub PR.  
4. **AWS Bedrock**: Provides the large language model capabilities (Claude Sonnet) for generating the code review and summary.  
5. **AWS Secrets Manager**: Securely stores sensitive credentials like the GitHub App private key and webhook secret.  
6. **AWS S3**: Stores example projects which can be used as a knowledge base for the LLM.  
7. **AWS IAM**: Manages permissions for the Lambda function to interact with Bedrock, Secrets Manager, S3, and CloudWatch Logs.

## **Prerequisites**

Before deploying, ensure you have:

* **AWS Account**: An active AWS account.  
* **AWS CLI**: Configured with credentials that have sufficient permissions to create/manage IAM roles, Lambda functions, API Gateway, and Secrets Manager.  
* **Python 3.9+**: Installed locally for packaging dependencies.  
* **pip**: Python package installer.  
* **zip**: Command-line utility for creating zip archives.  
* **Terraform (if using Terraform deployment)**: Install Terraform from [https://www.terraform.io/downloads.html](https://www.terraform.io/downloads.html).  
* **GitHub App**:  
  * Create a new GitHub App in your organization/account settings.  
  * **Permissions**:  
    * Pull requests: Read & Write  
    * Contents: Read  
    * Metadata: Read  
  * **Webhook**: Enable webhooks and set the webhook secret.  
  * **Subscribe to events**: Pull requests.  
  * Generate a **private key** and download it (.pem file).  
  * Note down your **App ID**.  
* **S3 Bucket for Knowledge Base**: An S3 bucket where you will store your example projects. Ensure the project files are organized under a specific prefix (e.g., my-example-projects/project-a/).

## **Project Structure**

* app.py: (Original Flask app, now mostly superseded by lambda\_function.py for Lambda deployment, but contains core logic for webhook handling that lambda\_function.py adapts).  
* github\_utils.py: Handles GitHub API interactions, including webhook validation, fetching diffs, and posting comments.  
* mcp\_client.py: **(Modified)** Now directly integrates with AWS Bedrock to invoke LLMs for review generation and summarization, using a multi-step prompting approach and optionally leveraging an S3 knowledge base.  
* lambda\_function.py: **(New)** The AWS Lambda handler, adapting the webhook logic for the Lambda environment.  
* guidelines.md: **(Updated)** Contains comprehensive code review guidelines.  
* requirements.txt: Lists Python dependencies.  
* secret\_utils.py: **(New)** Utility for securely retrieving secrets from AWS Secrets Manager.  
* s3\_utils.py: **(New)** Utility for reading files from an S3 bucket to form a knowledge base.  
* deploy\_lambda.sh: Script to package and deploy the Lambda function (shell-script based deployment).  
* create\_api\_gateway.sh: Script to set up the API Gateway endpoint (shell-script based deployment).  
* create\_iam\_role.sh: Script to create the necessary IAM role for the Lambda function (shell-script based deployment).  
* cloudformation.yaml: AWS CloudFormation template for deploying the entire stack.  
* terraform/: Contains Terraform configuration files.  
  * terraform/main.tf: Main Terraform configuration.  
  * terraform/variables.tf: Terraform input variables.  
  * terraform/outputs.tf: Terraform output values.  
* README.md: This file.

## **Deployment Options**

You have three main options for deploying the PR Review Bot:

### **Option 1: Shell Scripts (Manual Steps)**

This option uses individual shell scripts to perform each deployment step.

#### **1\. Prepare Your Project Files**

Ensure all your project files are in the same directory.

#### **2\. Create and Store Secrets in AWS Secrets Manager**

You need to create a secret in AWS Secrets Manager that will store your GitHub App credentials.

1. Prepare your secret content:  
   Create a JSON string containing your GitHub App ID, private key, and webhook secret.  
   Important: The GITHUB\_PRIVATE\_KEY should include actual newline characters (\\n), not escaped \\\\n.  
   {  
     "GITHUB\_APP\_ID": "YOUR\_GITHUB\_APP\_ID",  
     "GITHUB\_PRIVATE\_KEY": "-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n",  
     "GITHUB\_WEBHOOK\_SECRET": "your\_webhook\_secret\_string",  
     "BEDROCK\_MODEL\_ID": "anthropic.claude-3-sonnet-20240229-v1:0" \# Optional  
   }

   * Replace YOUR\_GITHUB\_APP\_ID with your GitHub App's ID.  
   * Replace \-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n with the *actual content* of your .pem private key file, ensuring newlines are preserved.  
   * Replace your\_webhook\_secret\_string with your GitHub webhook secret.  
   * BEDROCK\_MODEL\_ID is optional here; if provided, mcp\_client.py will use it from Secrets Manager. Otherwise, it falls back to the environment variable.  
2. **Store the secret using AWS CLI**:  
   aws secretsmanager create-secret \\  
       \--name github/pr-review-bot-secrets \\  
       \--description "GitHub App credentials for PR Review Bot" \\  
       \--secret-string '{"GITHUB\_APP\_ID":"YOUR\_GITHUB\_APP\_ID","GITHUB\_PRIVATE\_KEY":"-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n","GITHUB\_WEBHOOK\_SECRET":"your\_webhook\_secret\_string","BEDROCK\_MODEL\_ID":"anthropic.claude-3-sonnet-20240229-v1:0"}' \\  
       \--region YOUR\_AWS\_REGION

   * **IMPORTANT**: Replace YOUR\_GITHUB\_APP\_ID, the private key content, your\_webhook\_secret\_string, and YOUR\_AWS\_REGION with your actual values.  
   * The \--name (github/pr-review-bot-secrets) is the value you will use for SECRETS\_MANAGER\_SECRET\_NAME in your environment variables.

#### **3\. Set Up Environment Variables**

Create a .env file in your project root (or set these directly in your shell/CI/CD environment) with the following:

\# .env example  
SECRETS\_MANAGER\_SECRET\_NAME="github/pr-review-bot-secrets" \# The name of the secret created in AWS Secrets Manager  
TRIGGER\_TEAM\_SLUG="ai-review-bots" \# The slug of the GitHub team that triggers reviews (e.g., 'ai-review-bots')  
AWS\_REGION="us-east-1" \# Your desired AWS region for Lambda and Bedrock (must match region of your secret)  
BEDROCK\_MODEL\_ID="anthropic.claude-3-sonnet-20240229-v1:0" \# Optional: Only needed if not stored in Secrets Manager  
EXAMPLE\_PROJECT\_S3\_BUCKET="your-example-projects-s3-bucket" \# S3 bucket for knowledge base  
EXAMPLE\_PROJECT\_S3\_PREFIX="example-project-1/" \# S3 prefix (folder) for the specific example project  
LOG\_LEVEL="INFO" \# Logging level: DEBUG, INFO, WARNING, ERROR

#### **4\. Create IAM Role for Lambda**

This step creates an IAM role that your Lambda function will assume. This role grants the necessary permissions to execute, write logs to CloudWatch, invoke Bedrock models, and **retrieve** secrets from Secrets Manager and read from **S3**.

1. **Make the script executable**:  
   chmod \+x create\_iam\_role.sh

2. **Run the script**:  
   ./create\_iam\_role.sh

3. **Output**: The script will output the ARN of the newly created role (e.g., arn:aws:iam::YOUR\_AWS\_ACCOUNT\_ID:role/pr-review-bot-lambda-role). **Copy this ARN**, as you will need it in the next step.

#### **5\. Deploy Lambda Function**

This step packages your Python code and its dependencies into a ZIP file and deploys it as an AWS Lambda function.

1. **Update deploy\_lambda.sh**:  
   * Open deploy\_lambda.sh in a text editor.  
   * **Replace LAMBDA\_ROLE\_ARN**: Paste the IAM Role ARN you copied from the previous step.  
   * **Replace SECRETS\_MANAGER\_SECRET\_NAME**: Ensure this matches the name you used when creating the secret in AWS Secrets Manager.  
   * **Replace S3 Knowledge Base Variables**: Update EXAMPLE\_PROJECT\_S3\_BUCKET and EXAMPLE\_PROJECT\_S3\_PREFIX with your actual values.  
   * **Verify Region**: Ensure AWS\_REGION matches your desired region.  
   * **Note**: GITHUB\_APP\_ID, GITHUB\_PRIVATE\_KEY, and GITHUB\_WEBHOOK\_SECRET are now read from Secrets Manager, so they are removed from the explicit environment variable list in this script.  
2. **Make the script executable**:  
   chmod \+x deploy\_lambda.sh

3. **Run the script**:  
   ./deploy\_lambda.sh

4. **Output**: The script will confirm the creation or update of your Lambda function.

#### **6\. Create API Gateway Endpoint**

This step sets up an AWS API Gateway REST API that will serve as the public endpoint for your GitHub webhook and health checks.

1. **Update create\_api\_gateway.sh**:  
   * Open create\_api\_gateway.sh in a text editor.  
   * **Verify Lambda Function Name and Region**: Ensure LAMBDA\_FUNCTION\_NAME and AWS\_REGION match the values used when deploying your Lambda function.  
2. **Make the script executable**:  
   chmod \+x create\_api\_gateway.sh

3. **Run the script**:  
   ./create\_api\_gateway.sh

4. **Output**: The script will output your API Gateway **Webhook URL** (e.g., https://\<api-id\>.execute-api.\<region\>.amazonaws.com/\<stage\>/webhook) and **Health Check URL**. **Copy the Webhook URL**, as you will need it for configuring GitHub.

#### **7\. Configure GitHub Webhook**

This final step tells GitHub where to send the PR events.

1. **Go to your GitHub repository settings**: In your web browser, navigate to the GitHub repository where you want the bot to operate.  
2. **Access Webhooks**: Click on "Settings" \-\> "Webhooks" in the left sidebar.  
3. **Add Webhook**: Click the "Add webhook" button.  
4. **Fill in details**:  
   * **Payload URL**: Paste the **Webhook URL** you copied from the output of create\_api\_gateway.sh.  
   * **Content type**: Select application/json.  
   * **Secret**: Paste your GITHUB\_WEBHOOK\_SECRET (the same value you stored in Secrets Manager).  
   * **Which events would you like to trigger this webhook?**: Select "Let me select individual events" and ensure only Pull requests is checked.  
   * **Active**: Ensure the "Active" checkbox is ticked.  
5. Click "Add webhook".

### **Option 2: AWS CloudFormation**

This option uses a single CloudFormation template to define and deploy all necessary AWS resources.

#### **1\. Prepare Your Project Files**

Ensure all your project files are in the same directory.

#### **2\. Create a Deployment Package**

You need to package your Lambda code and its dependencies into a ZIP file.

\# Create a 'package' directory  
mkdir \-p package

\# Install Python dependencies into the 'package' directory  
pip install \-r requirements.txt \--target package/

\# Copy your application files into the 'package' directory  
cp lambda\_function.py package/  
cp github\_utils.py package/  
cp mcp\_client.py package/  
cp guidelines.md package/  
cp secret\_utils.py package/  
cp s3\_utils.py package/ \# Copy the new s3\_utils.py

\# Create the final deployment ZIP file  
(cd package && zip \-r ../pr\_review\_bot.zip .)

\# Clean up the temporary package directory  
rm \-rf package/

#### **3\. Deploy the CloudFormation Stack**

1. Upload the Lambda package to S3 and transform the template:  
   CloudFormation needs your Lambda code to be in an S3 bucket. The aws cloudformation package command handles this.  
   * **Create an S3 bucket** if you don't have one for deployment artifacts (e.g., your-unique-cf-bucket-12345).

   aws cloudformation package \\  
         \--template-file cloudformation.yaml \\  
         \--s3-bucket YOUR\_S3\_BUCKET\_FOR\_ARTIFACTS \\  
         \--output-template-file packaged-cloudformation.yaml \\  
         \--region YOUR\_AWS\_REGION

   * Replace YOUR\_S3\_BUCKET\_FOR\_ARTIFACTS with your S3 bucket name and YOUR\_AWS\_REGION with your desired AWS region.  
2. Deploy the CloudFormation stack:  
   Now, deploy the transformed template. You will pass the sensitive parameters directly here or use a parameter file.  
   aws cloudformation deploy \\  
       \--template-file packaged-cloudformation.yaml \\  
       \--stack-name pr-review-bot-stack \\  
       \--capabilities CAPABILITY\_IAM \\  
       \--parameter-overrides \\  
           GitHubAppId="YOUR\_GITHUB\_APP\_ID" \\  
           GitHubPrivateKey="-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n" \\  
           GitHubWebhookSecret="YOUR\_GITHUB\_WEBHOOK\_SECRET" \\  
           SecretsManagerSecretName="github/pr-review-bot-secrets" \\  
           BedrockModelId="anthropic.claude-3-sonnet-20240229-v1:0" \\  
           TriggerTeamSlug="ai-review-bots" \\  
           LogLevel="INFO" \\  
           ExampleProjectS3Bucket="your-example-projects-s3-bucket" \\  
           ExampleProjectS3Prefix="example-project-1/" \\  
       \--region YOUR\_AWS\_REGION

   * **IMPORTANT**: Replace all YOUR\_... placeholders with your actual values. Ensure GitHubPrivateKey has actual newlines.  
   * The SecretsManagerSecretName here should match the name you intend for your secret. The CloudFormation template will create this secret for you.  
3. Retrieve Outputs:  
   After successful deployment, retrieve the Webhook URL from the stack outputs:  
   aws cloudformation describe-stacks \\  
       \--stack-name pr-review-bot-stack \\  
       \--query 'Stacks\[0\].Outputs\[?OutputKey==\`WebhookUrl\`\].OutputValue' \\  
       \--output text \\  
       \--region YOUR\_AWS\_REGION

   You can also find this in the AWS CloudFormation console under the "Outputs" tab of your stack.

#### **4\. Configure GitHub Webhook**

Follow **Step 7** from the "Shell Scripts (Manual Steps)" section, using the Webhook URL obtained from CloudFormation outputs and your GITHUB\_WEBHOOK\_SECRET.

### **Option 3: Terraform**

This option uses Terraform to define and provision all necessary AWS infrastructure.

#### **1\. Prepare Your Project Files**

1. Ensure all your project files are in the main directory.  
2. Create a new directory named terraform in your project root.  
3. Move main.tf, variables.tf, and outputs.tf into the terraform directory.

#### **2\. Create a Deployment Package**

You need to package your Lambda code and its dependencies into a ZIP file. This ZIP file will be referenced by Terraform.

\# From your project root (one level above 'terraform' directory)  
\# Create a 'package' directory  
mkdir \-p package

\# Install Python dependencies into the 'package' directory  
pip install \-r requirements.txt \--target package/

\# Copy your application files into the 'package' directory  
cp lambda\_function.py package/  
cp github\_utils.py package/  
cp mcp\_client.py package/  
cp guidelines.md package/  
cp secret\_utils.py package/  
cp s3\_utils.py package/ \# Copy the new s3\_utils.py

\# Create the final deployment ZIP file in the 'terraform' directory  
(cd package && zip \-r ../terraform/pr\_review\_bot.zip .)

\# Clean up the temporary package directory  
rm \-rf package/

#### **3\. Initialize and Apply Terraform**

1. **Navigate to the terraform directory**:  
   cd terraform

2. **Initialize Terraform**:  
   terraform init

3. Create a terraform.tfvars file (recommended for sensitive variables):  
   Create a file named terraform.tfvars in the terraform directory and add your sensitive variables:  
   \# terraform.tfvars  
   aws\_region \= "us-east-1" \# Or your desired region  
   github\_app\_id \= "YOUR\_GITHUB\_APP\_ID"  
   github\_private\_key \= "-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n"  
   github\_webhook\_secret \= "YOUR\_GITHUB\_WEBHOOK\_SECRET"  
   example\_project\_s3\_bucket \= "your-example-projects-s3-bucket"  
   example\_project\_s3\_prefix \= "example-project-1/"  
   \# Other variables can be set here or left to their defaults in variables.tf  
   \# bedrock\_model\_id \= "anthropic.claude-3-sonnet-20240229-v1:0"

   * **IMPORTANT**: Replace YOUR\_... placeholders with your actual values. Ensure github\_private\_key has actual newlines.  
4. **Review the plan**:  
   terraform plan

   Review the proposed changes to ensure they match your expectations.  
5. **Apply the changes**:  
   terraform apply

   Type yes when prompted to confirm the deployment.

#### **4\. Retrieve Outputs**

After successful deployment, Terraform will output the webhook\_url and health\_check\_url.

terraform output webhook\_url  
terraform output health\_check\_url

#### **5\. Configure GitHub Webhook**

Follow **Step 7** from the "Shell Scripts (Manual Steps)" section, using the Webhook URL obtained from Terraform outputs and your GITHUB\_WEBHOOK\_SECRET.

### **Common Testing Steps (After any deployment option)**

1. **Create a new pull request**: In your GitHub repository, create a new pull request.  
2. **Request Review (Optional but Recommended)**: To ensure the bot is triggered, ensure the pull request has a review requested for the team specified in your TRIGGER\_TEAM\_SLUG environment variable (e.g., ai-review-bots).  
3. **Check Webhook Deliveries**: Go back to your GitHub webhook settings for the repository. In the "Recent Deliveries" section, you should see new deliveries with an HTTP 200 status code, indicating successful invocation of your Lambda function.  
4. **Monitor CloudWatch Logs**: Open the AWS CloudWatch console, navigate to "Log groups", and find the log group for your Lambda function (e.g., /aws/lambda/pr-review-bot-lambda). Monitor the logs for execution details, any errors, or messages indicating the review process.  
5. **Observe PR Comments**: Check the comments section of your pull request on GitHub. You should see the automated review summary, general comments, and security issues posted by the bot.

## **Troubleshooting**

* **Lambda Timeout**: If your reviews are large, the Lambda function might time out. Increase the TIMEOUT variable in deploy\_lambda.sh or LambdaTimeout parameter in CloudFormation/Terraform.  
* **Lambda Memory**: If the function runs out of memory, increase the MEMORY variable in deploy\_lambda.sh or LambdaMemory parameter in CloudFormation/Terraform.  
* **Permissions Errors**: Check your Lambda execution role'