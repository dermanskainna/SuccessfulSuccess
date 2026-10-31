# 0006 – LLM agenda parsing

## Context
The product needs a way for users to paste a free‑form meeting agenda and have the system extract structured data (name, description, location, date, times, participants).  We already have an Anthropic Claude model available via AWS Bedrock.

## Decision
We implement a single Lambda function (`agenda_lambda`) that receives the raw agenda text, validates the request (Cognito JWT + 10 000 char limit), forwards it to Claude (`anthropic.claude-opus-5-5`) and returns a JSON payload containing:
- `agenda` – the structured fields expected by the frontend form.
- `model` – the model identifier used.
- `prompt_version` – a version string for future prompt changes.
- `suggested_fields` (optional) – an array of field names the model inferred as relevant.

The Lambda is deployed **outside** a VPC so it can reach Bedrock without VPC‑endpoint configuration. The Function URL is exposed with CORS to the frontend.

## Rationale
- **Simplicity** – a single Lambda avoids the overhead of a separate validation service.
- **Security** – JWT validation ensures only authenticated users can invoke the parser.
- **Cost** – Bedrock pricing is per token; a single request per agenda keeps costs low.
- **Extensibility** – `prompt_version` allows future prompt tweaks without breaking clients.
- **User experience** – returning `suggested_fields` enables the UI to highlight inferred fields with a badge.

## Consequences
- The Lambda must have the IAM permission `bedrock-mantle:CreateInference` (added in `infra/ai.yml`).
- The frontend must know the Function URL (injected via an environment variable).
- Errors from the model (validation failures) are retried once in `parse_agenda`.
- Changing the prompt will require a new deployment of the Lambda.

## Alternatives considered
1. **Two‑Lambda architecture** – one for JWT validation, another for model call. Rejected due to added latency and deployment complexity.
2. **Direct Bedrock call from the frontend** – rejected because it would expose AWS credentials.
3. **Using a different LLM provider** – Anthropic was chosen for its strong reasoning capabilities.

## Implementation notes
- The parser lives in `backend/app/ai/agenda.py`.
- The Lambda handler is `backend/app/ai/agenda_lambda.py`.
- The Makefile target `make parse` is provided for local testing.
- UI changes are in `frontend/components/meeting-form-dialog.tsx`.
- Documentation updates: ADR (this file), C4 diagram (see next step), and `docs/step6_answers.md`.

