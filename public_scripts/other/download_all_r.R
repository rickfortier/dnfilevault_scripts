#!/usr/bin/env Rscript
# ==============================================================================
# DNFileVault Downloader for R
# ==============================================================================
# This script downloads ALL files from your DNFileVault account:
#   1. All Purchases
#   2. All Groups
#
# It automatically discovers available API servers and fails over
# to the next one if the primary is down.
#
# Designed for R users, data scientists, and academic researchers.
#
# BEFORE YOU RUN THIS:
# 1. Install R from https://cran.r-project.org/
# 2. Install required packages (run once):
#        install.packages(c("httr", "jsonlite"))
#
# HOW TO RUN:
#    source("dnfilevault_downloader.R")
#
# OR from command line:
#    Rscript dnfilevault_downloader.R
#
# HOW TO CONFIGURE:
#    Edit the CONFIGURATION section below, or set environment variables:
#        Sys.setenv(DNFV_EMAIL = "your_email@example.com")
#        Sys.setenv(DNFV_PASSWORD = "your_password")
#        Sys.setenv(DNFV_OUT_DIR = "C:/dnfilevault-downloads")
# ==============================================================================

# Load required packages
if (!requireNamespace("httr", quietly = TRUE)) {
  stop("Package 'httr' is required. Install with: install.packages('httr')")
}
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("Package 'jsonlite' is required. Install with: install.packages('jsonlite')")
}

library(httr)
library(jsonlite)

# ==============================================================================
# CONFIGURATION
# ==============================================================================

EMAIL    <- Sys.getenv("DNFV_EMAIL", unset = "your_email@example.com")
PASSWORD <- Sys.getenv("DNFV_PASSWORD", unset = "your_password")

# Where should files be saved?
# Windows: "C:/dnfilevault-downloads"  (use forward slashes in R)
# Mac:     "~/Documents/DNFileVault"
# Linux:   "~/dnfilevault-downloads"
OUTPUT_FOLDER <- Sys.getenv("DNFV_OUT_DIR", unset = file.path(path.expand("~"), "dnfilevault-downloads"))

# Set to a number (e.g., 1) to only download the newest N files per group.
# Set to NULL to download EVERYTHING.
DAYS_TO_CHECK <- NULL

# ==============================================================================


# API Discovery
DISCOVERY_URL <- "https://config.dnfilevault.com/endpoints.json"

FALLBACK_ENDPOINTS <- c(
  "https://api.dnfilevault.com",
  "https://api-redmint.dnfilevault.com"
)

USER_AGENT <- "DNFileVaultClient/1.0-R (+support@deltaneutral.com)"


# ------------------------------------------------------------------------------
# Utility Functions
# ------------------------------------------------------------------------------

log_msg <- function(...) {
  timestamp <- format(Sys.time(), "[%Y-%m-%d %H:%M:%S]")
  message(timestamp, " ", paste0(...))
}


sanitize_filename <- function(name) {
  if (is.null(name) || nchar(trimws(name)) == 0) return("unnamed_file")
  clean <- gsub('[<>:"/\\\\|?*]', "_", name)
  clean <- trimws(clean)
  if (nchar(clean) == 0) return("unnamed_file")
  return(clean)
}


ensure_folder_exists <- function(folder_path) {
  if (!dir.exists(folder_path)) {
    dir.create(folder_path, recursive = TRUE, showWarnings = FALSE)
    log_msg("Created folder: ", folder_path)
  }
}


safe_get <- function(url, ...) {
  tryCatch(
    GET(url, user_agent(USER_AGENT), ...),
    error = function(e) {
      log_msg("  Request failed: ", conditionMessage(e))
      return(NULL)
    }
  )
}


# ------------------------------------------------------------------------------
# Discovery & Failover
# ------------------------------------------------------------------------------

get_api_endpoints <- function() {
  log_msg("Discovering API endpoints...")
  
  resp <- tryCatch(
    GET(DISCOVERY_URL, user_agent(USER_AGENT), timeout(10)),
    error = function(e) NULL
  )
  
  if (!is.null(resp) && status_code(resp) == 200) {
    data <- fromJSON(content(resp, as = "text", encoding = "UTF-8"))
    endpoints <- data$endpoints
    endpoints <- endpoints[order(endpoints$priority), ]
    
    log_msg("  Found ", nrow(endpoints), " endpoints",
            " (config v", data$version, ", updated ", data$updated, ")")
    for (i in seq_len(nrow(endpoints))) {
      log_msg("    ", endpoints$priority[i], ". ", endpoints$url[i],
              " (", endpoints$label[i], ")")
    }
    return(endpoints$url)
  }
  
  log_msg("  Discovery unavailable, using fallback list.")
  return(FALLBACK_ENDPOINTS)
}


