using System;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

/// <summary>
/// The DNFileVault Manager provides a one-stop-shop for accessing files.
/// It automatically handles "Short Circuit" logic (checking local files first)
/// and falls back to API downloads if the file is missing.
/// </summary>
public class DNVManager : IDisposable
{
    private readonly HttpClient _http;
    private readonly string _localDownloadRoot;
    private string _token;

    /// <param name="baseUrl">The API base URL (e.g., https://api.dnfilevault.com)</param>
    /// <param name="localDownloadRoot">The root folder where the Python automation saves files (e.g., C:\dnfilevault-downloads)</param>
    public DNVManager(string baseUrl, string localDownloadRoot = @"C:\dnfilevault-downloads")
    {
        _localDownloadRoot = localDownloadRoot;
        _http = new HttpClient
        {
            BaseAddress = new Uri(baseUrl.TrimEnd('/') + "/"),
            Timeout = TimeSpan.FromMinutes(10)
        };
        _http.DefaultRequestHeaders.UserAgent.ParseAdd("DNFileVaultManager/1.0 (+support@deltaneutral.com)");
    }

    /// <summary>
    /// Ensures the file exists locally by checking the automated download folder first, 
    /// and then falling back to an API download if needed.
    /// </summary>
    /// <param name="fileName">The specific filename (e.g., "L2_20260114.zip")</param>
    /// <param name="groupName">The group folder to check (e.g., "eodLevel2")</param>
    /// <param name="email">Credentials for fallback download (only used if file is missing)</param>
    /// <param name="password">Credentials for fallback download (only used if file is missing)</param>
    /// <returns>The full path to the local file</returns>
    public async Task<string> GetFileAsync(string fileName, string groupName, string email = null, string password = null)
    {
        // 1. THE SHORT CIRCUIT
        // Search the automated download directory
        string searchDir = Path.Combine(_localDownloadRoot, "Groups");
        if (Directory.Exists(searchDir))
        {
            var groupDir = Directory.GetDirectories(searchDir)
                .FirstOrDefault(d => d.EndsWith(groupName, StringComparison.OrdinalIgnoreCase) 
                                  || d.Contains("-" + groupName));

            if (groupDir != null)
            {
                var localPath = Path.Combine(groupDir, fileName);
                if (File.Exists(localPath))
                {
                    Console.WriteLine($"[DNV] Short-circuit: Using existing file at {localPath}");
                    return localPath;
                }
            }
        }

        // 2. FALLBACK: API DOWNLOAD
        if (string.IsNullOrEmpty(email) || string.IsNullOrEmpty(password))
        {
            throw new FileNotFoundException($"File '{fileName}' not found locally, and no credentials provided for fallback download.");
        }

        Console.WriteLine($"[DNV] File '{fileName}' not found locally. Initiating API fallback...");
        
        await EnsureLoggedInAsync(email, password);

        // Find the group ID
        int? groupId = await FindGroupIdAsync(groupName);
        if (!groupId.HasValue) throw new Exception($"Group '{groupName}' not found or not accessible.");

        // Find the file UUID
        string uuid = await FindFileUuidAsync(groupId.Value, fileName);
        if (string.IsNullOrEmpty(uuid)) throw new Exception($"File '{fileName}' not found in group '{groupName}'.");

        // Download to a project-local 'Fallback' folder
        string fallbackDir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "DNV_Fallback");
        string outputPath = Path.Combine(fallbackDir, fileName);
        
        await DownloadFileAsync(uuid, outputPath);
        return outputPath;
    }

    private async Task EnsureLoggedInAsync(string email, string password)
    {
        if (!string.IsNullOrEmpty(_token)) return;

        var payload = new { email, password };
        var response = await _http.PostAsync("auth/login", new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json"));
        response.EnsureSuccessStatusCode();

        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        _token = doc.RootElement.GetProperty("token").GetString();
        _http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", _token);
    }

    private async Task<int?> FindGroupIdAsync(string groupName)
    {
        var response = await _http.GetAsync("groups");
        response.EnsureSuccessStatusCode();
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        
        foreach (var g in doc.RootElement.GetProperty("groups").EnumerateArray())
        {
            if (string.Equals(g.GetProperty("name").GetString(), groupName, StringComparison.OrdinalIgnoreCase))
                return g.GetProperty("id").GetInt32();
        }
        return null;
    }

    private async Task<string> FindFileUuidAsync(int groupId, string fileName)
    {
        var response = await _http.GetAsync($"groups/{groupId}/files");
        response.EnsureSuccessStatusCode();
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        
        foreach (var f in doc.RootElement.GetProperty("files").EnumerateArray())
        {
            string dname = f.GetProperty("display_name").GetString();
            if (string.Equals(dname, fileName, StringComparison.OrdinalIgnoreCase))
                return f.GetProperty("uuid_filename").GetString();
        }
        return null;
    }

    private async Task DownloadFileAsync(string uuid, string outputPath)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath));
        var tempPath = outputPath + ".part";

        using var response = await _http.GetAsync($"download/{uuid}", HttpCompletionOption.ResponseHeadersRead);
        response.EnsureSuccessStatusCode();

        using (var httpStream = await response.Content.ReadAsStreamAsync())
        using (var fileStream = new FileStream(tempPath, FileMode.Create, FileAccess.Write))
        {
            await httpStream.CopyToAsync(fileStream);
        }

        if (File.Exists(outputPath)) File.Delete(outputPath);
        File.Move(tempPath, outputPath);
    }

    public void Dispose() => _http?.Dispose();
}
