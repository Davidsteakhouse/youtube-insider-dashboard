Option Explicit

Dim shell, fso, rootDir, pythonExe, serverScript, serverUrl, healthUrl
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

rootDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonExe = "C:\Users\DanKim\anaconda3\python.exe"
serverScript = rootDir & "\scripts\serve_dashboard.py"
serverUrl = "http://127.0.0.1:8000"
healthUrl = serverUrl & "/api/health"

Function FileExists(path)
  FileExists = fso.FileExists(path)
End Function

Function ServerReady(url)
  On Error Resume Next
  Dim http
  Set http = CreateObject("MSXML2.XMLHTTP")
  http.Open "GET", url, False
  http.Send
  ServerReady = (Err.Number = 0 And http.Status = 200)
  Err.Clear
  On Error GoTo 0
End Function

If Not FileExists(pythonExe) Then
  MsgBox "python.exe를 찾을 수 없습니다: " & pythonExe, vbCritical, "대시보드 실행 실패"
  WScript.Quit 1
End If

If Not FileExists(serverScript) Then
  MsgBox "serve_dashboard.py를 찾을 수 없습니다: " & serverScript, vbCritical, "대시보드 실행 실패"
  WScript.Quit 1
End If

If Not ServerReady(healthUrl) Then
  shell.Run """" & pythonExe & """ """ & serverScript & """", 1, False

  Dim retries
  retries = 0
  Do While retries < 30
    If ServerReady(healthUrl) Then Exit Do
    WScript.Sleep 500
    retries = retries + 1
  Loop
End If

If Not ServerReady(healthUrl) Then
  MsgBox "대시보드 서버를 시작했지만 응답을 받지 못했습니다.", vbCritical, "대시보드 실행 실패"
  WScript.Quit 1
End If

shell.Run serverUrl, 1, False
