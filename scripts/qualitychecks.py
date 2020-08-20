#! /usr/bin/env python3

from collections import OrderedDict
from compare_locales.compare import compareProjects
from compare_locales.paths import TOMLParser, ConfigNotFound
from configparser import ConfigParser
from urllib.request import urlopen
import argparse
import datetime
import glob
import json
import os
import pickle
import re
import sys


class QualityCheck():

    excluded_products = (
        'calendar/',
        'chat/',
        'editor/',
        'extensions/',
        'mail/',
        'suite/',
    )

    def __init__(self, root_folder, tmx_path, l10nrepos_path, toml_path,
                 requested_check, verbose_mode, output_path):
        ''' Initialize object '''
        self.root_folder = root_folder
        self.tmx_path = tmx_path
        self.l10nrepos_path = l10nrepos_path
        self.toml_path = toml_path
        self.requested_check = requested_check
        self.verbose = verbose_mode
        self.output_path = output_path

        if self.output_path != '':
            # Read existing content
            self.archive_data = {}
            output_file = os.path.join(output_path, 'checks.json')
            if os.path.exists(output_file):
                try:
                    self.archive_data = json.load(open(output_file))
                except Exception as e:
                    print('Error loading JSON file {}'.format(output_file))
                    print(e)

        self.domain = 'https://transvision.flod.org'
        self.api_url = '{}/api/v1'.format(self.domain)

        self.general_errors = []

        self.date_key = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        print('\n--------\nRun: {}\n'.format(self.date_key))

        # Create a list of available checks in JSON format
        self.json_files = []
        for check in glob.glob('{}/*.json'.format(os.path.join(root_folder, 'checks'))):
            check = os.path.basename(check)
            self.json_files.append(os.path.splitext(check)[0])
        self.json_files.sort()

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

        # Check local TMX for FTL issues if available
        if requested_check == 'all' and self.tmx_path != '':
            self.checkTMX()

        # Run compare-locales checks if repos are available
        if requested_check == 'all' and self.l10nrepos_path != '':
            self.checkRepos()

        # Print errors
        if self.verbose:
            self.printErrors()

        # Compare with previous run
        if requested_check == 'all':
            self.comparePreviousRun()

    def comparePreviousRun(self):

        def diff(a, b):
            b = set(b)
            return [aa for aa in a if aa not in b]

        # Read the list of errors from a previous run (if available)
        pickle_file = os.path.join(self.root_folder, 'previous_errors.dump')
        previous_errors = {
            'errors': [],
            'summary': {}
        }
        if os.path.exists(pickle_file):
            try:
                with open(pickle_file, 'rb') as f:
                    previous_errors = pickle.load(f)
            except Exception as e:
                print(e)

        current_errors = []
        for locale, errors in self.error_messages.items():
            for e in errors:
                current_errors.append(u'{} - {}'.format(locale, e))
        current_errors.sort()

        changes = False
        new_errors = diff(current_errors, previous_errors['errors'])

        # Initialize output
        output = {
            'new': [],
            'fixed':  [],
            'message': [],
        }

        savetofile = self.output_path != ''
        if new_errors:
            changes = True
            print('New errors ({}):'.format(len(new_errors)))
            print('\n'.join(new_errors))
            output['new'] = new_errors
            output['message'].append('Total errors: {}'.format(len(current_errors)))

        fixed_errors = diff(previous_errors['errors'], current_errors)
        if fixed_errors:
            changes = True
            print('Fixed errors ({}):'.format(len(fixed_errors)))
            print('\n'.join(fixed_errors))
            output['fixed'] = fixed_errors
            if not output['message']:
                output['message'].append('Total errors: {}'.format(len(current_errors)))

        if 'compare-locales' in self.error_summary:
            # Create a starting point if the previous run doesn't have
            # compare-locales data
            if not 'compare-locales' in previous_errors['summary']:
                previous_errors['summary']['compare-locales'] = {
                    'errors': 0,
                    'warnings': 0
                }

            if self.error_summary['compare-locales'] != previous_errors['summary']['compare-locales']:
                changes = True
                warnings_change = self.error_summary['compare-locales']['warnings'] - \
                    previous_errors['summary']['compare-locales']['warnings']
                if warnings_change > 0:
                    output['message'].append('compare-locales warnings increased: {} ({})'.format(
                        self.error_summary['compare-locales']['warnings'],
                        warnings_change
                    ))
                elif warnings_change < 0:
                    output['message'].append('compare-locales warnings decreased: {} ({})'.format(
                        self.error_summary['compare-locales']['warnings'],
                        warnings_change
                    ))

                errors_change = self.error_summary['compare-locales']['errors'] - \
                    previous_errors['summary']['compare-locales']['errors']
                if errors_change > 0:
                    output['message'].append('compare-locales errors increased: {} ({})'.format(
                        self.error_summary['compare-locales']['errors'],
                        errors_change
                    ))
                elif errors_change < 0:
                    output['message'].append('compare-locales errors decreased: {} ({})'.format(
                        self.error_summary['compare-locales']['errors'],
                        errors_change
                    ))

        if not changes:
            print('No changes.')
            if savetofile:
                output['message'].append('No changes ({}).'.format(
                    len(current_errors)))

        for key in ['new', 'fixed']:
            if not output[key]:
                del output[key]

        if savetofile:
            if output['message']:
                output['message'] = '\n'.join(output['message'])
            self.archive_data[self.date_key] = output
            checks_file = os.path.join(self.output_path, 'checks.json')
            with open(checks_file, 'w') as outfile:
                json.dump(self.archive_data, outfile, sort_keys=True, indent=2)
            errors_file = os.path.join(self.output_path, 'errors.json')
            output_data = {
                'errors': current_errors,
                'summary': self.error_summary
            }
            with open(errors_file, 'w') as outfile:
                json.dump(output_data, outfile,
                          sort_keys=True, indent=2)

        # Write back the current list of errors
        with open(pickle_file, 'wb') as f:
            pickle.dump(output_data, f)

    def getJsonData(self, url, search_id):
        '''
        Return two values:
        - Array of data
        - If the request succeeded (boolean)
        '''
        for try_number in range(5):
            try:
                response = urlopen(url)
                json_data = json.load(response)
                return (json_data, True)
            except:
                # print('Error reading URL: {}'.format(url))
                continue

        self.general_errors.append('Error reading {}'.format(search_id))
        return ([], False)

    def getPluralForms(self):
        ''' Get the number of plural forms for each locale '''

        from compare_locales.plurals import get_plural

        url = '{}/entity/gecko_strings/?id=toolkit/chrome/global/intl.properties:pluralRule'.format(
            self.api_url)
        if self.verbose:
            print('Reading the list of plural forms')
        locales_plural_rules, success = self.getJsonData(
            url, 'list of plural forms')
        if not success:
            sys.exit('CRITICAL ERROR: List of plural forms not available')

        for locale, rule_number in locales_plural_rules.items():
            num_plurals = get_plural(locale)
            if num_plurals == None:
                # Temporary fix for szl
                if locale == 'szl':
                    num_plurals = 3
                else:
                    # Fall back to English
                    num_plurals = 2
            else:
                num_plurals = len(get_plural(locale))
            self.plural_forms[locale] = num_plurals

    def getLocales(self):
        ''' Get the list of supported locales '''
        if self.verbose:
            print('Reading the list of supported locales')
        url = '{}/locales/gecko_strings/'.format(self.api_url)
        self.locales, success = self.getJsonData(
            url, 'list of supported locales')
        # Remove en-US from locales
        self.locales.remove('en-US')
        if not success:
            sys.exit('CRITICAL ERROR: List of support locales not available')

    def printErrors(self):
        ''' Print error messages '''
        error_count = 0
        locales_with_errors = OrderedDict()
        for locale, errors in self.error_messages.items():
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
            for locale, num in locales_with_errors.items():
                print('- {} ({})'.format(locale, num))

        # Error summary
        if self.error_summary:
            print('\n----\nErrors summary by type:')
            for check, count in self.error_summary.items():
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
                    open(os.path.join(self.root_folder, 'checks', json_file + '.json')))
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
            if self.verbose:
                print('CHECK: {}'.format(json_file))
            try:
                checks = json.load(
                    open(os.path.join(self.root_folder, 'checks', json_file + '.json')))
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

                    for locale, translation in json_data.items():
                        # Ignore en-US
                        if locale == 'en-US':
                            continue

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
                                    error_msg = u'Missing {} ({}:{})'.format(
                                        t, c['file'], c['entity'])
                        elif c['type'] == 'include':
                            for t in c['checks']:
                                if t not in translation:
                                    error_msg = u'Missing {} ({}:{})'.format(
                                        t, c['file'], c['entity'])
                        elif c['type'] == 'not_include':
                            for t in c['checks']:
                                if t in translation:
                                    error_msg = u'Not expected text {} ({}:{})'.format(
                                        t, c['file'], c['entity'])
                        elif c['type'] == 'equal_to':
                            if c['value'].lower() != translation.lower():
                                error_msg = u'{} is not equal to {} ({}:{})'.format(
                                    translation, c['value'], c['file'], c['entity'])
                        elif c['type'] == 'not_equal_to':
                            if c['value'] == translation:
                                error_msg = u'{} is equal to {} ({}:{})'.format(
                                    translation, c['value'], c['file'], c['entity'])
                        elif c['type'] == 'acceptable_values':
                            if translation not in c['values']:
                                error_msg = u'{} is not an acceptable value ({}:{})'.format(
                                    translation, c['file'], c['entity'])
                        elif c['type'] == 'typeof':
                            if type(translation) != c['value']:
                                error_msg = u'{} is not of type {} ({}:{})'.format(
                                    translation, c['type'], c['file'], c['entity'])
                        elif c['type'] == 'bytes_length':
                            current_length = len(translation.encode('utf-8'))
                            if current_length > c['value']:
                                error_msg = u'String longer than {} bytes. Current length: {} bytes. Current text: {}. ({}:{})'.format(
                                    c['value'], current_length, translation, c['file'], c['entity'])
                        elif c['type'] == 'plural_forms':
                            num_forms = len(translation.split(';'))
                            if num_forms != self.plural_forms[locale]:
                                error_msg = u'String has {} plural forms, requested: {} ({}:{})'.format(
                                    num_forms, self.plural_forms[locale], c['file'], c['entity'])
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
            if self.verbose:
                print('CHECK: variables')
            url = '{}/variables/?locale={}&repo=gecko_strings&json'
        elif checkname == 'shortcuts':
            if self.verbose:
                print('CHECK: keyboard shortcuts')
            url = '{}/commandkeys/?locale={}&repo=gecko_strings&json'
        elif checkname == 'empty':
            if self.verbose:
                print('CHECK: empty strings')
            url = '{}/empty-strings/?locale={}&json'

        # Load individual locale exceptions
        exceptions = []
        exceptions_file = os.path.join(
            self.root_folder, 'exceptions', '{}.txt'.format(checkname))
        with open(exceptions_file) as f:
            for l in f:
                exceptions.append(l.rstrip())

        # Load general exclusions
        exclusions = []
        exclusions_file = os.path.join(
            self.root_folder, 'exceptions', 'exclusions.json')
        with open(exclusions_file) as f:
            json_data = json.load(f)
            if checkname in json_data:
                exclusions = json_data[checkname]

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
                if error in exclusions:
                    continue
                error_msg = '{}: {}'.format(locale, error)
                if error_msg in exceptions:
                    continue
                error_msg = error_msg.replace(locale, checkname, 1)
                self.error_messages[locale].append(error_msg)
                total_errors += 1

        if total_errors:
            self.error_summary[checkname] = total_errors

    def checkRepos(self):
        '''Run compare-locales against repos'''

        # Get the available locales
        locales = next(os.walk(self.l10nrepos_path))[1]
        locales.sort()

        configs = []
        config_env = {
            'l10n_base': self.l10nrepos_path
        }

        try:
            config = TOMLParser().parse(self.toml_path, env=config_env)
        except ConfigNotFound as e:
            print(e)
        configs.append(config)

        try:
            observers = compareProjects(
                configs,
                locales,
                self.l10nrepos_path)
        except (OSError, IOError) as exc:
            sys.exit('Error running compare-locales checks: ' + str(exc))

        data = [observer.toJSON() for observer in observers]

        total_errors = 0
        total_warnings = 0
        for locale, locale_data in data[0]['summary'].items():
            if locale_data['errors'] > 0:
                error_msg = 'compare-locales errors'
                total_errors += locale_data['errors']
                self.error_messages[locale].append(error_msg)
            if locale_data['warnings'] > 0:
                total_warnings += locale_data['warnings']

        self.error_summary['compare-locales'] = {
            'errors': total_errors,
            'warnings': total_warnings
        }


    def checkTMX (self):
        '''Check local TMX for issues, mostly on FTL files'''

        if self.verbose:
            print('Reading TMX data from Transvision')

        datal10n_pattern = re.compile(
            'data-l10n-name\s*=\s*"([a-zA-Z\-]*)"', re.UNICODE)
        css_pattern = re.compile('[^\d]*', re.UNICODE)

        strings_to_ignore = [
            'browser/browser/aboutDialog.ftl:channel-description',
            'browser/browser/browserSets.ftl:full-zoom-enlarge-shortcut-alt2.key',
            'browser/browser/browserSets.ftl:full-zoom-reduce-shortcut-alt-b.key',
            'browser/browser/browserSets.ftl:full-zoom-reduce-shortcut-alt.key',
            'browser/browser/browserSets.ftl:full-zoom-reset-shortcut-alt.key',
            'browser/browser/browserSets.ftl:picture-in-picture-toggle-shortcut-alt.key',
            'browser/browser/preferences/preferences.ftl:forms-primary-pw-former-name',
            'browser/browser/sanitize.ftl:clear-time-duration-prefix.value',
            'browser/browser/sanitize.ftl:clear-time-duration-suffix.value',
        ]

        locale_exceptions = {
            'de': [
                'browser/browser/sanitize.ftl:clear-time-duration-prefix.accesskey',
            ],
        }

        excluded_folders = (
            'calendar',
            'chat',
            'editor',
            'extensions',
            'mail',
            'other-licenses',
            'suite'
        )

        exceptions_http = [
            'browser/browser/aboutLogins.ftl:login-item-origin.placeholder',
            'browser/chrome/browser/browser.properties:certImminentDistrust.message',
            'devtools/client/scratchpad.properties:help.openDocumentationPage',
            'dom/chrome/dom/dom.properties:ImplicitMetaViewportTagFallback',
            'dom/chrome/dom/dom.properties:MediaWidevineNoWMF',
            'dom/chrome/dom/dom.properties:MediaWMFNeeded',
            'dom/chrome/dom/dom.properties:PushMessageBadCryptoError',
            'dom/chrome/dom/dom.properties:PushMessageBadCryptoKeyHeader',
            'dom/chrome/dom/dom.properties:PushMessageBadEncodingHeader',
            'dom/chrome/dom/dom.properties:PushMessageBadEncryptionHeader',
            'dom/chrome/dom/dom.properties:PushMessageBadEncryptionKeyHeader',
            'dom/chrome/dom/dom.properties:PushMessageBadPaddingError',
            'dom/chrome/dom/dom.properties:PushMessageBadRecordSize',
            'dom/chrome/dom/dom.properties:PushMessageBadSalt',
            'dom/chrome/dom/dom.properties:PushMessageBadSenderKey',
            'dom/chrome/dom/dom.properties:ShowModalDialogWarning',
            'dom/chrome/dom/dom.properties:SpeculationFailed',
            'dom/chrome/dom/dom.properties:SyncXMLHttpRequestWarning',
            'dom/chrome/dom/dom.properties:UseOfCaptureEventsWarning',
            'dom/chrome/dom/dom.properties:UseOfDOM3LoadMethodWarning',
            'dom/chrome/dom/dom.properties:UseOfReleaseEventsWarning',
            'dom/chrome/layout/layout_errors.properties:PrincipalWritingModePropagationWarning',
            'dom/chrome/layout/layout_errors.properties:ScrollLinkedEffectFound2',
            'dom/chrome/plugins.properties:cdm_description2',
            'dom/chrome/plugins.properties:openH264_description2',
            'dom/chrome/security/security.properties:InsecureFormActionPasswordsPresent',
            'dom/chrome/security/security.properties:InsecurePasswordsPresentOnIframe',
            'dom/chrome/security/security.properties:InsecurePasswordsPresentOnPage',
            'mobile/overrides/netError.dtd:malformedURI.longDesc2',
            'toolkit/toolkit/featuregates/features.ftl:experimental-features-cookie-samesite-schemeful-description',
        ]

        exceptions_xml = [
            'toolkit/toolkit/about/certviewer.ftl:certificate-viewer-unsupported',
            'toolkit/toolkit/featuregates/features.ftl:experimental-features-web-api-link-preload-description',
            'toolkit/toolkit/featuregates/features.ftl:experimental-features-web-api-beforeinput-description',
        ]

        # Some keys need to be defined
        mandatory_keys = [
            "toolkit/defines.inc:MOZ_LANG_TITLE",
            "toolkit/chrome/global/intl.properties:intl.accept_languages",
            "toolkit/chrome/global/intl.properties:font.language.group",
            "toolkit/chrome/global/intl.properties:pluralRule",
        ]

        # Read source data (en-US)
        ref_tmx_path = os.path.join(self.tmx_path, 'en-US',
                                    'cache_en-US_gecko_strings.json')
        with open(ref_tmx_path) as f:
            reference_data = json.load(f)

        # Remove strings from other products and irrelevant files
        reference_ids =[]
        for id in reference_data.keys():
            if 'region.properties' in id:
                continue

            if not id.startswith(excluded_folders):
                reference_ids.append(id)

        '''
        Store specific English strings for addictional FTL checks:
        - Strings with data-l10n-names
        - Strings with .style attributes
        '''
        ftl_ids = []
        data_l10n_ids = {}
        CSS_strings = {}
        for id, text in reference_data.items():
            file_id, message_id = id.split(':')

            # Ignore non ftl strings
            if not file_id.endswith('.ftl'):
                continue

            # Ignore strings from other products
            if file_id.startswith(excluded_folders):
                continue

            ftl_ids.append(id)

            matches_iterator = datal10n_pattern.finditer(text)
            matches = []
            for m in matches_iterator:
                matches.append(m.group(1))
            if matches:
                # Remove duplicates
                matches = list(set(matches))
                data_l10n_ids[id] = sorted(matches)

            if message_id.endswith('.style'):
                # Alway strip the closing ';', to avoid errors on mismatches
                matches = css_pattern.findall(text.rstrip(';'))
                # Drop empty elements, ignore period for decimals
                matches = [m for m in matches if m not in ['', '.']]
                CSS_strings[id] = matches

        for locale in self.locales:
            tmx_path = os.path.join(
                self.tmx_path, locale,
                'cache_{}_gecko_strings.json'.format(locale))
            with open(tmx_path) as f:
                locale_data = json.load(f)

            # Check for untranslated mandatory keys
            for string_id in mandatory_keys:
                if string_id not in locale_data:
                    error_msg = 'Missing translation for mandatory key ({})'.format(string_id)
                    self.error_messages[locale].append(error_msg)

            # General checks (all strings)
            for string_id in reference_ids:
                # Ignore untranslated strings
                if string_id not in locale_data:
                    continue

                # Ignore exceptions
                if string_id in strings_to_ignore:
                    continue
                if locale in locale_exceptions and string_id in locale_exceptions[locale]:
                    continue

                translation = locale_data[string_id]

                # Check for links in strings
                if string_id not in exceptions_http:
                    pattern = re.compile('http(s)*:\/\/', re.UNICODE)
                    if pattern.search(translation):
                        error_msg = 'Link in string ({})'.format(string_id)
                        self.error_messages[locale].append(error_msg)

            # FTL checks
            for string_id in ftl_ids:
                # Ignore untranslated strings
                if string_id not in locale_data:
                    continue

                # Ignore exceptions
                if string_id in strings_to_ignore:
                    continue
                if locale in locale_exceptions and string_id in locale_exceptions[locale]:
                    continue

                translation = locale_data[string_id]

                # Check for stray spaces
                if '{ "' in translation:
                    error_msg = 'Fluent literal in string ({})'.format(
                        string_id)
                    self.error_messages[locale].append(error_msg)

                # Check for DTD variables, e.g. '&something;'
                pattern = re.compile('&.*;', re.UNICODE)
                if pattern.search(translation):
                    if string_id in exceptions_xml:
                        continue
                    error_msg = 'XML entity in Fluent string ({})'.format(
                        string_id)
                    self.error_messages[locale].append(error_msg)

                # Check for properties variables '%S' or '%1$S'
                pattern = re.compile(
                    '(%(?:[0-9]+\$){0,1}(?:[0-9].){0,1}([sS]))', re.UNICODE)
                if pattern.search(translation):
                    error_msg = 'printf variables in Fluent string ({})'.format(
                        string_id)
                    self.error_messages[locale].append(error_msg)

                # Check for the message ID repeated in the translation
                message_id = string_id.split(':')[1]
                pattern = re.compile(re.escape(message_id) + '\s*=', re.UNICODE)
                if pattern.search(translation):
                    error_msg = 'Message ID is repeated in the Fluent string ({})'.format(
                        string_id)
                    self.error_messages[locale].append(error_msg)

            # Check data-l10n-names
            for string_id, groups in data_l10n_ids.items():
                if string_id not in locale_data:
                    continue

                translation = locale_data[string_id]
                matches_iterator = datal10n_pattern.finditer(translation)
                matches = []
                for m in matches_iterator:
                    matches.append(m.group(1))
                # Remove duplicates
                matches = list(set(matches))
                if matches:
                    translated_groups = sorted(matches)
                    if translated_groups != groups:
                        # Groups are not matching
                        error_msg = 'data-l10n-name mismatch in Fluent string ({})'.format(
                            string_id)
                        self.error_messages[locale].append(error_msg)
                else:
                    # There are no data-l10n-name
                    error_msg = 'data-l10n-name missing in Fluent string ({})'.format(
                        string_id)
                    self.error_messages[locale].append(error_msg)


            # Check for CSS mismatches
            for string_id, cleaned_source in CSS_strings.items():
                if string_id not in locale_data:
                    continue

                # Alway strip the closing ';', to avoid errors on mismatches
                translation = locale_data[string_id].rstrip(';')
                matches = css_pattern.findall(translation)
                # Drop empty elements, ignore period for decimals
                cleaned_translation = [m for m in matches if m not in ['', '.']]
                if cleaned_translation != cleaned_source:
                    # Groups are not matching
                    error_msg = 'CSS mismatch in Fluent string ({})'.format(
                        string_id)
                    self.error_messages[locale].append(error_msg)


