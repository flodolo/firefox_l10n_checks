<?php

include('shared.php');
$error_log = json_decode($json_file_errors, true);

$html_detail_body = '';
foreach ($error_log['errors'] as $error_message) {
    $html_detail_body .= "<tr>\n";
    // Message
    if (strpos($error_message, 'compare-locales') !== false) {
        $html_detail_body .= "\t<td>{$error_message}</td>\n";
    } else {
        $html_detail_body .= "\t<td><a href=\"" . $tranvision_link($error_message) . "\">{$error_message}</li>\n</td>\n";
    }
    $html_detail_body .= "</tr>\n";
}
?>
<!DOCTYPE html>
<html lang="en-US">
<head>
    <meta charset=utf-8>
    <title>Firefox Error Checks</title>
    <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/css/bootstrap.min.css" integrity="sha384-ggOyR0iXCbMQv3Xipma34MD+dH/1fQ784/j6cY/iJTQUOhcWr7x9JvoRxT2MZw1T" crossorigin="anonymous">
    <link rel="stylesheet" href="css/base.css">
</head>
<body>
    <div class="container">
        <p><a href="index.php">Back to main index</a></p>
        <table class="table table-bordered table-striped">
            <thead>
                <tr>
                    <th>Current Errors</th>
                </tr>
            </thead>
        <tbody>
<?php echo $html_detail_body; ?>
        </tbody>
        </table>
    </div>
</body>
