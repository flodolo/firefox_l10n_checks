#! /usr/bin/env python

import json
import os
import re
import sys
import urllib2

filenames = [
	'browser_dtd',
	'intl_properties',
	'mobile_phishing_dtd',
	'netError_dtd',
	'phishing-afterload-warning-message_dtd',
]
url = 'https://transvision.flod.org/api/v1/entity/central/?id={}:{}'

script_folder = os.path.dirname(os.path.realpath(__file__))
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
						if not re.search(t, str):
							print(u'  {}: missing {} in {}'.format(locale, t, c['entity']))
				elif c['type'] == 'include':
					for t in c['checks']:
						if t not in str:
							print(u'  {}: missing {} in {}'.format(locale, t, c['entity']))
				elif c['type'] == 'equal_to':
					if c['value'] != str:
						print(u'  {}: {} not equal to {} in {}'.format(locale, str, c['value'], c['entity']))
				elif c['type'] == 'not_equal_to':
					if c['value'] == str:
						print(u'  {}: {} is equal to {} in {}'.format(locale, str, c['value'], c['entity']))
				elif c['type'] == 'acceptable_values':
					if str not in c['values']:
						print(u'  {}: {} is not an acceptable value'.format(locale, str))
				elif c['type'] == 'typeof':
					if type(str) != c['value']:
						print(u'  {}: {} is not of type'.format(locale, str))
		except Exception as e:
			print(e)
