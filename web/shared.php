<?php

$root_folder = realpath(__DIR__ . '/../');
if (! file_exists("{$root_folder}/{$file_name}")) {
    exit("File {$file_name} does not exist.");
}
$json_file = file_get_contents("{$root_folder}/{$file_name}");

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

    // Search for the last "(" character, copy until the second to last character
    $key = mb_substr(
        $msg,
        mb_strrpos($msg, '(') + 1,
        mb_strlen($msg) - mb_strrpos($msg, '(') - 2
    );
    return $url . "&recherche={$key}";
};
