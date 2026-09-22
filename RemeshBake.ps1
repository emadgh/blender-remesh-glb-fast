Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Windows.Forms

$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" Title="GLB Remesh + Bake" Height="730" Width="850" MinHeight="650" MinWidth="720" WindowStartupLocation="CenterScreen" Background="#F5F5F4" FontFamily="Segoe UI">
  <Grid Margin="22">
    <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="220"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="*"/></Grid.RowDefinitions>
    <StackPanel Grid.Row="0" Margin="0,0,0,14">
      <TextBlock Text="GLB Remesh + Bake" FontSize="25" FontWeight="SemiBold" Foreground="#171717"/>
      <TextBlock Text="فایل‌های GLB را اینجا رها کنید، تنظیمات را انتخاب کنید و شروع را بزنید." FontSize="13" Foreground="#555" Margin="0,5,0,0" FlowDirection="RightToLeft" HorizontalAlignment="Left"/>
    </StackPanel>
    <Border Grid.Row="1" BorderBrush="#B5B5B0" BorderThickness="1" CornerRadius="8" Background="White" AllowDrop="True" Name="DropArea">
      <DockPanel Margin="12">
        <StackPanel DockPanel.Dock="Top" Orientation="Horizontal" Margin="0,0,0,10">
          <Button Name="AddFiles" Content="+ Add GLB files" Padding="13,7" Margin="0,0,8,0"/>
          <Button Name="RemoveFiles" Content="Remove selected" Padding="13,7" Margin="0,0,8,0"/>
          <Button Name="ClearFiles" Content="Clear" Padding="13,7"/>
        </StackPanel>
        <ListBox Name="FilesList" AllowDrop="True" BorderThickness="0" Background="Transparent" FontSize="13"/>
      </DockPanel>
    </Border>
    <Grid Grid.Row="2" Margin="0,17,0,12">
      <Grid.ColumnDefinitions><ColumnDefinition Width="100"/><ColumnDefinition Width="*"/><ColumnDefinition Width="100"/></Grid.ColumnDefinitions>
      <TextBlock Text="Output folder" VerticalAlignment="Center"/>
      <TextBox Name="OutputPath" Grid.Column="1" Height="28" VerticalContentAlignment="Center"/>
      <Button Name="BrowseOutput" Grid.Column="2" Content="Browse..." Margin="8,0,0,0"/>
    </Grid>
    <Grid Grid.Row="3" Margin="0,0,0,15">
      <Grid.ColumnDefinitions><ColumnDefinition Width="100"/><ColumnDefinition Width="*"/><ColumnDefinition Width="100"/></Grid.ColumnDefinitions>
      <TextBlock Text="Blender.exe" VerticalAlignment="Center"/>
      <TextBox Name="BlenderPath" Grid.Column="1" Height="28" VerticalContentAlignment="Center"/>
      <Button Name="BrowseBlender" Grid.Column="2" Content="Browse..." Margin="8,0,0,0"/>
    </Grid>
    <StackPanel Grid.Row="4" Margin="0,0,0,12">
      <WrapPanel>
        <StackPanel Width="145" Margin="0,0,12,8"><TextBlock Text="Texture size"/><ComboBox Name="TextureSize" SelectedIndex="1"><ComboBoxItem Content="512"/><ComboBoxItem Content="1024"/><ComboBoxItem Content="2048"/><ComboBoxItem Content="4096"/></ComboBox></StackPanel>
        <StackPanel Width="145" Margin="0,0,12,8"><TextBlock Text="Voxel size (%)"/><TextBox Name="VoxelSize" Text="0.5"/></StackPanel>
        <StackPanel Width="145" Margin="0,0,12,8"><TextBlock Text="Decimate (%)"/><TextBox Name="Decimate" Text="100"/></StackPanel>
        <StackPanel Width="145" Margin="0,0,12,8"><TextBlock Text="Cage extrusion (%)"/><TextBox Name="Cage" Text="2"/></StackPanel>
        <StackPanel Width="120" Margin="0,0,0,8"><TextBlock Text="Export"/><ComboBox Name="Format" SelectedIndex="0"><ComboBoxItem Content="glb"/><ComboBoxItem Content="fbx"/><ComboBoxItem Content="both"/></ComboBox></StackPanel>
      </WrapPanel>
      <StackPanel Orientation="Horizontal" Margin="0,8,0,0">
        <Button Name="Start" Content="▶  Remesh + Bake" Padding="20,10" Background="#222" Foreground="White" BorderThickness="0" FontWeight="SemiBold"/>
        <Button Name="Cancel" Content="Cancel" Padding="18,10" Margin="10,0,0,0" IsEnabled="False"/>
        <TextBlock Name="Status" Text="Ready" VerticalAlignment="Center" Margin="14,0,0,0" Foreground="#555"/>
      </StackPanel>
    </StackPanel>
    <TextBox Grid.Row="5" Name="Log" IsReadOnly="True" VerticalScrollBarVisibility="Auto" TextWrapping="Wrap" Background="#191919" Foreground="#E7E7E7" FontFamily="Consolas" FontSize="11" Padding="10"/>
  </Grid>
