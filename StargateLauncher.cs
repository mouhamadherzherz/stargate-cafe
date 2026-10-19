using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

class Program
{
    [STAThread]
    static void Main()
    {
        string targetUrl = "http://192.168.10.27:5000";
        string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string profileDir = Path.Combine(localAppData, "StargateCafePOSProfile");

        string progFilesX86 = Environment.GetEnvironmentVariable("ProgramFiles(x86)") ?? @"C:\Program Files (x86)";
        string progFiles = Environment.GetEnvironmentVariable("ProgramFiles") ?? @"C:\Program Files";

        string[] browserPaths = new string[]
        {
            Path.Combine(progFilesX86, @"Microsoft\Edge\Application\msedge.exe"),
            Path.Combine(progFiles, @"Microsoft\Edge\Application\msedge.exe"),
            Path.Combine(localAppData, @"Microsoft\Edge\Application\msedge.exe"),
            Path.Combine(progFiles, @"Google\Chrome\Application\chrome.exe"),
            Path.Combine(progFilesX86, @"Google\Chrome\Application\chrome.exe"),
            Path.Combine(localAppData, @"Google\Chrome\Application\chrome.exe")
        };

        string browserExe = null;
        foreach (var path in browserPaths)
        {
            if (File.Exists(path))
            {
                browserExe = path;
                break;
            }
        }

        try
        {
            if (browserExe != null)
            {
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = browserExe;
                psi.Arguments = string.Format("--user-data-dir=\"{0}\" --app=\"{1}\" --window-size=1360,880 --no-first-run", profileDir, targetUrl);
                psi.UseShellExecute = false;
                Process.Start(psi);
            }
            else
            {
                Process.Start(new ProcessStartInfo(targetUrl) { UseShellExecute = true });
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show("تعذر فتح البرنامج: " + ex.Message + "\nيرجى التأكد من اتصال الشبكة بالسيرفر 192.168.10.27", "STARGATE CAFE", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
