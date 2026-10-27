variable "name" {
  type = string
}

variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "labels" {
  type = map(string)
}

variable "writer_service_account_email" {
  description = "Service account that may create, read and delete files in the bucket."
  type        = string
}
