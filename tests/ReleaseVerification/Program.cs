using System.Security.Cryptography;
using System.Text.Json;
using SysTracker;
using var key=RSA.Create(3072);
var options=new JsonSerializerOptions{PropertyNamingPolicy=JsonNamingPolicy.SnakeCaseLower};
byte[] Payload(string url="https://updates.hbstest.com/SysTracker-0.2.0.msi",string version="0.2.0")=>JsonSerializer.SerializeToUtf8Bytes(new Release(version,url,new string('a',64),"Test release"),options);
byte[] Sign(byte[] b)=>key.SignData(b,HashAlgorithmName.SHA256,RSASignaturePadding.Pss);
void Reject(Action a){try{a();}catch(Exception ex) when(ex is CryptographicException or InvalidDataException){return;}throw new Exception("Unsafe manifest accepted");}
var bytes=Payload();var signature=Sign(bytes);var pub=key.ExportSubjectPublicKeyInfoPem();
if(ReleaseVerifier.Verify(bytes,signature,pub,"0.1.0")?.Version!="0.2.0")throw new Exception("Valid release rejected");
var tampered=Payload(version:"9.0.0");Reject(()=>ReleaseVerifier.Verify(tampered,signature,pub,"0.1.0"));
var other=Payload("https://other.example/update.msi");Reject(()=>ReleaseVerifier.Verify(other,Sign(other),pub,"0.1.0"));
var http=Payload("http://updates.hbstest.com/update.msi");Reject(()=>ReleaseVerifier.Verify(http,Sign(http),pub,"0.1.0"));
var downgrade=Payload(version:"0.0.9");if(ReleaseVerifier.Verify(downgrade,Sign(downgrade),pub,"0.1.0") is not null)throw new Exception("Downgrade accepted");
Console.WriteLine("5 release security checks passed: valid signature, tampering, foreign host, HTTP, downgrade.");
