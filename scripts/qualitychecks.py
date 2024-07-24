#! /usr/bin/env python3

from collections import OrderedDict
from compare_locales.compare import compareProjects
from compare_locales.paths import TOMLParser, ConfigNotFound
from configparser import ConfigParser
from custom_html_parser import MyHTMLParser
from fluent.syntax import parse, visitor
from fluent.syntax.serializer import FluentSerializer
from urllib.request import urlopen
import argparse
import datetime
import glob
import json
import os
import pickle
import re
import sys


class flattenSelectExpression(visitor.Transformer):
    def visit_SelectExpression(self, node):
        for variant in node.variants:
            if variant.default:
                default_variant = variant
                break

        node.variants = [default_variant]

        return node


class QualityCheck:

    excluded_products = (
        "calendar",
        "chat",
        "editor",
        "extensions",
        "mail",
        "other-licenses",
        "suite",
    )

    def __init__(
        self,
        root_folder,
        tmx_path,
        firefoxl10n_path,
        toml_path,
        requested_check,
        cli_options,
        output_path,
    ):
        """Initialize object"""
        self.root_folder = root_folder
        self.tmx_path = tmx_path
        self.firefoxl10n_path = firefoxl10n_path
        self.toml_path = toml_path
        self.requested_check = requested_check
        self.verbose = cli_options["verbose"]
        self.output_path = output_path

        if self.output_path != "":
            # Read existing content
            self.archive_data = {}
            output_file = os.path.join(output_path, "checks.json")
            if os.path.exists(output_file):
                try:
                    self.archive_data = json.load(open(output_file))
                except Exception as e:
                    print(f"Error loading JSON file {output_file}")
                    print(e)

        self.transvision_url = "https://transvision.flod.org"
        self.api_url = f"{self.transvision_url}/api/v1"

        self.general_errors = []

        start_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        print(f"\n--------\nRun: {start_datetime}\n")

        # Create a list of available checks in JSON format
        self.json_files = []
        for check in glob.glob("{}/*.json".format(os.path.join(root_folder, "checks"))):
            check = os.path.basename(check)
            self.json_files.append(os.path.splitext(check)[0])
        self.json_files.sort()

        # Get the list of supported locales
        if cli_options["locale"] is None:
            self.getLocales()
        else:
            self.locales = [cli_options["locale"]]

        # Store the number of plural forms for each locale
        self.plural_forms = {}
        self.getPluralForms()

        # Initialize other error messages
        self.error_messages = OrderedDict()
        self.error_summary = {}
        self.output_cl = {"errors": {}, "warnings": {}}
        for locale in self.locales:
            self.error_messages[locale] = []

        # Run checks
        if not cli_options["tmx"]:
            self.checkAPI()
            if requested_check == "all":
                self.checkView("variables")
                self.checkView("shortcuts")
                self.checkView("empty")

        # Check local TMX for FTL issues if available
        if requested_check == "all" and self.tmx_path != "":
            self.checkTMX()

        # Run compare-locales checks if repos are available
        if (
            not cli_options["tmx"]
            and requested_check == "all"
            and self.firefoxl10n_path != ""
        ):
            self.checkRepos()

        # Print errors
        if self.verbose:
            self.printErrors()

        # Compare with previous run
        if requested_check == "all":
            self.comparePreviousRun()

    def comparePreviousRun(self):
        def diff(a, b):
            b = set(b)
            return [aa for aa in a if aa not in b]

        def findDifferences(type, current, previous, output):
            changes = False
            new = diff(current, previous)
            if new:
                changes = True
                output["new"] += new
                print(f"New {type} ({len(new)}):")
                print("\n".join(new))

            fixed = diff(previous, current)
            if fixed:
                changes = True
                output["fixed"] += fixed
                print(f"Fixed {type} ({len(fixed)}):")
                print("\n".join(fixed))

            if changes:
                output["message"].append(f"Total {type}: {len(current)}")

            return changes

        # Read the list of errors from a previous run (if available)
        pickle_file = os.path.join(self.root_folder, "previous_errors.dump")
        previous_errors = {"errors": [], "compare-locales": [], "summary": {}}
        if os.path.exists(pickle_file):
            try:
                with open(pickle_file, "rb") as f:
                    previous_errors = pickle.load(f)
            except Exception as e:
                print(e)

        current_errors = []
        for locale, errors in self.error_messages.items():
            for e in errors:
                current_errors.append(f"{locale} - {e}")
        current_errors.sort()

        changes = False
        changes_cl = False
        # Initialize output
        output = {
            "new": [],
            "fixed": [],
            "message": [],
        }
        savetofile = self.output_path != ""

        changes = findDifferences(
            "errors", current_errors, previous_errors["errors"], output
        )

        flattened_cl = []
        for locale, warnings in self.output_cl["warnings"].items():
            for w in warnings:
                flattened_cl.append(f"{locale} (compare-locales warning): {w}")
        for locale, errors in self.output_cl["errors"].items():
            for e in errors:
                flattened_cl.append(f"{locale} (compare-locales error): {e}")
        flattened_cl.sort()
        previous_cl_output = previous_errors.get("compare-locales", [])
        changes_cl = findDifferences(
            "compare-locale errors", flattened_cl, previous_cl_output, output
        )

        if not changes and not changes_cl:
            print("No changes.")
            if savetofile:
                output["message"].append(f"No changes ({len(current_errors)}).")

        for key in ["new", "fixed"]:
            if not output[key]:
                del output[key]

        if savetofile:
            if output["message"]:
                output["message"] = "\n".join(output["message"])
            end_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            self.archive_data[end_datetime] = output
            checks_file = os.path.join(self.output_path, "checks.json")
            with open(checks_file, "w") as outfile:
                json.dump(self.archive_data, outfile, sort_keys=True, indent=2)
            errors_file = os.path.join(self.output_path, "errors.json")
            output_data = {
                "errors": current_errors,
                "compare-locales": flattened_cl,
                "summary": self.error_summary,
            }
            with open(errors_file, "w") as outfile:
                json.dump(output_data, outfile, sort_keys=True, indent=2)

            # Write back the current list of errors
            with open(pickle_file, "wb") as f:
                pickle.dump(output_data, f)

    def getJsonData(self, url, search_id):
        """
        Return two values:
        - Array of data
        - If the request succeeded (boolean)
        """
        for try_number in range(5):
            try:
                response = urlopen(url)
                json_data = json.load(response)
                return (json_data, True)
            except:
                # print(f"Error reading URL: {url}")
                continue

        self.general_errors.append(f"Error reading {search_id}")
        return ([], False)

    def getPluralForms(self):
        """Get the number of plural forms for each locale"""

        from compare_locales.plurals import get_plural

        url = f"{self.api_url}/entity/gecko_strings/?id=toolkit/chrome/global/intl.properties:pluralRule"
        if self.verbose:
            print("Reading the list of plural forms")
        locales_plural_rules, success = self.getJsonData(url, "list of plural forms")
        if not success:
            sys.exit("CRITICAL ERROR: List of plural forms not available")

        for locale, rule_number in locales_plural_rules.items():
            num_plurals = get_plural(locale)
            if num_plurals is None:
                # Temporary fix for szl
                if locale == "szl":
                    num_plurals = 3
                else:
                    # Fall back to English
                    num_plurals = 2
            else:
                num_plurals = len(get_plural(locale))
            self.plural_forms[locale] = num_plurals

    def getLocales(self):
        """Get the list of supported locales"""
        if self.verbose:
            print("Reading the list of supported locales")
        url = f"{self.api_url}/locales/gecko_strings/"
        self.locales, success = self.getJsonData(url, "list of supported locales")
        # Remove en-US from locales
        self.locales.remove("en-US")
        if not success:
            sys.exit("CRITICAL ERROR: List of support locales not available")

    def printErrors(self):
        """Print error messages"""
        error_count = 0
        locales_with_errors = OrderedDict()
        for locale, errors in self.error_messages.items():
            if errors:
                num_errors = len(errors)
                print(f"\n----\nLocale: {locale} ({num_errors})")
                locales_with_errors[locale] = num_errors
                error_count += num_errors
                for e in errors:
                    print(f"- {e}")
        if error_count:
            print(f"\n----\nTotal errors: {error_count}")
        else:
            print("\n----\nNo errors")

        if locales_with_errors:
            print(f"\n----\nLocales with errors ({len(locales_with_errors)} locales):")
            for locale, num in locales_with_errors.items():
                print(f"- {locale} ({num})")

        # Error summary
        if self.error_summary:
            print("\n----\nErrors summary by type:")
            for check, count in self.error_summary.items():
                print(f"- {check}: {count}")

        # General error (e.g. invalid API calls)
        if self.general_errors:
            print(f"\n----\nGeneral errors ({len(self.general_errors)} errors):")
            self.general_errors.sort()
            print("\n".join(self.general_errors))

    def sanityCheckJSON(self):
        """Do a sanity check on JSON files, checking for duplicates"""
        for json_file in self.json_files:
            try:
                checks = json.load(
                    open(os.path.join(self.root_folder, "checks", json_file + ".json"))
                )
            except Exception as e:
                print(f"Error loading JSON file {json_file}")
                sys.exit(e)

            available_checks = []
            for c in checks:
                id = f"{c['file']}-{c['entity']}-{c['type']}"
                if id in available_checks:
                    print(f"WARNING: check {id} is duplicated")
                    continue
                available_checks.append(id)

    def checkAPI(self):
        """Check strings via API requests"""
        self.sanityCheckJSON()
        if self.requested_check != "all":
            if self.requested_check not in self.json_files:
                print(
                    f"ERROR: The requested check ({self.requested_check}) does not exist. Available checks:"
                )
                for f in self.json_files:
                    print(f"- {f}")
                sys.exit(1)
            else:
                self.json_files = [self.requested_check]

        url = "{}/entity/gecko_strings/?id={}:{}"

        for json_file in self.json_files:
            total_errors = 0
            if self.verbose:
                print(f"CHECK: {json_file}")
            try:
                checks = json.load(
                    open(os.path.join(self.root_folder, "checks", json_file + ".json"))
                )
            except Exception as e:
                print(f"Error loading JSON file {json_file}")
                sys.exit(e)

            for c in checks:
                try:
                    # print(f"Checking {c['entity']}")
                    json_data, success = self.getJsonData(
                        url.format(self.api_url, c["file"], c["entity"]),
                        f"{c['file']}:{c['entity']}",
                    )

                    if not success:
                        self.general_errors.append(
                            f"Error checking {c['file']}:{c['entity']}"
                        )
                        continue

                    for locale, translation in json_data.items():
                        # Ignore en-US
                        if locale == "en-US":
                            continue

                        # Ignore some locales if exclusions are defined
                        if "excluded_locales" in c and locale in c["excluded_locales"]:
                            continue
                        if (
                            "included_locales" in c
                            and locale not in c["included_locales"]
                        ):
                            continue

                        error_msg = []
                        if c["type"] == "include_regex":
                            for t in c["checks"]:
                                pattern = re.compile(t, re.UNICODE)
                                if not pattern.search(translation):
                                    error_msg.append(
                                        f"Missing {t} ({c['file']}:{c['entity']})"
                                    )
                        if c["type"] == "not_include_regex":
                            for t in c["checks"]:
                                pattern = re.compile(t, re.UNICODE)
                                if pattern.search(translation):
                                    error_msg.append(
                                        f"String includes {t} ({c['file']}:{c['entity']})"
                                    )
                        elif c["type"] == "include":
                            for t in c["checks"]:
                                if t not in translation:
                                    error_msg.append(
                                        f"Missing {t} ({c['file']}:{c['entity']})"
                                    )
                        elif c["type"] == "not_include":
                            for t in c["checks"]:
                                if t in translation:
                                    error_msg.append(
                                        f"Not expected text {t} ({c['file']}:{c['entity']})"
                                    )
                        elif c["type"] == "equal_to":
                            if c["value"].lower() != translation.lower():
                                error_msg.append(
                                    f"{translation} is not equal to {c['value']} ({c['file']}:{c['entity']})"
                                )
                        elif c["type"] == "not_equal_to":
                            if c["value"] == translation:
                                error_msg.append(
                                    f"{translation} is equal to {c['value']} ({c['file']}:{c['entity']})"
                                )
                        elif c["type"] == "acceptable_values":
                            if translation not in c["values"]:
                                error_msg.append(
                                    f"{translation} is not an acceptable value ({c['file']}:{c['entity']})"
                                )
                        elif c["type"] == "typeof":
                            if type(translation) != c["value"]:
                                error_msg.append(
                                    f"{translation} is not of type {c['type']} ({c['file']}:{c['entity']})"
                                )
                        elif c["type"] == "bytes_length":
                            current_length = len(translation.encode("utf-8"))
                            if current_length > c["value"]:
                                error_msg.append(
                                    f"String longer than {c['value']} bytes. Current length: {current_length} bytes. Current text: {translation}. ({c['file']}:{c['entity']})"
                                )
                        elif c["type"] == "plural_forms":
                            num_forms = len(translation.split(";"))
                            if num_forms != self.plural_forms[locale]:
                                error_msg.append(
                                    f"String has {num_forms} plural forms, requested: {self.plural_forms[locale]} ({c['file']}:{c['entity']})"
                                )
                        if error_msg:
                            self.error_messages[locale] += error_msg
                            total_errors += 1
                except Exception as e:
                    print(e)
            if total_errors:
                self.error_summary[json_file] = total_errors

    def checkView(self, checkname):
        """Check views for access keys and keyboard shortcuts"""
        if checkname == "variables":
            if self.verbose:
                print("CHECK: variables")
            url = "{}/variables/?locale={}&repo=gecko_strings&json"
        elif checkname == "shortcuts":
            if self.verbose:
                print("CHECK: keyboard shortcuts")
            url = "{}/commandkeys/?locale={}&repo=gecko_strings&json"
        elif checkname == "empty":
            if self.verbose:
                print("CHECK: empty strings")
            url = "{}/empty-strings/?locale={}&json"

        # Load individual locale exceptions
        exceptions = []
        exceptions_file = os.path.join(
            self.root_folder, "exceptions", f"{checkname}.txt"
        )
        with open(exceptions_file) as f:
            for line in f:
                exceptions.append(line.rstrip())

        # Load general exclusions
        exclusions = []
        exclusions_file = os.path.join(
            self.root_folder, "exceptions", "exclusions.json"
        )
        with open(exclusions_file) as f:
            json_data = json.load(f)
            if checkname in json_data:
                exclusions = json_data[checkname]

        total_errors = 0
        for locale in self.locales:
            errors, success = self.getJsonData(
                url.format(self.transvision_url, locale),
                f"{checkname} for {locale}",
            )

            if not success:
                self.general_errors.append(
                    f"Error checking *{checkname}* for locale {locale}"
                )
                continue

            for error in errors:
                if error.startswith((self.excluded_products)):
                    continue
                if error in exclusions:
                    continue
                error_msg = f"{locale}: {error}"
                if error_msg in exceptions:
                    continue
                error_msg = error_msg.replace(locale, checkname, 1)
                self.error_messages[locale].append(error_msg)
                total_errors += 1

        if total_errors:
            self.error_summary[checkname] = total_errors

    def checkRepos(self):
        """Run compare-locales against repos"""

        def extractCompareLocalesMessages(data, cl_output):
            """Traverse JSON results to extract warnings and errors"""

            for node, node_data in data.items():
                if isinstance(node_data, list):
                    for line in node_data:
                        # Store the message without line and column, since
                        # those change frequently.
                        if "warning" in line:
                            msg = re.sub(
                                " at line [\d]+, column [\d]+", "", line["warning"]
                            )
                            cl_output["warnings"].append(msg)
                        if "error" in line:
                            msg = re.sub(
                                " at line [\d]+, column [\d]+", "", line["error"]
                            )
                            cl_output["errors"].append(msg)
                else:
                    extractCompareLocalesMessages(node_data, cl_output)

        # Get the available locales
        locales = next(os.walk(self.firefoxl10n_path))[1]
        locales.sort()

        configs = []
        config_env = {"l10n_base": self.firefoxl10n_path}

        try:
            config = TOMLParser().parse(self.toml_path, env=config_env)
        except ConfigNotFound as e:
            print(e)
        configs.append(config)

        try:
            observers = compareProjects(configs, locales, self.firefoxl10n_path)
        except (OSError, IOError) as exc:
            sys.exit("Error running compare-locales checks: " + str(exc))

        data = [observer.toJSON() for observer in observers]

        total_errors = 0
        total_warnings = 0

        """
        There's no guarantee that a "locale" key is present, it could
        be "it/browser". Create a mapping between locale code and their
        first key.
        """
        details_keys = list(data[0]["details"].keys())
        keys_mapping = {}
        for k in details_keys:
            if os.path.sep in k:
                keys_mapping[k.split(os.path.sep)[0]] = k

        for locale, locale_data in data[0]["summary"].items():
            if locale_data["errors"] + locale_data["warnings"] == 0:
                continue

            # Extract all warning and error messages
            cl_output = {"errors": [], "warnings": []}

            locale_key = keys_mapping.get(locale, locale)
            extractCompareLocalesMessages(data[0]["details"][locale_key], cl_output)

            if locale_data["errors"] > 0:
                if locale not in self.output_cl["errors"]:
                    self.output_cl["errors"][locale] = []
                total_errors += locale_data["errors"]
                self.output_cl["errors"][locale] = cl_output["errors"]
            if locale_data["warnings"] > 0:
                if locale not in self.output_cl["warnings"]:
                    self.output_cl["warnings"][locale] = []
                total_warnings += locale_data["warnings"]
                self.output_cl["warnings"][locale] = cl_output["warnings"]

        self.error_summary["compare-locales"] = {
            "errors": total_errors,
            "warnings": total_warnings,
        }

    def checkTMX(self):
        """Check local TMX for issues, mostly on FTL files"""

        def ignoreString(string_id, locale_data, exclusion_type):
            # Ignore untranslated strings
            if string_id not in locale_data:
                return True

            # Ignore strings from other products
            if string_id.startswith(self.excluded_products):
                return True

            # Check if entire file is excluded
            if (
                "files" in exclusions[exclusion_type]
                and string_id.split(":")[0] in exclusions[exclusion_type]["files"]
            ):
                return True

            # Ignore excluded strings
            if string_id in exclusions[exclusion_type]["strings"]:
                return True
            if (
                locale in exclusions[exclusion_type]["locales"]
                and string_id in exclusions[exclusion_type]["locales"][locale]
            ):
                return True

            return False

        if self.verbose:
            print("Reading TMX data from Transvision")

        datal10n_pattern = re.compile(
            r'data-l10n-name\s*=\s*"([a-zA-Z\-]*)"', re.UNICODE
        )
        placeable_pattern = re.compile(
            r'(?<!\{)\{\s*([\$|-]?[\w.-]+)(?:[\[(]?[\w.\-, :"]+[\])])*\s*\}', re.UNICODE
        )
        css_pattern = re.compile("[^\d]*", re.UNICODE)

        # Load TMX exclusions
        exclusions = {}
        exclusions_file = os.path.join(
            self.root_folder, "exceptions", "exclusions_tmx.json"
        )
        with open(exclusions_file) as f:
            exclusions = json.load(f)

        # Read source data (en-US)
        ref_tmx_path = os.path.join(
            self.tmx_path, "en-US", "cache_en-US_gecko_strings.json"
        )
        with open(ref_tmx_path) as f:
            reference_data = json.load(f)

        # Remove strings from other products and irrelevant files
        reference_ids = []
        for id in reference_data.keys():
            if "region.properties" in id:
                continue

            if not id.startswith(self.excluded_products):
                reference_ids.append(id)

        # Verify if there are non existing strings in the exclusions file,
        # report as error if there are
        for key, key_data in exclusions.items():
            for grp, grp_data in key_data.items():
                if grp == "files":
                    continue
                if grp == "locales":
                    for locale, locale_ids in grp_data.items():
                        for locale_id in locale_ids:
                            if locale_id not in reference_data:
                                self.general_errors.append(
                                    f"Non existing strings in exclusions_tmx.json ({key}, {grp}): {locale_id}"
                                )
                else:
                    for id in grp_data:
                        if id not in reference_data:
                            self.general_errors.append(
                                f"Non existing strings in exclusions_tmx.json ({key}, {grp}): {id}"
                            )

        """
        Store specific English strings for additional FTL checks:
        - Strings with data-l10n-names
        - Strings with .style attributes
        """
        ftl_ids = []
        data_l10n_ids = {}
        CSS_strings = {}
        for id, text in reference_data.items():
            file_id, message_id = id.split(":")

            # Ignore non ftl strings
            if not file_id.endswith(".ftl"):
                continue

            # Ignore strings from other products
            if file_id.startswith(self.excluded_products):
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

            if message_id.endswith(".style"):
                # Alway strip the closing ';', to avoid errors on mismatches
                matches = css_pattern.findall(text.rstrip(";"))
                # Drop empty elements, ignore period for decimals
                matches = [m for m in matches if m not in ["", "."]]
                CSS_strings[id] = matches

        # Store strings with HTML elements
        html_parser = MyHTMLParser()
        html_strings = {}
        for id, text in reference_data.items():
            if "*[" in text:
                resource = parse(f"temp_id = {text}")
                flattener = flattenSelectExpression()
                serializer = FluentSerializer()
                text = serializer.serialize(flattener.visit(resource))

            # Remove Fluent placeables before parsing HTML, because the parser
            # will consider curly parentheses and other elements as starting
            # tags.
            cleaned_text = placeable_pattern.sub("", text)
            html_parser.clear()
            html_parser.feed(cleaned_text)

            tags = html_parser.get_tags()
            if tags:
                html_strings[id] = tags

        tmx_errors = 0
        for locale in self.locales:
            tmx_path = os.path.join(
                self.tmx_path, locale, f"cache_{locale}_gecko_strings.json"
            )
            with open(tmx_path) as f:
                locale_data = json.load(f)

            # Check for untranslated mandatory keys
            for string_id in exclusions["mandatory"]["strings"]:
                if string_id not in locale_data:
                    error_msg = f"Missing translation for mandatory key ({string_id})"
                    self.error_messages[locale].append(error_msg)
                    tmx_errors += 1

            # General checks (all strings)
            for string_id in reference_ids:
                # Ignore strings
                if ignoreString(string_id, locale_data, "ignore"):
                    continue

                translation = locale_data[string_id]

                # Check for links in strings
                if not ignoreString(string_id, locale_data, "http"):
                    pattern = re.compile("http(s)*:\/\/", re.UNICODE)
                    if pattern.search(translation):
                        error_msg = f"Link in string ({string_id})"
                        self.error_messages[locale].append(error_msg)
                        tmx_errors += 1

                # Check for pilcrow character
                if "¶" in translation:
                    error_msg = f"Pilcrow character in string ({string_id})"
                    self.error_messages[locale].append(error_msg)
                    tmx_errors += 1

            # Check for HTML elements mismatch
            html_parser = MyHTMLParser()
            for string_id, ref_tags in html_strings.items():
                # Ignore strings
                if ignoreString(string_id, locale_data, "HTML"):
                    continue

                translation = locale_data[string_id]
                if "*[" in translation:
                    resource = parse(f"temp_id = {translation}")
                    flattener = flattenSelectExpression()
                    serializer = FluentSerializer()
                    translation = serializer.serialize(flattener.visit(resource))

                html_parser.clear()
                cleaned_translation = placeable_pattern.sub("", translation)
                html_parser.feed(cleaned_translation)
                tags = html_parser.get_tags()

                if tags != ref_tags:
                    # Ignore if only the order was changed
                    if sorted(tags) == sorted(ref_tags):
                        continue
                    error_msg = (
                        f"Mismatched HTML elements in string ({string_id})\n"
                        f"  Translation tags ({len(tags)}): {', '.join(tags)}\n"
                        f"  Reference tags ({len(ref_tags)}): {', '.join(ref_tags)}\n"
                        f"  Translation: {translation}\n"
                        f"  Reference: {reference_data[string_id]}"
                    )
                    self.error_messages[locale].append(error_msg)
                    tmx_errors += 1

            # FTL checks
            for string_id in ftl_ids:
                # Ignore strings
                if ignoreString(string_id, locale_data, "ignore"):
                    continue

                translation = locale_data[string_id]

                # Check for stray spaces
                if (
                    '{ "' in translation
                    and not ignoreString(string_id, locale_data, "ftl_literals")
                ):
                    error_msg = f"Fluent literal in string ({string_id})"
                    self.error_messages[locale].append(error_msg)
                    tmx_errors += 1

                # Check for DTD variables, e.g. '&something;'
                pattern = re.compile("&.*;", re.UNICODE)
                if pattern.search(translation):
                    if string_id in exclusions["xml"]["strings"]:
                        continue
                    error_msg = f"XML entity in Fluent string ({string_id})"
                    self.error_messages[locale].append(error_msg)
                    tmx_errors += 1

                # Check for properties variables '%S' or '%1$S'
                if string_id not in exclusions["printf"]["strings"]:
                    pattern = re.compile(
                        "(%(?:[0-9]+\$){0,1}(?:[0-9].){0,1}([sS]))", re.UNICODE
                    )
                    if pattern.search(translation):
                        error_msg = f"printf variables in Fluent string ({string_id})"
                        self.error_messages[locale].append(error_msg)
                        tmx_errors += 1

                # Check for the message ID repeated in the translation
                message_id = string_id.split(":")[1]
                pattern = re.compile(re.escape(message_id) + "\s*=", re.UNICODE)
                if pattern.search(translation):
                    error_msg = (
                        f"Message ID is repeated in the Fluent string ({string_id})"
                    )
                    self.error_messages[locale].append(error_msg)
                    tmx_errors += 1

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
                        error_msg = (
                            f"data-l10n-name mismatch in Fluent string ({string_id})"
                        )
                        self.error_messages[locale].append(error_msg)
                        tmx_errors += 1
                else:
                    # There are no data-l10n-name
                    error_msg = f"data-l10n-name missing in Fluent string ({string_id})"
                    self.error_messages[locale].append(error_msg)
                    tmx_errors += 1

            # Check for CSS mismatches
            for string_id, cleaned_source in CSS_strings.items():
                if string_id not in locale_data:
                    continue

                # Alway strip the closing ';', to avoid errors on mismatches
                translation = locale_data[string_id].rstrip(";")
                matches = css_pattern.findall(translation)
                # Drop empty elements, ignore period for decimals
                cleaned_translation = [m for m in matches if m not in ["", "."]]
                if cleaned_translation != cleaned_source:
                    # Groups are not matching
                    error_msg = f"CSS mismatch in Fluent string ({string_id})"
                    self.error_messages[locale].append(error_msg)
                    tmx_errors += 1
        self.error_summary["TMX checks"] = tmx_errors


