#! /usr/bin/env python

import argparse
from collections import OrderedDict
import json
import os
import pickle
import re
import sys
import urllib2


class QualityCheck():

    # Number of plural forms for each rule
    # Reference:
    # https://searchfox.org/mozilla-central/source/intl/locale/PluralForm.jsm
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
        # 14: Unused
        3,
        # 15: Icelandic, Macedonian
        2,
        # 16: Breton
        5,
        # 17: Shuar
        2,
        # 18: Welsh
        6,
        # 19: Slavic
        3,
    ]

    json_files = [
        'boolean_values',
        'browser_installer_nsistr',
        'intl_properties',
        'mobile_netError_dtd',
        'mobile_phishing_dtd',
        'netError_dtd',
        'pipnss_properties',
        'plurals',
        'pocket',
    ]

    excluded_products = (
        'calendar/',
        'chat/',
        'editor/',
        'extensions/',
        'mail/',
        'suite/',
    )

    def __init__(self, script_folder, requested_check):
        ''' Initialize object '''
        self.script_folder = script_folder
        self.requested_check = requested_check

        self.domain = 'https://transvision.flod.org'
        self.api_url = '{}/api/v1'.format(self.domain)

        self.general_errors = []

        # Get the list of supported locales
        self.getLocales()

        # Store the number of plural forms for each locale
        self.plural_forms = {}
        self.getPluralForms()

        # Initialize other error messages
        self.error_messages = OrderedDict()
        self.error_summary = {}
        for locale in self.locales:
            self.error_messages[locale] = []

        # Run checks
        self.checkAPI()
        if requested_check == 'all':
            self.checkView('variables')
            self.checkView('shortcuts')
            self.checkView('empty')

        # Print errors
        self.printErrors()

        # Compare with previous run
        if requested_check == 'all':
            self.comparePreviousRun()

    def comparePreviousRun(self):

        def diff(a, b):
            b = set(b)
            return [aa for aa in a if aa not in b]

        # Read the list of errors from a previous run (if available)
        file_name = os.path.join(self.script_folder, 'previous_errors.dump')
        previous_errors = []
        if os.path.exists(file_name):
            try:
                f = open(file_name, 'rb')
                previous_errors = pickle.load(f)
                f.close()
            except Exception as e:
                print(e)

        current_errors = []
        for locale, errors in self.error_messages.iteritems():
            for e in errors:
                current_errors.append(u'{} - {}'.format(locale, e))
        current_errors.sort()

        changes = False
        new_errors = diff(current_errors, previous_errors)
        if new_errors:
            changes = True
            print('\n----\nNew errors ({}):'.format(len(new_errors)))
            print('\n'.join(new_errors))

        fixed_errors = diff(previous_errors, current_errors)
        if fixed_errors:
            changes = True
            print('\n----\nFixed errors ({}):'.format(len(fixed_errors)))
            print('\n'.join(fixed_errors))

        if not changes:
            print('\n----\nThere are no changes from previous run.')

        # Write back the current list of errors
        f = open(file_name, 'wb')
        pickle.dump(current_errors, f)
        f.close()

    def getJsonData(self, url, search_id):
        '''
        Return two values:
        - Array of data
        - If the request succeeded (boolean)
        '''
        for try_number in range(5):
            try:
                response = urllib2.urlopen(url)
                json_data = json.load(response)
                return (json_data, True)
            except Exception as e:
                continue

        self.general_errors.append('Error reading {}'.format(search_id))
        return ([], False)

    def getPluralForms(self):
        ''' Get the number of plural forms for each locale '''
        url = '{}/entity/gecko_strings/?id=toolkit/chrome/global/intl.properties:pluralRule'.format(
            self.api_url)
        print('Reading the list of plural forms')
        locales_plural_rules, success = self.getJsonData(
            url, 'list of plural forms')
        if not success:
            print('CRITICAL ERROR: List of plural forms not available')
            sys.exit(1)

        for locale, rule_number in locales_plural_rules.iteritems():
            self.plural_forms[locale] = self.plural_rules[int(rule_number)]

    def getLocales(self):
        ''' Get the list of supported locales '''
        print('Reading the list of supported locales')
        url = '{}/locales/gecko_strings/'.format(self.api_url)
        self.locales, success = self.getJsonData(
            url, 'list of supported locales')
        if not success:
            print('CRITICAL ERROR: List of support locales not available')
            sys.exit(1)

    def printErrors(self):
        ''' Print error messages '''
        error_count = 0
        locales_with_errors = OrderedDict()
        for locale, errors in self.error_messages.iteritems():
            if errors:
                num_errors = len(errors)
                print('\n----\nLocale: {} ({})'.format(locale, num_errors))
                locales_with_errors[locale] = num_errors
                error_count += num_errors
                for e in errors:
                    print(u'- {}'.format(e))
        if error_count:
            print('\n----\nTotal errors: {}'.format(error_count))
        else:
            print('\n----\nNo errors')

        if locales_with_errors:
            print(
                '\n----\nLocales with errors ({} locales):'.format(len(locales_with_errors)))
            for locale, num in locales_with_errors.iteritems():
                print('- {} ({})'.format(locale, num))

        # Error summary
        if self.error_summary:
            print('\n----\nErrors summary by type:')
            for check, count in self.error_summary.iteritems():
                print ('- {}: {}'.format(check, count))

        # General error (e.g. invalid API calls)
        if self.general_errors:
            print('\n----\nGeneral errors ({} errors):'.format(len(self.general_errors)))
            self.general_errors.sort()
            print(u'\n'.join(self.general_errors))

    def sanityCheckJSON(self):
        ''' Do a sanity check on JSON files, checking for duplicates '''
        for json_file in self.json_files:
            try:
                checks = json.load(
                    open(os.path.join(self.script_folder, 'checks', json_file + '.json')))
            except Exception as e:
                print('Error loading JSON file {}'.format(json_file))
                print(e)
                sys.exit(1)

            available_checks = []
            for c in checks:
                id = '{}-{}-{}'.format(c['file'], c['entity'], c['type'])
                if id in available_checks:
                    print('ERROR: check {} is duplicated'.format(id))
                    continue
                available_checks.append(id)

    def checkAPI(self):
        ''' Check strings via API requests '''
        self.sanityCheckJSON()
        if self.requested_check != 'all':
            if self.requested_check not in self.json_files:
                print('ERROR: The requested check ({}) does not exist. Available checks:'.format(
                    self.requested_check))
                for f in self.json_files:
                    print('- {}'.format(f))
                sys.exit(1)
            else:
                self.json_files = [self.requested_check]

        url = '{}/entity/gecko_strings/?id={}:{}'

        for json_file in self.json_files:
            total_errors = 0
            print('CHECK: {}'.format(json_file))
            try:
                checks = json.load(
                    open(os.path.join(self.script_folder, 'checks', json_file + '.json')))
            except Exception as e:
                print('Error loading JSON file {}'.format(json_file))
                print(e)
                sys.exit(1)

            for c in checks:
                try:
                    # print('Checking {}'.format(c['entity']))
                    json_data, success = self.getJsonData(url.format(
                        self.api_url, c['file'], c['entity']), '{}:{}'.format(c['file'], c['entity']))

                    if not success:
                        self.general_errors.append(
                            'Error checking {}:{}'.format(c['file'], c['entity']))
                        continue

                    for locale, translation in json_data.iteritems():
                        # Ignore some locales if exclusions are defined
                        if 'excluded_locales' in c and locale in c['excluded_locales']:
                            continue
                        if 'included_locales' in c and locale not in c['included_locales']:
                            continue

                        error_msg = ''
                        if c['type'] == 'include_regex':
                            for t in c['checks']:
                                pattern = re.compile(t, re.UNICODE)
                                if not pattern.search(translation):
                                    error_msg = u'Missing {} in {} ({})'.format(
                                        t, c['entity'], c['file'])
                        elif c['type'] == 'include':
                            for t in c['checks']:
                                if t not in translation:
                                    error_msg = u'Missing {} in {} ({})'.format(
                                        t, c['entity'], c['file'])
                        elif c['type'] == 'equal_to':
                            if c['value'].lower() != translation.lower():
                                error_msg = u'{} is not equal to {} in {} ({})'.format(
                                    translation, c['value'], c['entity'], c['file'])
                        elif c['type'] == 'not_equal_to':
                            if c['value'] == translation:
                                error_msg = u'{} is equal to {} in {} ({})'.format(
                                    translation, c['value'], c['entity'], c['file'])
                        elif c['type'] == 'acceptable_values':
                            if translation not in c['values']:
                                error_msg = u'{} is not an acceptable value for {} ({})'.format(
                                    translation, c['entity'], c['file'])
                        elif c['type'] == 'typeof':
                            if type(translation) != c['value']:
                                error_msg = u'{} ({}) is not of type {}'.format(
                                    translation, c['file'], c['type'])
                        elif c['type'] == 'bytes_length':
                            current_length = len(translation.encode('utf-8'))
                            if current_length > c['value']:
                                error_msg = u'{} ({}) is longer than {} bytes (current length: {} bytes - current text: {})'.format(
                                    c['entity'], c['file'], c['value'], current_length, translation)
                        elif c['type'] == 'plural_forms':
                            num_forms = len(translation.split(';'))
                            if num_forms != self.plural_forms[locale]:
                                error_msg = u'{} ({}) has {} plural forms (requested: {})'.format(
                                    c['entity'], c['file'], num_forms, self.plural_forms[locale])
                        if error_msg:
                            self.error_messages[locale].append(error_msg)
                            total_errors += 1
                except Exception as e:
                    print(e)
            if total_errors:
                self.error_summary[json_file] = total_errors

    def checkView(self, checkname):
        ''' Check views for access keys and keyboard shortcuts '''
        if checkname == 'variables':
            print('CHECK: variables')
            url = '{}/variables/?locale={}&repo=gecko_strings&json'
        elif checkname == 'shortcuts':
            print('CHECK: keyboard shortcuts')
            url = '{}/commandkeys/?locale={}&repo=gecko_strings&json'
        elif checkname == 'empty':
            print('CHECK: empty strings')
            url = '{}/empty-strings/?locale={}&json'

        f = open(os.path.join(self.script_folder, 'exceptions',
                              '{}.txt'.format(checkname)), 'r')
        exceptions = []
        for l in f:
            exceptions.append(l.rstrip())
        total_errors = 0
        for locale in self.locales:

            errors, success = self.getJsonData(url.format(
                self.domain, locale), '{} for {}'.format(checkname, locale))

            if not success:
                self.general_errors.append(
                    'Error checking *{}* for locale {}'.format(checkname, locale))
                continue

            for error in errors:
                if error.startswith((self.excluded_products)):
                    continue
                error_msg = '{}: {}'.format(locale, error)
                if error_msg in exceptions:
                    continue
                error_msg = error_msg.replace(locale, checkname, 1)
                self.error_messages[locale].append(error_msg)
                total_errors += 1

        if total_errors:
            self.error_summary[checkname] = total_errors


def main():
    # Parse command line options
    cl_parser = argparse.ArgumentParser()
    cl_parser.add_argument(
        'check', help='Run a single check', default='all', nargs='?')
    args = cl_parser.parse_args()

    script_folder = os.path.dirname(os.path.realpath(__file__))
    checks = QualityCheck(script_folder, args.check)


if __name__ == '__main__':
    main()
