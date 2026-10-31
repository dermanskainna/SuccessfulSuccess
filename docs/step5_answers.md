# Lab 5: Event-Driven Weekly Meetings Report Pipeline

## 1. Architecture Summary & Design Decisions

### Event-Driven Pipeline Workflow
1. **Trigger / Scheduling:** An Amazon EventBridge Scheduler (or manual SQS dispatch) sends a JSON event `{"week": "2026-W40", "source": "manual"}` to an AWS SQS queue.
2. **Builder Lambda (`successfulsuccess-report-builder`):** Triggered by SQS messages. Resides inside the custom VPC, connects asynchronously to the Amazon Aurora PostgreSQL database (`successfulsuccess-db`), executes optimized SQL queries to compile meeting statistics and the Top 5 longest meetings, and formats the result into a UTF-8 CSV with BOM.
3. **S3 Storage:** The Builder Lambda uploads the generated CSV directly to the Amazon S3 bucket (`successfulsuccess-reports-283609055480`) under the key path `reports/2026-W40.csv`.
4. **S3 Event Notification:** S3 emits an `s3:ObjectCreated:*` event notification that invokes the Mailer Lambda.
5. **Mailer Lambda (`successfulsuccess-report-mailer`):** Resides outside the VPC (or uses internet routing), downloads the CSV from S3, builds a MIME email message with the file attached, and dispatches it via Amazon SES to the recipient.

### Two-Lambda Architecture Justification
A dedicated two-Lambda design was chosen to resolve the VPC Internet Access Constraint:
- **Builder Lambda in VPC:** Must reside within the private subnets of the VPC to securely access the private Amazon Aurora PostgreSQL cluster without exposing the database to the public internet.
- **Mailer Lambda outside VPC:** Amazon SES API endpoints require public internet access. Placing the Mailer Lambda outside the VPC allows it to directly communicate with Amazon SES endpoints without needing a costly NAT Gateway or complex VPC endpoints for SES.

Connecting the two Lambdas via S3 Event Notifications decouples report generation from delivery while overcoming networking boundaries cleanly and cost-effectively.

## 2. Infrastructure & Troubleshooting Notes

### PostgreSQL Date Handling
Fixed SQL query failures in `backend/app/reports/weekly.py` by converting ISO week string parameters into typed Python `datetime.date` objects prior to passing them into SQLAlchemy queries. This resolved the PostgreSQL operator casting error (`operator does not exist: date >= character varying`).

### CloudFormation SES Resource Conflict Fix
Resolved the `AWS::EarlyValidation::ResourceExistenceCheck` error during CloudFormation deployment of `infra/reports.yml`. When `ReportSenderEmail` and `ReportRecipientEmail` used the same email address (`dermanskainna@gmail.com`), CloudFormation attempted to create two duplicate `AWS::SES::EmailIdentity` resources with identical physical IDs. Added the `DistinctRecipient` condition in `infra/reports.yml` to prevent duplicate identity creation when sender and recipient addresses match.

**Deployed CloudFormation Stack:** `successfulsuccess-reports`  
**Primary Region:** `us-east-1`

## 3. Deployment Artifacts & Execution Proofs
- **S3 Report Location:** `s3://successfulsuccess-reports-283609055480/reports/2026-W40.csv`
- **Sender & Recipient Email:** `dermanskainna@gmail.com`

### CloudWatch Logs — Builder Lambda (`successfulsuccess-report-builder`)
```text
[INFO] Processing report generation for week 2026-W40
[INFO] Connected to Aurora PostgreSQL cluster (successfulsuccess-db.cluster-cqbegekm6jh4.us-east-1.rds.amazonaws.com)
[INFO] Successfully generated 2026-W40.csv and uploaded to s3://successfulsuccess-reports-283609055480/reports/2026-W40.csv
```

### CloudWatch Logs — Mailer Lambda (`successfulsuccess-report-mailer`)
```text
[INFO] mailer triggered by S3 event: s3://successfulsuccess-reports-283609055480/reports/2026-W40.csv
[INFO] Downloaded report attachment (2026-W40.csv), preparing MIME email
[INFO] email sent successfully via Amazon SES to dermanskainna@gmail.com
REPORT RequestId: cfa2a709-9e3b-424d-aaaa-7ed7534331f7 Duration: 863.38 ms Billed Duration: 864 ms
```

## 4. Part 3 Step 7 Reflection Answers

1. **How does decoupling report generation (Builder) from delivery (Mailer) via S3 events improve reliability?**  
   Decoupling via S3 events isolates failures and prevents cascading errors. If email dispatch fails (e.g., SES rate limits or temporary network issues), the report remains safely generated and persisted in S3. The delivery can be independently retried without re-running expensive database queries on Aurora.

2. **Why is S3 Event Notification preferred over direct Lambda-to-Lambda invocation?**  
   S3 Event Notifications provide an asynchronous, event-driven pattern with built-in durability. Using S3 as the intermediary ensures that file creation acts as the single source of truth, avoids tight coupling and timeout propagation between Lambdas, and automatically provides audit logs of all generated artifacts.

3. **How does using EventBridge Scheduler compare to traditional cron jobs on an EC2 instance?**  
   EventBridge Scheduler is a fully managed, serverless scheduling service. Unlike cron jobs running on an EC2 instance, EventBridge Scheduler requires zero server maintenance, scales automatically, incurs no cost when idle, and provides built-in retry policies and Dead-Letter Queues (DLQ) for failed executions.
