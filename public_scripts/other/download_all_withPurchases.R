# --- DNFileVault API: Download All Group and Purchase Files (R) ---
# This script retrieves file listings from BOTH your "Groups" and your "Purchases".
# Prerequisites: install.packages(c("httr", "jsonlite"))

library(httr)
library(jsonlite)

# 1. Configuration --------------------------------------------------------
base_url <- "https://api.dnfilevault.com"
email    <- Sys.getenv("DNFV_EMAIL", "your_email@example.com")
password <- Sys.getenv("DNFV_PASSWORD", "your_password_here")

# Set a custom User-Agent to ensure optimal performance/avoid throttling
ua <- user_agent("DNFileVaultRBulkDownloader/1.1")

# 2. Login to get JWT Token -----------------------------------------------
message("Logging in...")
login_url  <- paste0(base_url, "/auth/login")
login_resp <- POST(login_url, 
                   body = list(email = email, password = password), 
                   encode = "json", 
                   ua)

if (status_code(login_resp) != 200) {
  stop("Login failed. Check your credentials or DNFV_EMAIL/DNFV_PASSWORD environment variables.")
}

token <- content(login_resp)$token
auth_header <- add_headers(Authorization = paste("Bearer", token))

# 3. Retrieve Group Files -------------------------------------------------
message("Fetching Group files...")
groups_url  <- paste0(base_url, "/groups")
groups_resp <- GET(groups_url, auth_header, ua)
groups_data <- fromJSON(content(groups_resp, "text"))$groups

all_files_metadata <- list()

if (!is.null(groups_data) && length(groups_data) > 0) {
  for (i in 1:nrow(groups_data)) {
    group_id   <- groups_data$id[i]
    group_name <- groups_data$name[i]
    
    files_url  <- paste0(base_url, "/groups/", group_id, "/files")
    files_resp <- GET(files_url, auth_header, ua)
    files      <- fromJSON(content(files_resp, "text"))$files
    
    if (!is.null(files) && length(files) > 0) {
      # Add metadata about where this file came from
      files$source_type <- "Group"
      files$source_name <- group_name
      all_files_metadata[[length(all_files_metadata) + 1]] <- files
    }
  }
}

# 4. Retrieve Purchase Files ----------------------------------------------
message("Fetching Purchase files...")
purchases_url  <- paste0(base_url, "/purchases")
purchases_resp <- GET(purchases_url, auth_header, ua)
purchases_data <- fromJSON(content(purchases_resp, "text"))$purchases

if (!is.null(purchases_data) && length(purchases_data) > 0) {
  for (i in 1:nrow(purchases_data)) {
    purchase_id   <- purchases_data$id[i]
    product_name  <- purchases_data$product_name[i]
    
    files_url  <- paste0(base_url, "/purchases/", purchase_id, "/files")
    files_resp <- GET(files_url, auth_header, ua)
    files      <- fromJSON(content(files_resp, "text"))$files
    
    if (!is.null(files) && length(files) > 0) {
      # Add metadata about where this file came from
      files$source_type <- "Purchase"
      files$source_name <- product_name
      all_files_metadata[[length(all_files_metadata) + 1]] <- files
    }
  }
}

# 5. Summary and Results --------------------------------------------------
if (length(all_files_metadata) > 0) {
  df_files <- do.call(rbind, all_files_metadata)
  
  # Clean up display names for safe filing
  all_filenames <- df_files$display_name
  
  message(sprintf("\nSuccess! Found %d total files across Groups and Purchases.", length(all_filenames)))
  
  # Print break down
  print(table(df_files$source_type))
  
  message("\nFirst 10 files:")
  print(head(df_files[, c("display_name", "source_type", "source_name")], 10))
  
} else {
  message("No files found in any groups or purchases.")
}

# --- 6. Example: How to download all files ---
# (Uncomment this section to actually download the files to your current directory)

# if (exists("df_files") && nrow(df_files) > 0) {
#   message("\nStarting downloads...")
#   for (i in 1:nrow(df_files)) {
#     dest_file    <- df_files$display_name[i]
#     uuid_name    <- df_files$uuid_filename[i]
#     download_url <- paste0(base_url, "/download/", uuid_name)
#     
#     if (!file.exists(dest_file)) {
#       message(paste("Downloading:", dest_file, "(From", df_files$source_type[i], ":", df_files$source_name[i], ")"))
#       GET(download_url, 
#           auth_header, 
#           write_disk(dest_file, overwrite = TRUE), 
#           ua)
#     } else {
#       message(paste("Skipping (already exists):", dest_file))
#     }
#   }
#   message("All downloads complete.")
# }
