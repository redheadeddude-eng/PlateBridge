using System;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Drawing;
using System.Windows.Forms;
using System.Diagnostics;
using System.Threading.Tasks;
using System.Security.Cryptography;
using System.Text;
using System.Linq;

class Setup : Form {
    static readonly string AppRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "PlateBridge");
    static readonly string Menu = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "PlateBridge.lnk");
    readonly Label detail = new Label();
    readonly Button action = new Button();
    bool finished;
    string appDir;

    static string Extract(string root) {
        Directory.CreateDirectory(root);
        using (Stream payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("app.zip")) {
            string tag;
            using (var hash = SHA256.Create()) tag = BitConverter.ToString(hash.ComputeHash(payload)).Replace("-","").Substring(0,16);
            payload.Position=0;
            string dest=Path.Combine(root,"app-"+tag);
            string temp=Path.Combine(root,"stage-"+Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(temp);
            try {
                using (var zip=new ZipArchive(payload,ZipArchiveMode.Read)) {
                    foreach (var file in zip.Entries) {
                        string target=Path.GetFullPath(Path.Combine(temp,file.FullName));
                        if (!target.StartsWith(temp+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) throw new IOException("Invalid package.");
                        Directory.CreateDirectory(Path.GetDirectoryName(target));
                        file.ExtractToFile(target);
                    }
                }
                if (!Directory.Exists(dest)) Directory.Move(temp,dest);
                return dest;
            } finally { if(Directory.Exists(temp)) Directory.Delete(temp,true); }
        }
    }
    static string Install() {
        string dest=Extract(AppRoot);
        Directory.CreateDirectory(Path.GetDirectoryName(Menu));
        dynamic shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
        dynamic shortcut=shell.CreateShortcut(Menu);
        shortcut.TargetPath=Path.Combine(dest,"runtime","pythonw.exe");
        shortcut.Arguments="-I \""+Path.Combine(dest,"PlateBridge.py")+"\"";
        shortcut.WorkingDirectory=dest;
        shortcut.IconLocation=Path.Combine(dest,"PlateBridge.ico"); shortcut.Description="Prepare 3MF projects for Flash Studio";
        shortcut.Save();
        return dest;
    }
    Setup() {
        Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath); Text="PlateBridge Setup"; StartPosition=FormStartPosition.CenterScreen; FormBorderStyle=FormBorderStyle.FixedDialog;
        MaximizeBox=false; ClientSize=new Size(452,252); BackColor=Color.FromArgb(88,69,140);
        Font=new Font("Segoe UI",10); AutoScaleMode=AutoScaleMode.Dpi;
        var title=new Label{Text="PlateBridge",Font=new Font("Segoe UI",24,FontStyle.Bold|FontStyle.Italic),ForeColor=Color.White,Location=new Point(23,13),Size=new Size(400,50)};
        detail.Bounds=new Rectangle(25,74,402,90);detail.Padding=new Padding(14);detail.BackColor=Color.FromArgb(209,227,172);detail.ForeColor=Color.FromArgb(37,59,49);
        detail.Text="Install PlateBridge for this Windows account. Setup includes its runtime and adds a Start menu shortcut.";
        action.Text=File.Exists(Menu)?"Update PlateBridge":"Install PlateBridge";action.Bounds=new Rectangle(231,185,196,42);
        action.BackColor=Color.FromArgb(255,216,121);action.FlatStyle=FlatStyle.Flat;
        Controls.AddRange(new Control[]{title,detail,action}); AcceptButton=action;
        action.Click+=async delegate {
            try {
                if(finished) {Process.Start(Path.Combine(appDir,"runtime","pythonw.exe"),"-I \""+Path.Combine(appDir,"PlateBridge.py")+"\""); Close();return;}
                action.Enabled=false;detail.Text="Installing PlateBridge…";
                appDir=await Task.Run((Func<string>)Install);
                detail.Text="PlateBridge is installed. You can also find it in the Start menu.";finished=true;action.Text="Open PlateBridge";
            } catch(Exception error) {MessageBox.Show(error.Message,"PlateBridge Setup");}
            finally {action.Enabled=true;}
        };
    }
    [STAThread] static int Main(string[] args) {
        try {
            if(args.Length==2 && args[0]=="--stage"){Extract(Path.GetFullPath(args[1]));return 0;}
            if(args.Length==1 && args[0]=="--install"){Install();return 0;}
            Application.EnableVisualStyles();Application.Run(new Setup());return 0;
        } catch(Exception e) {if(args.Length==0)MessageBox.Show(e.Message,"PlateBridge Setup");return 1;}
    }
}

