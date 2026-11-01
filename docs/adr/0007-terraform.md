# 0007 – Migration to Terraform and HCP Terraform

## Context
Our project originally provisioned cloud infrastructure across multiple CloudFormation stacks (`auth.yml`, `reports.yml`, `ai.yml`, `backend.yml`, `frontend.yml`). While CloudFormation provided basic deployment automation, managing cross-stack dependencies, drift detection, modularity, and fine-grained state management became increasingly complex as the architecture evolved (incorporating EventBridge, SQS, SES, VPC endpoints, and Bedrock AI Lambda functions).

For Lab 7, we require an Infrastructure as Code (IaC) tooling upgrade that provides:
1. Standardized declarative infrastructure configuration in HashiCorp Configuration Language (HCL).
2. Remote state management with locking and encryption.
3. Automated speculative planning on Pull Requests and controlled applies upon merging.
4. Clean separation of secret configuration from version-controlled codebase.

## Decision
We migrate our infrastructure definitions from AWS CloudFormation templates to **Terraform (>= 1.10)** using the **AWS provider (~> 6.0)**, managed through **HCP Terraform (HashiCorp Cloud Platform)** via the `cloud {}` backend block.

### Key Implementation Choices:
1. **Directory Structure (`infra/`)**:
   - `versions.tf`: Defines required versions (Terraform >= 1.10, AWS ~> 6.0, Random, TLS), HCP Terraform `cloud {}` block (`organization = "SuccessfulSuccess"`, `workspaces = "successfulsuccess-prod"`), and default resource tags (`PROJECT_NAME` and `ManagedBy = "terraform"`).
   - `variables.tf`: Explicit variable definitions with type constraints, defaults, and `sensitive = true` flags for secrets (e.g., `google_client_secret`, `database_url`).
   - `auth.tf`: Translates `auth.yml` (Cognito User Pool, User Pool Domain, Google Identity Provider, User Pool Client, Managed Login Branding) preserving exact physical names to facilitate zero-downtime resource imports.
   - `reports.tf`: Translates `reports.yml` (S3 bucket with distinct lifecycle and notification sub-resources, SQS queues and redrive policy, EventBridge Scheduler, SES Email Identities, and builder/mailer Lambdas with IAM roles).
   - `ai.tf`: Translates `ai.yml` (Agenda parser Lambda outside VPC, Lambda Function URL with CORS, IAM roles with Bedrock inference policies).
   - `outputs.tf`: Exports structured values for downstream services, Next.js build scripts, and local developer environment (`user_pool_id`, `hosted_domain`, `reports_bucket_name`, `report_requests_queue_url`, `ai_parser_function_url`).

2. **Secrets Handling**:
   - Secrets are explicitly marked with `sensitive = true`.
   - No `.tfvars` containing plaintext secrets are committed to Git.
   - Secrets and environment-specific credentials are injected via HCP Terraform workspace variables (marked sensitive) or environment variables.

3. **Remote Execution Workflow**:
   - Local developer machines only run `make infra-plan` or `terraform plan` for previewing changes.
   - Local or Makefile-based `terraform apply` is strictly prohibited.
   - All applies are executed remotely in HCP Terraform upon merging pull requests to the `main` branch.

## Alternatives Considered
1. **Retaining CloudFormation**:
   - *Pros*: Native AWS integration, no state management needed.
   - *Cons*: Limited cross-cloud tooling, verbose JSON/YAML templates, slow rollbacks on failed updates, and lack of built-in speculative planning workflows comparable to HCP Terraform.
2. **AWS CDK (Cloud Development Kit)**:
   - *Pros*: Programming language support (TypeScript/Python).
   - *Cons*: Higher build overhead, synthesis step creates CFn templates beneath the hood, less platform-agnostic than Terraform.
3. **Self-Managed S3 + DynamoDB Backend**:
   - *Pros*: No external SaaS dependencies.
   - *Cons*: Requires provisioning and managing S3 bucket policies, DynamoDB state lock tables, and manual CI/CD pipeline integration for plans/applies. HCP Terraform provides these natively out of the box.

## Consequences
- **Zero-Downtime Migration**: Existing CloudFormation resources can be mapped directly into Terraform state using `terraform import` without recreating active databases or user pools.
- **Workflow Change**: Developers no longer run ad-hoc deployment commands (`aws cloudformation deploy`); all infrastructure changes must follow the PR -> Speculative Plan -> Review -> Merge -> HCP Apply lifecycle.
- **Enhanced Observability**: Every resource automatically inherits the `ManagedBy = "terraform"` default tag, allowing unified resource tracking in AWS Resource Groups and Cost Explorer.

