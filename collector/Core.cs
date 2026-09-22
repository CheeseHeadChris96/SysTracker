using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Reflection;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;

namespace SysTracker;

public record Target(string Id, string Kind, string Address, string Username, string Password, bool WinRmHttps = true, string ApiVersion = "1.2-rev1");
public class Config
{
    public string Endpoint { get; set; } = "https://ingest.hbstest.com";
    public string Name { get; set; } = Environment.MachineName;
    public string Customer { get; set; } = "Not enrolled";
    public string Token { get; set; } = "";
    public string CollectorId { get; set; } = "";
    public int IntervalHours { get; set; } = 24;
    public List<Target> Targets { get; set; } = [];
}
public record InventoryItem(string Identity, string Product, string Name, string Version, string Target = "");
public record CollectionFailure(string Target, string Category);
public class Batch
{
    public string BatchId { get; set; } = Guid.NewGuid().ToString();
    public long CollectedAt { get; set; } = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
    public string Version { get; set; } = Store.Version;
    public string UpdateVersion { get; set; } = "";
    public List<InventoryItem> Devices { get; set; } = [];
    public List<CollectionFailure> Failures { get; set; } = [];
}
public class Status
{
    public long LastCollection { get; set; }
    public long LastUpload { get; set; }
    public long LastUpdateCheck { get; set; }
    public string UpdateVersion { get; set; } = "";
    public string UpdateState { get; set; } = "Not checked";
    public string Message { get; set; } = "Ready to configure";
    public int DroppedReports { get; set; }
    public Batch? LastBatch { get; set; }
}
public static class Store
{
    public const string ServiceName = "SysTrackerCollector";
    public static readonly string Version = Assembly.GetExecutingAssembly().GetName().Version!.ToString(3);
    public static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower, PropertyNameCaseInsensitive = true, WriteIndented = true };
    public static readonly string Root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "SysTracker");
    public static void Initialize()
    {
        Directory.CreateDirectory(Root);
        var acl = new DirectorySecurity(); acl.SetAccessRuleProtection(true, false);
        foreach (var sid in new[] { WellKnownSidType.LocalSystemSid, WellKnownSidType.BuiltinAdministratorsSid })
            acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(sid, null), FileSystemRights.FullControl, InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
        new DirectoryInfo(Root).SetAccessControl(acl);
        Directory.CreateDirectory(Path.Combine(Root, "queue"));
    }
    public static T Read<T>(string filename, T fallback)
    {
        string path=Path.Combine(Root, filename);
        if (!File.Exists(path)) return fallback;
        var raw=ProtectedData.Unprotect(File.ReadAllBytes(path), null, DataProtectionScope.LocalMachine);
        return JsonSerializer.Deserialize<T>(raw, Json) ?? throw new InvalidDataException("Invalid local configuration.");
    }
    public static void Write<T>(string filename,T value)
    {
        string path=Path.Combine(Root, filename), temp=path+"."+Guid.NewGuid()+".tmp";
        File.WriteAllBytes(temp,ProtectedData.Protect(JsonSerializer.SerializeToUtf8Bytes(value, Json),null,DataProtectionScope.LocalMachine));
        File.Move(temp,path,true);
    }
    public static Config Config() => Read("config.dat",new Config());
    public static Status Status() => Read("status.dat",new Status());
    public static HttpClient Http()
    {
        // Never follow redirects carrying enrollment credentials or reporting tokens.
        return new HttpClient(new HttpClientHandler { AllowAutoRedirect=false }) { Timeout=TimeSpan.FromSeconds(60), MaxResponseContentBufferSize=2*1024*1024 };
    }
    public static Uri ReportingUri(Config config,string path)
    {
        var uri=new Uri(config.Endpoint);
        if (uri.Scheme!="https" || uri.Host!="ingest.hbstest.com" || !uri.IsDefaultPort || uri.AbsolutePath!="/" || uri.UserInfo!="" || uri.Query!="" || uri.Fragment!="")
            throw new InvalidOperationException("The reporting address must be https://ingest.hbstest.com.");
        return new Uri(uri,path);
    }
    public static async Task Enroll(Config config,string code)
    {
        using var http=Http();
        using var result=await http.PostAsJsonAsync(ReportingUri(config,"/ingest/enroll"),new { code, name=config.Name });
        if (!result.IsSuccessStatusCode) throw new InvalidOperationException("Enrollment failed. Check the code, service availability, and HTTPS certificate.");
        var body=await result.Content.ReadFromJsonAsync<JsonElement>();
        config.Token=body.GetProperty("token").GetString()!; config.CollectorId=body.GetProperty("collector_id").GetString()!;
        config.Customer=body.GetProperty("customer_name").GetString()!; Write("config.dat",config);
    }
}
public static class Connector
{
    public static async Task<List<InventoryItem>> Query(Target target,CancellationToken ct=default)
    {
        if (target.Address.Length>160 || target.Address.Length==0) throw new InvalidOperationException("Invalid address.");
        string ps=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell","v1.0","powershell.exe");
        var start=new ProcessStartInfo(ps) { UseShellExecute=false, CreateNoWindow=true, RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true };
        foreach (var arg in new[]{"-NoLogo","-NoProfile","-NonInteractive","-File",Path.Combine(AppContext.BaseDirectory,"Connectors.ps1")}) start.ArgumentList.Add(arg);
        using var process=Process.Start(start) ?? throw new InvalidOperationException("PowerShell could not start.");
        using var timeout=CancellationTokenSource.CreateLinkedTokenSource(ct);timeout.CancelAfter(TimeSpan.FromMinutes(3));
        var output=process.StandardOutput.ReadToEndAsync(timeout.Token);var errors=process.StandardError.ReadToEndAsync(timeout.Token);
        try
        {
            await process.StandardInput.WriteAsync(JsonSerializer.Serialize(target,Store.Json));process.StandardInput.Close();
            await process.WaitForExitAsync(timeout.Token);var json=await output;await errors;
            if(process.ExitCode!=0) throw new InvalidOperationException(process.ExitCode switch { 2=>"authentication",3=>"permissions",4=>"unreachable",5=>"unsupported",_=>"query_failed" });
            return JsonSerializer.Deserialize<List<InventoryItem>>(json,Store.Json) ?? [];
        }
        catch(OperationCanceledException) { if(!process.HasExited)process.Kill(true);throw new InvalidOperationException("unreachable"); }
    }
}
public static class Runner
{
    public static async Task Collect(Config config,Status status,CancellationToken ct)
    {
        var batch=new Batch { UpdateVersion=status.UpdateVersion };
        foreach(var target in config.Targets)
        {
            ct.ThrowIfCancellationRequested();
            try { batch.Devices.AddRange(await Connector.Query(target,ct)); }
            catch(Exception ex) when(ex is not OperationCanceledException)
            {
                string category=new[]{"authentication","permissions","unreachable","unsupported"}.Contains(ex.Message)?ex.Message:"query_failed";
                batch.Failures.Add(new(target.Address,category));
            }
        }
        status.LastCollection=batch.CollectedAt;status.LastBatch=batch;
        Store.Write(Path.Combine("queue",batch.BatchId+".dat"),batch);
        status.Message=$"Collected {batch.Devices.Count} records; {batch.Failures.Count} connections need attention.";
        Store.Write("status.dat",status);
    }
    public static async Task Upload(Config config,Status status,CancellationToken ct)
    {
        if(string.IsNullOrEmpty(config.Token))return;
        var files=new DirectoryInfo(Path.Combine(Store.Root,"queue")).GetFiles("*.dat").OrderBy(f=>f.CreationTimeUtc).ToList();
        foreach(var f in files.Where(f=>f.CreationTimeUtc<DateTime.UtcNow.AddDays(-7)).ToList()) { f.Delete();files.Remove(f);status.DroppedReports++; }
        while(files.Count>168 || files.Sum(f=>f.Length)>50*1024*1024) { files[0].Delete();files.RemoveAt(0);status.DroppedReports++; }
        using var http=Store.Http();http.DefaultRequestHeaders.Authorization=new AuthenticationHeaderValue("Bearer",config.Token);
        foreach(var f in files)
        {
            var batch=Store.Read<Batch>(Path.Combine("queue",f.Name),new Batch());
            using var result=await http.PostAsJsonAsync(Store.ReportingUri(config,"/ingest/inventory"),batch,Store.Json,ct);
            if(!result.IsSuccessStatusCode) { status.Message=$"Upload failed (HTTP {(int)result.StatusCode}). Inventory remains queued. Check enrollment or reporting service.";break; }
            var ack=await result.Content.ReadFromJsonAsync<JsonElement>(ct);
            if(!ack.TryGetProperty("accepted",out var accepted)||accepted.ValueKind!=JsonValueKind.True)throw new InvalidDataException("Invalid acknowledgement.");
            f.Delete();status.LastUpload=DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        }
        Store.Write("status.dat",status);
    }
    public static async Task Loop(CancellationToken ct)
    {
        while(!ct.IsCancellationRequested)
        {
            var status=Store.Status();
            try
            {
                var config=Store.Config();long now=DateTimeOffset.UtcNow.ToUnixTimeSeconds();
                if(now-status.LastUpdateCheck>=86400)
                {
                    try { var release=await Updater.Check();status.UpdateVersion=release?.Version??"";status.UpdateState=release is null?"Up to date":"Update available in local GUI"; }
                    catch { status.UpdateState="Update service unavailable or release verification failed"; }
                    status.LastUpdateCheck=now;Store.Write("status.dat",status);
                }
                if(!string.IsNullOrEmpty(config.Token)&&config.Targets.Count>0 && (now-status.LastCollection>=Math.Clamp(config.IntervalHours,1,168)*3600 || File.Exists(Path.Combine(Store.Root,"collect.request"))))
                {
                    File.Delete(Path.Combine(Store.Root,"collect.request"));await Collect(config,status,ct);
                }
                await Upload(config,status,ct);
            }
            catch(OperationCanceledException) when(ct.IsCancellationRequested){break;}
            catch { status.Message="Collection or upload failed. Check local connections and service availability.";Store.Write("status.dat",status); }
            try { await Task.Delay(TimeSpan.FromMinutes(5),ct); } catch(OperationCanceledException){break;}
        }
    }
}
public static class Updater
{
    const string Origin="https://updates.hbstest.com/";
    public static async Task<Release?> Check()
    {
        using var http=Store.Http();
        var bytes=await http.GetByteArrayAsync(Origin+"stable.json");
        var signature=await http.GetByteArrayAsync(Origin+"stable.sig");
        using var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("SysTracker.Collector.update-public-key.pem")??throw new InvalidDataException("Release key missing.");
        using var reader=new StreamReader(stream);
        return ReleaseVerifier.Verify(bytes,signature,await reader.ReadToEndAsync(),Store.Version);
    }
    // Only called by the GUI after the engineer clicks Update now and confirms.
    public static async Task Install()
    {
        var release=await Check()??throw new InvalidOperationException("No update available.");
        using var http=Store.Http();using var response=await http.GetAsync(release.Url,HttpCompletionOption.ResponseHeadersRead);response.EnsureSuccessStatusCode();
        string filename=Path.Combine(Store.Root,"update.msi");
        await using(var file=File.Create(filename))
        {
            await using var input=await response.Content.ReadAsStreamAsync();var buffer=new byte[65536];long total=0;int count;
            while((count=await input.ReadAsync(buffer))>0){total+=count;if(total>300*1024*1024)throw new InvalidDataException("Update exceeds size limit.");await file.WriteAsync(buffer.AsMemory(0,count));}
        }
        await using(var file=File.OpenRead(filename))
        {
            var hash=Convert.ToHexString(await SHA256.HashDataAsync(file));
            if(!hash.Equals(release.Sha256,StringComparison.OrdinalIgnoreCase)){File.Delete(filename);throw new CryptographicException("Update hash mismatch.");}
        }
        var start=new ProcessStartInfo("msiexec.exe") { UseShellExecute=true,Verb="runas" };
        start.Arguments=$"/i \"{filename}\"";Process.Start(start);
    }
}
