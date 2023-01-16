<?php

$root_folder = realpath(__DIR__ . '/../');

# Load checks.json
$file_name = 'checks.json';
if (! file_exists("{$root_folder}/{$file_name}")) {
    exit("File {$file_name} does not exist.");
}
$json_file_checks = file_get_contents("{$root_folder}/{$file_name}");

# Load errors.json
$file_name = 'errors.json';
if (! file_exists("{$root_folder}/{$file_name}")) {
    exit("File {$file_name} does not exist.");
}
$json_file_errors = file_get_contents("{$root_folder}/{$file_name}");

$tranvision_link = function($msg) {
    // URL
    $url = 'https://transvision.flod.org/?repo=gecko_strings&sourcelocale=en-US&search_type=entities';

    /*
        compare-locales errors have a fixed structure:
            LOCALE (compare-locales TYPE): DESCRIPTION for ENTITY
    */
    if (strpos($msg, 'compare-locales') !== false) {
        $locale = explode(' ', $msg)[0];
        $matches = [];
        preg_match('/ for (.*)$/', $msg, $matches);
        if (empty($matches)) {
            return $msg;
        }
        $key = $matches[1];
        $url .= "&locale={$locale}&recherche={$key}";

        return str_replace($key, "<a href=\"{$url}\">{$key}</a>", $msg);
    }

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
            $url .= "&recherche={$key}";

            return str_replace($key, "<a href=\"{$url}\">{$key}</a>", $msg);
        }
    }

    // Clean up HTML from the message
    $msg = str_replace("\n", '<br/>', htmlspecialchars($msg));

    // Assume the key is between the first parentheses
    $key = mb_substr(
        $msg,
        mb_strpos($msg, '(') + 1,
        mb_strpos($msg, ')') - mb_strpos($msg, '(') - 1,
    );
    $url .= "&recherche={$key}";

    return str_replace($key, "<a href=\"{$url}\">{$key}</a>", $msg);
};
