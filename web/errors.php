<?php

$root_folder = realpath(__DIR__ . '/../');
if (! file_exists("{$root_folder}/errors.json")) {
    exit('File errors.json does not exist.');
}
$json_file = file_get_contents("{$root_folder}/errors.json");
$error_log = json_decode($json_file, true);

$tranvision_link = function($msg) {
    // URL
    $url = 'https://transvision.flod.org/?repo=gecko_strings&sourcelocale=en-US&search_type=entities';

    // Extract the locale code
    $locale = explode(' - ', $msg)[0];
    $url .= "&locale={$locale}";

    // Variables, shortcuts, empty string errors
    $needles = [
        'empty: ',
        'shortcuts: ',
        'variables: ',
    ];
    foreach ($needles as $needle) {
        if (mb_strpos($msg, $needle) !== false) {
            $start = (mb_strpos($msg, $needle));
            $key = mb_substr($msg, $start + strlen($needle), mb_strlen($msg) - 1);

            return $url . "&recherche={$key}";
        }
    }

    $key = mb_substr($msg, mb_strpos($msg, '(') + 1, mb_strpos($msg, ')') - mb_strpos($msg, '(') - 1);
    return $url . "&recherche={$key}";
};

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
