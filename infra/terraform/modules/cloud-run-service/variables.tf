variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "labels" {
  type = map(string)
}

variable "service_account_email" {
  type = string
}

variable "env" {
  type        = map(string)
  default     = {}
  description = "Plain environment variables. Nothing sensitive: use secret_env."
}

variable "secret_env" {
  type        = map(string)
  default     = {}
  description = "Environment variable name to Secret Manager secret id. Cloud Run reads the latest version when an instance starts."
}

variable "min_instances" {
  type    = number
  default = 0
}

variable "max_instances" {
  type    = number
  default = 3
}

variable "concurrency" {
  type    = number
  default = 80
}

variable "timeout_seconds" {
  type    = number
  default = 60
}

variable "cpu" {
  type    = string
  default = "1"
}

variable "memory" {
  type    = string
  default = "512Mi"
}

variable "vpc" {
  type = object({
    network = string
    subnet  = string
  })
  default     = null
  description = "Direct VPC egress, to reach private addresses such as Cloud SQL."
}

variable "public" {
  type        = bool
  default     = true
  description = "Anyone on the internet can reach the service. The app does its own sign-in."
}
