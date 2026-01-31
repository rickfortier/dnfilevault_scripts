using System;
using System.IO;
using System.Linq;

/// <summary>
/// Helper class to handle "Short Circuit" file logic.
/// Encourages using local files downloaded by the Python automation skip redundant FTP/API calls.
/// </summary>
public static class DNVFileLink
{
    // This should match the OUTPUT_FOLDER in the Python script
    private const string BaseDownloadPath = @"C:\dnfilevault-downloads";

    /// <summary>
    /// Gets the path to a file. If it exists in the automated download folder, returns that path.
    /// Otherwise, executes the fallback download logic.
    /// </summary>
    /// <param name="fileName">The name of the file (e.g., "data_2023_10_01.zip")</param>
    /// <param name="subFolder">Optional: The subfolder (e.g., "eodLevel3")</param>
    /// <param name="fallbackDownloadAction">A function to call if the file is missing</param>
    /// <returns>The path to the local file</returns>
    public static string GetLocalFile(string fileName, string subFolder, Action fallbackDownloadAction)
    {
        // 1. Check the automated download directory first
        // Note: The Python script organizes by "Groups/<ID> - <Name>"
        // We look for any directory ending with the group name.
        string searchDir = Path.Combine(BaseDownloadPath, "Groups");
        string targetPath = null;

        if (Directory.Exists(searchDir))
        {
            var groupDir = Directory.GetDirectories(searchDir)
                .FirstOrDefault(d => d.EndsWith(subFolder, StringComparison.OrdinalIgnoreCase) 
                                  || d.Contains("-" + subFolder));

            if (groupDir != null)
            {
                var possiblePath = Path.Combine(groupDir, fileName);
                if (File.Exists(possiblePath))
                {
                    targetPath = possiblePath;
                }
            }
        }

        // 2. Short Circuit: If found, return it and skip the fallback
        if (targetPath != null)
        {
            Console.WriteLine($"[DNV] Using existing file: {targetPath}");
            return targetPath;
        }

        // 3. Fallback: Run the project's original download logic
        Console.WriteLine($"[DNV] File {fileName} not found locally. Running fallback download...");
        fallbackDownloadAction();

        // After fallback, we assume it's in the project's default location
        return fileName; 
    }
}
