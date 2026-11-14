# 0002 – Розгортання ядра SuccessfulSuccess у Google Cloud Platform (Multi-Cloud / GCP Migration)

## Статус
Прийнято

## Контекст
У попередніх лабораторних роботах (Lab 1–7) інфраструктура проєкту `SuccessfulSuccess` розгорталася в Amazon Web Services (AWS) за допомогою AWS CloudFormation та Terraform (HCP Terraform). Стек включав AWS Lambda (FastAPI бекенд через Mangum, AI agenda parser, щотижневі звіти), Amazon Aurora Serverless v2 PostgreSQL, Amazon Cognito, Amazon S3, SQS, SES та Bedrock.

Для реалізації стратегії Multi-Cloud та забезпечення відмовостійкості / запобігання vendor lock-in ми розгортаємо паралельне ядро додатку (HTTP API бекенд та реляційну базу даних) у **Google Cloud Platform (GCP)**, зберігаючи при цьому стабільний робочий стан існуючого AWS-середовища.

## Рішення

1. **Ізоляція інфраструктурного коду**:
   - Створено окрему ізольовану директорію `gcp/`, що містить власний Terraform-стек із провайдером `hashicorp/google (~> 6.0)`.
   - Керування станом здійснюється через окремий воркспейс у HCP Terraform: `organization = "SuccessfulSuccess"`, `workspaces = "successfulsuccess-gcp"`.
   - Існуючий стек AWS у папці `infra/` та кодова база проєкту залишаються незмінними.

2. **Матриця вибору сервісів GCP замість AWS**:

| Компонент системи | Поточний сервіс в AWS | Обраний сервіс у GCP | Обґрунтування вибору |
| :--- | :--- | :--- | :--- |
| **Backend Compute (API)** | AWS Lambda (Image + Mangum) | **Cloud Run v2** | Повноцінний бессерверний запуск контейнерів за стандартом OCI з автоматичним масштабуванням до 0 (`min_instance_count = 0`), нативною підтримкою HTTP/HTTPS без трансляторів подій (Mangum) та швидким холодним стартом. |
| **База даних (RDBMS)** | Amazon Aurora PostgreSQL v2 | **Cloud SQL for PostgreSQL 16** (`db-f1-micro`) | Повна сумісність із поточними моделями SQLAlchemy та драйвером `asyncpg`. Безпечне локальне підключення через сокет `/cloudsql/<connection_name>` без виставлення публічних портів. |
| **Реєстр Docker-образів** | Amazon ECR | **Artifact Registry** (`DOCKER`) | Сучасний стандартизований регіональний реєстр артефактів GCP із гранулярним контролем доступу через IAM. |
| **Управління секретами** | AWS Secrets Manager / SSM | **Secret Manager** | Безпечне зберігання `DATABASE_URL` з автоматичним монтуванням та інжекцією змінної в Cloud Run без хардкоду в HCL/Git. |
| **Identity & IAM** | AWS IAM Roles & Policies | **Google Cloud Service Account + IAM** | Принцип найменших привілеїв: виділений Service Account для бекенду з ролями `roles/cloudsql.client` та `roles/secretmanager.secretAccessor`. |

---

## Відповіді на ключові архітектурні питання

### 1. Стратегія бази даних (Cloud SQL 24/7 vs зупинка на ніч vs Firestore vs cross-cloud Aurora)
- **Вибір**: **Cloud SQL for PostgreSQL 16 (`db-f1-micro`, 10 GB PD_SSD)** у режимі роботи з оптимізованими навчальними налаштуваннями (single-zone, без зайвих реплік, `deletion_protection = false`).
- **Чому не Firestore (NoSQL)?** Додаток побудований на реляційній схемі з зовнішніми ключами (таблиці `users`, `meetings`, `participants`), активними міграціями Alembic та складними SQL-вибірками агрегації для звітів. Перехід на NoSQL зруйнував би зворотну сумісність коду бекенду.
- **Чому не Cross-Cloud AWS Aurora?** З'єднання Cloud Run у GCP з AWS Aurora через публічний інтернет збільшує затримку (latency) кожного запиту до БД на 50–150 мс, вимагає складного налаштування VPN/Interconnect та створює додаткові витрати на Cross-Cloud Egress трафік.
- **Оптимізація витрат**: За потреби навчальний інстанс `db-f1-micro` можна зупиняти поза робочими годинами за розкладом через Cloud Scheduler + Cloud Functions, оскільки мінімальний інстанс не підтримує нативне автоматичне масштабування до нуля як Cloud Run.

### 2. Вибір провайдера для E-mail і зберігання ключа
- **Вибір**: Для надсилання сповіщень та щотижневих звітів у гібридному режимі залишається зв'язка з **AWS SES**, або за потреби міграції в GCP — використання **SendGrid** чи **Mailgun** через SMTP/REST API (оскільки GCP не має власного нативного сервісу на кшталт SES і рекомендує партнерські рішення).
- **Зберігання ключів/секретів**: Будь-які API-ключі (SendGrid API Key, Google OAuth Client Secret, SES SMTP Credentials) зберігаються суворо в **Google Secret Manager** і підтягуються в контейнери Cloud Run через блок `value_source.secret_key_ref`.

### 3. Які функції залишаються на AWS і чому (Гібридна архітектура)
На поточному етапі на AWS залишаються наступні модулі:
1. **Amazon Cognito (User Pool & App Client)**:
   - *Чому*: Усі існуючі користувачі, хеші паролів та Google Federated Identity зареєстровані в Cognito. FastAPI бекенд у Cloud Run перевіряє JWT-токени за допомогою публічних ключів JWKS (`https://cognito-idp.us-east-1.amazonaws.com/<pool_id>/.well-known/jwks.json`). Оскільки верифікація асиметрична і вимагає лише завантаження відкритих ключів, Cloud Run у GCP повністю валідує токени Cognito без перенесення бази користувачів.
2. **AI Agenda Parser (Bedrock Mantle / Anthropic Claude Sonnet 4.6)**:
   - *Чому*: Модуль парсингу винесений в окрему незалежну Lambda-функцію з власним Function URL. Поки модель не перенесена на Google Cloud Vertex AI (Gemini), фронтенд або бекенд можуть викликати існуючий Function URL без блокування релізу ядра в GCP.
3. **Weekly Reports Pipeline (EventBridge Scheduler + SQS + Lambda + SES + S3)**:
   - *Чому*: Повний конвеєр генерації CSV-звітів, черги DLQ, планувальника та надсилання листів автономний і працює за розкладом в AWS. Перенесення його на GCP Cloud Scheduler + Cloud Pub/Sub + GCS планується окремою наступною ітерацією.

## Наслідки
- **Позитивні**: Ядро системи отримало незалежне середовище виконання в GCP. Повний цикл CI/CD та IaC підтримується через HCP Terraform воркспейс `successfulsuccess-gcp`.
- **Компроміси**: Гібридний режим вимагає передачі змінних `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID` та `COGNITO_REGION` у Cloud Run для валідації токенів сесії користувачів.
