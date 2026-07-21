$docx = 'c:\Users\czy2004\Desktop\RAG面试追问问题清单.docx'
$pdf = 'c:\Users\czy2004\Desktop\RAG面试追问问题清单.pdf'
$app = New-Object -ComObject Word.Application
$app.Visible = $false
$d = $app.Documents.Open($docx)
$d.SaveAs([ref]$pdf, [ref]17)
$d.Close()
$app.Quit()