</Window>
'@

$reader = [System.Xml.XmlNodeReader]::new([xml]$xaml)
$window = [Windows.Markup.XamlReader]::Load($reader)
$names = 'DropArea','FilesList','AddFiles','RemoveFiles','ClearFiles','OutputPath','BrowseOutput','BlenderPath','BrowseBlender','TextureSize','VoxelSize','Decimate','Cage','Format','Start','Cancel','Status','Log'
foreach ($name in $names) { Set-Variable -Name $name -Value $window.FindName($name) -Scope Script }

$script:queue = [System.Collections.Generic.List[string]]::new()
$script:job = $null
$script:logOffset = 0
$script:logFile = $null
$script:errorFile = $null
$script:runFolder = $null
$script:arguments = @()
$script:current = 0
$script:failCount = 0
$OutputPath.Text = [Environment]::GetFolderPath('Desktop')
$knownBlender = 'C:\Program Files\Blender Foundation\Blender 4.3\blender.exe'
if (Test-Path -LiteralPath $knownBlender) { $BlenderPath.Text = $knownBlender }

function Add-Paths($paths) {
    foreach ($path in $paths) {
        if (Test-Path -LiteralPath $path -PathType Container) {
            Get-ChildItem -LiteralPath $path -Filter '*.glb' -File | ForEach-Object { Add-Paths @($_.FullName) }
        } elseif ([IO.Path]::GetExtension($path).ToLowerInvariant() -eq '.glb' -and (Test-Path -LiteralPath $path -PathType Leaf)) {
            $resolved = (Resolve-Path -LiteralPath $path).Path
            if (-not $script:queue.Contains($resolved)) {
                $script:queue.Add($resolved)
                [void]$FilesList.Items.Add($resolved)
            }
        }
    }
    $Status.Text = "$($script:queue.Count) file(s) ready"
}

$dropHandler = [System.Windows.DragEventHandler]{
    param($sender,$event)
    if ($event.Data.GetDataPresent([Windows.DataFormats]::FileDrop)) {
        Add-Paths ([string[]]$event.Data.GetData([Windows.DataFormats]::FileDrop))
    }
    $event.Handled = $true
}
$DropArea.Add_Drop($dropHandler)
$FilesList.Add_Drop($dropHandler)
$AddFiles.Add_Click({
    $dialog = [Microsoft.Win32.OpenFileDialog]::new()
    $dialog.Filter = 'GLB files (*.glb)|*.glb'
    $dialog.Multiselect = $true
    if ($dialog.ShowDialog() -eq $true) { Add-Paths $dialog.FileNames }
})
$RemoveFiles.Add_Click({
    $selected = @($FilesList.SelectedItems)
    foreach ($item in $selected) { [void]$script:queue.Remove($item); $FilesList.Items.Remove($item) }
    $Status.Text = "$($script:queue.Count) file(s) ready"
})
$ClearFiles.Add_Click({ $script:queue.Clear(); $FilesList.Items.Clear(); $Status.Text = 'Ready' })
$BrowseOutput.Add_Click({
    $dialog = [System.Windows.Forms.FolderBrowserDialog]::new()
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $OutputPath.Text = $dialog.SelectedPath }
})
$BrowseBlender.Add_Click({
    $dialog = [Microsoft.Win32.OpenFileDialog]::new()
    $dialog.Filter = 'Blender (blender.exe)|blender.exe'
    if ($dialog.ShowDialog() -eq $true) { $BlenderPath.Text = $dialog.FileName }
})

