Imports System
Imports System.IO
Imports System.Net
Imports System.Net.Http
Imports System.Net.Http.Headers
Imports System.Text
Imports System.Threading.Tasks
Imports System.Collections.Generic
Imports System.Web.Script.Serialization ' Requires Reference to System.Web.Extensions

''' <summary>
''' DNFileVault Automated Download Sync Tool (.NET Framework Compatible)
''' -------------------------------------------------------------------
''' This version is designed for .NET Framework 4.7.2 / 4.8.
''' It uses JavaScriptSerializer (System.Web.Extensions) for ZERO external dependencies.
''' </summary>
Module Program
    ' --- CONFIGURATION ---
    Private Const BaseUrl As String = "https://api.dnfilevault.com"
    Private Const GroupName As String = "eodLevel2"
    ' Use a proper Windows path, avoiding ~/ web paths
    Private ReadOnly OutputDirectory As String = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads", "DNFileVault")

    Sub Main()
        ' Ensure TLS 1.2 is enabled (Critical for .NET Framework 4.x)
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12 Or SecurityProtocolType.Tls11 Or SecurityProtocolType.Tls

        Dim email As String = Environment.GetEnvironmentVariable("DNFV_EMAIL")
        Dim password As String = Environment.GetEnvironmentVariable("DNFV_PASSWORD")

        ' Fallback for testing if env vars aren't set
        If String.IsNullOrEmpty(email) Then email = "your@email.com"
        If String.IsNullOrEmpty(password) Then password = "your_password"

        Console.WriteLine($"Starting DNFileVault Sync for {GroupName}...")
        Console.WriteLine($"Saving to: {OutputDirectory}")

        Try
            Task.Run(Async Function() Await SyncLoop(email, password)).Wait()
        Catch ex As Exception
            Console.WriteLine("FATAL ERROR: " & ex.InnerException?.Message)
        End Try

        Console.WriteLine("Done. Press any key to exit.")
        Console.ReadKey()
    End Sub

    Async Function SyncLoop(email As String, password As String) As Task
        Directory.CreateDirectory(OutputDirectory)

        Using client As New HttpClient()
            client.Timeout = TimeSpan.FromMinutes(10)
            client.DefaultRequestHeaders.UserAgent.ParseAdd("DNFileVaultVBSync/1.0")

            ' 1. LOGIN
            Console.WriteLine("Logging in...")
            Dim loginData As String = String.Format("{{""email"":""{0}"",""password"":""{1}""}}", email, password)
            Dim content As New StringContent(loginData, Encoding.UTF8, "application/json")
            
            Dim response = Await client.PostAsync(BaseUrl & "/auth/login", content)
            If Not response.IsSuccessStatusCode Then
                Throw New Exception("Login failed. Check email/password.")
            End If

            Dim jsonResponse = Await response.Content.ReadAsStringAsync()
            Dim serializer As New JavaScriptSerializer()
            Dim loginResult = serializer.Deserialize(Of Dictionary(Of String, Object))(jsonResponse)
            Dim token = loginResult("token").ToString()

            client.DefaultRequestHeaders.Authorization = New AuthenticationHeaderValue("Bearer", token)

            ' 2. FIND GROUP ID
            Console.WriteLine("Locating group...")
            Dim groupsJson = Await client.GetStringAsync(BaseUrl & "/groups")
            Dim groupsResult = serializer.Deserialize(Of Dictionary(Of String, Object))(groupsJson)
            Dim groupsList = DirectCast(groupsResult("groups"), Array)

            Dim groupId As Integer = -1
            For Each g As Dictionary(Of String, Object) In groupsList
                If String.Equals(g("name").ToString(), GroupName, StringComparison.OrdinalIgnoreCase) Then
                    groupId = CInt(g("id"))
                    Exit For
                End If
            Next

            If groupId = -1 Then
                Console.WriteLine($"Error: Group '{GroupName}' not found.")
                Return
            End If

            ' 3. GET FILES
            Console.WriteLine("Fetching file list...")
            Dim filesJson = Await client.GetStringAsync(BaseUrl & "/groups/" & groupId & "/files")
            Dim filesResult = serializer.Deserialize(Of Dictionary(Of String, Object))(filesJson)
            Dim filesList = DirectCast(filesResult("files"), Array)

            ' 4. DOWNLOAD
            For Each f As Dictionary(Of String, Object) In filesList
                Dim uuid = f("uuid_filename").ToString()
                Dim displayName = f("display_name").ToString()
                Dim fileSize = Convert.ToInt64(f("file_size"))
                Dim localPath = Path.Combine(OutputDirectory, displayName)

                ' Smart Sync: Skip if exists and size matches
                If File.Exists(localPath) Then
                    Dim fi As New FileInfo(localPath)
                    If fi.Length = fileSize Then
                        Console.WriteLine("- Skipping " & displayName & " (Up to date)")
                        Continue For
                    End If
                End If

                Console.WriteLine("- Downloading " & displayName & "...")
                Await DownloadFile(client, uuid, localPath)
            Next

        End Using
    End Function

    Async Function DownloadFile(client As HttpClient, uuid As String, outPath As String) As Task
        Dim tempPath = outPath & ".part"
        
        Using response = Await client.GetAsync(BaseUrl & "/download/" & uuid, HttpCompletionOption.ResponseHeadersRead)
            response.EnsureSuccessStatusCode()
            Using stream = Await response.Content.ReadAsStreamAsync()
                Using fs = New FileStream(tempPath, FileMode.Create, FileAccess.Write, FileShare.None)
                    Await stream.CopyToAsync(fs)
                End Using
            End Using
        End Using

        If File.Exists(outPath) Then File.Delete(outPath)
        File.Move(tempPath, outPath)
    End Function
End Module
