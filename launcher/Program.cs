using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

namespace QuietFocusLauncher
{
    internal static class Program
    {
        private const string BundleVersion = "1.0.2";
        private const string PayloadResource = "payload.zip";

        [STAThread]
        private static void Main()
        {
            Application.EnableVisualStyles();
            try
            {
                string exePath = EnsureBundle();
                StartApp(exePath);
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    "静界启动失败：\r\n" + ex.Message +
                    "\r\n\r\n如果系统提示 SmartScreen，请选择“更多信息 → 仍要运行”。\r\n" +
                    "也可以改用便携版压缩包。",
                    "静界 QuietFocus",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
            }
        }

        private static string EnsureBundle()
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(
                Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            string parent = baseDir;
            string target = Path.Combine(parent, "QuietFocus");
            string targetExe = Path.Combine(target, "QuietFocus.exe");
            string marker = Path.Combine(target, "version.txt");

            if (IsCurrent(targetExe, marker))
            {
                return targetExe;
            }

            bool alreadyExists = File.Exists(targetExe);
            if (!IsWritable(baseDir))
            {
                parent = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "QuietFocus",
                    "app");
                target = Path.Combine(parent, "QuietFocus");
                targetExe = Path.Combine(target, "QuietFocus.exe");
                marker = Path.Combine(target, "version.txt");
                alreadyExists = File.Exists(targetExe);
            }

            Form splash = null;
            try
            {
                if (!IsCurrent(targetExe, marker))
                {
                    splash = ShowSplash();
                    Directory.CreateDirectory(parent);
                    ExtractPayload(parent);
                    File.WriteAllText(marker, BundleVersion, Encoding.ASCII);
                }
            }
            catch
            {
                // If an older bundle is already present, prefer starting it over
                // failing completely (for example when the running app locks the
                // files during an in-place upgrade).
                if (!alreadyExists)
                {
                    throw;
                }
            }
            finally
            {
                if (splash != null)
                {
                    splash.Close();
                    splash.Dispose();
                }
            }

            if (!File.Exists(targetExe))
            {
                throw new FileNotFoundException("运行时文件缺失", targetExe);
            }
            return targetExe;
        }

        private static bool IsCurrent(string targetExe, string marker)
        {
            if (!File.Exists(targetExe) || !File.Exists(marker))
            {
                return false;
            }
            try
            {
                return File.ReadAllText(marker).Trim() == BundleVersion;
            }
            catch
            {
                return false;
            }
        }

        private static bool IsWritable(string directory)
        {
            try
            {
                string probe = Path.Combine(
                    directory, ".qf_write_" + Guid.NewGuid().ToString("N"));
                using (File.Create(probe))
                {
                }
                File.Delete(probe);
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static void ExtractPayload(string parent)
        {
            Assembly assembly = Assembly.GetExecutingAssembly();
            using (Stream stream = assembly.GetManifestResourceStream(PayloadResource))
            {
                if (stream == null)
                {
                    throw new InvalidOperationException("内置运行包缺失");
                }
                using (ZipArchive archive = new ZipArchive(stream, ZipArchiveMode.Read))
                {
                    string root = Path.GetFullPath(parent)
                        .TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
                    foreach (ZipArchiveEntry entry in archive.Entries)
                    {
                        string relative = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                        string destination = Path.GetFullPath(Path.Combine(parent, relative));
                        if (!destination.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                        {
                            throw new InvalidDataException("运行包路径无效");
                        }
                        if (string.IsNullOrEmpty(entry.Name))
                        {
                            Directory.CreateDirectory(destination);
                        }
                        else
                        {
                            string directory = Path.GetDirectoryName(destination);
                            if (!string.IsNullOrEmpty(directory))
                            {
                                Directory.CreateDirectory(directory);
                            }
                            entry.ExtractToFile(destination, true);
                        }
                    }
                }
            }
        }

        private static Form ShowSplash()
        {
            Form form = new Form();
            form.Text = "静界 QuietFocus";
            form.FormBorderStyle = FormBorderStyle.FixedDialog;
            form.StartPosition = FormStartPosition.CenterScreen;
            form.MinimizeBox = false;
            form.MaximizeBox = false;
            form.ControlBox = false;
            form.TopMost = true;
            form.ClientSize = new Size(360, 96);
            form.BackColor = Color.White;
            Label label = new Label();
            label.Text = "正在准备静界，请稍候…";
            label.Dock = DockStyle.Fill;
            label.TextAlign = ContentAlignment.MiddleCenter;
            label.Font = new Font("Microsoft YaHei UI", 10F);
            form.Controls.Add(label);
            form.Show();
            form.Refresh();
            return form;
        }

        private static void StartApp(string exePath)
        {
            StringBuilder arguments = new StringBuilder();
            string[] commandLine = Environment.GetCommandLineArgs();
            for (int i = 1; i < commandLine.Length; i++)
            {
                if (arguments.Length > 0)
                {
                    arguments.Append(' ');
                }
                string value = commandLine[i];
                if (value.IndexOf(' ') >= 0 || value.IndexOf('\t') >= 0)
                {
                    arguments.Append('"').Append(value.Replace("\"", "\\\"")).Append('"');
                }
                else
                {
                    arguments.Append(value);
                }
            }

            ProcessStartInfo info = new ProcessStartInfo(exePath);
            info.Arguments = arguments.ToString();
            info.WorkingDirectory = Path.GetDirectoryName(exePath);
            // Launch the already-extracted runtime directly. This bypasses a
            // second SmartScreen/shell prompt for the inner executable.
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            Process.Start(info);
        }
    }
}
