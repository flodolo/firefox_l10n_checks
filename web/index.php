<?php

include('shared.php');
$error_log = json_decode($json_file_checks, true);
$error_log = array_reverse($error_log, true);

$errors_list = json_decode($json_file_errors, true);

$html_detail_body = '';
foreach ($error_log as $day => $day_info) {
    $html_detail_body .= "<tr>\n";

    // Day
    $html_detail_body .= "\t<td>" . str_replace(' ', ' ', $day) . "</td>\n";

    // Message
    $html_detail_body .= "\t<td>";
    $html_detail_body .= isset($day_info['message'])
        ? str_replace("\n", '<br/>', $day_info['message'])
        : ' ';
    $html_detail_body .= "</td>\n";

    // Details
    $html_detail_body .= "\t<td>";
    if (isset($day_info['new'])) {
        $html_detail_body .= '<p class="new_errors">New errors (' . count($day_info['new']) . "):</p>\n";
        $html_detail_body .= "<ul>\n";
        foreach ($day_info['new'] as $error) {
            $html_detail_body .= '<li>' . $tranvision_link($error) . "</li>\n";
        }
        $html_detail_body .= "</ul>\n";
    }
    if (isset($day_info['fixed'])) {
        $html_detail_body .= '<p class="fixed_errors">Fixed errors (' . count($day_info['fixed']) . "):</p>\n";
        $html_detail_body .= "<ul>\n";
        foreach ($day_info['fixed'] as $error) {
            $html_detail_body .= '<li>' . $tranvision_link($error) . "</li>\n";
        }
        $html_detail_body .= "</ul>\n";
    }
    $html_detail_body .= "</td>\n";
    $html_detail_body .= "</tr>\n";
}

// Summary table
foreach ($errors_list['summary'] as $check_name => $check_value) {
    $html_summary_body .= "<tr>\n";
    if ($check_name == 'compare-locales') {
        $html_summary_body .= "\t<td>{$check_name}</td>\n\t<td>{$check_value['errors']} ({$check_value['warnings']} warnings)</td>\n";
    } else {
        $html_summary_body .= "\t<td>{$check_name}</td>\n\t<td>{$check_value}</td>\n";
    }
    $html_summary_body .= "</tr>\n";
}

?>
<!DOCTYPE html>
<html lang="en-US">
<head>
    <meta charset=utf-8>
    <title>Firefox Error Checks</title>
    <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css" integrity="sha384-JcKb8q3iqJ61gNV9KGb8thSsNjpSL0n8PARn9HuZOnIxN0hoP+VmmDGMN5t9UJ0Z" crossorigin="anonymous">
    <link rel="stylesheet" href="css/base.css">
    <link rel="icon" type="image/png" sizes="196x196" href="img/favicon.png">
</head>
<body>
    <div class="container">
        <p><a href="errors.php">List of current errors</a></p>

        <h1>Summary</h1>
        <table class="table w-auto table-bordered table-striped">
            <thead>
                <tr>
                    <th>Check</th>
                    <th>Errors</th>
                </tr>
            </thead>
        <tbody>
<?php echo $html_summary_body; ?>
        </tbody>
        </table>

        <h1>Changelog</h1>
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
