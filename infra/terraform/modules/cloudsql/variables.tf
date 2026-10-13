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

variable "private_connection_id" {
  type        = string
  description = "Only used to make the instance wait for the private services connection."
}

variable "db_tier" {
  type = string
}

variable "db_version" {
  type = string
}

variable "db_name" {
  type = string
}
