$docx = 'c:\Users\czy2004\Desktop\RAG_painpoints_solution_prompts.docx'
$pdf = 'c:\Users\czy2004\Desktop\RAG_painpoints_solution_prompts.pdf'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$d = $word.Documents.Open($docx, $false, $true)
$d.ExportAsFixedFormat($pdf, 17)
$d.Close($false)
$word.Quit()
