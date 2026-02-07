/*
 * ==============================================================================
 * DNFileVault Downloader for Java
 * ==============================================================================
 * This application downloads ALL files from your DNFileVault account:
 *   1. All Purchases
 *   2. All Groups
 *
 * It automatically discovers available API servers and fails over
 * to the next one if the primary is down.
 *
 * Requires Java 11+ (uses java.net.http.HttpClient, no external dependencies).
 *
 * COMPILE:
 *     javac DNFileVaultDownloader.java
 *
 * RUN:
 *     java DNFileVaultDownloader
 *
 * OR with environment variables:
 *     DNFV_EMAIL=you@example.com DNFV_PASSWORD=secret java DNFileVaultDownloader
 *
 * CONFIGURATION:
 *     Edit the constants below, or set environment variables:
 *         DNFV_EMAIL       - Your login email
 *         DNFV_PASSWORD    - Your password
 *         DNFV_OUT_DIR     - Download folder (default: ./dnfilevault-downloads)
 *         DNFV_DAYS_CHECK  - Only download newest N files (default: all)
 * ==============================================================================
 */

import java.io.*;
import java.net.URI;
import java.net.http.*;
import java.nio.file.*;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.regex.*;
import java.util.stream.*;

/**
 * Self-contained DNFileVault downloader. No external dependencies — uses only
 * the built-in java.net.http client and a minimal inline JSON parser.
 */
public class DNFileVaultDownloader {

    // =========================================================================
    // CONFIGURATION
    // =========================================================================

    private static final String EMAIL = env("DNFV_EMAIL", "your_email@example.com");
    private static final String PASSWORD = env("DNFV_PASSWORD", "your_password");
    private static final String OUTPUT_FOLDER = env("DNFV_OUT_DIR", "dnfilevault-downloads");
    private static final Integer DAYS_TO_CHECK = envInt("DNFV_DAYS_CHECK", null);

    // =========================================================================

    private static final String DISCOVERY_URL = "https://config.dnfilevault.com/endpoints.json";
    private static final String USER_AGENT = "DNFileVaultClient/1.0-Java (+support@deltaneutral.com)";

    private static final String[] FALLBACK_ENDPOINTS = {
        "https://api.dnfilevault.com",
        "https://api-redmint.dnfilevault.com"
    };

