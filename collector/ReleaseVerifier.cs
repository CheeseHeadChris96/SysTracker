using System.Security.Cryptography;
using System.IO;
using System.Text.Json;

namespace SysTracker;
public record Release(string Version,string Url,string Sha256,string Notes);
public static class ReleaseVerifier
{
    public static Release? Verify(byte[] bytes,byte[] signature,string publicKey,string installed)
    {
        if(bytes.Length>65536)throw new InvalidDataException("Manifest too large.");
        using var key=RSA.Create();key.ImportFromPem(publicKey);
        if(!key.VerifyData(bytes,signature,HashAlgorithmName.SHA256,RSASignaturePadding.Pss))throw new CryptographicException("Invalid release signature.");
        var options=new JsonSerializerOptions{PropertyNamingPolicy=JsonNamingPolicy.SnakeCaseLower};
        var release=JsonSerializer.Deserialize<Release>(bytes,options)??throw new InvalidDataException();
        if(!System.Version.TryParse(release.Version,out var remote)||remote<=System.Version.Parse(installed))return null;
        var uri=new Uri(release.Url);
        if(uri.Scheme!="https"||uri.Host!="updates.hbstest.com"||!uri.IsDefaultPort||uri.UserInfo!=""||uri.Query!=""||uri.Fragment!=""||!uri.AbsolutePath.EndsWith(".msi",StringComparison.OrdinalIgnoreCase))throw new InvalidDataException("Unexpected update address.");
        if(release.Sha256.Length!=64||!release.Sha256.All(Uri.IsHexDigit))throw new InvalidDataException("Invalid update hash.");
        return release;
    }
}
