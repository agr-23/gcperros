###############################################################################
# Versiones de Terraform y de los providers
###############################################################################

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Estado remoto en Cloud Storage. El estado contiene los nombres de las
  # service accounts y la topología completa: no se versiona en Git.
  # Se activa creando primero el bucket (ver README, "Estado remoto") y
  # ejecutando despues: terraform init -migrate-state
  #
  # backend "gcs" {
  #   bucket = "gcperros-tfstate"
  #   prefix = "infra/dev"
  # }
}
