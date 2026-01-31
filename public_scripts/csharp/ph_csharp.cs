using System;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

/// <summary>
/// A professional API Client for DNFileVault.
/// Follows best practices from the Customer Download Code Cookbook.
/// </summary>
public class DnFileVaultClient : IDisposable
{
    private readonly HttpClient _http;
    private readonly JsonSerializerOptions _jsonOpts;

    public DnFileVaultClient(string baseUrl)
    {
        _http = new HttpClient
        {
            BaseAddress = new Uri(baseUrl.TrimEnd('/') + "/"),
            // Large ZIP files need longer timeouts
            Timeout = TimeSpan.FromMinutes(10)
        };

        // Custom User-Agent prevents API throttling/slowdown
        _http.DefaultRequestHeaders.UserAgent.ParseAdd("DNFileVaultClient/1.2 (C#; +support@deltaneutral.com)");

        _jsonOpts = new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true
        };
    }

    /// <summary>
    /// Authenticates with the API using Email/Password and sets the Bearer token.
    /// </summary>
    public async Task<string> LoginAsync(string email, string password)
    {
        var payload = new { email, password };
        var json = JsonSerializer.Serialize(payload);
        var content = new StringContent(json, Encoding.UTF8, "application/json");

        var response = await _http.PostAsync("auth/login", content);
        response.EnsureSuccessStatusCode();

        var responseJson = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(responseJson);
        var token = doc.RootElement.GetProperty("token").GetString();

        if (string.IsNullOrEmpty(token))
            throw new Exception("Login succeeded but no token was returned.");

        // Apply token to all future requests
        _http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);

        return token;
    }

    /// <summary>
    /// Downloads a file by its UUID filename.
    /// Uses streaming to disk to handle large files efficiently.
    /// </summary>
    public async Task DownloadFileAsync(string uuidFilename, string outputPath)
    {
        var directory = Path.GetDirectoryName(outputPath);
        if (!string.IsNullOrEmpty(directory))
            Directory.CreateDirectory(directory);

        // Download to a temporary file first so we don't end up with corrupt files if the app crashes
        var tempPath = outputPath + ".part";

        using var response = await _http.GetAsync($"download/{uuidFilename}", HttpCompletionOption.ResponseHeadersRead);
        response.EnsureSuccessStatusCode();

        using (var httpStream = await response.Content.ReadAsStreamAsync())
        using (var fileStream = new FileStream(tempPath, FileMode.Create, FileAccess.Write, FileShare.None))
        {
            await httpStream.CopyToAsync(fileStream);
        }

        // Move the completed file to the final destination
        if (File.Exists(outputPath)) 
            File.Delete(outputPath);
            
        File.Move(tempPath, outputPath);
    }

    public async Task<JsonElement> GetPurchasesAsync()
    {
        var response = await _http.GetAsync("purchases");
        response.EnsureSuccessStatusCode();
        return JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement;
    }

    public async Task<JsonElement> GetPurchaseFilesAsync(int purchaseId)
    {
        var response = await _http.GetAsync($"purchases/{purchaseId}/files");
        response.EnsureSuccessStatusCode();
        return JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement;
    }

    public async Task<JsonElement> GetGroupsAsync()
    {
        var response = await _http.GetAsync("groups");
        response.EnsureSuccessStatusCode();
        return JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement;
    }

    public async Task<JsonElement> GetGroupFilesAsync(int groupId)
    {
        var response = await _http.GetAsync($"groups/{groupId}/files");
        response.EnsureSuccessStatusCode();
        return JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement;
    }

    public void Dispose()
    {
        _http?.Dispose();
    }
}
