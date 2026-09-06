# Solus CI/CD — ARM build on AWS self-hosted runner → ECS deploy.
stages: [lint, typecheck, test, security, build, deploy]

workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == "main"
    - if: $CI_COMMIT_TAG

default:
  interruptible: true

variables:
  PNPM_STORE: "$CI_PROJECT_DIR/.pnpm-store"
  UV_CACHE_DIR: "$CI_PROJECT_DIR/.uv-cache"
  IMAGE_TAG: "arm-latest" # the tag your ECS task definition references

# Validate relevant changes before merge; protected main requires a successful
# MR pipeline and only builds/deploys afterward. `needs: []` avoids stage waits.
.python-rules:
  needs: []
  rules:
    - if: $CI_COMMIT_TAG
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - .gitlab-ci.yml
        - pyproject.toml
        - uv.lock
        - .dockerignore
        - infrastructure/**/*
        - packages/api/**/*
        - packages/companion/**/*
        - packages/contracts/python/**/*
        - livebench/**/*
        - integrations/**/*
        - reasoning/**/*
        - scripts/**/*.py

.node-rules:
  needs: []
  rules:
    - if: $CI_COMMIT_TAG
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - .gitlab-ci.yml
        - package.json
        - pnpm-lock.yaml
        - pnpm-workspace.yaml
        - .npmrc
        - tsconfig.base.json
        - eslint.config.mjs
        - .prettierrc.json
        - vitest.config.ts
        - apps/**/*
        - packages/shared-types/**/*
        - packages/contracts/**/*
        - scripts/**/*

.node-base:
  image: node:22
  tags: [aws-arm]
  before_script:
    - corepack enable
    - pnpm config set store-dir "$PNPM_STORE"
    - pnpm install --frozen-lockfile
  cache:
    key: { files: [pnpm-lock.yaml] }
    paths: [.pnpm-store]
    policy: pull

.python-base:
  image: ghcr.io/astral-sh/uv:python3.12-bookworm-slim
  tags: [aws-arm]
  before_script:
    - uv sync --all-packages --locked
  cache:
    key: { files: [uv.lock] }
    paths: [.uv-cache]
    policy: pull

lint:python:
  extends: .python-rules
  stage: lint
  # Match uv.lock without installing the API, CAD kernel, or simulator for lint.
  image: { name: "ghcr.io/astral-sh/ruff:0.15.17-alpine", entrypoint: [""] }
  tags: [aws-arm]
  script: ruff check .

lint:node:
  extends: [.node-base, .node-rules]
  stage: lint
  cache:
    policy: pull-push
  script: pnpm lint

typecheck:python:
  extends: [.python-base, .python-rules]
  stage: typecheck
  # One writer per dependency cache; later jobs only extract it.
  cache:
    policy: pull-push
  script: uv run --no-sync mypy packages/api/src packages/companion/src

typecheck:node:
  extends: [.node-base, .node-rules]
  stage: typecheck
  variables:
    # The renderer's `tsc` needs ~500 MB of V8 heap; retain the established cap.
    NODE_OPTIONS: "--max-old-space-size=1536"
  script: pnpm typecheck

