variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "max_dispatches_per_second" {
  type    = number
  default = 2
}

variable "max_concurrent_dispatches" {
  type        = number
  default     = 2
  description = "Calls running at the same time. Each one holds a database connection while it works."
}

variable "max_attempts" {
  type    = number
  default = 5
}
