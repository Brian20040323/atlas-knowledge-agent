$docx='c:\Users\czy2004\Desktop\openclaw_collab_gaps.docx'
$pdf='c:\Users\czy2004\Desktop\openclaw_collab_gaps.pdf'
$w=New-Object -ComObject Word.Application
$w.Visible=$false
$w.DisplayAlerts=0
$d=$w.Documents.Open($docx,$false,$true)
$d.ExportAsFixedFormat($pdf,17)
$d.Close($false)
$w.Quit()
