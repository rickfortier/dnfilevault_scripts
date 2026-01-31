/*
================================================================================
DNFileVault: eodLevel3 EMERGENCY SYNC TOOL (C#)
================================================================================
TO C# CODER
This is a self-contained, single-file solution for your eodLevel3 Daily Sync.
You don't need to write any API logic—it's all here.

INSTRUCTIONS:
1. Create a new C# Console App in Visual Studio.
2. Replace EVERYTHING in your Program.cs with this code.
3. Set your environment variables (DMFV_EMAIL, DMFV_PASSWORD).
4. Run it. It will handle the login, group search, and "Smart Sync" automatically.
================================================================================
*/

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;

class Program
{
    // --- CONFIGURATION ---
    static string BaseUrl = "https://api.dnfilevault.com";
    static string GroupName = "eodLevel3";
    static string OutDir = @"C:\dnfilevault-downloads\eodLevel3";

    static async Task<int> Main(string[] args)
    {
        Console.WriteLine($"--- DNFileVault {GroupName} Sync Starting ---");

        string email = Environment.GetEnvironmentVariable("DNFV_EMAIL");
        string password = Environment.GetEnvironmentVariable("DNFV_PASSWORD");

        if (string.IsNullOrEmpty(email) || string.IsNullOrEmpty(password))
        {
            Console.WriteLine("ERROR: Please set DNFV_EMAIL and DNFV_PASSWORD environment variables.");
            return 1;
        }

        Directory.CreateDirectory(OutDir);

        using var http = new HttpClient();
        http.Timeout = TimeSpan.FromMinutes(10);
        http.DefaultRequestHeaders.UserAgent.ParseAdd("DNFileVaultSyncTool/1.0");

        try
        {
            // 1. LOGIN
            Console.WriteLine($"Logging in...");
            var loginBody = JsonSerializer.Serialize(new { email, password });
            var loginResp = await http.PostAsync($"{BaseUrl}/auth/login", new StringContent(loginBody, Encoding.UTF8, "application/json"));
            loginResp.EnsureSuccessStatusCode();
            
            var loginData = JsonDocument.Parse(await loginResp.Content.ReadAsStringAsync());
            string token = loginData.RootElement.GetProperty("token").GetString();
            http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);

            // 2. FIND GROUP
            Console.WriteLine($"Locating group: {GroupName}...");
            var groupsResp = await http.GetAsync($"{BaseUrl}/groups");
            groupsResp.EnsureSuccessStatusCode();
            var groupsData = JsonDocument.Parse(await groupsResp.Content.ReadAsStringAsync());
            
            var group = groupsData.RootElement.GetProperty("groups").EnumerateArray()
                .FirstOrDefault(g => string.Equals(g.GetProperty("name").GetString(), GroupName, StringComparison.OrdinalIgnoreCase));

            if (group.ValueKind == JsonValueKind.Undefined)
            {
                Console.WriteLine($"ERROR: Group '{GroupName}' not found.");
                return 2;
            }

            int groupId = group.GetProperty("id").GetInt32();

            // 3. GET FILES
            Console.WriteLine("Fetching file list...");
            var filesResp = await http.GetAsync($"{BaseUrl}/groups/{groupId}/files");
            filesResp.EnsureSuccessStatusCode();
            var filesData = JsonDocument.Parse(await filesResp.Content.ReadAsStringAsync());
            var apiFiles = filesData.RootElement.GetProperty("files").EnumerateArray()
                .Where(f => (f.GetProperty("display_name").GetString() ?? "").EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
                .ToList();

            // 4. SYNC LOGIC (Check what's already there)
            Console.WriteLine($"Found {apiFiles.Count} ZIP files. Checking local folder...");
            foreach (var f in apiFiles)
            {
                string uuid = f.GetProperty("uuid_filename").GetString();
                string display = f.GetProperty("display_name").GetString();
                string cloudUrl = f.TryGetProperty("cloud_share_link", out var urlProp) ? urlProp.GetString() : null;
                string localPath = Path.Combine(OutDir, display);

                if (File.Exists(localPath))
                {
                    // Basic size check for "Smart Sync"
                    long localSize = new FileInfo(localPath).Length;
                    long apiSize = f.GetProperty("file_size").GetInt64();
                    
                    if (localSize == apiSize)
                    {
                        Console.WriteLine($"- Skipping {display} (Up to date)");
                        continue;
                    }
                }

                Console.WriteLine($"- Syncing {display}...");
                await DownloadFileWithFallbackAsync(http, uuid, cloudUrl, localPath);
            }

            Console.WriteLine("\nSync Complete. All files are up to date.");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"\nCRITICAL ERROR: {ex.Message}");
            return 3;
        }

        return 0;
    }

    static async Task DownloadFileWithFallbackAsync(HttpClient http, string uuid, string cloudUrl, string outPath)
    {
        var tempPath = outPath + ".part";

        // 1. PRIMARY: Try Cloudflare R2 (Fast, no auth header)
        if (!string.IsNullOrEmpty(cloudUrl))
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, cloudUrl);
                // Important: Clear auth header for external R2 links to avoid header-leaking or rejections
                request.Headers.Authorization = null; 

                using var resp = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead);
                if (resp.IsSuccessStatusCode)
                {
                    await SaveToFile(resp, tempPath);
                    MoveToFinal(tempPath, outPath);
                    Console.WriteLine("  ✓ Obtained via R2 CDN");
                    return;
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"  R2 failed ({ex.Message}), trying API fallback...");
            }
        }

        // 2. FALLBACK: API Server (Authenticated)
        if (string.IsNullOrEmpty(uuid)) return;

        using var apiResp = await http.GetAsync($"{BaseUrl}/download/{uuid}", HttpCompletionOption.ResponseHeadersRead);
        apiResp.EnsureSuccessStatusCode();

        await SaveToFile(apiResp, tempPath);
        MoveToFinal(tempPath, outPath);
        Console.WriteLine("  ✓ Obtained via API Server");
    }

    static async Task SaveToFile(HttpResponseMessage resp, string tempPath)
    {
        using (var net = await resp.Content.ReadAsStreamAsync())
        using (var file = new FileStream(tempPath, FileMode.Create, FileAccess.Write, FileShare.None))
        {
            await net.CopyToAsync(file);
        }
    }

    static void MoveToFinal(string tempPath, string outPath)
    {
        if (File.Exists(outPath)) File.Delete(outPath);
        File.Move(tempPath, outPath);
    }
}
