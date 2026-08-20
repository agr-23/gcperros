###############################################################################
# Configuración del provider de Google Cloud
# Las credenciales se toman de Application Default Credentials (ADC),
# es decir de: gcloud auth application-default login
#
# Politica del proyecto (matriz de riesgos, "Exposicion accidental de
# credenciales"): no se descargan llaves JSON de service account ni se
# referencian archivos de credenciales desde el codigo.
###############################################################################

provider "google" {
  project = var.project_id
  region  = var.region

  default_labels = local.common_labels
}
