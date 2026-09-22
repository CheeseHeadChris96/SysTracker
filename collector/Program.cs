using System.IO;
using System.ServiceProcess;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;

namespace SysTracker;

public class CollectorService : ServiceBase
{
    private readonly CancellationTokenSource stop=new();
    private Task? work;
    public CollectorService(){ServiceName=Store.ServiceName;CanStop=true;}
    protected override void OnStart(string[] args){Store.Initialize();work=Task.Run(()=>Runner.Loop(stop.Token));}
    protected override void OnStop(){stop.Cancel();work?.Wait(TimeSpan.FromSeconds(20));}
}
public static class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
        if(args.Contains("--service")){ServiceBase.Run(new CollectorService());return;}
        Store.Initialize();
        if(args.Contains("--purge")) { Directory.Delete(Store.Root,true);return; }
        new Application().Run(new CollectorWindow());
    }
}
public class CollectorWindow : Window
{
    private Config config=Store.Config();
    private readonly TextBlock status=new(){TextWrapping=TextWrapping.Wrap,FontSize=15,Margin=new Thickness(0,12,0,12)};
    private readonly TextBlock update=new(){TextWrapping=TextWrapping.Wrap};
    private readonly DataGrid inventory=new(){IsReadOnly=true,AutoGenerateColumns=true,MinHeight=200};
    private readonly ListBox targets=new(){MinHeight=140,DisplayMemberPath="Address"};
    private readonly TextBox name=new();
    private readonly TextBox interval=new();
    private readonly Button install=new(){Content="Update now",Padding=new Thickness(14,8,14,8),Margin=new Thickness(0,15,0,0),IsEnabled=false};
    private readonly TextBlock result=new(){TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,12,0,0)};
    private readonly DispatcherTimer timer=new(){Interval=TimeSpan.FromSeconds(5)};
    public CollectorWindow()
    {
        Title="SysTracker Collector";Width=940;Height=710;MinWidth=720;MinHeight=580;FontFamily=new FontFamily("Segoe UI");FontSize=15;Background=new SolidColorBrush(Color.FromRgb(244,247,249));
        var dock=new DockPanel{Margin=new Thickness(28)};Content=dock;
        var title=new TextBlock{Text="SysTracker Collector",FontSize=27,FontWeight=FontWeights.SemiBold,Margin=new Thickness(0,0,0,18)};DockPanel.SetDock(title,Dock.Top);dock.Children.Add(title);
        var tabs=new TabControl();dock.Children.Add(tabs);
        var overview=Page(tabs,"Overview");overview.Children.Add(status);
        Button(overview,"Collect now",()=>{if(string.IsNullOrEmpty(config.Token))throw new InvalidOperationException("Enroll this collector first.");File.WriteAllText(Path.Combine(Store.Root,"collect.request"),"collect");MessageBox.Show("Collection requested. The service will pick it up within five minutes.");return Task.CompletedTask;});
        overview.Children.Add(new TextBlock{Text="Service runs in the background when this window is closed.",Margin=new Thickness(0,15,0,15)});
        Button(overview,"Start service",()=>{using var s=new ServiceController(Store.ServiceName);if(s.Status!=ServiceControllerStatus.Running)s.Start();return Task.CompletedTask;});
        var connections=Page(tabs,"Connections");connections.Children.Add(targets);
        Button(connections,"Add connection",()=>{EditTarget(null);return Task.CompletedTask;});
        Button(connections,"Edit selected",()=>{if(targets.SelectedItem is Target t)EditTarget(t);return Task.CompletedTask;});
        Button(connections,"Test selected connection",async()=>{if(targets.SelectedItem is not Target t)return;result.Text="Testing connection…";var records=await Connector.Query(t);result.Text=$"Connected. Read {records.Count} record(s).";inventory.ItemsSource=records;});
        Button(connections,"Remove selected",()=>{if(targets.SelectedItem is Target t&&MessageBox.Show("Remove this connection and its saved credentials?","Remove connection",MessageBoxButton.YesNo)==MessageBoxResult.Yes){config.Targets.Remove(t);Save();}return Task.CompletedTask;});connections.Children.Add(result);
        var inv=Page(tabs,"Inventory");inv.Children.Add(new TextBlock{Text="Last collected inventory (connection tests also preview here)",Margin=new Thickness(0,0,0,15)});inv.Children.Add(inventory);
        var settings=Page(tabs,"Enrollment & settings");Label(settings,"Reporting service");settings.Children.Add(new TextBlock{Text="https://ingest.hbstest.com"});Label(settings,"Collector name");name.Text=config.Name;settings.Children.Add(name);Label(settings,"Collection interval (hours, 1–168)");interval.Text=config.IntervalHours.ToString();settings.Children.Add(interval);
        Button(settings,"Save local settings",()=>{if(!int.TryParse(interval.Text,out int hours)||hours<1||hours>168)throw new InvalidOperationException("Enter an interval from 1 to 168 hours.");if(string.IsNullOrWhiteSpace(name.Text)||name.Text.Length>160)throw new InvalidOperationException("Enter a collector name.");config.IntervalHours=hours;config.Name=name.Text.Trim();Save();return Task.CompletedTask;});
        Label(settings,"One-time enrollment code");var code=new PasswordBox();settings.Children.Add(code);
        Button(settings,"Enroll collector",async()=>{if(!string.IsNullOrEmpty(config.Token))throw new InvalidOperationException("This installation is already enrolled. Uninstall and reinstall to change customer ownership.");config.Name=name.Text.Trim();if(config.Name.Length==0||config.Name.Length>160)throw new InvalidOperationException("Enter a collector name.");await Store.Enroll(config,code.Password.Trim());code.Clear();Refresh();});
        var updates=Page(tabs,"Updates");updates.Children.Add(update);Button(updates,"Check for updates",CheckUpdates);updates.Children.Add(install);
        install.Click+=async(_,_)=>{if(MessageBox.Show("Install the verified update? Collection will pause during installation.","Update collector",MessageBoxButton.YesNo)!=MessageBoxResult.Yes)return;install.IsEnabled=false;try{await Updater.Install();Close();}catch{MessageBox.Show("Update could not be verified or installed. The current installation remains in place.");install.IsEnabled=true;}};
        var diagnostics=Page(tabs,"Diagnostics");diagnostics.Children.Add(new TextBlock{Text="Credentials and reporting tokens are excluded from exported diagnostics. Review system names before sharing.",TextWrapping=TextWrapping.Wrap});
        Button(diagnostics,"Export diagnostics",()=>{var dialog=new Microsoft.Win32.SaveFileDialog{FileName="SysTracker-diagnostics.json",Filter="JSON|*.json"};if(dialog.ShowDialog()==true)File.WriteAllText(dialog.FileName,System.Text.Json.JsonSerializer.Serialize(new{version=Store.Version,status=Store.Status()},Store.Json));return Task.CompletedTask;});
        diagnostics.Children.Add(new TextBlock{Text="Uninstall through Windows Installed Apps. Then archive/revoke the collector in the dashboard and remove dedicated collection accounts if no longer used.",TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,20,0,0)});
        Refresh();timer.Tick+=(_,_)=>Refresh();timer.Start();Closed+=(_,_)=>timer.Stop();Loaded+=async(_,_)=>await CheckUpdates();
    }
    private static StackPanel Page(TabControl tabs,string label){var panel=new StackPanel{Margin=new Thickness(22)};tabs.Items.Add(new TabItem{Header=label,Content=new ScrollViewer{Content=panel,VerticalScrollBarVisibility=ScrollBarVisibility.Auto}});return panel;}
    private static void Label(Panel p,string text)=>p.Children.Add(new TextBlock{Text=text,Margin=new Thickness(0,14,0,6),FontWeight=FontWeights.SemiBold});
    private static void Button(Panel p,string label,Func<Task> action){var b=new Button{Content=label,HorizontalAlignment=HorizontalAlignment.Left,Padding=new Thickness(14,8,14,8),Margin=new Thickness(0,10,0,0)};p.Children.Add(b);b.Click+=async(_,_)=>{b.IsEnabled=false;try{await action();}catch(Exception ex){MessageBox.Show(ex is InvalidOperationException?ex.Message:"The operation failed. Check the local configuration and service status.","SysTracker");}finally{b.IsEnabled=true;}};}
    private void Save(){Store.Write("config.dat",config);Refresh();}
    private static string Date(long at)=>at==0?"Not yet":DateTimeOffset.FromUnixTimeSeconds(at).LocalDateTime.ToString("g");
    private void Refresh()
    {
        try{var s=Store.Status();string service;try{using var ctl=new ServiceController(Store.ServiceName);service=ctl.Status.ToString();}catch{service="Not installed";}
        status.Text=$"Customer: {config.Customer}\nCollector: {config.Name}\nService: {service}\nVersion: {Store.Version}\nLast collection: {Date(s.LastCollection)}\nLast upload: {Date(s.LastUpload)}\nQueued reports: {Directory.GetFiles(Path.Combine(Store.Root,"queue"),"*.dat").Length}\nExpired/overflow reports discarded: {s.DroppedReports}\n\n{s.Message}";
        var selected=(targets.SelectedItem as Target)?.Id;targets.ItemsSource=config.Targets.ToList();targets.SelectedItem=config.Targets.FirstOrDefault(t=>t.Id==selected);if(s.LastBatch is not null)inventory.ItemsSource=s.LastBatch.Devices;
        }catch{status.Text="Local state could not be read. Check permissions and the collector service.";}
    }
    private async Task CheckUpdates(){try{var r=await Updater.Check();update.Text=r is null?$"Installed: {Store.Version}\nYou are up to date.":$"Installed: {Store.Version}\nAvailable: {r.Version}\n\n{r.Notes}";install.IsEnabled=r is not null;}catch{update.Text=$"Installed: {Store.Version}\nThe update service is unavailable or a trusted release has not been configured. No update will be installed.";install.IsEnabled=false;}}
    private void EditTarget(Target? current)
    {
        var window=new Window{Title=current is null?"Add connection":"Edit connection",Owner=this,Width=540,Height=650,WindowStartupLocation=WindowStartupLocation.CenterOwner,FontSize=15};
        var p=new StackPanel{Margin=new Thickness(25)};window.Content=new ScrollViewer{Content=p};
        Label(p,"Product");var kind=new ComboBox{ItemsSource=new[]{"Windows","Hyper-V","VMware","Veeam","Palo Alto"},SelectedItem=current?.Kind??"Windows"};p.Children.Add(kind);
        Label(p,"Management hostname or IP (no URL)");var address=new TextBox{Text=current?.Address??""};p.Children.Add(address);
        Label(p,"Username (DOMAIN\\user for Windows)");var username=new TextBox{Text=current?.Username??""};p.Children.Add(username);
        Label(p,current is null?"Password":"Password (leave empty to keep existing)");var password=new PasswordBox();p.Children.Add(password);
        var https=new CheckBox{Content="Windows: use WinRM HTTPS (5986)",IsChecked=current?.WinRmHttps??true,Margin=new Thickness(0,15,0,10)};p.Children.Add(https);
        Label(p,"Veeam API revision (match the installed server)");var revision=new TextBox{Text=current?.ApiVersion??"1.2-rev1"};p.Children.Add(revision);
        p.Children.Add(new TextBlock{Text="VMware and Palo Alto use HTTPS 443. Veeam uses HTTPS 9419. Certificates must be trusted by this server. Credentials stay local.",TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,15,0,0)});
        Button(p,"Save connection",()=>{string host=address.Text.Trim();if(Uri.CheckHostName(host)==UriHostNameType.Unknown||host.Length>160)throw new InvalidOperationException("Enter a hostname or IP address without a URL or port.");if(string.IsNullOrWhiteSpace(username.Text))throw new InvalidOperationException("Enter a username.");string secret=password.Password.Length>0?password.Password:current?.Password??"";if(secret.Length==0)throw new InvalidOperationException("Enter a password.");
        if(current is not null)config.Targets.Remove(current);config.Targets.Add(new Target(current?.Id??Guid.NewGuid().ToString(),(string)kind.SelectedItem,host,username.Text,secret,https.IsChecked==true,revision.Text));Save();window.Close();return Task.CompletedTask;});window.ShowDialog();
    }
}
