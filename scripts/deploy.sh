#!/usr/bin/env bash
set -euo pipefail
: "${OCI_HOST:?Set OCI_HOST to the VM public IP or DNS name}"
if [[ ! "$OCI_HOST" =~ ^[a-zA-Z0-9.-]+$ ]]; then
  echo 'OCI_HOST must be a hostname or IPv4 address' >&2
  exit 1
fi
if [[ ! -f compose.yaml ]]; then echo 'Run from the repository root' >&2; exit 1; fi
ssh "ubuntu@$OCI_HOST" 'cloud-init status --wait && mkdir -p ~/llm-serving-observatory'
rsync -av --exclude=.git --exclude=.venv --exclude=.env --exclude=data --exclude=models --exclude=.terraform --exclude='*.tfstate*' --exclude='*.tfvars' ./ "ubuntu@$OCI_HOST:llm-serving-observatory/"
ssh "ubuntu@$OCI_HOST" 'cd ~/llm-serving-observatory && docker compose up -d --build && docker compose ps'
echo 'CPU lab deployed. Use the SSH tunnel in the Terraform output to open localhost:8000.'
