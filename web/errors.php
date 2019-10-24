<?php

$file_name = 'errors.json';
include('shared.php');
$error_log = json_decode($json_file, true);

$html_detail_body = '';
foreach ($error_log as $error_message) {
    $html_detail_body .= "<tr>\n";
    // Message
    $html_detail_body .= "\t<td><a href=\"" . $tranvision_link($error_message) . "\">{$error_message}</li>\n</td>\n";
    $html_detail_body .= "</tr>\n";
}
?>
<!DOCTYPE html>
<html lang="en-US">
<head>
    <meta charset=utf-8>
    <title>Firefox Error Checks</title>
    <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/css/bootstrap.min.css" integrity="sha384-ggOyR0iXCbMQv3Xipma34MD+dH/1fQ784/j6cY/iJTQUOhcWr7x9JvoRxT2MZw1T" crossorigin="anonymous">
    <style type="text/css">
        body {
            font-size: 13px;
        }

        .container {
            margin-top: 20px;
        }

        .new_errors {
            color: red;
        }

        .fixed_errors {
            color: green;
        }
    </style>
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
