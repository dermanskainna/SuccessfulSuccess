FROM public.ecr.aws/lambda/python:3.12

# Set working directory
WORKDIR /var/task

# Copy project files
COPY pyproject.toml ./

# Install UV (Python package manager) and project dependencies
RUN pip install uv && \
    uv sync --no-install-project --no-dev

# Copy the rest of the source code
COPY . .

# Lambda expects the handler function; set CMD accordingly
CMD ["app.ai.agenda_lambda.handler"]