def main():
    # Parse command line options
    cl_parser = argparse.ArgumentParser()
    cl_parser.add_argument(
        'check', help='Run a single check', default='all', nargs='?')
    cl_parser.add_argument('--verbose', dest='verbose', action='store_true')
    cl_parser.add_argument(
        '-output', nargs='?',
        help='Path to folder where to store output in JSON format',
        default='')
    args = cl_parser.parse_args()

    # Check if there's a config file (optional)
    root_folder = os.path.join(os.path.dirname(
        os.path.realpath(__file__)), os.pardir)
    config_file = os.path.join(root_folder, 'config', 'config.ini')

    tmx_path = ''
    if os.path.isfile(config_file):
        config_parser = ConfigParser()
        config_parser.read(config_file)

        def getConfig(key):
            try:
                value = config_parser.get('config', key)
                if key != 'toml_path':
                    value = os.path.join(value, '')
            except:
                print('{key} not found in config.ini')
            if not os.path.exists(value):
                print(f'Path in {key} is not valid: {value}')
                value = ''

            return value

        tmx_path = getConfig('tmx_path')
        l10nrepos_path = getConfig('l10nrepos_path')
        toml_path = getConfig('toml_path')

    # Check if checks are already running for some reason
    semaphore = os.path.join(root_folder, '.running')
    if os.path.isfile(semaphore):
        sys.exit('Checks are already running')
    else:
        try:
            open(semaphore, 'w')
        except:
            sys.exit('Can\'t create semaphore file')

    QualityCheck(
        root_folder, tmx_path, l10nrepos_path, toml_path,
        args.check, args.verbose, args.output)

    # Remove semaphore file
    os.remove(semaphore)

if __name__ == '__main__':
    main()
