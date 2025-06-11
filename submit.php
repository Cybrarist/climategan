<?php

set_time_limit(100);

$allowedMimes = ['image/jpeg', 'image/png', 'image/gif'];
$allowedExts  = ['jpg', 'jpeg', 'png', 'gif'];

// Ensure base temp directory exists
$baseTempDir = 'temp';
if (!is_dir($baseTempDir)) {
    mkdir($baseTempDir, 0777, true);
}
// Create unique subdirectories for this upload batch
$uniqueId  = bin2hex(random_bytes(4));  // random identifier
$uploadDir = $baseTempDir . '/upload_' . $uniqueId;
$outputDir = $baseTempDir . '/output_' . $uniqueId;
mkdir($uploadDir, 0777, true);

// Check that files were uploaded
if (!isset($_FILES['images']) || empty($_FILES['images']['name'][0])) {
    die('<div class="container mt-4"><div class="alert alert-danger">No images were uploaded.</div></div>');
}

// Process each uploaded file
$finfo = finfo_open(FILEINFO_MIME_TYPE);
$files = $_FILES['images'];

for ($i = 0; $i < count($files['name']); $i++) {
    if ($files['error'][$i] !== UPLOAD_ERR_OK) {
        continue;
    }


    $tmpPath = $files['tmp_name'][$i];
    // Validate MIME type against allowed list
    $mimeType = finfo_file($finfo, $tmpPath);

    if (!in_array($mimeType, $allowedMimes)) {
        finfo_close($finfo);
        // Remove any files saved so far and directories, then error out
        array_map('unlink', glob("$uploadDir/*"));
        rmdir($uploadDir);
        rmdir($outputDir);
        die('<div class="container mt-4"><div class="alert alert-danger">'
            . 'Invalid file type for ' . htmlentities($files['name'][$i]) . '.</div></div>');
    }
    // Determine a safe file extension based on MIME type
    $ext = match($mimeType) {
        'image/jpeg' => 'jpg',
        'image/png'  => 'png',
        'image/gif'  => 'gif',
    };
    // Generate a secure random filename for the image
    $newName = bin2hex(random_bytes(8)) . ".$ext";
    $destination = "$uploadDir/$newName";

    if (!move_uploaded_file($tmpPath, $destination)) {
        finfo_close($finfo);
        // Cleanup and error if file couldn't be moved
        array_map('unlink', glob("$uploadDir/*"));
        rmdir($uploadDir);
        rmdir($outputDir);
        die('<div class="container mt-4"><div class="alert alert-danger">'
            . 'Failed to save uploaded file ' . htmlentities($files['name'][$i]) . '.</div></div>');
    }


}
finfo_close($finfo);  // Close the file info resource

// Retrieve and sanitize form inputs
$batchSize  = isset($_POST['batch_size']) ? (int)$_POST['batch_size'] : 4;
$targetSize = isset($_POST['target_size']) ? (int)$_POST['target_size'] : 640;
$maxWidth   = isset($_POST['max_im_width']) ? (int)$_POST['max_im_width'] : -1;
if ($batchSize < 1) $batchSize = 4;             // enforce a minimum batch size
if ($targetSize < 128) $targetSize = 640;       // enforce minimum target size
if ($targetSize % 128 !== 0) {
    // Target size not a multiple of 128, cleanup and return an error
    array_map('unlink', glob("$uploadDir/*"));
    rmdir($uploadDir);
    rmdir($outputDir);
    die('<div class="container mt-4"><div class="alert alert-danger">'
        . 'Error: Target size must be a multiple of 128.</div></div>');
}
$noTime   = isset($_POST['no_time']);
$useHalf  = isset($_POST['half']);
$noCloudy = isset($_POST['no_cloudy']);
$useFuse  = isset($_POST['fuse']);

// Build the shell command parts safely
$cmdParts   = [];
$cmdParts[] = '.venv/bin/python3';  // the Python interpreter
$cmdParts[] = escapeshellarg('apply_events.py');  // the script to run
$cmdParts[] = '-b ' . escapeshellarg($batchSize);
if ($noTime)   $cmdParts[] = '--no_time';
if ($useHalf)  $cmdParts[] = '--half';
if ($noCloudy) $cmdParts[] = '--no_cloudy';
if ($useFuse)  $cmdParts[] = '--fuse';
$cmdParts[] = '--target_size ' . escapeshellarg($targetSize);
if ($maxWidth !== -1) {
    $cmdParts[] = '--max_im_width ' . escapeshellarg($maxWidth);
}
$cmdParts[] = '-i ' . escapeshellarg($uploadDir);
$cmdParts[] = '-r ' . escapeshellarg('config/model/masker');
$cmdParts[] = '--output_path ' . escapeshellarg($outputDir);
$command = implode(' ', $cmdParts);


// Execute the external Python script
exec($command, $outputLines, $status);  // $outputLines captures output, $status is exit code


foreach ($outputLines as $line) {
    echo $line . '<br>';
}

if ($status !== 0) {
    // If the script failed, clean up and inform the user
    array_map('unlink', glob("$uploadDir/*"));
    array_map('unlink', glob("$outputDir/*"));
    rmdir($uploadDir);
    rmdir($outputDir);
    die('<div class="container mt-4"><div class="alert alert-danger">'
        . 'Error: The image processing script failed. Please try again.</div></div>');
}

// Create a ZIP archive of all files in the output directory
$zipPath = "$baseTempDir/results_$uniqueId.zip";
$zip = new ZipArchive();
if ($zip->open($zipPath, ZipArchive::CREATE) === TRUE) {
    foreach (glob("$outputDir/*") as $filePath) {
        $zip->addFile($filePath, basename($filePath));
    }
    $zip->close();
} else {
    // Cleanup and error if ZIP creation failed
    array_map('unlink', glob("$uploadDir/*"));
    array_map('unlink', glob("$outputDir/*"));
    rmdir($uploadDir);
    rmdir($outputDir);
    die('<div class="container mt-4"><div class="alert alert-danger">'
        . 'Failed to create ZIP archive of results.</div></div>');
}

// Remove all input and output files now that they are zipped
array_map('unlink', glob("$uploadDir/*"));
array_map('unlink', glob("$outputDir/*"));
rmdir($uploadDir);
rmdir($outputDir);

// Output a link for the user to download the ZIP file
echo '<div class="container mt-4"><div class="alert alert-success">'
    . 'Processing complete. <a href="temp/' . basename($zipPath) . '" download>Download Results</a>'
    . '</div></div>';
?>
