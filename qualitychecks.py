#! /usr/bin/env python

import json
import os
import re
import sys
import urllib2

def check_api(script_folder):
    filenames = [
        'abouttabcrashed_dtd',
        'browser_dtd',
        'browser_installer_nsistr',
        'intl_properties',
        'mobile_phishing_dtd',
        'mobile_netError_dtd',
        'netError_dtd',
        'phishing-afterload-warning-message_dtd',
        'preferences_properties',
        'pipnss_properties',
    ]
    url = 'https://transvision.flod.org/api/v1/entity/gecko_strings/?id={}:{}'

    error_messages = []
    for filename in filenames:
        print('\n---\nCheck name: {}\n'.format(filename))
        try:
            checks = json.load(open(os.path.join(script_folder, 'checks', filename + '.json')))
        except Exception as e:
            print('Error loading JSON file {}'.format(filename))
            print(e)
            sys.exit(1)

        for c in checks:
            try:
                print('Checking {}'.format(c['entity']))
                response = urllib2.urlopen(url.format(c['file'], c['entity']))
                json_data = json.load(response)
                for locale, str in json_data.iteritems():
                    # Ignore some locales if exclusions are defined
                    if 'excluded_locales' in c and locale in c['excluded_locales']:
                        continue
                    if 'included_locales' in c and locale not in c['included_locales']:
                        continue

                    if c['type'] == 'include_regex':
                        for t in c['checks']:
                            pattern = re.compile(t, re.UNICODE)
                            if not pattern.search(str):
                                error_msg = u'{}: missing {} in {}'.format(locale, t, c['entity'])
                                print(u'  {}'.format(error_msg))
                                error_messages.append(u'  {} - {}'.format(filename, error_msg))
                    elif c['type'] == 'include':
                        for t in c['checks']:
                            if t not in str:
                                error_msg = u'{}: missing {} in {}'.format(locale, t, c['entity'])
                                print(u'  {}'.format(error_msg))
                                error_messages.append(u'  {} - {}'.format(filename, error_msg))
                    elif c['type'] == 'equal_to':
                        if c['value'].lower() != str.lower():
                            error_msg = u'  {}: {} not equal to {} in {}'.format(locale, str, c['value'], c['entity'])
                            print(u'  {}'.format(error_msg))
                            error_messages.append(u'  {} - {}'.format(filename, error_msg))
                    elif c['type'] == 'not_equal_to':
                        if c['value'] == str:
                            error_msg = u'  {}: {} is equal to {} in {}'.format(locale, str, c['value'], c['entity'])
                            print(u'  {}'.format(error_msg))
                            error_messages.append(u'  {} - {}'.format(filename, error_msg))
                    elif c['type'] == 'acceptable_values':
                        if str not in c['values']:
                            error_msg = u'  {}: {} is not an acceptable value'.format(locale, str)
                            print(u'  {}'.format(error_msg))
                            error_messages.append(u'  {} - {}'.format(filename, error_msg))
                    elif c['type'] == 'typeof':
                        if type(str) != c['value']:
                            error_msg = u'  {}: {} is not of type'.format(locale, str)
                            print(u'  {}'.format(error_msg))
                            error_messages.append(u'  {} - {}'.format(filename, error_msg))
                    elif c['type'] == 'bytes_length':
                        current_length = len(str.encode('utf-8'))
                        if current_length > c['value']:
                            error_msg = u'  {}: {} ({}) is longer than {} bytes (current length: {} bytes)'.format(locale, c['entity'], str, c['value'], current_length)
                            print(u'  {}'.format(error_msg))
                            error_messages.append(u'  {} - {}'.format(filename, error_msg))
            except Exception as e:
                print(e)

    if error_messages:
        print('\nThere are errors ({})'.format(len(error_messages)))
        error_messages.sort()
        print(u'\n'.join(error_messages))
    else:
        print('\nThere are no errors.')


def check_views(script_folder):
    base_url='https://transvision.flod.org'
    url_locales = '{}/api/v1/locales/gecko_strings/'.format(base_url)
    try:
        response = urllib2.urlopen(url_locales)
        locales = json.load(response)
    except Exception as e:
        print(e)

    excluded_products = (
        'calendar/',
        'chat/',
        'editor/',
        'extensions/',
        'mail/',
        'suite/',
    )

    print('\n-----\nChecking variables\n-----')
    f = open(os.path.join(script_folder, 'exceptions', 'variables.txt'), 'r')
    exceptions = []
    for l in f:
        exceptions.append(l.rstrip())
    for locale in locales:
        url = '{}/variables/?locale={}&repo=gecko_strings&json'.format(base_url, locale)
        response = urllib2.urlopen(url)
        variable_errors = json.load(response)
        for error in variable_errors:
            if error.startswith((excluded_products)):
                continue
            str = '{}: {}'.format(locale, error)
            if str in exceptions:
                continue
            print(str)


    f = open(os.path.join(script_folder, 'exceptions', 'shortcuts.txt'), 'r')
    exceptions = []
    for l in f:
        exceptions.append(l.rstrip())
    print('\n-----\nChecking variables\n-----')
    for locale in locales:
        url = '{}/commandkeys/?locale={}&repo=gecko_strings&json'.format(base_url, locale)
        response = urllib2.urlopen(url)
        variable_errors = json.load(response)
        for error in variable_errors:
            if error.startswith((excluded_products)):
                continue
            str = '{}: {}'.format(locale, error)
            if str in exceptions:
                continue
            print(str)


def main():
    script_folder = os.path.dirname(os.path.realpath(__file__))
    check_api(script_folder)
    check_views(script_folder)

if __name__ == '__main__':
    main()
