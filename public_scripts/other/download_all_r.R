# --- DNFileVault API Replacement for FTP (R Language) ---
# This script replaces the old RCurl/FTP method with modern API calls.
# Prerequisites: install.packages(c("httr", "jsonlite"))

library(httr)
library(jsonlite)

# 1. Configuration
# Note: It is best practice to use Environment Variables for security.
base_url <- "https://api.dnfilevault.com"
email    <- Sys.getenv("DNFV_EMAIL", "your_email@example.com")
password <- Sys.getenv("DNFV_PASSWORD", "your_password_here")

# Set a custom User-Agent as required by the API to avoid throttling
ua <- user_agent("DNFileVaultRDownloader/1.0")

# 2. Login to get JWT Token
login_url  <- paste0(base_url, "/auth/login")
login_resp <- POST(login_url, 
                   body = list(email = email, password = password), 
                   encode = "json", 
                   ua)

if (status_code(login_resp) != 200) {
  stop("Login failed. Check your credentials or DNFV_EMAIL/DNFV_PASSWORD environment variables.")
}

token <- content(login_resp)$token

# 3. Retrieve all files from your Groups
# (Equivalent to 'getURL' on the old FTP server root)
groups_url  <- paste0(base_url, "/groups")
groups_resp <- GET(groups_url, add_headers(Authorization = paste("Bearer", token)), ua)
groups_data <- fromJSON(content(groups_resp, "text"))$groups

all_files_metadata <- list()

if (length(groups_data) > 0) {
  for (i in 1:nrow(groups_data)) {
    group_id   <- groups_data$id[i]
    files_url  <- paste0(base_url, "/groups/", group_id, "/files")
    files_resp <- GET(files_url, add_headers(Authorization = paste("Bearer", token)), ua)
    files      <- fromJSON(content(files_resp, "text"))$files
    
    if (!is.null(files) && length(files) > 0) {
      all_files_metadata[[length(all_files_metadata) + 1]] <- files
    }
  }
}

# Combine into a single data frame if any files were found
if (length(all_files_metadata) > 0) {
  df_files <- do.call(rbind, all_files_metadata)
  
  # 4. Result: A vector of filenames (matches the customer's original 'all_files' format)
  all_files <- df_files$display_name
  
  print(paste("Found", length(all_files), "files."))
  print("First 5 files:")
  print(head(all_files, 5))
} else {
  all_files <- character(0)
  print("No files found in any groups.")
}

# --- Example: How to download the first file ---
# if (length(all_files) > 0) {
#   dest_file <- all_files[1]
#   download_url <- paste0(base_url, "/download/", df_files$uuid_filename[1])
#   print(paste("Downloading:", dest_file))
#   GET(download_url, 
#       add_headers(Authorization = paste("Bearer", token)), 
#       write_disk(dest_file, overwrite = TRUE), 
#       ua)
# }
