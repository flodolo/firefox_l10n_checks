<?php

$file_name = 'checks.json';
include('shared.php');
$error_log = json_decode($json_file, true);
$error_log = array_reverse($error_log, true);

$html_detail_body = '';
foreach ($error_log as $day => $day_info) {
    $html_detail_body .= "<tr>\n";

    // Day
    $html_detail_body .= "\t<td>" . str_replace(' ', ' ', $day) . "</td>\n";

    // Message
    $html_detail_body .= "\t<td>";
    $html_detail_body .= isset($day_info['message'])
        ? $day_info['message']
        : ' ';
    $html_detail_body .= "</td>\n";

    // Details
    $html_detail_body .= "\t<td>";
    if (isset($day_info['new'])) {
        $html_detail_body .= '<p class="new_errors">New errors (' . count($day_info['new']) . "):</p>\n";
        $html_detail_body .= "<ul>\n";
        foreach ($day_info['new'] as $error) {
            $html_detail_body .= '<li><a href="' . $tranvision_link($error) . "\">{$error}</li>\n";
        }
        $html_detail_body .= "</ul>\n";
    }
    if (isset($day_info['fixed'])) {
        $html_detail_body .= '<p class="fixed_errors">Fixed errors (' . count($day_info['fixed']) . "):</p>\n";
        $html_detail_body .= "<ul>\n";
        foreach ($day_info['fixed'] as $error) {
            $html_detail_body .= '<li><a href="' . $tranvision_link($error) . "\">{$error}</li>\n";
        }
        $html_detail_body .= "</ul>\n";
    }
    $html_detail_body .= "</td>\n";
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
        <p><a href="errors.php">List of current errors</a></p>
        <table class="table table-bordered table-striped">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Message</th>
                    <th>Details</th>
                </tr>
            </thead>
        <tbody>
<?php echo $html_detail_body; ?>
        </tbody>
        </table>
    </div>
</body>