find_working_api <- function(endpoints) {
  log_msg("Finding a healthy API server...")
  
  for (url in endpoints) {
    resp <- tryCatch(
      GET(paste0(url, "/health"), user_agent(USER_AGENT), timeout(10)),
      error = function(e) NULL
    )
    
    if (!is.null(resp) && status_code(resp) == 200) {
      data <- fromJSON(content(resp, as = "text", encoding = "UTF-8"))
      if (identical(data$status, "healthy")) {
        log_msg("  \u2713 ", url, " - healthy")
        return(url)
      } else {
        log_msg("  \u2717 ", url, " - status: ", data$status)
      }
    } else {
      log_msg("  \u2717 ", url, " - unreachable")
    }
  }
  
  return(NULL)
}


# ------------------------------------------------------------------------------
# Authentication
# ------------------------------------------------------------------------------

login_to_api <- function(base_url) {
  log_msg("Logging in as ", EMAIL, "...")
  
  resp <- tryCatch(
    POST(
      paste0(base_url, "/auth/login"),
      body = list(email = EMAIL, password = PASSWORD),
      encode = "json",
      user_agent(USER_AGENT),
      timeout(60)
    ),
    error = function(e) {
      log_msg("Login failed: ", conditionMessage(e))
      return(NULL)
    }
  )
  
  if (is.null(resp)) return(NULL)
  
  if (status_code(resp) == 200) {
    data <- fromJSON(content(resp, as = "text", encoding = "UTF-8"))
    log_msg("Login successful!")
    return(data$token)
  } else if (status_code(resp) == 401) {
    log_msg("Login failed: Incorrect email or password.")
  } else {
    log_msg("Login failed: Server returned ", status_code(resp))
  }
  
  return(NULL)
}


# ------------------------------------------------------------------------------
# File Download
# ------------------------------------------------------------------------------

download_file <- function(file_info, save_directory, base_url, token) {
  uuid_filename <- file_info$uuid_filename
  cloud_url     <- file_info$cloud_share_link
  display_name  <- file_info$display_name
  if (is.null(display_name) || nchar(display_name) == 0) display_name <- uuid_filename
  
  safe_name     <- sanitize_filename(display_name)
  full_save_path <- file.path(save_directory, safe_name)
  
  # Skip if already downloaded
  if (file.exists(full_save_path)) return(invisible(FALSE))
  
  temp_path <- paste0(full_save_path, ".tmp")
  
  # Method 1: R2 Direct Link (PRIMARY)
  if (!is.null(cloud_url) && nchar(cloud_url) > 0) {
    log_msg("  Downloading: ", safe_name, " via R2...")
    resp <- tryCatch(
      GET(cloud_url, write_disk(temp_path, overwrite = TRUE), timeout(120)),
      error = function(e) NULL
    )
    
    if (!is.null(resp) && status_code(resp) == 200) {
      file.rename(temp_path, full_save_path)
      size_mb <- round(file.size(full_save_path) / (1024 * 1024), 1)
      log_msg("  \u2713 Complete (R2) - ", size_mb, " MB")
      return(invisible(TRUE))
    } else {
      if (file.exists(temp_path)) file.remove(temp_path)
      log_msg("  R2 failed, trying fallback...")
    }
  }
  
  # Method 2: API Server (FALLBACK)
  if (is.null(uuid_filename) || nchar(uuid_filename) == 0) {
    log_msg("  \u2717 No download ID for ", safe_name)
    return(invisible(FALSE))
  }
  
  log_msg("  Downloading: ", safe_name, " via API...")
  resp <- tryCatch(
    GET(
      paste0(base_url, "/download/", uuid_filename),
      add_headers(Authorization = paste("Bearer", token)),
      user_agent(USER_AGENT),
      write_disk(temp_path, overwrite = TRUE),
      timeout(300)
    ),
    error = function(e) NULL
  )
  
  if (!is.null(resp) && status_code(resp) == 200) {
    file.rename(temp_path, full_save_path)
    size_mb <- round(file.size(full_save_path) / (1024 * 1024), 1)
    log_msg("  \u2713 Complete (API) - ", size_mb, " MB")
    return(invisible(TRUE))
  } else {
    if (file.exists(temp_path)) file.remove(temp_path)
    log_msg("  \u2717 Failed: ", safe_name)
    return(invisible(FALSE))
  }
}


# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

main <- function() {
  log_msg(strrep("=", 50))
  log_msg("DNFileVault Downloader v2.0 (R)")
  log_msg(strrep("=", 50))
  log_msg("Output: ", OUTPUT_FOLDER)
  
  # Discover API endpoints
  endpoints <- get_api_endpoints()
  
  # Find healthy server
  base_url <- find_working_api(endpoints)
  if (is.null(base_url)) {
    log_msg("ERROR: All API servers are unreachable!")
    log_msg("Contact support@deltaneutral.com if this persists.")
    stop("All API servers unreachable", call. = FALSE)
  }
  
  log_msg("Using API: ", base_url)
  
  # Login
  token <- login_to_api(base_url)
  if (is.null(token)) {
    stop("Login failed", call. = FALSE)
  }
  
  auth_header <- add_headers(Authorization = paste("Bearer", token))
  ensure_folder_exists(OUTPUT_FOLDER)
  total_downloaded <- 0
  
  # Download Purchases
  log_msg("--- Checking Purchases ---")
  purchases <- tryCatch({
    resp <- GET(paste0(base_url, "/purchases"),
                auth_header, user_agent(USER_AGENT), timeout(60))
    fromJSON(content(resp, as = "text", encoding = "UTF-8"))$purchases
  }, error = function(e) {
    log_msg("Error checking purchases: ", conditionMessage(e))
    data.frame()
  })
  
  if (is.null(purchases) || nrow(purchases) == 0) {
    log_msg("No purchases found.")
  } else {
    for (i in seq_len(nrow(purchases))) {
      p <- purchases[i, ]
      folder_name <- paste0(p$id, " - ", ifelse(is.null(p$product_name), "Unknown", p$product_name))
      product_path <- file.path(OUTPUT_FOLDER, "Purchases", sanitize_filename(folder_name))
      ensure_folder_exists(product_path)
      
      files <- tryCatch({
        resp <- GET(paste0(base_url, "/purchases/", p$id, "/files"),
                    auth_header, user_agent(USER_AGENT), timeout(60))
        fromJSON(content(resp, as = "text", encoding = "UTF-8"))$files
      }, error = function(e) {
        log_msg("Error getting files for purchase ", p$id, ": ", conditionMessage(e))
        data.frame()
      })
      
      if (!is.null(files) && nrow(files) > 0) {
        if (!is.null(DAYS_TO_CHECK)) {
          files <- head(files, DAYS_TO_CHECK)
        }
        for (j in seq_len(nrow(files))) {
          result <- download_file(files[j, ], product_path, base_url, token)
          if (isTRUE(result)) total_downloaded <- total_downloaded + 1
        }
      }
    }
  }
  
  # Download Groups
  log_msg("--- Checking Groups ---")
  groups <- tryCatch({
    resp <- GET(paste0(base_url, "/groups"),
                auth_header, user_agent(USER_AGENT), timeout(60))
    fromJSON(content(resp, as = "text", encoding = "UTF-8"))$groups
  }, error = function(e) {
    log_msg("Error checking groups: ", conditionMessage(e))
    data.frame()
  })
  
  if (is.null(groups) || nrow(groups) == 0) {
    log_msg("No groups found.")
  } else {
    for (i in seq_len(nrow(groups))) {
      g <- groups[i, ]
      folder_name <- paste0(g$id, " - ", ifelse(is.null(g$name), "Unknown", g$name))
      group_path <- file.path(OUTPUT_FOLDER, "Groups", sanitize_filename(folder_name))
      ensure_folder_exists(group_path)
      
      files <- tryCatch({
        resp <- GET(paste0(base_url, "/groups/", g$id, "/files"),
                    auth_header, user_agent(USER_AGENT), timeout(60))
        fromJSON(content(resp, as = "text", encoding = "UTF-8"))$files
      }, error = function(e) {
        log_msg("Error getting files for group ", g$id, ": ", conditionMessage(e))
        data.frame()
      })
      
      if (!is.null(files) && nrow(files) > 0) {
        if (!is.null(DAYS_TO_CHECK)) {
          files <- head(files, DAYS_TO_CHECK)
        }
        for (j in seq_len(nrow(files))) {
          result <- download_file(files[j, ], group_path, base_url, token)
          if (isTRUE(result)) total_downloaded <- total_downloaded + 1
        }
      }
    }
  }
  
  log_msg("All done! Downloaded ", total_downloaded, " new file(s).")
  log_msg("Files saved to: ", OUTPUT_FOLDER)
}

# Run
main()