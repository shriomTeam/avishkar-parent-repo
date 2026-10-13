variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "labels" {
  type = map(string)
}

variable "network_id" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "secret_ids" {
  type        = map(string)
  description = "Secret Manager secret ids with keys owner-url, app-password, system-password."
}