function Quote-Arg([string]$value) { return '"' + $value.Replace('"','\"') + '"' }
function Start-Next {
    if ($script:current -ge $script:queue.Count) {
        $Start.IsEnabled = $true; $Cancel.IsEnabled = $false
        $Status.Text = "Finished: $($script:queue.Count - $script:failCount) succeeded, $($script:failCount) failed"
        return
    }
    $file = $script:queue[$script:current]
    $script:current++
    $script:logOffset = 0
    $script:logFile = Join-Path $script:runFolder ("job_{0}.out.log" -f $script:current)
    $script:errorFile = Join-Path $script:runFolder ("job_{0}.err.log" -f $script:current)
    $scriptPath = Join-Path $PSScriptRoot 'blender_batch_remesh_bake.py'
    $argLine = '-b --python ' + (Quote-Arg $scriptPath) + ' -- --input ' + (Quote-Arg $file) + ' --output ' + (Quote-Arg $OutputPath.Text) + ' ' + ($script:arguments -join ' ')
    $Status.Text = "Processing $($script:current)/$($script:queue.Count): $([IO.Path]::GetFileName($file))"
    $Log.AppendText("`r`n=== $file ===`r`n")
    $script:job = Start-Process -FilePath $BlenderPath.Text -ArgumentList $argLine -PassThru -WindowStyle Hidden -RedirectStandardOutput $script:logFile -RedirectStandardError $script:errorFile
}

$timer = [Windows.Threading.DispatcherTimer]::new()
$timer.Interval = [TimeSpan]::FromMilliseconds(750)
$timer.Add_Tick({
    if ($script:logFile -and (Test-Path -LiteralPath $script:logFile)) {
        try {
            $stream = [IO.File]::Open($script:logFile, 'Open', 'Read', 'ReadWrite')
            try {
                if ($stream.Length -gt $script:logOffset) {
                    $stream.Position = $script:logOffset
                    $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8, $true, 1024, $true)
                    try { $chunk = $reader.ReadToEnd(); $script:logOffset = $stream.Position }
                    finally { $reader.Dispose() }
                    $Log.AppendText($chunk); $Log.ScrollToEnd()
                }
            } finally { $stream.Dispose() }
        } catch {}
    }
    if ($script:job -and $script:job.HasExited) {
        $code = $script:job.ExitCode
        if ($code -ne 0) {
            $script:failCount++
            if (Test-Path -LiteralPath $script:errorFile) { $Log.AppendText([IO.File]::ReadAllText($script:errorFile)) }
            $Log.AppendText("`r`nFAILED (exit $code)`r`n")
        } else { $Log.AppendText("`r`nDONE`r`n") }
        $script:job.Dispose(); $script:job = $null
        Start-Next
    }
})
$timer.Start()

$Start.Add_Click({
    if ($script:queue.Count -eq 0) { [Windows.MessageBox]::Show('Add at least one GLB file.'); return }
    if (-not (Test-Path -LiteralPath $BlenderPath.Text -PathType Leaf)) { [Windows.MessageBox]::Show('Select blender.exe.'); return }
    if (-not $OutputPath.Text.Trim()) { [Windows.MessageBox]::Show('Select an output folder.'); return }
    try {
        $culture = [Globalization.CultureInfo]::InvariantCulture
        $voxel = [double]::Parse($VoxelSize.Text.Replace(',','.'), $culture) / 100
        $decimate = [double]::Parse($Decimate.Text.Replace(',','.'), $culture) / 100
        $cage = [double]::Parse($Cage.Text.Replace(',','.'), $culture) / 100
        if ($voxel -le 0 -or $voxel -ge 1 -or $decimate -le 0 -or $decimate -gt 1 -or $cage -lt 0) { throw 'Range error' }
    } catch { [Windows.MessageBox]::Show('Check numeric settings: voxel > 0, decimate 0-100, cage >= 0.'); return }
    [IO.Directory]::CreateDirectory($OutputPath.Text) | Out-Null
    $script:runFolder = Join-Path $OutputPath.Text ("remesh_logs_" + (Get-Date -Format 'yyyyMMdd_HHmmss'))
    [IO.Directory]::CreateDirectory($script:runFolder) | Out-Null
    $size = $TextureSize.SelectedItem.Content
    $format = $Format.SelectedItem.Content
    $script:arguments = @('--texture-size', $size, '--voxel-size', $voxel.ToString($culture), '--decimate-ratio', $decimate.ToString($culture), '--cage-extrusion', $cage.ToString($culture), '--format', $format)
    $script:current = 0; $script:failCount = 0
    $Start.IsEnabled = $false; $Cancel.IsEnabled = $true
    $Log.Clear()
    Start-Next
})
$Cancel.Add_Click({
    if ($script:job -and -not $script:job.HasExited) { $script:job.Kill() }
    $script:current = $script:queue.Count
    $Status.Text = 'Cancelled'
})
$window.Add_Closing({ if ($script:job -and -not $script:job.HasExited) { $script:job.Kill() } })
[void]$window.ShowDialog()