test:python:
  extends: [.python-base, .python-rules]
  stage: test
  services:
    - name: pgvector/pgvector:pg16
      alias: postgres
      # Disposable job database: avoid durable disk flushing on every fixture
      # TRUNCATE. Never apply these settings to a persistent database.
      command:
        [
          "postgres",
          "-c",
          "fsync=off",
          "-c",
          "synchronous_commit=off",
          "-c",
          "full_page_writes=off",
        ]
  variables:
    FF_NETWORK_PER_BUILD: "true"
    POSTGRES_USER: solus
    POSTGRES_PASSWORD: solus
    POSTGRES_DB: solus
    SOLUS_TEST_DATABASE_URL: "postgresql+asyncpg://solus:solus@postgres:5432/solus_test"
  script:
    # The OCCT wheel is in the dev group precisely so CI exercises the real STEP
    # path (packages/api/pyproject.toml), but it dlopens libGL and bookworm-slim
    # ships no OpenGL runtime — so it imported nowhere and ~40 CAD tests SKIPPED
    # silently while the rest failed on unrelated-looking assertions.
    # Git is also needed by the scanner's temporary-repository regression tests.
    - apt-get update -qq && apt-get install -y -qq --no-install-recommends libgl1 git
    # Fail LOUDLY if that ever regresses. A silent skip is the failure mode that
    # hid this: the suite stays green while the CAD path goes entirely untested.
    - uv run --no-sync python -c 'from solus_api.connectors.step_parser import step_reader_available as ok; assert ok(), "OCCT unavailable — CAD tests would silently skip"'
    # The aws-arm t4g.micro has 1 GiB RAM. Two workers regressed the real suite
    # from 27 min to 48 min; use serial execution and expose slow-test timings.
    - uv run --no-sync pytest -q -rfE -m 'not live' --durations=20 --junitxml=reports/pytest.xml
  artifacts:
    when: always
    expire_in: 7 days
    reports:
      junit: reports/pytest.xml

test:node:
  extends: [.node-base, .node-rules]
  stage: test
  script: pnpm test

security:gitleaks:
  stage: security
  needs: []
  tags: [aws-arm]
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_TAG
  variables:
    GIT_DEPTH: "0" # The MR base must exist; scan every introduced commit.
  image: { name: "zricethezav/gitleaks:latest", entrypoint: [""] }
  script: sh infrastructure/ci/scan-secrets.sh

build:api-image:
  stage: build
  tags: [aws-arm]
  image: docker:27
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  before_script:
    - docker run --rm -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_REGION amazon/aws-cli:latest ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_URI"
  script:
    - docker build -f infrastructure/docker/api.Dockerfile -t "$ECR_URI:$CI_COMMIT_SHORT_SHA" -t "$ECR_URI:$IMAGE_TAG" .
    - docker push "$ECR_URI:$CI_COMMIT_SHORT_SHA"
    - docker push "$ECR_URI:$IMAGE_TAG"

deploy:staging:
  stage: deploy
  needs: ["build:api-image"]
  interruptible: false
  tags: [aws-arm]
  image: { name: "amazon/aws-cli:latest", entrypoint: [""] }
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  environment:
    name: staging
  script:
    # REGISTER the task definition, then point the service at it. `--force-new-deployment`
    # alone only re-pulls the image and leaves the service on whatever revision it was
    # created with — which is how staging ran for weeks on a console-made `solus-api:1`
    # whose variable names (`DB_HOST`) are not the ones the code reads
    # (`SOLUS_DATABASE_URL`), until a restart finally surfaced it as
    # `ConnectionRefusedError ('127.0.0.1', 5432)` during alembic.
    - TASKDEF_ARN=$(aws ecs register-task-definition --cli-input-json file://infrastructure/aws/taskdef.json --query 'taskDefinition.taskDefinitionArn' --output text --region "$AWS_REGION")
    - aws ecs update-service --cluster "$ECS_CLUSTER" --service "$ECS_SERVICE" --task-definition "$TASKDEF_ARN" --force-new-deployment --region "$AWS_REGION"
    - echo "Staging deploy triggered — image $CI_COMMIT_SHORT_SHA, taskdef $TASKDEF_ARN."
# deploy:production (enable when prod ECS service exists):
# deploy:production:
#   stage: deploy
#   tags: [aws-arm]
#   image: { name: "amazon/aws-cli:latest", entrypoint: [""] }
#   rules:
#     - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
#       when: manual
#   environment:
#     name: production
#   script:
#     - aws ecs update-service --cluster "$ECS_CLUSTER" --service "$ECS_SERVICE_PROD" --force-new-deployment --region "$AWS_REGION"
