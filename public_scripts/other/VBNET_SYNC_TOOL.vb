' ==============================================================================
' DNFileVault Downloader for VB.NET (.NET 6+)
' ==============================================================================
' This console application downloads ALL files from your DNFileVault account:
'   1. All Purchases
'   2. All Groups
'
' It automatically discovers available API servers and fails over
' to the next one if the primary is down.
'
' SETUP:
' 1. Create a new VB.NET Console App:
'        dotnet new console -lang VB -n DNFileVaultDownloader
' 2. Add Newtonsoft.Json:
'        dotnet add package Newtonsoft.Json
' 3. Replace Program.vb with this file
' 4. Run:
'        dotnet run
'
' CONFIGURATION:
'    Edit the constants below, or set environment variables:
'        set DNFV_EMAIL=your_email@example.com
'        set DNFV_PASSWORD=your_password
'        set DNFV_OUT_DIR=C:\dnfilevault-downloads
' ==============================================================================

Imports System
Imports System.IO
Imports System.Net.Http
Imports System.Net.Http.Headers
Imports System.Text
Imports System.Text.RegularExpressions
Imports Newtonsoft.Json
Imports Newtonsoft.Json.Linq

Module Program

    ' ==========================================================================
    ' CONFIGURATION
    ' ==========================================================================

    Private ReadOnly EMAIL As String =
        If(Environment.GetEnvironmentVariable("DNFV_EMAIL"), "your_email@example.com")

    Private ReadOnly PASSWORD As String =
        If(Environment.GetEnvironmentVariable("DNFV_PASSWORD"), "your_password")

    Private ReadOnly OUTPUT_FOLDER As String =
        If(Environment.GetEnvironmentVariable("DNFV_OUT_DIR"), "C:\dnfilevault-downloads")

    ' Set to a number (e.g., 1) to only download the newest N files per group.
    ' Set to Nothing to download EVERYTHING.
    Private ReadOnly DAYS_TO_CHECK As Integer? = Nothing

    ' ==========================================================================

    Private Const DISCOVERY_URL As String = "https://config.dnfilevault.com/endpoints.json"
    Private Const USER_AGENT As String = "DNFileVaultClient/1.0-VBNet (+support@deltaneutral.com)"

    Private ReadOnly FALLBACK_ENDPOINTS As String() = {
        "https://api.dnfilevault.com",
        "https://api-redmint.dnfilevault.com"
    }

    Private _httpClient As HttpClient


    ' --------------------------------------------------------------------------
    ' Logging
    ' --------------------------------------------------------------------------

    Private Sub Log(msg As String)
        Dim timestamp As String = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")
        Console.WriteLine($"[{timestamp}] {msg}")
    End Sub


    ' --------------------------------------------------------------------------
    ' Discovery & Failover
    ' --------------------------------------------------------------------------

    Private Async Function GetApiEndpoints() As Task(Of List(Of String))
        Log("Discovering API endpoints...")

        Try
            Dim response = Await _httpClient.GetAsync(DISCOVERY_URL)
            If response.IsSuccessStatusCode Then
                Dim json = Await response.Content.ReadAsStringAsync()
                Dim data = JObject.Parse(json)
                Dim endpoints = data("endpoints").
                    OrderBy(Function(e) CInt(e("priority"))).
                    ToList()

                Dim version = data("version")?.ToString()
                Dim updated = data("updated")?.ToString()
                Log($"  Found {endpoints.Count} endpoints (config v{version}, updated {updated})")

                Dim urls As New List(Of String)
                For Each ep In endpoints
                    Dim url = ep("url").ToString()
                    Dim label = ep("label")?.ToString()
                    Dim priority = ep("priority")?.ToString()
                    Log($"    {priority}. {url} ({label})")
                    urls.Add(url)
                Next
                Return urls
            Else
                Log($"  Discovery returned status {CInt(response.StatusCode)}, using fallback list.")
            End If
        Catch ex As Exception
            Log($"  Discovery unavailable ({ex.Message}), using fallback list.")
        End Try

        Log($"  Using {FALLBACK_ENDPOINTS.Length} fallback endpoints.")
        Return FALLBACK_ENDPOINTS.ToList()
    End Function


    Private Async Function FindWorkingApi(endpoints As List(Of String)) As Task(Of String)
        Log("Finding a healthy API server...")

        For Each url In endpoints
            Try
                Using cts As New Threading.CancellationTokenSource(TimeSpan.FromSeconds(10))
                    Dim response = Await _httpClient.GetAsync($"{url}/health", cts.Token)
                    If response.IsSuccessStatusCode Then
                        Dim json = Await response.Content.ReadAsStringAsync()
                        Dim data = JObject.Parse(json)
                        Dim status = data("status")?.ToString()
                        If status = "healthy" Then
                            Log($"  ✓ {url} - healthy")
                            Return url
                        Else
                            Log($"  ✗ {url} - status: {status}")
                        End If
                    Else
                        Log($"  ✗ {url} - returned {CInt(response.StatusCode)}")
                    End If
                End Using
            Catch ex As TaskCanceledException
                Log($"  ✗ {url} - timed out")
            Catch ex As HttpRequestException
                Log($"  ✗ {url} - connection failed")
            Catch ex As Exception
                Log($"  ✗ {url} - error: {ex.Message}")
            End Try
        Next

        Return Nothing
    End Function


    ' --------------------------------------------------------------------------
    ' Authentication
    ' --------------------------------------------------------------------------

    Private Async Function LoginToApi(baseUrl As String) As Task(Of String)
        Log($"Logging in as {EMAIL}...")

        Try
            Dim payload As New JObject From {
                {"email", EMAIL},
                {"password", PASSWORD}
            }
            Dim content As New StringContent(payload.ToString(), Encoding.UTF8, "application/json")
            Dim response = Await _httpClient.PostAsync($"{baseUrl}/auth/login", content)

            If response.IsSuccessStatusCode Then
                Dim json = Await response.Content.ReadAsStringAsync()
                Dim data = JObject.Parse(json)
                Dim token = data("token")?.ToString()
                Log("Login successful!")
                Return token
            ElseIf CInt(response.StatusCode) = 401 Then
                Log("Login failed: Incorrect email or password.")
            Else
                Log($"Login failed: Server returned {CInt(response.StatusCode)}")
            End If
        Catch ex As HttpRequestException
            Log($"Login failed: Could not reach {baseUrl}")
        Catch ex As TaskCanceledException
            Log("Login failed: Request timed out.")
        Catch ex As Exception
            Log($"Login failed: {ex.Message}")
        End Try

        Return Nothing
    End Function


    ' --------------------------------------------------------------------------
    ' File Download
    ' --------------------------------------------------------------------------

    Private Function SanitizeFilename(name As String) As String
        If String.IsNullOrWhiteSpace(name) Then Return "unnamed_file"
        Dim clean = Regex.Replace(name, "[<>:""/\\|?*]", "_")
        clean = clean.Trim()
        Return If(String.IsNullOrEmpty(clean), "unnamed_file", clean)
    End Function


    Private Sub EnsureFolderExists(folderPath As String)
        If Not Directory.Exists(folderPath) Then
            Directory.CreateDirectory(folderPath)
            Log($"Created folder: {folderPath}")
        End If
    End Sub


    Private Async Function DownloadFile(fileInfo As JObject, saveDirectory As String,
                                         baseUrl As String, token As String) As Task(Of Boolean)
        Dim uuidFilename = fileInfo("uuid_filename")?.ToString()
        Dim cloudUrl = fileInfo("cloud_share_link")?.ToString()
        Dim displayName = fileInfo("display_name")?.ToString()
        If String.IsNullOrEmpty(displayName) Then displayName = uuidFilename

        Dim safeName = SanitizeFilename(displayName)
        Dim fullSavePath = Path.Combine(saveDirectory, safeName)

        ' Skip if already downloaded
        If File.Exists(fullSavePath) Then Return False

        Dim tempPath = fullSavePath & ".tmp"

        ' Method 1: R2 Direct Link (PRIMARY)
        If Not String.IsNullOrEmpty(cloudUrl) Then
            Log($"  Downloading: {safeName} via R2...")
            Try
                Using response = Await _httpClient.GetAsync(cloudUrl, HttpCompletionOption.ResponseHeadersRead)
                    If response.IsSuccessStatusCode Then
                        Await SaveContent(response, tempPath, fullSavePath)
                        Dim sizeMb = Math.Round(New FileInfo(fullSavePath).Length / (1024.0 * 1024.0), 1)
                        Log($"  ✓ Complete (R2) - {sizeMb} MB")
                        Return True
                    Else
                        Log($"  R2 returned {CInt(response.StatusCode)}, trying fallback...")
                    End If
                End Using
            Catch ex As Exception
                Log($"  R2 failed: {ex.Message}, trying fallback...")
                If File.Exists(tempPath) Then File.Delete(tempPath)
            End Try
        End If

        ' Method 2: API Server (FALLBACK)
        If String.IsNullOrEmpty(uuidFilename) Then
            Log($"  ✗ No download ID for {safeName}")
            Return False
        End If

        Log($"  Downloading: {safeName} via API...")
        Try
            Dim request As New HttpRequestMessage(HttpMethod.Get, $"{baseUrl}/download/{uuidFilename}")
            request.Headers.Authorization = New AuthenticationHeaderValue("Bearer", token)

            Using response = Await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead)
                If response.IsSuccessStatusCode Then
                    Await SaveContent(response, tempPath, fullSavePath)
                    Dim sizeMb = Math.Round(New FileInfo(fullSavePath).Length / (1024.0 * 1024.0), 1)
                    Log($"  ✓ Complete (API) - {sizeMb} MB")
                    Return True
                Else
                    Log($"  ✗ Failed: {safeName} - Status {CInt(response.StatusCode)}")
                End If
            End Using
        Catch ex As Exception
            Log($"  ✗ Error: {safeName} - {ex.Message}")
            If File.Exists(tempPath) Then File.Delete(tempPath)
        End Try

        Return False
    End Function


    Private Async Function SaveContent(response As HttpResponseMessage,
                                        tempPath As String, finalPath As String) As Task
        Dim totalSize = response.Content.Headers.ContentLength
        Dim totalDownloaded As Long = 0
        Dim startTime = DateTime.Now
        Dim buffer(1024 * 1024 - 1) As Byte  ' 1 MB buffer

        Using stream = Await response.Content.ReadAsStreamAsync()
            Using fileStream As New FileStream(tempPath, FileMode.Create, FileAccess.Write, FileShare.None,
                                                buffer.Length, True)
                Dim bytesRead As Integer
                Do
                    bytesRead = Await stream.ReadAsync(buffer, 0, buffer.Length)
                    If bytesRead > 0 Then
                        Await fileStream.WriteAsync(buffer, 0, bytesRead)
                        totalDownloaded += bytesRead

                        Dim elapsed = (DateTime.Now - startTime).TotalSeconds
                        If elapsed > 0 AndAlso Console.IsOutputRedirected = False Then
                            Dim speedMbps = (totalDownloaded / (1024.0 * 1024.0)) / elapsed
                            If totalSize.HasValue AndAlso totalSize.Value > 0 Then
                                Dim percent = (totalDownloaded / CDbl(totalSize.Value)) * 100
                                Console.Write($"{vbCr}    Progress: {percent:F1}% | Speed: {speedMbps:F2} MB/s")
                            Else
                                Console.Write($"{vbCr}    Downloaded: {totalDownloaded / (1024.0 * 1024.0):F1} MB | Speed: {speedMbps:F2} MB/s")
                            End If
                        End If
                    End If
                Loop While bytesRead > 0
            End Using
        End Using

        If Not Console.IsOutputRedirected Then Console.WriteLine()

        If File.Exists(finalPath) Then File.Delete(finalPath)
        File.Move(tempPath, finalPath)
    End Function


    ' --------------------------------------------------------------------------
    ' Main
    ' --------------------------------------------------------------------------

    Async Function Main() As Task
        Log(New String("="c, 50))
        Log("DNFileVault Downloader v2.0 (VB.NET)")
        Log(New String("="c, 50))
        Log($"Output: {OUTPUT_FOLDER}")

        ' Set up HttpClient with custom User-Agent
        Dim handler As New HttpClientHandler()
        _httpClient = New HttpClient(handler)
        _httpClient.DefaultRequestHeaders.UserAgent.ParseAdd(USER_AGENT)
        _httpClient.Timeout = TimeSpan.FromMinutes(10)

        ' Discover API endpoints
        Dim endpoints = Await GetApiEndpoints()

        ' Find healthy server
        Dim baseUrl = Await FindWorkingApi(endpoints)
        If baseUrl Is Nothing Then
            Log("ERROR: All API servers are unreachable!")
            Log("Contact support@deltaneutral.com if this persists.")
            Console.WriteLine("Press Enter to exit...")
            Console.ReadLine()
            Return
        End If

        Log($"Using API: {baseUrl}")

        ' Login
        Dim token = Await LoginToApi(baseUrl)
        If token Is Nothing Then
            Log("Exiting due to login failure.")
            Console.WriteLine("Press Enter to exit...")
            Console.ReadLine()
            Return
        End If

        _httpClient.DefaultRequestHeaders.Authorization =
            New AuthenticationHeaderValue("Bearer", token)

        EnsureFolderExists(OUTPUT_FOLDER)
        Dim totalDownloaded As Integer = 0

        ' Download Purchases
        Log("--- Checking Purchases ---")
        Try
            Dim resp = Await _httpClient.GetStringAsync($"{baseUrl}/purchases")
            Dim data = JObject.Parse(resp)
            Dim purchases = CType(data("purchases"), JArray)

            If purchases Is Nothing OrElse purchases.Count = 0 Then
                Log("No purchases found.")
            Else
                For Each p As JObject In purchases
                    Dim pid = p("id")?.ToString()
                    Dim productName = If(p("product_name")?.ToString(), "Unknown")
                    Dim folderName = SanitizeFilename($"{pid} - {productName}")
                    Dim productPath = Path.Combine(OUTPUT_FOLDER, "Purchases", folderName)
                    EnsureFolderExists(productPath)

                    Try
                        Dim filesResp = Await _httpClient.GetStringAsync($"{baseUrl}/purchases/{pid}/files")
                        Dim filesData = JObject.Parse(filesResp)
                        Dim files = CType(filesData("files"), JArray)

                        If files IsNot Nothing AndAlso files.Count > 0 Then
                            Dim filesToDownload = If(DAYS_TO_CHECK.HasValue,
                                files.Take(DAYS_TO_CHECK.Value),
                                files.AsEnumerable())

                            For Each f As JObject In filesToDownload
                                Dim result = Await DownloadFile(f, productPath, baseUrl, token)
                                If result Then totalDownloaded += 1
                            Next
                        End If
                    Catch ex As Exception
                        Log($"Error getting files for purchase {pid}: {ex.Message}")
                    End Try
                Next
            End If
        Catch ex As Exception
            Log($"Error checking purchases: {ex.Message}")
        End Try

        ' Download Groups
        Log("--- Checking Groups ---")
        Try
            Dim resp = Await _httpClient.GetStringAsync($"{baseUrl}/groups")
            Dim data = JObject.Parse(resp)
            Dim groups = CType(data("groups"), JArray)

            If groups Is Nothing OrElse groups.Count = 0 Then
                Log("No groups found.")
            Else
                For Each g As JObject In groups
                    Dim gid = g("id")?.ToString()
                    Dim groupName = If(g("name")?.ToString(), "Unknown")
                    Dim folderName = SanitizeFilename($"{gid} - {groupName}")
                    Dim groupPath = Path.Combine(OUTPUT_FOLDER, "Groups", folderName)
                    EnsureFolderExists(groupPath)

                    Try
                        Dim filesResp = Await _httpClient.GetStringAsync($"{baseUrl}/groups/{gid}/files")
                        Dim filesData = JObject.Parse(filesResp)
                        Dim files = CType(filesData("files"), JArray)

                        If files IsNot Nothing AndAlso files.Count > 0 Then
                            Dim filesToDownload = If(DAYS_TO_CHECK.HasValue,
                                files.Take(DAYS_TO_CHECK.Value),
                                files.AsEnumerable())

                            For Each f As JObject In filesToDownload
                                Dim result = Await DownloadFile(f, groupPath, baseUrl, token)
                                If result Then totalDownloaded += 1
                            Next
                        End If
                    Catch ex As Exception
                        Log($"Error getting files for group {gid}: {ex.Message}")
                    End Try
                Next
            End If
        Catch ex As Exception
            Log($"Error checking groups: {ex.Message}")
        End Try

        Log($"All done! Downloaded {totalDownloaded} new file(s).")
        Log($"Files saved to: {OUTPUT_FOLDER}")
        Console.WriteLine("Press Enter to exit...")
        Console.ReadLine()
    End Function

End Module