def main():
    # Parse command line options
    cl_parser = argparse.ArgumentParser()
    cl_parser.add_argument("check", help="Run a single check", default="all", nargs="?")
    cl_parser.add_argument("--locale", dest="locale", help="Run single locale")
    cl_parser.add_argument("--verbose", dest="verbose", action="store_true")
    cl_parser.add_argument("--tmx", dest="tmx", action="store_true")
    cl_parser.add_argument(
        "-output",
        nargs="?",
        help="Path to folder where to store output in JSON format",
        default="",
    )
    args = cl_parser.parse_args()

    # Check if there's a config file (optional)
    root_folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir)
    config_file = os.path.join(root_folder, "config", "config.ini")

    tmx_path = ""
    if os.path.isfile(config_file):
        config_parser = ConfigParser()
        config_parser.read(config_file)

        def getConfig(key):
            try:
                value = config_parser.get("config", key)
                if key != "toml_path":
                    value = os.path.join(value, "")
            except:
                sys.exit(f"{key} not found in config.ini")
            if not os.path.exists(value):
                print(f"Path in {key} is not valid: {value}")
                value = ""

            return value

        tmx_path = getConfig("tmx_path")
        firefoxl10n_path = getConfig("firefoxl10n_path")
        toml_path = getConfig("toml_path")

    # Check if checks are already running for some reason
    semaphore = os.path.join(root_folder, ".running")
    if os.path.isfile(semaphore):
        sys.exit("Checks are already running")
    else:
        try:
            open(semaphore, "w")
        except:
            sys.exit("Can't create semaphore file")

    cli_options = {
        "verbose": args.verbose,
        "tmx": args.tmx,
        "locale": args.locale,
    }

    QualityCheck(
        root_folder,
        tmx_path,
        firefoxl10n_path,
        toml_path,
        args.check,
        cli_options,
        args.output,
    )

    # Remove semaphore file
    os.remove(semaphore)


if __name__ == "__main__":
    main()
