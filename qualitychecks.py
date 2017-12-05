#! /usr/bin/env python

import argparse
import json
import os
import re
import sys
import urllib2

class QualityCheck():

    # Number of plural forms for each rule
    # Reference: https://searchfox.org/mozilla-central/source/intl/locale/PluralForm.jsm
    plural_rules = [
        # 0: Chinese
        1,
        # 1: English
        2,
        # 2: French
        2,
        # 3: Latvian
        3,
        # 4: Scottish Gaelic
        4,
        # 5: Romanian
        3,
        # 6: Lithuanian
        3,
        # 7: Russian
        3,
        # 8: Slovak
        3,
        # 9: Polish
        3,
        # 10: Slovenian
        4,
        # 11: Irish Gaeilge
        5,
        # 12: Arabic
        6,
        # 13: Maltese
        4,
        # 14: Macedonian
        3,
        # 15: Icelandic
        2,
        # 16: Breton
        5,
        # 17: Shuar
        2,
    ]

    json_files = [
        'abouttabcrashed_dtd',
        'browser_installer_nsistr',
        'intl_properties',
        'mobile_phishing_dtd',
        'mobile_netError_dtd',
        'netError_dtd',
        'phishing-afterload-warning-message_dtd',
        'preferences_properties',
        'pipnss_properties',
        'plurals',
    ]

    def __init__(self, script_folder, requested_check):
        ''' Initialize object '''
        self.script_folder = script_folder
        self.requested_check = requested_check

        self.domain = 'https://transvision.flod.org'
        self.api_url = '{}/api/v1'.format(self.domain)

        # Store the number of plural forms for each locale
        self.plural_forms = {}
        self.getPluralForms()

        # Run checks
        self.checkAPI()
        if requested_check == 'all':
            self.checkViews()

    def getPluralForms(self):
        ''' Get the number of plural forms for each locale '''
        url = '{}/entity/gecko_strings/?id=toolkit/chrome/global/intl.properties:pluralRule'.format(self.api_url)
        try:
            response = urllib2.urlopen(url)
            locales_plural_rules = json.load(response)
        except Exception as e:
            print(e)

        for locale, rule_number in locales_plural_rules.iteritems():
            self.plural_forms[locale] = self.plural_rules[int(rule_number)]

    def checkAPI(self):

        if self.requested_check != 'all':
            if self.requested_check not in self.json_files:
                print('Requested check ({}) does not exist. Available checks:'.format(self.requested_check))
                print('\n'.join(self.json_files))
                sys.exit(1)
            else:
                self.json_files = [self.requested_check]

        url = '{}/entity/gecko_strings/?id={}:{}'

        error_messages = []
        for json_file in self.json_files:
            print('\n---\nCheck name: {}\n'.format(json_file))
            try:
                checks = json.load(open(os.path.join(self.script_folder, 'checks', json_file + '.json')))
            except Exception as e:
                print('Error loading JSON file {}'.format(json_file))
                print(e)
                sys.exit(1)

            for c in checks:
                try:
                    print('Checking {}'.format(c['entity']))
                    try:
                        response = urllib2.urlopen(url.format(self.api_url, c['file'], c['entity']))
                        json_data = json.load(response)
                    except Exception as e:
                        error_messages.append('  ERROR checking {}:{}: {}'.format(c['file'], c['entity'], e))
                    for locale, translation in json_data.iteritems():
                        # Ignore some locales if exclusions are defined
                        if 'excluded_locales' in c and locale in c['excluded_locales']:
                            continue
                        if 'included_locales' in c and locale not in c['included_locales']:
                            continue

                        if c['type'] == 'include_regex':
                            for t in c['checks']:
                                pattern = re.compile(t, re.UNICODE)
                                if not pattern.search(translation):
                                    error_msg = u'{}: missing {} in {}'.format(locale, t, c['entity'])
                                    print(u'  {}'.format(error_msg))
                                    error_messages.append(u'  {} - {}'.format(json_file, error_msg))
                        elif c['type'] == 'include':
                            for t in c['checks']:
                                if t not in translation:
                                    error_msg = u'{}: missing {} in {}'.format(locale, t, c['entity'])
                                    print(u'  {}'.format(error_msg))
                                    error_messages.append(u'  {} - {}'.format(json_file, error_msg))
                        elif c['type'] == 'equal_to':
                            if c['value'].lower() != translation.lower():
                                error_msg = u'  {}: {} not equal to {} in {}'.format(locale, translation, c['value'], c['entity'])
                                print(u'  {}'.format(error_msg))
                                error_messages.append(u'  {} - {}'.format(json_file, error_msg))
                        elif c['type'] == 'not_equal_to':
                            if c['value'] == translation:
                                error_msg = u'  {}: {} is equal to {} in {}'.format(locale, translation, c['value'], c['entity'])
                                print(u'  {}'.format(error_msg))
                                error_messages.append(u'  {} - {}'.format(json_file, error_msg))
                        elif c['type'] == 'acceptable_values':
                            if translation not in c['values']:
                                error_msg = u'  {}: {} is not an acceptable value'.format(locale, translation)
                                print(u'  {}'.format(error_msg))
                                error_messages.append(u'  {} - {}'.format(json_file, error_msg))
                        elif c['type'] == 'typeof':
                            if type(translation) != c['value']:
                                error_msg = u'  {}: {} is not of type'.format(locale, translation)
                                print(u'  {}'.format(error_msg))
                                error_messages.append(u'  {} - {}'.format(json_file, error_msg))
                        elif c['type'] == 'bytes_length':
                            current_length = len(translation.encode('utf-8'))
                            if current_length > c['value']:
                                error_msg = u'  {}: {} ({}) is longer than {} bytes (current length: {} bytes)'.format(locale, c['entity'], translation, c['value'], current_length)
                                print(u'  {}'.format(error_msg))
                                error_messages.append(u'  {} - {}'.format(json_file, error_msg))
                        elif c['type'] == 'plural_forms':
                            if 'excluded_locales' in c and locale in c['excluded_locales']:
                                continue
                            num_forms = len(translation.split(';'))
                            if num_forms != self.plural_forms[locale]:
                                error_msg = u'  {}: {} has {} plural forms (requested: {})'.format(locale, c['entity'], num_forms, self.plural_forms[locale])
                                print(u'  {}'.format(error_msg))
                                error_messages.append(u'  {} - {}'.format(json_file, error_msg))
                except Exception as e:
                    print(e)

        if error_messages:
            print('\nThere are errors ({})'.format(len(error_messages)))
            error_messages.sort()
            print(u'\n'.join(error_messages))
        else:
            print('\nThere are no errors.')

    def checkViews(self):
        ''' Check views for access keys and keyboard shortcuts '''
        url_locales = '{}/locales/gecko_strings/'.format(self.api_url)
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
        f = open(os.path.join(self.script_folder, 'exceptions', 'variables.txt'), 'r')
        exceptions = []
        for l in f:
            exceptions.append(l.rstrip())
        for locale in locales:
            url = '{}/variables/?locale={}&repo=gecko_strings&json'.format(self.domain, locale)
            response = urllib2.urlopen(url)
            variable_errors = json.load(response)
            for error in variable_errors:
                if error.startswith((excluded_products)):
                    continue
                error_msg = '{}: {}'.format(locale, error)
                if error_msg in exceptions:
                    continue
                print(error_msg)


        f = open(os.path.join(self.script_folder, 'exceptions', 'shortcuts.txt'), 'r')
        exceptions = []
        for l in f:
            exceptions.append(l.rstrip())
        print('\n-----\nChecking keyboard shortcuts\n-----')
        for locale in locales:
            url = '{}/commandkeys/?locale={}&repo=gecko_strings&json'.format(self.domain, locale)
            response = urllib2.urlopen(url)
            variable_errors = json.load(response)
            for error in variable_errors:
                if error.startswith((excluded_products)):
                    continue
                error_msg = '{}: {}'.format(locale, error)
                if error_msg in exceptions:
                    continue
                print(error_msg)

def main():
    # Parse command line options
    cl_parser = argparse.ArgumentParser()
    cl_parser.add_argument('check', help='Run a single check', default='all', nargs='?')
    args = cl_parser.parse_args()

    script_folder = os.path.dirname(os.path.realpath(__file__))
    checks = QualityCheck(script_folder, args.check)

if __name__ == '__main__':
    main()