    private static final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(30))
            .followRedirects(HttpClient.Redirect.NORMAL)
            .build();

    private static String authToken = null;


    // =========================================================================
    // Utility
    // =========================================================================

    private static String env(String key, String fallback) {
        String val = System.getenv(key);
        return (val != null && !val.isEmpty()) ? val : fallback;
    }

    private static Integer envInt(String key, Integer fallback) {
        String val = System.getenv(key);
        if (val != null && !val.isEmpty()) {
            try { return Integer.parseInt(val); } catch (NumberFormatException e) { /* ignore */ }
        }
        return fallback;
    }

    private static void log(String msg) {
        String ts = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
        System.out.println("[" + ts + "] " + msg);
    }

    private static String sanitizeFilename(String name) {
        if (name == null || name.trim().isEmpty()) return "unnamed_file";
        String clean = name.replaceAll("[<>:\"/\\\\|?*]", "_").trim();
        return clean.isEmpty() ? "unnamed_file" : clean;
    }

    private static void ensureFolderExists(Path path) {
        try {
            if (!Files.exists(path)) {
                Files.createDirectories(path);
                log("Created folder: " + path);
            }
        } catch (IOException e) {
            log("Error creating folder " + path + ": " + e.getMessage());
        }
    }


    // =========================================================================
    // Minimal JSON helpers (no external library needed)
    // =========================================================================

    /**
     * Extract a string value for a given key from a JSON object string.
     * Handles simple flat objects. For nested/array access, use the
     * dedicated methods below.
     */
    private static String jsonString(String json, String key) {
        // Match "key": "value" or "key":"value"
        Pattern p = Pattern.compile("\"" + Pattern.quote(key) + "\"\\s*:\\s*\"([^\"]*)\"");
        Matcher m = p.matcher(json);
        return m.find() ? m.group(1) : null;
    }

    /** Extract an integer value for a given key. */
    private static Integer jsonInt(String json, String key) {
        Pattern p = Pattern.compile("\"" + Pattern.quote(key) + "\"\\s*:\\s*(-?\\d+)");
        Matcher m = p.matcher(json);
        return m.find() ? Integer.parseInt(m.group(1)) : null;
    }

    /** Extract a JSON array as a list of JSON object strings. */
    private static List<String> jsonArray(String json, String key) {
        List<String> items = new ArrayList<>();
        // Find the array start
        String searchKey = "\"" + key + "\"";
        int keyIdx = json.indexOf(searchKey);
        if (keyIdx < 0) return items;

        int bracketStart = json.indexOf('[', keyIdx);
        if (bracketStart < 0) return items;

        // Parse objects within the array by matching braces
        int depth = 0;
        int objStart = -1;
        for (int i = bracketStart + 1; i < json.length(); i++) {
            char c = json.charAt(i);
            if (c == '{') {
                if (depth == 0) objStart = i;
                depth++;
            } else if (c == '}') {
                depth--;
                if (depth == 0 && objStart >= 0) {
                    items.add(json.substring(objStart, i + 1));
                    objStart = -1;
                }
            } else if (c == ']' && depth == 0) {
                break;
            }
        }
        return items;
    }


    // =========================================================================
    // Discovery & Failover
    // =========================================================================

    private static List<String> getApiEndpoints() {
        log("Discovering API endpoints...");

        try {
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(DISCOVERY_URL))
                    .header("User-Agent", USER_AGENT)
                    .timeout(Duration.ofSeconds(10))
                    .GET().build();

            HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());

            if (resp.statusCode() == 200) {
                String body = resp.body();
                String version = jsonString(body, "version");
                if (version == null) {
                    Integer vi = jsonInt(body, "version");
                    version = vi != null ? vi.toString() : "?";
                }
                String updated = jsonString(body, "updated");

                List<String> endpoints = jsonArray(body, "endpoints");
                // Sort by priority
                endpoints.sort(Comparator.comparingInt(e -> {
                    Integer pri = jsonInt(e, "priority");
                    return pri != null ? pri : 99;
                }));

                log("  Found " + endpoints.size() + " endpoints (config v" + version +
                        ", updated " + (updated != null ? updated : "?") + ")");

                List<String> urls = new ArrayList<>();
                for (String ep : endpoints) {
                    String url = jsonString(ep, "url");
                    String label = jsonString(ep, "label");
                    Integer priority = jsonInt(ep, "priority");
                    log("    " + priority + ". " + url + " (" + label + ")");
                    urls.add(url);
                }
                return urls;
            } else {
                log("  Discovery returned status " + resp.statusCode() + ", using fallback list.");
            }
        } catch (Exception e) {
            log("  Discovery unavailable (" + e.getMessage() + "), using fallback list.");
        }

        log("  Using " + FALLBACK_ENDPOINTS.length + " fallback endpoints.");
        return Arrays.asList(FALLBACK_ENDPOINTS);
    }


    private static String findWorkingApi(List<String> endpoints) {
        log("Finding a healthy API server...");

        for (String url : endpoints) {
            try {
                HttpRequest req = HttpRequest.newBuilder()
                        .uri(URI.create(url + "/health"))
                        .header("User-Agent", USER_AGENT)
                        .timeout(Duration.ofSeconds(10))
                        .GET().build();

                HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());

                if (resp.statusCode() == 200) {
                    String status = jsonString(resp.body(), "status");
                    if ("healthy".equals(status)) {
                        log("  \u2713 " + url + " - healthy");
                        return url;
                    } else {
                        log("  \u2717 " + url + " - status: " + status);
                    }
                } else {
                    log("  \u2717 " + url + " - returned " + resp.statusCode());
                }
            } catch (java.net.http.HttpTimeoutException e) {
                log("  \u2717 " + url + " - timed out");
            } catch (java.net.ConnectException e) {
                log("  \u2717 " + url + " - connection failed");
            } catch (Exception e) {
                log("  \u2717 " + url + " - error: " + e.getMessage());
            }
        }
        return null;
    }


    // =========================================================================
    // Authentication
    // =========================================================================

    private static String loginToApi(String baseUrl) {
        log("Logging in as " + EMAIL + "...");

        try {
            String payload = "{\"email\":\"" + EMAIL + "\",\"password\":\"" + PASSWORD + "\"}";

            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/auth/login"))
                    .header("User-Agent", USER_AGENT)
                    .header("Content-Type", "application/json")
                    .timeout(Duration.ofSeconds(60))
                    .POST(HttpRequest.BodyPublishers.ofString(payload))
                    .build();

            HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());

            if (resp.statusCode() == 200) {
                String token = jsonString(resp.body(), "token");
                log("Login successful!");
                return token;
            } else if (resp.statusCode() == 401) {
                log("Login failed: Incorrect email or password.");
            } else {
                log("Login failed: Server returned " + resp.statusCode());
            }
        } catch (java.net.http.HttpTimeoutException e) {
            log("Login failed: Request timed out.");
        } catch (java.net.ConnectException e) {
            log("Login failed: Could not reach " + baseUrl);
        } catch (Exception e) {
            log("Login failed: " + e.getMessage());
        }
        return null;
    }


    // =========================================================================
    // File Download
    // =========================================================================

    private static boolean downloadFile(String fileJson, String saveDirectory,
                                         String baseUrl) {
        String uuidFilename = jsonString(fileJson, "uuid_filename");
        String cloudUrl = jsonString(fileJson, "cloud_share_link");
        String displayName = jsonString(fileJson, "display_name");
        if (displayName == null || displayName.isEmpty()) displayName = uuidFilename;

        String safeName = sanitizeFilename(displayName);
        Path fullSavePath = Paths.get(saveDirectory, safeName);

        // Skip if already downloaded
        if (Files.exists(fullSavePath)) return false;

        Path tempPath = Paths.get(saveDirectory, safeName + ".tmp");

        // Method 1: R2 Direct Link (PRIMARY)
        if (cloudUrl != null && !cloudUrl.isEmpty()) {
            log("  Downloading: " + safeName + " via R2...");
            try {
                HttpRequest req = HttpRequest.newBuilder()
                        .uri(URI.create(cloudUrl))
                        .timeout(Duration.ofMinutes(5))
                        .GET().build();

                HttpResponse<InputStream> resp = httpClient.send(req,
                        HttpResponse.BodyHandlers.ofInputStream());

                if (resp.statusCode() == 200) {
                    saveContent(resp, tempPath, fullSavePath);
                    long sizeMb = Files.size(fullSavePath) / (1024 * 1024);
                    log("  \u2713 Complete (R2) - " + sizeMb + " MB");
                    return true;
                } else {
                    log("  R2 returned " + resp.statusCode() + ", trying fallback...");
                }
            } catch (Exception e) {
                log("  R2 failed: " + e.getMessage() + ", trying fallback...");
                try { Files.deleteIfExists(tempPath); } catch (IOException ignored) {}
            }
        }

        // Method 2: API Server (FALLBACK)
        if (uuidFilename == null || uuidFilename.isEmpty()) {
            log("  \u2717 No download ID for " + safeName);
            return false;
        }

        log("  Downloading: " + safeName + " via API...");
        try {
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/download/" + uuidFilename))
                    .header("User-Agent", USER_AGENT)
                    .header("Authorization", "Bearer " + authToken)
                    .timeout(Duration.ofMinutes(10))
                    .GET().build();

            HttpResponse<InputStream> resp = httpClient.send(req,
                    HttpResponse.BodyHandlers.ofInputStream());

            if (resp.statusCode() == 200) {
                saveContent(resp, tempPath, fullSavePath);
                long sizeMb = Files.size(fullSavePath) / (1024 * 1024);
                log("  \u2713 Complete (API) - " + sizeMb + " MB");
                return true;
            } else {
                log("  \u2717 Failed: " + safeName + " - Status " + resp.statusCode());
            }
        } catch (Exception e) {
            log("  \u2717 Error: " + safeName + " - " + e.getMessage());
            try { Files.deleteIfExists(tempPath); } catch (IOException ignored) {}
        }
        return false;
    }


    private static void saveContent(HttpResponse<InputStream> resp,
                                     Path tempPath, Path finalPath) throws IOException {
        long totalSize = resp.headers().firstValueAsLong("content-length").orElse(0);
        long totalDownloaded = 0;
        long startTime = System.currentTimeMillis();
        byte[] buffer = new byte[1024 * 1024]; // 1 MB

        try (InputStream in = resp.body();
             OutputStream out = new BufferedOutputStream(new FileOutputStream(tempPath.toFile()))) {

            int bytesRead;
            while ((bytesRead = in.read(buffer)) != -1) {
                out.write(buffer, 0, bytesRead);
                totalDownloaded += bytesRead;

                long elapsed = System.currentTimeMillis() - startTime;
                if (elapsed > 0 && System.console() != null) {
                    double speedMbps = (totalDownloaded / (1024.0 * 1024.0)) / (elapsed / 1000.0);
                    if (totalSize > 0) {
                        double percent = (totalDownloaded / (double) totalSize) * 100;
                        System.out.printf("\r    Progress: %6.1f%% | Speed: %6.2f MB/s", percent, speedMbps);
                    } else {
                        System.out.printf("\r    Downloaded: %7.1f MB | Speed: %6.2f MB/s",
                                totalDownloaded / (1024.0 * 1024.0), speedMbps);
                    }
                }
            }
        }

        if (System.console() != null) System.out.println();

        Files.deleteIfExists(finalPath);
        Files.move(tempPath, finalPath);
    }


    // =========================================================================
    // Main
    // =========================================================================

    public static void main(String[] args) throws Exception {
        log("==================================================");
        log("DNFileVault Downloader v2.0 (Java)");
        log("==================================================");
        log("Output: " + OUTPUT_FOLDER);

        // Discover API endpoints
        List<String> endpoints = getApiEndpoints();

        // Find healthy server
        String baseUrl = findWorkingApi(endpoints);
        if (baseUrl == null) {
            log("ERROR: All API servers are unreachable!");
            log("Contact support@deltaneutral.com if this persists.");
            System.out.println("Press Enter to exit...");
            System.in.read();
            return;
        }
        log("Using API: " + baseUrl);

        // Login
        authToken = loginToApi(baseUrl);
        if (authToken == null) {
            log("Exiting due to login failure.");
            System.out.println("Press Enter to exit...");
            System.in.read();
            return;
        }

        ensureFolderExists(Paths.get(OUTPUT_FOLDER));
        int totalDownloaded = 0;

        // Download Purchases
        log("--- Checking Purchases ---");
        try {
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/purchases"))
                    .header("User-Agent", USER_AGENT)
                    .header("Authorization", "Bearer " + authToken)
                    .timeout(Duration.ofSeconds(60))
                    .GET().build();

            HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
            List<String> purchases = jsonArray(resp.body(), "purchases");

            if (purchases.isEmpty()) {
                log("No purchases found.");
            }

            for (String p : purchases) {
                String pid = jsonString(p, "id");
                if (pid == null) {
                    Integer pidInt = jsonInt(p, "id");
                    pid = pidInt != null ? pidInt.toString() : "unknown";
                }
                String productName = jsonString(p, "product_name");
                if (productName == null) productName = "Unknown";

                String folderName = sanitizeFilename(pid + " - " + productName);
                String productPath = Paths.get(OUTPUT_FOLDER, "Purchases", folderName).toString();
                ensureFolderExists(Paths.get(productPath));

                try {
                    HttpRequest filesReq = HttpRequest.newBuilder()
                            .uri(URI.create(baseUrl + "/purchases/" + pid + "/files"))
                            .header("User-Agent", USER_AGENT)
                            .header("Authorization", "Bearer " + authToken)
                            .timeout(Duration.ofSeconds(60))
                            .GET().build();

                    HttpResponse<String> filesResp = httpClient.send(filesReq,
                            HttpResponse.BodyHandlers.ofString());
                    List<String> files = jsonArray(filesResp.body(), "files");

                    if (DAYS_TO_CHECK != null && files.size() > DAYS_TO_CHECK) {
                        files = files.subList(0, DAYS_TO_CHECK);
                    }

                    for (String f : files) {
                        if (downloadFile(f, productPath, baseUrl)) totalDownloaded++;
                    }
                } catch (Exception e) {
                    log("Error getting files for purchase " + pid + ": " + e.getMessage());
                }
            }
        } catch (Exception e) {
            log("Error checking purchases: " + e.getMessage());
        }

        // Download Groups
        log("--- Checking Groups ---");
        try {
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/groups"))
                    .header("User-Agent", USER_AGENT)
                    .header("Authorization", "Bearer " + authToken)
                    .timeout(Duration.ofSeconds(60))
                    .GET().build();

            HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
            List<String> groups = jsonArray(resp.body(), "groups");

            if (groups.isEmpty()) {
                log("No groups found.");
            }

            for (String g : groups) {
                String gid = jsonString(g, "id");
                if (gid == null) {
                    Integer gidInt = jsonInt(g, "id");
                    gid = gidInt != null ? gidInt.toString() : "unknown";
                }
                String groupName = jsonString(g, "name");
                if (groupName == null) groupName = "Unknown";

                String folderName = sanitizeFilename(gid + " - " + groupName);
                String groupPath = Paths.get(OUTPUT_FOLDER, "Groups", folderName).toString();
                ensureFolderExists(Paths.get(groupPath));

                try {
                    HttpRequest filesReq = HttpRequest.newBuilder()
                            .uri(URI.create(baseUrl + "/groups/" + gid + "/files"))
                            .header("User-Agent", USER_AGENT)
                            .header("Authorization", "Bearer " + authToken)
                            .timeout(Duration.ofSeconds(60))
                            .GET().build();

                    HttpResponse<String> filesResp = httpClient.send(filesReq,
                            HttpResponse.BodyHandlers.ofString());
                    List<String> files = jsonArray(filesResp.body(), "files");

                    if (DAYS_TO_CHECK != null && files.size() > DAYS_TO_CHECK) {
                        files = files.subList(0, DAYS_TO_CHECK);
                    }

                    for (String f : files) {
                        if (downloadFile(f, groupPath, baseUrl)) totalDownloaded++;
                    }
                } catch (Exception e) {
                    log("Error getting files for group " + gid + ": " + e.getMessage());
                }
            }
        } catch (Exception e) {
            log("Error checking groups: " + e.getMessage());
        }

        log("All done! Downloaded " + totalDownloaded + " new file(s).");
        log("Files saved to: " + OUTPUT_FOLDER);
        System.out.println("Press Enter to exit...");
        System.in.read();
    }
}